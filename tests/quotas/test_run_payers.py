"""Who each kind of run bills, as the usage rows record it, while it still runs as the agent's owner."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from docsgpt.usage import gen_token_usage


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    pg_conn.execute(
        text("INSERT INTO agents (id, user_id, name, status, key) VALUES (CAST(:id AS uuid), 'owner', 'a', "
             "'published', 'agent-key')"),
        {"id": AGENT_ID},
    )
    with patch("docsgpt.quotas.service.db_readonly", _yield), patch(
        "docsgpt.agents.headless_runner.db_readonly", _yield
    ), patch("docsgpt.usage.db_session", _yield):
        yield pg_conn


class _OwnerLLM:
    """An LLM the agent builds from the run's identity: the agent's owner."""

    def __init__(self, decoded_token):
        self.decoded_token = decoded_token
        self.user_api_key = "agent-key"
        self.agent_id = AGENT_ID
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}


@gen_token_usage
def _call(self, model, messages, stream, tools, **kwargs):
    return "an answer"


AGENT_ID = str(uuid.uuid4())


def _stub_runner(monkeypatch, calls_per_run=1):
    """Stub the agent so each run makes ``calls_per_run`` model calls under the identity it was built with."""
    from docsgpt.agents import headless_runner as hr

    seen = {}

    def _create(*_args, **kwargs):
        seen["agent_kwargs"] = kwargs
        agent = MagicMock(name="agent")
        agent.llm.token_usage = {}

        def _gen(query):
            for _ in range(calls_per_run):
                # A workflow's nodes and a title or compression call build LLMs of their own.
                _call(_OwnerLLM(kwargs["decoded_token"]), "m", [{"role": "user", "content": query}], False, None)
            yield {"answer": "ok"}

        agent.gen.side_effect = _gen
        return agent

    def _executor(*_args, **kwargs):
        seen["executor"] = kwargs
        return MagicMock(headless_denials=[], cannot_complete=None)

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever",
                        classmethod(lambda cls, *a, **kw: MagicMock(search=MagicMock(return_value=[]))))
    monkeypatch.setattr(hr, "ToolExecutor", _executor)
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: _create(*a, **kw)))
    for target, value in (
        ("docsgpt.core.model_utils.validate_model_id", True),
        ("docsgpt.core.model_utils.get_provider_from_model_id", "openai"),
        ("docsgpt.core.model_utils.get_api_key_for_provider", "k"),
        ("docsgpt.utils.calculate_doc_token_budget", 1000),
    ):
        monkeypatch.setattr(target, MagicMock(return_value=value))
    return seen


def _rows(conn):
    return [
        dict(row._mapping)
        for row in conn.execute(
            text("SELECT user_id, api_key, request_id FROM token_usage WHERE agent_id = CAST(:a AS uuid)"),
            {"a": AGENT_ID},
        )
    ]


def _agent_row():
    return {"user_id": "owner", "id": AGENT_ID, "key": "agent-key", "default_model_id": "m", "agent_type": "classic"}


class TestScheduledRun:
    def test_bills_the_person_who_set_it_and_runs_as_the_owner(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        seen = _stub_runner(monkeypatch)
        run_agent_headless(_agent_row(), "report", endpoint="schedule", payer="setter")

        assert [row["user_id"] for row in _rows(db)] == ["setter"]
        # Runs as the owner: their sources, tools, prompt and model.
        assert seen["agent_kwargs"]["decoded_token"] == {"sub": "owner"}
        assert seen["executor"]["user"] == "owner"

    def test_every_call_of_a_workflow_run_bills_the_payer_as_one_request(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        _stub_runner(monkeypatch, calls_per_run=3)
        run_agent_headless(_agent_row(), "report", endpoint="schedule", payer="setter")

        rows = _rows(db)
        assert {row["user_id"] for row in rows} == {"setter"}
        assert len(rows) == 3 and len({row["request_id"] for row in rows}) == 1
        assert rows[0]["request_id"]


class TestWebhookRun:
    def test_bills_whoever_pays_for_the_agents_outside_traffic(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        _stub_runner(monkeypatch)
        run_agent_headless(_agent_row(), "{}", endpoint="webhook")

        assert [row["user_id"] for row in _rows(db)] == ["owner"]


class TestBackgroundContinuation:
    def test_a_teammates_chat_continues_on_the_teammates_bill(self, db, monkeypatch):
        """A teammate chats with a shared agent; the turn goes on in the background after the request ended."""
        from docsgpt.background import continuation

        seen = _stub_runner(monkeypatch)
        monkeypatch.setattr(continuation, "db_readonly", MagicMock())
        monkeypatch.setattr(continuation, "_agent_config", lambda *a: _agent_row())
        conversation = {"id": str(uuid.uuid4()), "user_id": "teammate", "agent_id": AGENT_ID}

        continuation._run_turn(conversation, [], [{"source": "job", "title": "done"}], message_id="m-1")

        assert [row["user_id"] for row in _rows(db)] == ["teammate"]
        assert seen["agent_kwargs"]["decoded_token"] == {"sub": "owner"}
