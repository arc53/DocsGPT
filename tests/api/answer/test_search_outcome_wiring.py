"""A chat turn's pre-fetch hands the agent which sources failed to search.

Without it the agent can only say "nothing relevant was found", which is what
every answer said while the embeddings worker was down.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.api.answer.services.stream_processor import StreamProcessor
from docsgpt.retriever.base import SearchOutcome


def _processor() -> StreamProcessor:
    sp = StreamProcessor.__new__(StreamProcessor)
    sp.data = {"question": "Summarize test-1"}
    sp.agent_id = None
    sp.agent_config = {"prompt_id": "default", "agent_type": "classic"}
    sp.source = {"active_docs": ["src-1", "src-2"]}
    sp.all_sources = [{"id": "src-1", "retrieval": None}, {"id": "src-2", "retrieval": None}]
    sp.retriever_config = {"retriever_name": "classic", "chunks": 2, "doc_token_limit": 50000}
    sp.retrieved_docs = []
    return sp


@pytest.mark.unit
class TestPrefetchRecordsTheOutcome:
    def test_the_retrievers_outcome_is_kept(self):
        sp = _processor()
        retriever = MagicMock()
        retriever.search.return_value = []
        retriever.last_outcome = SearchOutcome.of(["src-1", "src-2"], ["src-2"])

        with patch.object(sp, "create_retriever", return_value=retriever):
            assert sp.pre_fetch_docs("Summarize test-1") == (None, None)

        assert sp.search_outcome == SearchOutcome(("src-1", "src-2"), ("src-2",))

    def test_a_retrieval_that_raises_fails_every_source(self):
        sp = _processor()

        with patch.object(sp, "create_retriever", side_effect=RuntimeError("pool exhausted")):
            assert sp.pre_fetch_docs("Summarize test-1") == (None, None)

        assert sp.search_outcome == SearchOutcome(("src-1", "src-2"), ("src-1", "src-2"))

    def test_a_retriever_without_an_outcome_counts_every_source_searched(self):
        sp = _processor()
        sp.source = {"active_docs": "src-1"}
        retriever = MagicMock(spec=["search", "chunks", "doc_token_limit"])
        retriever.search.return_value = []

        with patch.object(sp, "create_retriever", return_value=retriever):
            sp.pre_fetch_docs("Summarize test-1")

        assert sp.search_outcome == SearchOutcome(("src-1",), ())


@pytest.mark.unit
def test_create_agent_forwards_the_outcome():
    sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
    sp._get_prompt_content = MagicMock(return_value="SYSTEM")
    sp.agent_config = {"agent_type": "classic", "prompt_id": "custom", "user_api_key": None}
    sp.model_id = "m1"
    sp.source = {"active_docs": ["src-1"]}
    sp.prompt_renderer = MagicMock()
    sp.prompt_renderer.render_prompt.return_value = "rendered"
    sp.search_outcome = SearchOutcome.of(["src-1"], ["src-1"])
    agent_kwargs = {}

    def capture(_agent_type, **kwargs):
        agent_kwargs.update(kwargs)
        return MagicMock()

    with patch(
        "docsgpt.api.answer.services.stream_processor.get_provider_from_model_id", return_value="openai"
    ), patch(
        "docsgpt.api.answer.services.stream_processor.get_api_key_for_provider", return_value="key"
    ), patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()), patch(
        "docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler", return_value=MagicMock()
    ), patch(
        "docsgpt.agents.agent_creator.AgentCreator.create_agent", side_effect=capture
    ), patch.object(StreamProcessor, "_enabled_tool_names", return_value=set()):
        sp.create_agent()

    assert agent_kwargs["search_outcome"] == SearchOutcome(("src-1",), ("src-1",))
    assert agent_kwargs["sources_were_searched"] is True
