"""Webhook and scheduled runs use an agent's sources the way a chat turn does.

The headless runner built every agent without a ``retriever_config``, so an
agentic or research agent had no ``internal_search`` tool, and it pre-fetched
every source with the raw run input (a webhook's whole JSON body) as the
query, which a chat turn of those agents never does.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

QUERY = '{"event": "push", "ref": "main"}'


def _source(source_id: str, exposure: str = "prefetch") -> dict:
    return {"id": source_id, "config": {"retrieval": {"exposure": exposure}}}


def _run(monkeypatch, agent_type: str, sources: list, prompt_id: str = "default") -> dict:
    """Run a headless agent over ``sources``; return what the run was built with."""
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}
    retriever = MagicMock(name="retriever")
    retriever.search.return_value = [{"text": "chunk", "source": "s"}]
    tool_executor = MagicMock(name="tool_executor")
    tool_executor.headless_denials = []
    seen: dict = {"dispatchers": [], "prompts": []}

    def _dispatcher(_legacy, sources=None, **kwargs):
        seen["dispatchers"].append({"sources": sources, "source": kwargs.get("source")})
        return retriever

    def _create_agent(cls, agent_type, **kwargs):
        seen["agent_type"] = agent_type
        seen["agent_kwargs"] = kwargs
        return agent

    def _get_prompt(pid):
        seen["prompts"].append(pid)
        return "system prompt"

    @contextmanager
    def _conn():
        yield MagicMock()

    monkeypatch.setattr(hr, "get_prompt", _get_prompt)
    monkeypatch.setattr(hr, "db_readonly", _conn)
    monkeypatch.setattr(hr, "authorized_agent_sources", lambda _c, _row: (sources[0], sources))
    monkeypatch.setattr(hr, "build_dispatcher", _dispatcher)
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(_create_agent))
    config = {
        "user_id": "owner-1", "id": "agent-1", "default_model_id": "m",
        "agent_type": agent_type, "prompt_id": prompt_id, "source_id": sources[0]["id"],
    }
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
         patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
         patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000), \
         patch("docsgpt.agents.headless_runner.QuotaService.check", return_value=None):
        hr.run_agent_headless(config, QUERY, endpoint="webhook")
    seen["searches"] = [c.args[0] for c in retriever.search.call_args_list]
    return seen


def _ids(entries) -> list:
    return [entry["id"] for entry in entries]


@pytest.mark.unit
class TestHeadlessAgenticSources:
    @pytest.mark.parametrize("agent_type", ["agentic", "research"])
    def test_gets_internal_search_over_every_source_and_no_prefetch(self, monkeypatch, agent_type):
        from docsgpt.agents.tools.internal_search import INTERNAL_TOOL_ID, add_internal_search_tool

        seen = _run(monkeypatch, agent_type, [_source("s1"), _source("s2"), _source("s3")])

        assert seen["searches"] == []
        assert seen["agent_kwargs"]["retrieved_docs"] == []
        config = seen["agent_kwargs"]["retriever_config"]
        assert _ids(config["sources"]) == ["s1", "s2", "s3"]
        assert config["source"] == {"active_docs": ["s1", "s2", "s3"]}
        assert config["agent_id"] == "agent-1"
        assert config["source_owner_id"] == "owner-1"
        tools: dict = {}
        add_internal_search_tool(tools, config)
        assert INTERNAL_TOOL_ID in tools

    def test_uses_the_agentic_prompt_preset(self, monkeypatch):
        seen = _run(monkeypatch, "agentic", [_source("s1")])
        assert seen["prompts"] == ["agentic_default"]

    def test_mixed_exposure_prefetches_only_prefetch_sources(self, monkeypatch):
        seen = _run(monkeypatch, "agentic", [_source("s1"), _source("s2", "agentic_tool")])

        assert seen["searches"] == [QUERY]
        prefetch = seen["dispatchers"][-1]
        assert _ids(prefetch["sources"]) == ["s1"]
        assert prefetch["source"] == {"active_docs": ["s1"]}
        config = seen["agent_kwargs"]["retriever_config"]
        assert _ids(config["sources"]) == ["s2"]
        assert config["source"] == {"active_docs": ["s2"]}


@pytest.mark.unit
class TestHeadlessClassicSources:
    def test_prefetches_every_source_and_adds_no_search_tool(self, monkeypatch):
        seen = _run(monkeypatch, "classic", [_source("s1"), _source("s2")])

        assert seen["searches"] == [QUERY]
        assert _ids(seen["dispatchers"][-1]["sources"]) == ["s1", "s2"]
        assert "retriever_config" not in seen["agent_kwargs"]
        assert seen["prompts"] == ["default"]

    def test_agentic_tool_sources_get_the_search_tool(self, monkeypatch):
        seen = _run(monkeypatch, "classic", [_source("s1"), _source("s2", "agentic_tool")])

        assert seen["searches"] == [QUERY]
        assert _ids(seen["dispatchers"][-1]["sources"]) == ["s1"]
        assert _ids(seen["agent_kwargs"]["retriever_config"]["sources"]) == ["s2"]
