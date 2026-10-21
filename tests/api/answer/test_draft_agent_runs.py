"""A request that names a draft agent runs that agent, not an agentless chat.

A draft has no API key yet. ``/api/answer`` and ``/stream`` read an agent's
prompt, model, type, sources and tools only through its key, so a draft
named by ``agent_id`` answered with the default model and prompt, the
owner's chat tools, and a conversation saved with no ``agent_id``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

OWNER = "owner-1"
AGENT_MODEL = "agent-model"


def _seed(pg_engine, agent_type: str = "agentic") -> dict:
    """A draft agent (agentic by default) with a custom prompt, one source and no tools."""
    from docsgpt.storage.db.repositories.agents import AgentsRepository
    from docsgpt.storage.db.repositories.prompts import PromptsRepository
    from docsgpt.storage.db.repositories.sources import SourcesRepository
    from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

    with pg_engine.begin() as conn:
        prompt = PromptsRepository(conn).create(OWNER, "p", "You are the draft agent's prompt.")
        source = SourcesRepository(conn).create("docs", user_id=OWNER)
        UserToolsRepository(conn).create(user_id=OWNER, name="telegram", status=True)
        agent = AgentsRepository(conn).create(
            user_id=OWNER,
            name="draft",
            status="draft",
            agent_type=agent_type,
            prompt_id=str(prompt["id"]),
            source_id=str(source["id"]),
            default_model_id=AGENT_MODEL,
            tools=[],
        )
    assert agent.get("key") is None
    return {"agent": agent, "prompt": prompt, "source": source}


def _fake_agent() -> MagicMock:
    agent = MagicMock(name="agent")
    agent.gen.side_effect = lambda *a, **kw: iter([{"answer": "hello"}])
    agent.apply_input_guardrails = lambda question: (question, None)
    agent.guardrails_config = {}
    agent.compression_metadata = None
    agent.compression_saved = False
    agent.tool_executor.tool_calls = []
    agent.tool_executor.get_truncated_tool_calls.return_value = []
    return agent


@pytest.mark.unit
class TestDraftAgentThroughAnswerRoute:
    @staticmethod
    def _answer(pg_engine, monkeypatch, seeded: dict) -> tuple:
        """Ask the draft one question through ``/api/answer``; return the response and the agent kwargs."""
        from flask import Flask, request

        from docsgpt.api.answer.routes.answer import AnswerResource
        from docsgpt.api.answer.services import stream_processor as sp

        agent_id = str(seeded["agent"]["id"])

        built: dict = {}

        def _create_agent(cls, agent_type, **kwargs):
            built.update(kwargs, agent_type=agent_type)
            return _fake_agent()

        monkeypatch.setattr(sp.AgentCreator, "create_agent", classmethod(_create_agent))
        monkeypatch.setattr(sp, "validate_model_id", lambda model_id, user_id=None: model_id == AGENT_MODEL)
        monkeypatch.setattr(sp, "get_default_model_id", lambda: "default-model")
        monkeypatch.setattr(sp, "get_provider_from_model_id", lambda *a, **kw: "openai")
        monkeypatch.setattr(sp, "get_api_key_for_provider", lambda *a, **kw: "k")
        monkeypatch.setattr(sp, "calculate_doc_token_budget", lambda **kw: 1000)
        monkeypatch.setattr("docsgpt.llm.llm_creator.LLMCreator.create_llm", lambda *a, **kw: MagicMock())

        app = Flask(__name__)
        body = {"question": "hi", "agent_id": agent_id, "isNoneDoc": True}
        with app.test_request_context("/api/answer", method="POST", json=body), \
                patch("docsgpt.api.answer.routes.base.QuotaService.check", return_value=None):
            request.decoded_token = {"sub": OWNER}
            response = AnswerResource().post()
        return response, built

    def test_draft_agent_runs_as_itself(self, pg_engine, monkeypatch):
        monkeypatch.setattr("docsgpt.storage.db.session.get_engine", lambda: pg_engine)
        seeded = _seed(pg_engine)
        agent_id = str(seeded["agent"]["id"])
        response, built = self._answer(pg_engine, monkeypatch, seeded)

        assert response.status_code == 200, response.get_data(as_text=True)
        payload = json.loads(response.get_data(as_text=True))

        assert built["agent_type"] == "agentic"
        assert built["model_id"] == AGENT_MODEL
        assert "You are the draft agent's prompt." in built["prompt"]
        # Agentic agents search their sources through internal_search.
        tool_sources = [entry["id"] for entry in built["retriever_config"]["sources"]]
        assert tool_sources == [str(seeded["source"]["id"])]
        assert built["tool_executor"].get_tools() == {}

        with pg_engine.connect() as conn:
            saved = conn.execute(
                text("SELECT agent_id FROM conversations WHERE id = CAST(:id AS uuid)"),
                {"id": payload["conversation_id"]},
            ).scalar()
        assert str(saved) == agent_id

    def test_draft_with_blank_type_runs_as_classic(self, pg_engine, monkeypatch):
        # Legacy drafts carried Mongo's ``""`` over in the backfill.
        monkeypatch.setattr("docsgpt.storage.db.session.get_engine", lambda: pg_engine)
        seeded = _seed(pg_engine, agent_type="")
        response, built = self._answer(pg_engine, monkeypatch, seeded)

        assert response.status_code == 200, response.get_data(as_text=True)
        assert built["agent_type"] == "classic"
