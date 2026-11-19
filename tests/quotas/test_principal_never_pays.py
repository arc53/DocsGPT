"""A team principal is never a payer: every run on a team agent bills a person.

A team's agent runs as the team's principal (its sources, tools, prompt and model), but ``token_usage.user_id``
is always a person: the member chatting, the person who set a schedule, or whoever pays for the agent's
published access (``agents.access_payer_id``). With nobody to bill, outside traffic is refused (``no_payer``)
before anything is spent.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.quotas.payer import NO_PAYER_CODE, billed_to, current_run_billing, published_access_payer
from docsgpt.quotas.service import NoPayerError, QuotaExceededError, QuotaService
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.usage import gen_token_usage
from docsgpt.workspaces.principal import is_principal_id, principal_id

PRINCIPAL = principal_id(uuid.uuid4())

# Every module that opens a connection on the paths these tests drive.
_DB_TARGETS = (
    "docsgpt.quotas.service.db_readonly",
    "docsgpt.quotas.payer.db_readonly",
    "docsgpt.agents.headless_runner.db_readonly",
    "docsgpt.usage.db_session",
    "docsgpt.api.answer.routes.base.db_readonly",
    "docsgpt.agents.tools.scheduler.db_readonly",
    "docsgpt.agents.tools.scheduler.db_session",
)


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    for target in _DB_TARGETS:
        monkeypatch.setattr(target, _yield)
    return pg_conn


def _team(conn, owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"))):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _team_agent(conn, principal, *, payer=None, key=None):
    return AgentsRepository(conn).create(
        principal, "Team bot", "published", key=key or f"k-{uuid.uuid4().hex[:8]}", access_payer_id=payer,
        created_by="adam", default_model_id="m", agent_type="classic",
    )


def _deactivate(conn, user_id):
    UsersRepository(conn).upsert(user_id)
    conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": user_id})


def _usage_rows(conn, agent_id):
    return [
        dict(row._mapping)
        for row in conn.execute(
            text("SELECT user_id, api_key FROM token_usage WHERE agent_id = CAST(:a AS uuid)"), {"a": str(agent_id)}
        )
    ]


class _RunsAsLLM:
    """An LLM built from the run's identity, as every agent, title and workflow LLM is."""

    def __init__(self, sub, agent_id, key="k"):
        self.decoded_token = {"sub": sub}
        self.user_api_key = key
        self.agent_id = agent_id
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}


@gen_token_usage
def _call(self, model, messages, stream, tools, **kwargs):
    return "an answer"


def _model_call(sub, agent_id, key="k"):
    _call(_RunsAsLLM(sub, agent_id, key), "m", [{"role": "user", "content": "hi"}], False, None)


# ---------------------------------------------------------------------------
# The quota service and the payer seam
# ---------------------------------------------------------------------------


class TestQuotaServiceFailsClosed:
    def test_a_principal_is_refused_before_any_lookup(self, monkeypatch):
        reads = []
        monkeypatch.setattr(QuotaService, "status", staticmethod(lambda *a, **k: reads.append(a)))

        with pytest.raises(NoPayerError) as raised:
            QuotaService.check(PRINCIPAL, "agent")

        assert raised.value.code == NO_PAYER_CODE and not reads

    def test_the_refusal_is_a_quota_refusal_so_every_headless_caller_stops_the_run(self):
        assert issubclass(NoPayerError, QuotaExceededError)

    def test_status_never_hands_a_principal_to_the_defaults_provider(self, monkeypatch):
        seen = []
        monkeypatch.setattr("docsgpt.quotas.service.default_rows", lambda uid: seen.append(uid) or [])

        with pytest.raises(NoPayerError):
            QuotaService.status(PRINCIPAL)

        assert seen == []

    def test_a_person_is_checked_as_before(self, monkeypatch):
        monkeypatch.setattr(QuotaService, "status", staticmethod(lambda *a, **k: []))
        assert QuotaService.check("alice", "agent") is None


