"""Smoke tests for ``agent_webhook_worker`` (the shared headless runner).

``agent_webhook_worker`` doesn't write to Postgres directly — it only
*reads* the agent row. The concrete PG side-effect we assert is
therefore a read: the task has to resolve the row from the ephemeral
DB to proceed at all; if the lookup returned ``None`` the task would
short-circuit with a "not found" error.

The LLM, retriever, and agent factory are all stubbed — we only care
that the PG read path wires up correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.storage.db.repositories.agents import AgentsRepository


@pytest.mark.unit
class TestAgentWebhookWorker:
    def test_resolves_agent_by_uuid_and_runs_logic(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.agents import headless_runner

        agent = AgentsRepository(pg_conn).create(
            user_id="alice",
            name="hook-agent",
            status="active",
            agent_type="classic",
            retriever="classic",
            chunks=2,
            key="sk-test-123",
        )
        agent_id = str(agent["id"])

        # Capture the resolved agent_config + input; return a fake result.
        captured: dict = {}

        def _fake_run_agent_headless(agent_config, query, **kwargs):
            captured["config"] = agent_config
            captured["input"] = query
            captured["kwargs"] = kwargs
            return {
                "answer": "ok",
                "sources": [],
                "tool_calls": [],
                "thought": "",
                "prompt_tokens": 0,
                "generated_tokens": 0,
                "denied": [],
                "error_type": None,
                "model_id": "fake",
            }

        monkeypatch.setattr(
            headless_runner, "run_agent_headless", _fake_run_agent_headless,
        )

        result = worker.agent_webhook_worker(
            task_self, agent_id, {"event": "ping"}
        )

        assert result == {
            "status": "success",
            "result": {"answer": "ok", "sources": [], "tool_calls": [], "thought": ""},
        }
        # The row pulled from PG is the one we seeded.
        assert captured["config"]["name"] == "hook-agent"
        assert str(captured["config"]["id"]) == agent_id
        assert captured["input"] == '{"event": "ping"}'
        # Webhook caller should pass endpoint='webhook'.
        assert captured["kwargs"].get("endpoint") == "webhook"

    def test_missing_agent_raises(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.agents import headless_runner

        monkeypatch.setattr(
            headless_runner, "run_agent_headless", lambda *a, **k: {},
        )
        with pytest.raises(ValueError, match="not found"):
            worker.agent_webhook_worker(task_self, "no-such-agent", {})

    def test_agent_webhook_worker_propagates_runtime_errors(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        """Headless runner errors must raise — a returned dict reads as success."""
        from application import worker
        from application.agents import headless_runner
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            user_id="alice", name="hook-agent", status="active",
            agent_type="classic", retriever="classic", chunks=2, key="sk-test-123",
        )
        agent_id = str(agent["id"])

        def _boom(*a, **k):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(headless_runner, "run_agent_headless", _boom)

        with pytest.raises(RuntimeError, match="LLM exploded"):
            worker.agent_webhook_worker(task_self, agent_id, {"event": "ping"})

    def test_webhook_journals_headless_denial_for_approval_gated_tool(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        """Wire-through: approval-gated denial journals to tool_call_attempts."""
        from contextlib import contextmanager
        from types import SimpleNamespace

        from application import worker
        from application.agents import headless_runner
        from application.agents.tool_executor import ToolExecutor
        from application.llm.handlers.base import (
            LLMHandler,
            ToolCall,
        )
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            user_id="alice", name="hook-agent", status="active",
            agent_type="classic", retriever="classic", chunks=2,
            key="sk-deny-test",
        )
        agent_id = str(agent["id"])

        @contextmanager
        def _use_pg_conn():
            yield pg_conn

        monkeypatch.setattr(
            "application.agents.tool_executor.db_session", _use_pg_conn,
        )

        # Stub model resolution + retriever so the call threads through.
        monkeypatch.setattr(
            "application.core.model_utils.get_default_model_id",
            lambda: "gpt-4",
        )
        monkeypatch.setattr(
            "application.core.model_utils.validate_model_id",
            lambda m, **_kwargs: True,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda m, **_kwargs: "openai",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda p: "sk-test",
        )
        monkeypatch.setattr(
            "application.utils.calculate_doc_token_budget",
            lambda model_id=None, **_kwargs: 1000,
        )
        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.get_prompt",
            lambda prompt_id: "prompt text",
        )
        monkeypatch.setattr(
            "application.retriever.retriever_creator.RetrieverCreator.create_retriever",
            lambda *a, **kw: SimpleNamespace(search=lambda q: []),
        )

        # Approval-gated tool + an agent that funnels one call through handle_tool_calls.
        approval_tool_id = "tool-approval-gated"
        approval_tool_row = {
            "id": approval_tool_id,
            "name": "telegram",
            "actions": [
                {
                    "name": "send_message",
                    "active": True,
                    "require_approval": True,
                    "parameters": {"type": "object", "properties": {}},
                },
            ],
        }

        def _fake_agent_factory(*a, **kw):
            executor: ToolExecutor = kw["tool_executor"]
            tools_dict = {approval_tool_id: approval_tool_row}
            executor._name_to_tool = {
                "send_message": (approval_tool_id, "send_message"),
            }

            class _MockLLM:
                token_usage: dict = {}

            class _FakeAgent:
                def __init__(self):
                    self.tool_executor = executor
                    self.llm = _MockLLM()
                    self.conversation_id = None

                def gen(self, query):
                    # arguments must be a JSON string for the default OpenAI-shaped parser.
                    import json as _json
                    call = ToolCall(
                        id="webhook-denial-call",
                        name="send_message",
                        arguments=_json.dumps({"to": "x"}),
                    )

                    class _Handler(LLMHandler):
                        def parse_response(self, response):
                            return None

                        def create_tool_message(self, tool_call, result):
                            return {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": result,
                            }

                        def _iterate_stream(self, response):
                            yield from ()

                    handler = _Handler()
                    for evt in handler.handle_tool_calls(
                        self, [call], tools_dict, [],
                    ):
                        yield evt
                    yield {"answer": "ack"}

            return _FakeAgent()

        monkeypatch.setattr(
            "application.agents.agent_creator.AgentCreator.create_agent",
            _fake_agent_factory,
        )
        monkeypatch.setattr(headless_runner, "db_readonly", _use_pg_conn)

        result = worker.agent_webhook_worker(
            task_self, agent_id, {"event": "ping"}
        )

        assert result["status"] == "success"

        from sqlalchemy import text as sql_text

        row = pg_conn.execute(
            sql_text(
                "SELECT status, error FROM tool_call_attempts "
                "WHERE call_id = :cid"
            ),
            {"cid": "webhook-denial-call"},
        ).fetchone()
        assert row is not None, "denial must be journaled"
        assert row.status == "failed"
        assert (row.error or "").startswith("headless: ")


@pytest.mark.unit
class TestRunAgentHeadlessFromWebhook:
    def test_reads_source_row_from_pg(
        self, pg_conn, patch_worker_db, monkeypatch
    ):
        """Smoke-test that run_agent_headless reads the source row from PG."""
        from contextlib import contextmanager

        from application.agents import headless_runner
        from application.storage.db.repositories.sources import SourcesRepository

        @contextmanager
        def _use_pg_conn():
            yield pg_conn
        monkeypatch.setattr(headless_runner, "db_readonly", _use_pg_conn)

        src = SourcesRepository(pg_conn).create(
            "src",
            user_id="alice",
            type="local",
            retriever="hybrid",
        )
        source_id = str(src["id"])

        # Silence model/provider resolution so we don't need a real key.
        monkeypatch.setattr(
            "application.core.model_utils.get_default_model_id", lambda: "gpt-4"
        )
        monkeypatch.setattr(
            "application.core.model_utils.validate_model_id", lambda m, **_kwargs: True
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda m, **_kwargs: "openai",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda p: "sk-test",
        )
        monkeypatch.setattr(
            "application.utils.calculate_doc_token_budget",
            lambda model_id=None, **_kwargs: 1000,
        )
        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.get_prompt",
            lambda prompt_id: "prompt text",
        )

        # Retriever search returns no docs; agent gen yields a single answer
        # line so the aggregation loop runs through.
        captured_source: dict = {}

        class _FakeRetriever:
            def __init__(self, *args, **kwargs):
                captured_source.update(kwargs.get("source", {}))

            def search(self, query):
                return []

        monkeypatch.setattr(
            "application.retriever.retriever_creator.RetrieverCreator.create_retriever",
            lambda *a, **kw: _FakeRetriever(**kw),
        )

        fake_agent = MagicMock(name="agent")
        fake_agent.gen.return_value = iter([{"answer": "done"}])
        fake_agent.current_token_count = 0
        monkeypatch.setattr(
            "application.agents.agent_creator.AgentCreator.create_agent",
            lambda *a, **kw: fake_agent,
        )

        agent_config = {
            "id": "agent-uuid",
            "source_id": source_id,
            "user_id": "alice",
            "key": "sk-user",
            "agent_type": "classic",
            "chunks": 2,
            "prompt_id": "default",
        }

        outcome = headless_runner.run_agent_headless(agent_config, "hello")

        assert outcome["answer"] == "done"
        assert captured_source.get("active_docs") == source_id
