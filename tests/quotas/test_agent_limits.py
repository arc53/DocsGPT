"""The agent limit covers one agent however it is reached, and is checked before the payer's allowance."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.quotas.agent_limits import AgentLimitExceededError, agent_limit_exceeded
from docsgpt.quotas.service import QuotaExceededError
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with patch("docsgpt.quotas.service.db_readonly", _yield), patch(
        "docsgpt.api.answer.routes.base.db_readonly", _yield
    ), patch("docsgpt.agents.headless_runner.db_readonly", _yield):
        yield pg_conn


def _agent(conn, owner="owner", **fields) -> dict:
    return AgentsRepository(conn).create(owner, "a", "published", **fields)


def _workflow_step(conn, agent_id, tokens, request_id="run-1", user_id="setter"):
    """A row as a workflow node writes it: the agent's id, no key."""
    TokenUsageRepository(conn).insert(
        user_id=user_id, agent_id=str(agent_id), prompt_tokens=tokens, request_id=request_id
    )


class TestAgentLimitExceeded:
    def test_an_agent_without_limits_is_never_refused(self, pg_conn):
        agent = _agent(pg_conn, key="k0")
        _workflow_step(pg_conn, agent["id"], 10**9)
        assert agent_limit_exceeded(pg_conn, agent) is None

    def test_workflow_steps_count_toward_the_token_limit(self, pg_conn):
        agent = _agent(pg_conn, key="k1", limited_token_mode=True, token_limit=100)
        _workflow_step(pg_conn, agent["id"], 60)
        TokenUsageRepository(pg_conn).insert(user_id="caller", api_key="k1", prompt_tokens=40)

        hit = agent_limit_exceeded(pg_conn, agent)

        assert (hit.dimension, hit.usage, hit.limit) == ("tokens", 100, 100)
        assert "agent's token limit" in hit.message
        assert "100 of 100 tokens in the last 24 hours" in hit.message

    def test_a_run_counts_once_toward_the_request_limit(self, pg_conn):
        agent = _agent(pg_conn, key="k2", limited_request_mode=True, request_limit=2)
        for _ in range(3):
            _workflow_step(pg_conn, agent["id"], 1, request_id="one-run")
        assert agent_limit_exceeded(pg_conn, agent) is None

        _workflow_step(pg_conn, agent["id"], 1, request_id="another-run")
        hit = agent_limit_exceeded(pg_conn, agent)
        assert (hit.dimension, hit.usage, hit.limit) == ("requests", 2, 2)

    def test_a_keyless_agent_is_counted_by_its_id(self, pg_conn):
        agent = _agent(pg_conn, limited_token_mode=True, token_limit=5)
        _workflow_step(pg_conn, agent["id"], 5)
        assert agent_limit_exceeded(pg_conn, agent).dimension == "tokens"

    def test_the_refusal_is_a_quota_refusal_naming_the_agent_limit(self, pg_conn):
        agent = _agent(pg_conn, key="k3", limited_token_mode=True, token_limit=1)
        _workflow_step(pg_conn, agent["id"], 1)
        error = AgentLimitExceededError(agent_limit_exceeded(pg_conn, agent))
        # Headless callers already stop a run on a quota refusal, with its message as the reason.
        assert isinstance(error, QuotaExceededError)
        assert "agent's token limit" in str(error)


def _check(flask_app, agent_config, decoded_token=None, agent_id=None):
    from docsgpt.api.answer.routes.base import BaseAnswerResource

    with flask_app.app_context():
        return BaseAnswerResource().check_usage(agent_config, decoded_token, agent_id=agent_id)


