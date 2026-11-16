"""How a stop by a limit reaches the person chatting, and what an outside caller is told instead.

A chat runs under its payer's limits for its whole length. When a model call is refused mid-turn, the partial answer
is saved as failed and the stream ends with ``{type: "error", code: "quota-exceeded", params}``, decorated by the
quota provider as the pre-run refusal is. Outside traffic (a key, the widget, a public link, ``/v1``) never learns
the payer's numbers: before the run and during it, it is told only that the agent is paused, and the provider hook
is never called with the payer's id.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.api.owner_pause import PAUSED_MESSAGE
from docsgpt.quotas import providers
from docsgpt.quotas.payer import current_run_billing
from docsgpt.quotas.run_limits import RunLimitReached
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.workspaces.principal import principal_id

_NUMBERS = ("usage", "limit", "bucket", "dimension", "unit", "resets_at", "source")


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    for target in (
        "docsgpt.quotas.run_limits.db_readonly",
        "docsgpt.quotas.service.db_readonly",
        "docsgpt.quotas.payer.db_readonly",
        "docsgpt.api.answer.routes.base.db_readonly",
    ):
        monkeypatch.setattr(target, _yield)
    monkeypatch.setattr("docsgpt.quotas.run_limits.settings.QUOTA_PERIOD", "month")
    monkeypatch.setattr("docsgpt.quotas.service.settings.QUOTA_PERIOD", "month")
    return pg_conn


class _RecordingProvider(providers.QuotaDefaultsProvider):
    """A cloud-style provider: adds an upgrade link and remembers whose refusal it decorated."""

    def __init__(self) -> None:
        self.decorated_for: list = []

    def error_payload(self, payload: dict, user_id: str) -> dict:
        self.decorated_for.append(user_id)
        return {**payload, "upgrade_url": f"https://example.test/upgrade?u={user_id}"}


@pytest.fixture
def provider(monkeypatch):
    recording = _RecordingProvider()
    monkeypatch.setattr(providers, "_provider", recording)
    return recording


def _over_allowance(conn, user_id, tokens=100, **spend):
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user_id, token_limit=tokens)
    TokenUsageRepository(conn).insert(user_id=user_id, prompt_tokens=tokens, **spend)


def _turn_then_refused_call(answer="Half of the answer"):
    """An agent turn that streams some text, then makes a model call the run's limits refuse."""

    def gen(*_args, **_kwargs):
        yield {"answer": answer}
        current_run_billing().limits.check_call()
        yield {"answer": " and the rest"}

    return gen


def _stream(flask_app, agent, *, decoded_token, persist=True, agent_id=None, user_api_key=None):
    from docsgpt.api.answer.routes.base import BaseAnswerResource

    # The journal and the turn log write through the app's own engine; these turns' rows are mocks.
    with flask_app.app_context(), patch("docsgpt.api.answer.routes.base.BatchedJournalWriter"):
        resource = BaseAnswerResource()
        resource._persist_turn_log = MagicMock()
        resource.conversation_service = MagicMock()
        resource.conversation_service.save_user_question.return_value = {"conversation_id": "c1", "message_id": "m1"}
        frames = list(
            resource.complete_stream(
                question="Write the report",
                agent=agent,
                conversation_id=None,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
                should_persist=persist,
                agent_id=agent_id,
            )
        )
    events = [json.loads(frame.split("data: ", 1)[1]) for frame in frames if "data: " in frame]
    return resource, events


def _agent(external=False, gen=None):
    agent = MagicMock(name="agent")
    agent.is_v1 = False
    agent.tool_executor.external_caller = external
    agent.tool_executor.public_link_caller = False
    agent.tool_executor.workspace_team_id = None
    agent.decision_record = None
    if gen is not None:
        agent.gen.side_effect = gen
    return agent