class TestPublishedAccessPayer:
    def test_the_access_payer_wins(self):
        assert published_access_payer({"user_id": PRINCIPAL, "access_payer_id": "adam"}) == "adam"
        assert published_access_payer({"user_id": "lena", "access_payer_id": "adam"}) == "adam"

    def test_a_person_owner_pays_when_no_access_payer_is_set(self):
        assert published_access_payer({"user_id": "lena", "access_payer_id": None}) == "lena"
        assert published_access_payer({"user": "lena"}) == "lena"

    def test_a_team_agent_without_an_access_payer_has_none(self):
        assert published_access_payer({"user_id": PRINCIPAL}) is None

    def test_a_principal_is_never_returned_even_as_access_payer(self):
        assert published_access_payer({"user_id": PRINCIPAL, "access_payer_id": PRINCIPAL}) is None


# ---------------------------------------------------------------------------
# Outside access on a team agent: refused with no payer, paused with a deactivated one
# ---------------------------------------------------------------------------


class TestOutsideAccess:
    def test_a_team_agent_with_no_access_payer_is_refused_no_payer(self, db):
        from docsgpt.api.owner_pause import AgentPausedError, outside_access_refusal, refuse_if_owner_deactivated

        _, principal = _team(db)
        agent = _team_agent(db, principal)

        refusal = outside_access_refusal(db, agent)
        assert isinstance(refusal, AgentPausedError) and refusal.code == "no_payer"
        with pytest.raises(AgentPausedError) as raised:
            refuse_if_owner_deactivated(db, agent)
        assert raised.value.code == "no_payer"

    def test_a_team_agent_with_an_active_access_payer_answers(self, db):
        from docsgpt.api.owner_pause import outside_access_refusal, refuse_if_owner_deactivated

        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")

        assert outside_access_refusal(db, agent) is None
        refuse_if_owner_deactivated(db, agent)

    def test_a_deactivated_access_payer_pauses_outside_access(self, db):
        from docsgpt.api.owner_pause import PAUSED_CODE, outside_access_refusal

        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")
        _deactivate(db, "adam")

        refusal = outside_access_refusal(db, agent)
        assert refusal is not None and refusal.code == PAUSED_CODE

    def test_a_deactivated_access_payer_on_a_personal_agent_pauses_it_too(self, db):
        from docsgpt.api.owner_pause import PAUSED_CODE, outside_access_refusal

        agent = AgentsRepository(db).create("lena", "Mine", "published", key="lk", access_payer_id="dana")
        _deactivate(db, "dana")

        assert outside_access_refusal(db, agent).code == PAUSED_CODE

    def test_a_personal_agent_is_unchanged(self, db):
        from docsgpt.api.owner_pause import outside_access_refusal

        agent = AgentsRepository(db).create("lena", "Mine", "published", key="lk2")
        assert outside_access_refusal(db, agent) is None


class TestCheckUsage:
    """``check_usage`` (``/stream``, ``/api/answer``, ``/v1``): outside traffic checks the published-access payer."""

    @pytest.fixture
    def app(self):
        app = Flask(__name__)
        with app.app_context():
            yield app

    def _check(self, agent, decoded_token, **flags):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        config = {"user_api_key": agent["key"], "user_id": agent["user_id"], **flags}
        return BaseAnswerResource().check_usage(config, decoded_token, agent_id=str(agent["id"]))

    def test_key_traffic_on_a_team_agent_with_no_payer_is_refused_before_any_spend(self, db, app, monkeypatch):
        checked = []
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, uid, *a, **k: checked.append(uid)))
        _, principal = _team(db)
        agent = _team_agent(db, principal)

        response = self._check(agent, {"sub": principal}, external_api_caller=True)

        assert response.status_code == 403
        assert response.get_json()["code"] == "no_payer" and checked == []

    def test_key_traffic_checks_the_access_payers_allowance(self, db, app, monkeypatch):
        checked = []
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, uid, *a, **k: checked.append(uid)))
        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")

        assert self._check(agent, {"sub": principal}, external_api_caller=True) is None
        assert checked == ["adam"]

    def test_a_signed_in_public_link_visitor_checks_their_own_allowance_not_the_publishers(
        self, db, app, monkeypatch
    ):
        checked = []
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, uid, *a, **k: checked.append(uid)))
        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")

        assert self._check(agent, {"sub": "stranger"}, public_link_caller=True) is None
        assert checked == ["stranger"]

    def test_a_public_link_visitor_not_signed_in_checks_the_publisher(self, db, app, monkeypatch):
        checked = []
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, uid, *a, **k: checked.append(uid)))
        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")

        assert self._check(agent, None, public_link_caller=True) is None
        assert checked == ["adam"]

    def test_a_member_chatting_pays_for_their_own_chat(self, db, app, monkeypatch):
        checked = []
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, uid, *a, **k: checked.append(uid)))
        _, principal = _team(db)
        agent = _team_agent(db, principal)

        assert self._check(agent, {"sub": "eddie"}) is None
        assert checked == ["eddie"]

    def test_a_principal_that_slips_through_as_the_payer_is_refused(self, db, app):
        """No flag says it is outside traffic, but the identity is the team: the quota service refuses it."""
        _, principal = _team(db)
        agent = AgentsRepository(db).create(principal, "Keyless", "published", default_model_id="m")

        from docsgpt.api.answer.routes.base import BaseAnswerResource

        response = BaseAnswerResource().check_usage({"user_id": principal}, {"sub": principal}, agent_id=None)
        assert response.status_code == 403 and response.get_json()["code"] == "no_payer"
        assert agent  # created only so the principal owns something