class TestCheckUsageOrder:
    def test_the_agent_limit_is_named_before_the_allowance(self, db, flask_app):
        agent = _agent(db, key="k4", limited_token_mode=True, token_limit=10)
        _workflow_step(db, agent["id"], 10, user_id="caller")
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="caller", token_limit=10)

        response = _check(flask_app, {"user_api_key": "k4", "user_id": "owner"}, {"sub": "caller"})

        assert response.status_code == 429
        body = json.loads(response.data)
        assert body["error_code"] == "agent-limit-exceeded"
        assert body["dimension"] == "tokens"
        assert "agent's token limit" in body["message"]

    def test_the_allowance_is_named_when_the_agent_has_room(self, db, flask_app):
        _agent(db, key="k5", limited_token_mode=True, token_limit=1000)
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="caller", token_limit=0)

        response = _check(flask_app, {"user_api_key": "k5", "user_id": "owner"}, {"sub": "caller"})

        assert json.loads(response.data)["error_code"] == "quota-exceeded"

    def test_workflow_steps_count_toward_a_chats_agent_limit(self, db, flask_app):
        agent = _agent(db, key="k6", limited_token_mode=True, token_limit=10)
        _workflow_step(db, agent["id"], 10)

        response = _check(flask_app, {"user_api_key": "k6"}, {"sub": "caller"})

        assert json.loads(response.data)["error_code"] == "agent-limit-exceeded"

    def test_a_keyless_agents_limit_applies_by_its_id(self, db, flask_app):
        agent = _agent(db, limited_token_mode=True, token_limit=10)
        _workflow_step(db, agent["id"], 10)

        response = _check(flask_app, {"user_api_key": None}, {"sub": "owner"}, agent_id=str(agent["id"]))

        assert json.loads(response.data)["error_code"] == "agent-limit-exceeded"


def _run_headless(monkeypatch, config, **kwargs):
    """Drive the real headless runner (limits and payer included) over a stub agent."""
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {}
    retriever = MagicMock(search=MagicMock(return_value=[]))
    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever", classmethod(lambda cls, *a, **kw: retriever))
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[], cannot_complete=None))
    create = MagicMock(return_value=agent)
    monkeypatch.setattr(hr.AgentCreator, "create_agent", create)
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
            patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
            patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
            patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        hr.run_agent_headless(config, "do the thing", **kwargs)
    return create


def _limited_config(agent_id, **limits):
    return {"user_id": "owner", "id": agent_id, "key": "hk", "default_model_id": "m", **limits}


class TestHeadlessRuns:
    @pytest.mark.parametrize("endpoint", ["schedule", "webhook", "continuation"])
    def test_a_run_over_the_agent_limit_never_starts(self, db, monkeypatch, endpoint):
        agent_id = str(_agent(db, key="hk")["id"])
        _workflow_step(db, agent_id, 10)

        with pytest.raises(AgentLimitExceededError) as raised:
            _run_headless(
                monkeypatch, _limited_config(agent_id, limited_token_mode=True, token_limit=10),
                endpoint=endpoint, payer="setter",
            )

        assert "agent's token limit" in str(raised.value)

    def test_a_run_over_the_request_limit_never_starts(self, db, monkeypatch):
        agent_id = str(_agent(db, key="hk")["id"])
        _workflow_step(db, agent_id, 1, request_id="earlier-run")

        with pytest.raises(AgentLimitExceededError) as raised:
            _run_headless(
                monkeypatch, _limited_config(agent_id, limited_request_mode=True, request_limit=1),
                endpoint="schedule", payer="setter",
            )

        assert raised.value.exceeded.dimension == "requests"

    def test_the_agent_limit_is_named_before_the_payers_allowance(self, db, monkeypatch):
        agent_id = str(_agent(db, key="hk")["id"])
        _workflow_step(db, agent_id, 10)
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="setter", token_limit=0)

        with pytest.raises(AgentLimitExceededError):
            _run_headless(
                monkeypatch, _limited_config(agent_id, limited_token_mode=True, token_limit=10),
                endpoint="schedule", payer="setter",
            )

    def test_a_schedule_checks_the_setters_allowance_not_the_owners(self, db, monkeypatch):
        agent_id = str(_agent(db, key="hk")["id"])
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="setter", token_limit=0)

        with pytest.raises(QuotaExceededError) as raised:
            _run_headless(monkeypatch, _limited_config(agent_id), endpoint="schedule", payer="setter")
        assert raised.value.exceeded.user_id == "setter"

        # The owner out of allowance does not stop a teammate's schedule.
        QuotaPoliciesRepository(db).delete("user", "setter")
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="owner", token_limit=0)
        create = _run_headless(monkeypatch, _limited_config(agent_id), endpoint="schedule", payer="setter")
        create.assert_called_once()

    def test_a_run_with_no_payer_bills_the_published_access_payer(self, db, monkeypatch):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="owner", token_limit=0)

        with pytest.raises(QuotaExceededError) as raised:
            _run_headless(monkeypatch, _limited_config(str(_agent(db, key="hk")["id"])), endpoint="webhook")

        assert raised.value.exceeded.user_id == "owner"