@pytest.mark.unit
class TestAChatStoppedMidTurn:
    def test_the_stream_ends_with_the_quota_error_and_its_numbers(self, db, flask_app, provider):
        _over_allowance(db, "dana")

        _, events = _stream(flask_app, _agent(gen=_turn_then_refused_call()), decoded_token={"sub": "dana"})

        error = [e for e in events if e.get("type") == "error"][-1]
        assert error["code"] == "quota-exceeded"
        params = error["params"]
        assert (params["dimension"], params["unit"], params["usage"], params["limit"], params["bucket"]) == (
            "tokens", "tokens", 100, 100, "all"
        )
        assert params["resets_at"]
        assert "Please try again later" not in error["error"]

    def test_the_partial_answer_is_saved_as_failed(self, db, flask_app, provider):
        _over_allowance(db, "dana")

        resource, events = _stream(flask_app, _agent(gen=_turn_then_refused_call()), decoded_token={"sub": "dana"})

        kwargs = resource.conversation_service.finalize_message.call_args.kwargs
        args = resource.conversation_service.finalize_message.call_args.args
        assert kwargs["status"] == "failed"
        assert args[1] == "Half of the answer"
        assert kwargs["metadata"]["error_code"] == "quota-exceeded"
        assert kwargs["metadata"]["error_params"]["resets_at"]

    def test_the_saved_message_keeps_the_tool_calls_that_ran(self, db, flask_app, provider):
        # The agent reports its calls when its turn ends, which a stop never reaches.
        _over_allowance(db, "dana")
        agent = _agent(gen=_turn_then_refused_call())
        ran = {"call_id": "c1", "tool_name": "search", "status": "completed"}
        agent._get_truncated_tool_calls.return_value = [ran]

        resource, _ = _stream(flask_app, agent, decoded_token={"sub": "dana"})

        kwargs = resource.conversation_service.finalize_message.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["tool_calls"] == [ran]

    def test_the_provider_decorates_the_person_chatting_own_refusal(self, db, flask_app, provider):
        _over_allowance(db, "dana")

        _, events = _stream(flask_app, _agent(gen=_turn_then_refused_call()), decoded_token={"sub": "dana"})

        error = [e for e in events if e.get("type") == "error"][-1]
        assert error["params"]["upgrade_url"].endswith("u=dana")
        assert provider.decorated_for == ["dana"]

    def test_a_stop_a_workflow_step_turned_into_an_error_event_is_still_curated(self, db, flask_app, provider):
        _over_allowance(db, "dana")

        def gen(*_args, **_kwargs):
            yield {"answer": "Step one"}
            limits = current_run_billing().limits
            try:
                limits.check_call()
            except RunLimitReached:
                pass
            # The engine reports the failed step with the provider-ish text, sanitized.
            yield {"type": "error", "error": "quota reached"}

        _, events = _stream(flask_app, _agent(gen=gen), decoded_token={"sub": "dana"})

        error = [e for e in events if e.get("type") == "error"][-1]
        assert error["code"] == "quota-exceeded"
        assert error["params"]["resets_at"]

    def test_a_chat_with_room_is_not_stopped(self, db, flask_app, provider):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="dana", token_limit=1_000)

        _, events = _stream(flask_app, _agent(gen=_turn_then_refused_call()), decoded_token={"sub": "dana"})

        assert not [e for e in events if e.get("type") == "error"]
        assert "".join(e.get("answer", "") for e in events) == "Half of the answer and the rest"


