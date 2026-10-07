"""``run_agent_headless`` searches with ``retrieval_query`` when it is given.

A webhook run hands the agent its whole JSON payload as input; searching
with that string drowned the query in JSON and blew up the embedder. The
caller now supplies a separate, bounded retrieval query.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _run(monkeypatch, query, **kwargs):
    """Run headless with everything stubbed; return what was searched and generated."""
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}
    retriever = MagicMock(name="retriever")
    retriever.search.return_value = []
    tool_executor = MagicMock(name="tool_executor")
    tool_executor.headless_denials = []

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(
        hr.RetrieverCreator, "create_retriever", classmethod(lambda cls, *a, **kw: retriever),
    )
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: agent))

    config = {"user_id": "u1", "id": "agent-1", "default_model_id": "m"}
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
         patch("docsgpt.core.model_utils.get_default_model_id", return_value="m"), \
         patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
         patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        hr.run_agent_headless(config, query, **kwargs)
    return retriever.search.call_args.args[0], agent.gen.call_args.kwargs["query"]


@pytest.mark.unit
class TestHeadlessRetrievalQuery:
    def test_retriever_receives_the_retrieval_query(self, monkeypatch):
        searched, generated = _run(
            monkeypatch, '{"pr": {"title": "Fix login"}}', retrieval_query="Fix login"
        )

        assert searched == "Fix login"
        assert generated == '{"pr": {"title": "Fix login"}}'

    def test_retriever_receives_the_query_otherwise(self, monkeypatch):
        searched, generated = _run(monkeypatch, "do the thing")

        assert searched == "do the thing"
        assert generated == "do the thing"