# ---------------------------------------------------------------------------
# Headless runs: webhook, schedule, continuation
# ---------------------------------------------------------------------------


def _stub_runner(monkeypatch, agent_id, key):
    """Stub the agent: each run makes one model call under the identity it was built with (the team)."""
    from docsgpt.agents import headless_runner as hr

    seen = {"created": 0}

    def _create(*_args, **kwargs):
        seen["created"] += 1
        seen["agent_kwargs"] = kwargs
        agent = MagicMock(name="agent")
        agent.llm.token_usage = {}

        def _gen(query):
            _model_call(kwargs["decoded_token"]["sub"], agent_id, key)
            yield {"answer": "ok"}

        agent.gen.side_effect = _gen
        return agent

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever",
                        classmethod(lambda cls, *a, **kw: MagicMock(search=MagicMock(return_value=[]))))
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[], cannot_complete=None))
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: _create(*a, **kw)))
    for target, value in (
        ("docsgpt.core.model_utils.validate_model_id", True),
        ("docsgpt.core.model_utils.get_provider_from_model_id", "openai"),
        ("docsgpt.core.model_utils.get_api_key_for_provider", "k"),
        ("docsgpt.utils.calculate_doc_token_budget", 1000),
    ):
        monkeypatch.setattr(target, MagicMock(return_value=value))
    return seen


