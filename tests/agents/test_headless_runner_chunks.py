"""``run_agent_headless`` passes the agent's ``chunks`` to the retriever.

``chunks=0`` switches retrieval off, but ``int(... or 2)`` read it as unset,
so a scheduled run of an agent with retrieval off retrieved anyway.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _retriever_chunks(agent_config, monkeypatch):
    """The ``chunks`` a headless run hands to the retriever."""
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}

    retriever = MagicMock(name="retriever")
    retriever.search.return_value = []
    created = {}

    def create_retriever(cls, *args, **kwargs):
        created.update(kwargs)
        return retriever

    tool_executor = MagicMock(name="tool_executor")
    tool_executor.headless_denials = []

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(
        hr.RetrieverCreator, "create_retriever", classmethod(create_retriever),
    )
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
    monkeypatch.setattr(
        hr.AgentCreator, "create_agent",
        classmethod(lambda cls, *a, **kw: agent),
    )

    config = {"user_id": "u1", "id": "agent-1", "default_model_id": "m", **agent_config}
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
         patch("docsgpt.core.model_utils.get_default_model_id", return_value="m"), \
         patch(
             "docsgpt.core.model_utils.get_provider_from_model_id",
             return_value="openai",
         ), \
         patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        hr.run_agent_headless(config, "do the thing")
    return created["chunks"]


@pytest.mark.unit
class TestHeadlessRunnerChunks:
    def test_unset_chunks_uses_the_default(self, monkeypatch):
        assert _retriever_chunks({}, monkeypatch) == 6

    def test_null_chunks_uses_the_default(self, monkeypatch):
        assert _retriever_chunks({"chunks": None}, monkeypatch) == 6

    def test_zero_chunks_keeps_retrieval_off(self, monkeypatch):
        assert _retriever_chunks({"chunks": 0}, monkeypatch) == 0

    def test_explicit_chunks_is_kept(self, monkeypatch):
        assert _retriever_chunks({"chunks": 4}, monkeypatch) == 4
