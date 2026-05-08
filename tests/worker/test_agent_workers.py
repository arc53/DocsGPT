"""Smoke tests for ``agent_webhook_worker`` and ``run_agent_logic``.

Neither task writes to Postgres directly — they only *read* the agent
row (and, in ``run_agent_logic``, the referenced source row). The
concrete PG side-effect we assert is therefore a read: the task has
to resolve the row from the ephemeral DB to proceed at all; if the
lookup returned ``None`` the task would short-circuit with a
"not found" error.

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

        def _fake_run_agent_logic(agent_config, input_data):
            captured["config"] = agent_config
            captured["input"] = input_data
            return {"answer": "ok", "sources": [], "tool_calls": [], "thought": ""}

        monkeypatch.setattr(worker, "run_agent_logic", _fake_run_agent_logic)

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

    def test_missing_agent_raises(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        monkeypatch.setattr(worker, "run_agent_logic", lambda *a, **k: {})
        with pytest.raises(ValueError, match="not found"):
            worker.agent_webhook_worker(task_self, "no-such-agent", {})

    def test_run_agent_logic_failure_propagates(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            user_id="alice", name="hook-agent", status="active",
            agent_type="classic", retriever="classic", chunks=2, key="sk-test-123",
        )
        agent_id = str(agent["id"])

        def _boom(*a, **k):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(worker, "run_agent_logic", _boom)

        with pytest.raises(RuntimeError, match="LLM exploded"):
            worker.agent_webhook_worker(task_self, agent_id, {"event": "ping"})


@pytest.mark.unit
class TestRunAgentLogic:
    def test_reads_source_row_from_pg(
        self, pg_conn, patch_worker_db, monkeypatch
    ):
        """``run_agent_logic`` looks up the agent's ``source_id`` in PG to
        pick up the source's ``retriever`` override. Proving the read
        wires up end-to-end is enough for a smoke test."""
        from application import worker
        from application.storage.db.repositories.sources import SourcesRepository

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

        result = worker.run_agent_logic(agent_config, "hello")

        assert result["answer"] == "done"
        # Proves the PG read hit the seeded source and its id flowed into
        # the retriever's ``source={"active_docs": ...}`` param.
        assert captured_source.get("active_docs") == source_id