@pytest.mark.unit
class TestAnOutsideCaller:
    def _keyed_agent(self, conn, owner="sam"):
        return AgentsRepository(conn).create(owner, "Desk", "published", key=f"k-{uuid.uuid4().hex[:8]}")

    def test_the_pre_run_refusal_says_paused_and_nothing_more(self, db, flask_app, provider):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        agent = self._keyed_agent(db)
        _over_allowance(db, "sam")

        with flask_app.app_context():
            response = BaseAnswerResource().check_usage(
                {"user_api_key": agent["key"], "external_api_caller": True}, {"sub": "sam"}
            )

        assert response.status_code == 429
        body = response.get_json()
        assert body == {"success": False, "error_code": "agent_paused", "code": "agent_paused",
                        "message": PAUSED_MESSAGE}
        assert int(response.headers["Retry-After"]) >= 1
        assert response.headers["x-should-retry"] == "false"
        assert provider.decorated_for == []

    @pytest.mark.parametrize("caller", ["public_link_caller", "no_token"])
    def test_a_public_link_or_anonymous_caller_is_told_the_same(self, db, flask_app, provider, caller):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        agent = self._keyed_agent(db)
        _over_allowance(db, "sam")
        config = {"user_api_key": agent["key"]}
        token = {"sub": "visitor"}
        if caller == "public_link_caller":
            config["public_link_caller"] = True
        else:
            token = None

        with flask_app.app_context():
            response = BaseAnswerResource().check_usage(config, token)

        body = response.get_json()
        assert response.status_code == 429 and body["code"] == "agent_paused"
        assert not set(_NUMBERS) & set(body)
        assert provider.decorated_for == []

    def test_a_team_agents_outside_traffic_is_told_paused(self, db, flask_app, provider):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        team = TeamsRepository(db).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "lena")
        agent = AgentsRepository(db).create(
            principal_id(str(team["id"])), "Team desk", "published", key=f"k-{uuid.uuid4().hex[:8]}",
            access_payer_id="lena",
        )
        _over_allowance(db, "lena")

        with flask_app.app_context():
            response = BaseAnswerResource().check_usage(
                {"user_api_key": agent["key"], "external_api_caller": True}, {"sub": principal_id(str(team["id"]))}
            )

        assert response.status_code == 429 and response.get_json()["code"] == "agent_paused"
        assert provider.decorated_for == []

    def test_the_agents_own_limit_keeps_its_message(self, db, flask_app, provider):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        agent = AgentsRepository(db).create(
            "sam", "Desk", "published", key=f"k-{uuid.uuid4().hex[:8]}", limited_token_mode=True, token_limit=10,
        )
        TokenUsageRepository(db).insert(user_id="sam", api_key=agent["key"], prompt_tokens=10)

        with flask_app.app_context():
            response = BaseAnswerResource().check_usage(
                {"user_api_key": agent["key"], "external_api_caller": True}, {"sub": "sam"}
            )

        assert response.get_json()["error_code"] == "agent-limit-exceeded"

    def test_a_person_chatting_still_gets_their_numbers(self, db, flask_app, provider):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        _over_allowance(db, "dana")
        with flask_app.app_context():
            response = BaseAnswerResource().check_usage({}, {"sub": "dana"})

        body = response.get_json()
        assert body["error_code"] == "quota-exceeded" and body["usage"] == 100
        assert provider.decorated_for == ["dana"]

    def test_an_in_run_stop_says_paused_with_no_numbers(self, db, flask_app, provider):
        agent_row = self._keyed_agent(db)
        _over_allowance(db, "sam", api_key=agent_row["key"])

        _, events = _stream(
            flask_app,
            _agent(external=True, gen=_turn_then_refused_call()),
            decoded_token={"sub": "sam"},
            agent_id=str(agent_row["id"]),
            user_api_key=agent_row["key"],
        )

        error = [e for e in events if e.get("type") == "error"][-1]
        assert error["code"] == "agent_paused"
        assert error["error"] == PAUSED_MESSAGE
        assert "params" not in error
        assert provider.decorated_for == []


@pytest.mark.unit
class TestNobodyToPay:
    def test_a_stream_whose_payer_is_a_team_principal_never_runs(self, db, flask_app, provider):
        team = TeamsRepository(db).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "lena")
        agent = _agent(gen=_turn_then_refused_call())

        _, events = _stream(flask_app, agent, decoded_token={"sub": principal_id(str(team["id"]))}, persist=False)

        assert [e.get("code") for e in events if e.get("type") == "error"] == ["no_payer"]
        agent.gen.assert_not_called()