class TestHeadless:
    def test_a_webhook_run_bills_the_access_payer(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")
        seen = _stub_runner(monkeypatch, agent["id"], agent["key"])

        run_agent_headless(agent, "{}", endpoint="webhook", payer=published_access_payer(agent))

        assert [r["user_id"] for r in _usage_rows(db, agent["id"])] == ["adam"]
        assert seen["agent_kwargs"]["decoded_token"] == {"sub": principal}

    def test_a_run_with_nobody_to_bill_never_starts(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        _, principal = _team(db)
        agent = _team_agent(db, principal)
        seen = _stub_runner(monkeypatch, agent["id"], agent["key"])

        with pytest.raises(NoPayerError):
            run_agent_headless(agent, "{}", endpoint="webhook")

        assert seen["created"] == 0 and _usage_rows(db, agent["id"]) == []

    def test_a_principal_handed_in_as_payer_is_refused(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")
        seen = _stub_runner(monkeypatch, agent["id"], agent["key"])

        with pytest.raises(NoPayerError):
            run_agent_headless(agent, "{}", endpoint="schedule", payer=principal)
        assert seen["created"] == 0


class TestContinuationPayer:
    def test_a_key_traffic_conversation_continues_on_the_access_payers_bill(self):
        from docsgpt.background.continuation import continuation_payer

        conversation = {"user_id": PRINCIPAL}
        assert continuation_payer(conversation, {"user_id": PRINCIPAL, "access_payer_id": "adam"}) == "adam"
        assert continuation_payer(conversation, {"user_id": PRINCIPAL}) is None

    def test_a_members_chat_continues_on_the_members_bill(self):
        from docsgpt.background.continuation import continuation_payer

        assert continuation_payer({"user_id": "eddie"}, {"user_id": PRINCIPAL, "access_payer_id": "adam"}) == "eddie"


# ---------------------------------------------------------------------------
# The scheduler tool in a run whose identity is the team
# ---------------------------------------------------------------------------


class TestSchedulerTool:
    def _tool(self, principal, agent_id):
        from docsgpt.agents.tools.scheduler import SchedulerTool

        return SchedulerTool({"agent_id": str(agent_id), "created_via": "api"}, user_id=principal)

    def test_stores_the_runs_payer_as_the_schedules_person(self, db):
        _, principal = _team(db)
        agent = _team_agent(db, principal, payer="adam")

        with billed_to("adam"):
            result = json.loads(self._tool(principal, agent["id"]).execute_action(
                "schedule_task", instruction="ping", delay="1h"))

        row = db.execute(text("SELECT user_id, agent_id FROM schedules WHERE id = CAST(:id AS uuid)"),
                         {"id": result["task_id"]}).fetchone()
        assert row.user_id == "adam" and str(row.agent_id) == str(agent["id"])

    def test_refuses_when_the_run_has_no_payer(self, db):
        _, principal = _team(db)
        agent = _team_agent(db, principal)

        result = self._tool(principal, agent["id"]).execute_action("schedule_task", instruction="ping", delay="1h")

        assert result.startswith("Error:")
        count = db.execute(text("SELECT count(*) FROM schedules WHERE agent_id = CAST(:a AS uuid)"),
                           {"a": str(agent["id"])}).scalar()
        assert count == 0

    def test_a_tool_never_mints_a_schedule_for_the_principal(self, db):
        _, principal = _team(db)
        agent = _team_agent(db, principal)

        with billed_to(principal):
            result = self._tool(principal, agent["id"]).execute_action(
                "schedule_task", instruction="ping", delay="1h")

        assert result.startswith("Error:")
        owners = db.execute(text("SELECT user_id FROM schedules")).scalars().all()
        assert not any(is_principal_id(o) for o in owners)


# ---------------------------------------------------------------------------
# A background tool call in a Celery worker keeps the run's payer
# ---------------------------------------------------------------------------


class TestCeleryRunnerCarriesThePayer:
    def test_the_payload_carries_the_payer_of_the_run(self):
        from docsgpt.background.celery_runner import worker_payload

        executor = MagicMock(user=PRINCIPAL, user_api_key="k", agent_id="a", external_caller=True,
                             public_link_caller=False, api_write_allowlist=[], conversation_id="c", message_id="m")
        with billed_to("adam"):
            payload = worker_payload(executor, {"id": "t", "name": "x"}, "act", {})
        assert payload["payer"] == "adam" and payload["user"] == PRINCIPAL

    def test_a_chat_carries_the_chatter_as_its_payer(self):
        from docsgpt.background.celery_runner import worker_payload

        executor = MagicMock(user="eddie", user_api_key=None, agent_id=None, external_caller=False,
                             public_link_caller=False, api_write_allowlist=[], conversation_id="c", message_id="m")
        # Every chat opens its billing, so the job knows its payer without re-deriving it from the identity.
        with billed_to("eddie", kind="chat"):
            payload = worker_payload(executor, {"id": "t", "name": "x"}, "act", {})
        assert (payload["payer"], payload["run_kind"]) == ("eddie", "chat")

    def test_the_job_runs_billed_to_the_payer(self, monkeypatch):
        from docsgpt.background import celery_runner

        seen = {}
        monkeypatch.setattr(celery_runner, "_run_job", lambda job_id, payload: seen.update(
            billing=current_run_billing()) or {"state": "finished"})

        celery_runner.run_job("j", {"user": PRINCIPAL, "payer": "adam"})

        assert seen["billing"] is not None and seen["billing"].payer == "adam"


# ---------------------------------------------------------------------------
# The usage guard, and every run kind on a team agent billing a person
# ---------------------------------------------------------------------------


def _principal_billed(caplog):
    return [r for r in caplog.records if r.getMessage().startswith("principal_billed")]


class TestUsageGuard:
    def test_a_row_that_would_bill_the_principal_is_logged_and_never_stored_as_it(self, db, caplog):
        _, principal = _team(db)
        agent = _team_agent(db, principal)

        with caplog.at_level(logging.ERROR, logger="docsgpt.usage"):
            _model_call(principal, agent["id"], agent["key"])

        assert _principal_billed(caplog)
        rows = _usage_rows(db, agent["id"])
        # The key keeps the agent's own limit counting; the principal is never stored as a payer.
        assert rows == [{"user_id": None, "api_key": agent["key"]}]

    def test_without_a_key_the_row_is_dropped_with_the_error(self, db, caplog):
        _, principal = _team(db)
        agent = _team_agent(db, principal)

        with caplog.at_level(logging.ERROR, logger="docsgpt.usage"):
            _model_call(principal, agent["id"], key=None)

        assert _principal_billed(caplog) and _usage_rows(db, agent["id"]) == []


def _run_schedule(db, monkeypatch, principal, agent):
    from docsgpt.agents.headless_runner import run_agent_headless

    _stub_runner(monkeypatch, agent["id"], agent["key"])
    run_agent_headless(agent, "report", endpoint="schedule", payer="eddie")
    return "eddie"


def _run_webhook(db, monkeypatch, principal, agent):
    from docsgpt.agents.headless_runner import run_agent_headless

    _stub_runner(monkeypatch, agent["id"], agent["key"])
    run_agent_headless(agent, "{}", endpoint="webhook", payer=published_access_payer(agent))
    return "adam"


def _run_key_continuation(db, monkeypatch, principal, agent):
    from docsgpt.background import continuation

    _stub_runner(monkeypatch, agent["id"], agent["key"])
    monkeypatch.setattr(continuation, "db_readonly", MagicMock())
    monkeypatch.setattr(continuation, "_agent_config", lambda *a: agent)
    conversation = {"id": str(uuid.uuid4()), "user_id": principal, "agent_id": str(agent["id"])}
    continuation._run_turn(conversation, [], [{"source": "job", "title": "done"}], message_id="m-1")
    return "adam"


def _run_member_continuation(db, monkeypatch, principal, agent):
    from docsgpt.background import continuation

    _stub_runner(monkeypatch, agent["id"], agent["key"])
    monkeypatch.setattr(continuation, "db_readonly", MagicMock())
    monkeypatch.setattr(continuation, "_agent_config", lambda *a: agent)
    conversation = {"id": str(uuid.uuid4()), "user_id": "eddie", "agent_id": str(agent["id"])}
    continuation._run_turn(conversation, [], [{"source": "job", "title": "done"}], message_id="m-1")
    return "eddie"


def _stream(decoded_token, agent_id, key, *, external=False, public_link=False):
    """Drive ``complete_stream``'s wrapper the way ``/stream``, ``/api/answer`` and ``/v1`` do."""
    from docsgpt.api.answer.routes.base import _traced_stream

    class _Resource:
        @_traced_stream
        def complete_stream(self, question, agent, conversation_id, user_api_key, decoded_token,
                            agent_id=None, request_id=None, trace=None, _continuation=None):
            # The agent's LLM is built from the run's identity, as in a real turn.
            _model_call(decoded_token["sub"], agent_id, user_api_key)
            yield "data: done\n\n"

    agent = MagicMock(name="agent")
    agent.tool_executor.external_caller = external
    agent.tool_executor.public_link_caller = public_link
    agent.decision_record = None
    list(_Resource().complete_stream("q", agent, None, key, decoded_token, agent_id=str(agent_id)))


def _run_api_key_chat(db, monkeypatch, principal, agent):
    # ``stream_processor`` hands key traffic the agent owner's identity: the team.
    _stream({"sub": principal}, agent["id"], agent["key"], external=True)
    return "adam"


def _run_v1(db, monkeypatch, principal, agent):
    # ``/v1/chat/completions`` builds ``{"sub": <owner>}`` and an external-caller processor.
    _stream({"sub": principal}, agent["id"], agent["key"], external=True)
    return "adam"


def _run_public_link(db, monkeypatch, principal, agent):
    # A signed-in visitor pays for their own chat.
    _stream({"sub": "stranger"}, agent["id"], agent["key"], public_link=True)
    return "stranger"


def _run_member_chat(db, monkeypatch, principal, agent):
    _stream({"sub": "eddie"}, agent["id"], agent["key"])
    return "eddie"


def _run_background_job(db, monkeypatch, principal, agent):
    from docsgpt.background import celery_runner

    def _job(job_id, payload):
        _model_call(payload["user"], agent["id"], agent["key"])
        return {"state": "finished"}

    monkeypatch.setattr(celery_runner, "_run_job", _job)
    executor = MagicMock(user=principal, user_api_key=agent["key"], agent_id=agent["id"], external_caller=True,
                         public_link_caller=False, api_write_allowlist=[], conversation_id="c", message_id="m")
    with billed_to("adam"):
        payload = celery_runner.worker_payload(executor, {"id": "t", "name": "x"}, "act", {})
    celery_runner.run_job("j", payload)
    return "adam"


def _run_guard_judge(db, monkeypatch, principal, agent):
    """A finished job's result is scanned by the agent's judge after the turn ended."""
    from docsgpt.background import guard

    class _Engine:
        context = MagicMock()
        recorder = None

        def evaluate(self, value, stage):
            _model_call(principal, agent["id"], agent["key"])
            return MagicMock()

    monkeypatch.setattr(guard, "_agent_row", lambda agent_id: dict(agent))
    monkeypatch.setattr("docsgpt.guardrails.runtime.resolve_config",
                        lambda raw: MagicMock(enabled=True, has_any=lambda stage: True))
    monkeypatch.setattr("docsgpt.guardrails.runtime.build_engine", lambda owner: _Engine())
    monkeypatch.setattr(guard, "_EngineOwner", lambda **kwargs: MagicMock())
    monkeypatch.setattr(guard, "resolve_tool_result", lambda value, decision: value)
    engine = guard.engine_for(user_id=principal, agent_id=str(agent["id"]))
    guard.scan(engine, "text", tool_name="t", action_name="a")
    return "adam"


RUN_KINDS = {
    "schedule": _run_schedule,
    "webhook": _run_webhook,
    "api_key_chat": _run_api_key_chat,
    "v1": _run_v1,
    "public_link": _run_public_link,
    "member_chat": _run_member_chat,
    "key_traffic_continuation": _run_key_continuation,
    "member_continuation": _run_member_continuation,
    "background_job": _run_background_job,
    "guardrail_judge": _run_guard_judge,
}


@pytest.mark.parametrize("kind", sorted(RUN_KINDS))
def test_every_run_kind_on_a_team_agent_bills_a_person(kind, db, monkeypatch, caplog):
    _, principal = _team(db)
    agent = _team_agent(db, principal, payer="adam")

    with caplog.at_level(logging.ERROR, logger="docsgpt.usage"):
        expected = RUN_KINDS[kind](db, monkeypatch, principal, agent)

    rows = _usage_rows(db, agent["id"])
    assert rows and {r["user_id"] for r in rows} == {expected}
    assert not any(is_principal_id(r["user_id"]) for r in rows)
    assert _principal_billed(caplog) == []


# ---------------------------------------------------------------------------
# A monitor a team agent's outside traffic left
# ---------------------------------------------------------------------------


class TestMonitorJudge:
    def _monitor(self):
        return {"id": "m-1", "user_id": PRINCIPAL, "agent_id": str(uuid.uuid4()), "monitor_spec": {}}

    def test_with_nobody_to_bill_the_condition_waits(self, monkeypatch):
        from docsgpt.monitors import tick

        monkeypatch.setattr("docsgpt.quotas.payer.agent_access_payer", lambda agent_id=None, api_key=None: None)
        monkeypatch.setattr("docsgpt.monitors.judge.judge", MagicMock(side_effect=AssertionError("judged")))

        assert tick._judge(self._monitor(), MagicMock(), MagicMock()) == ("no_payer", None)

    def test_the_judge_bills_the_access_payer(self, monkeypatch):
        from contextlib import nullcontext

        from docsgpt.monitors import tick

        seen = {}
        monkeypatch.setattr("docsgpt.quotas.payer.agent_access_payer", lambda agent_id=None, api_key=None: "adam")
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, uid, *a: seen.update(checked=uid)))

        def _judge(**kwargs):
            seen["billing"] = current_run_billing()
            return MagicMock(match=True, tokens=3)

        monkeypatch.setattr("docsgpt.monitors.judge.judge", _judge)
        monkeypatch.setattr(tick, "db_session", lambda: nullcontext(MagicMock()))

        outcome, _ = tick._judge(self._monitor(), MagicMock(), MagicMock())

        assert outcome == "match" and seen["checked"] == "adam" and seen["billing"].payer == "adam"
