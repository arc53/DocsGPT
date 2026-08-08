"""Retrieved documents must survive the whole request path to the user turn.

The document-placement change was originally verified by constructing a
``ClassicAgent`` with ``retrieved_docs`` already populated, which skipped the
seam that actually carries them: retrieval -> ``StreamProcessor`` ->
``agent_kwargs`` -> ``BaseAgent._build_messages``. A break anywhere along it
looks exactly like "the model ignored my source", so it is pinned here.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from application.agents.classic_agent import ClassicAgent
from application.api.answer.services.stream_processor import StreamProcessor

DOCS = [
    {"text": "Clause 4: reporting is due within 30 days.", "filename": "aml.pdf"},
    {"text": "Clause 9: records are kept for five years.", "filename": "aml.pdf"},
]


def _processor(**data) -> StreamProcessor:
    """A processor with only the fields the retrieval seam touches."""
    sp = StreamProcessor.__new__(StreamProcessor)
    sp.data = {"question": "Summarize current context", **data}
    sp.agent_id = None
    sp.agent_config = {"prompt_id": "default", "agent_type": "classic"}
    sp.source = {"active_docs": "src-1"}
    sp.all_sources = [{"id": "src-1", "retrieval": None}]
    sp.retriever_config = {
        "retriever_name": "classic",
        "chunks": 2,
        "doc_token_limit": 50000,
    }
    sp.retrieved_docs = []
    return sp


@pytest.mark.unit
class TestRetrievalReachesTheAgent:
    def test_prefetch_populates_retrieved_docs(self):
        sp = _processor()
        retriever = MagicMock()
        retriever.search.return_value = DOCS
        retriever.chunks = 2
        retriever.doc_token_limit = 50000

        with patch.object(sp, "create_retriever", return_value=retriever):
            docs_together, docs = sp.pre_fetch_docs("Summarize current context")

        assert docs == DOCS
        assert docs_together and "Clause 4" in docs_together
        # This is the attribute agent_kwargs forwards; empty here means the
        # model silently answers with no source material.
        assert sp.retrieved_docs == DOCS

    def test_no_active_docs_retrieves_nothing(self):
        """The signature of a request that forgot to attach its source."""
        sp = _processor()
        sp.source = {}
        sp.all_sources = []

        docs_together, docs = sp.pre_fetch_docs("Summarize current context")

        assert docs is None and docs_together is None
        assert sp.retrieved_docs == []


@pytest.mark.unit
class TestDocumentsLandInTheUserTurn:
    def _agent(self, **kwargs):
        with patch("application.llm.llm_creator.LLMCreator.create_llm"), patch(
            "application.llm.handlers.handler_creator.LLMHandlerCreator.create_handler"
        ):
            return ClassicAgent(
                endpoint="stream",
                llm_name="openai",
                model_id="gpt-4o",
                api_key="k",
                prompt="SYSTEM",
                decoded_token={"sub": "u"},
                tool_executor=MagicMock(),
                **kwargs,
            )

    def test_documents_reach_the_user_turn(self):
        agent = self._agent(retrieved_docs=DOCS)
        messages = agent._build_messages("SYSTEM", "Summarize current context")

        system, user = messages[0]["content"], messages[-1]["content"]
        assert "Clause 4" not in system, "documents must not sit in the system prompt"
        assert "<documents>" in user and "Clause 4" in user and "Clause 9" in user
        assert user.rstrip().endswith("Summarize current context")

    def test_empty_retrieval_leaves_the_question_alone(self):
        agent = self._agent(retrieved_docs=[])
        user = agent._build_messages("SYSTEM", "Summarize current context")[-1]["content"]
        assert user == "Summarize current context"


@pytest.mark.unit
class TestChunksPrecedence:
    """A source that tuned its own top-k outranks the request body.

    The agentless path took ``chunks`` straight from the request, unbounded, so
    a client could both override an owner's tuning and ask for any number.
    """

    def _sp(self, request_chunks=None, source_chunks=None):
        from application.storage.db.source_config import RetrievalConfig

        sp = _processor()
        sp._agent_data = None
        sp.model_id = "gpt-4o"
        sp.model_user_id = None
        sp.agent_key = None
        if request_chunks is not None:
            sp.data["chunks"] = request_chunks
        retrieval = (
            RetrievalConfig(chunks=source_chunks) if source_chunks else RetrievalConfig()
        )
        sp.all_sources = [{"id": "src-1", "retrieval": retrieval}]
        sp._configure_retriever()
        return sp.retriever_config["chunks"]

    def test_request_applies_when_source_is_unconfigured(self):
        assert self._sp(request_chunks="7") == 7

    def test_configured_source_beats_the_request(self):
        assert self._sp(request_chunks="100", source_chunks=5) == 5

    @pytest.mark.parametrize(
        "sent,expected",
        [
            ("0", 0),  # 0 means "suppress retrieval" — must survive clamping
            ("-5", 0),
            ("100000", 500),
            ("501", 500),
            ("abc", 2),
        ],
    )
    def test_request_chunks_is_clamped(self, sent, expected):
        assert self._sp(request_chunks=sent) == expected

    def test_agent_chunks_is_clamped_too(self):
        """The agent path was unbounded even after the request path was fixed."""
        sp = _processor()
        sp._agent_data = {"chunks": 100000}
        sp.model_id = "gpt-4o"
        sp.model_user_id = None
        sp.agent_key = None
        sp.all_sources = []
        sp._configure_retriever()
        assert sp.retriever_config["chunks"] == 500
