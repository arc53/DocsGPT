"""An empty retrieval must be visible to both the model and the client.

Two independent suppressions made "searched your sources, found nothing"
indistinguishable from "no source was attached": the ``source`` SSE event was
skipped when the list was empty, and the prompt said nothing at all. Together
they let a retrieval failure surface as a confident, ungrounded answer.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from application.agents.classic_agent import ClassicAgent


def _agent(**kwargs):
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


@pytest.mark.unit
class TestEmptyRetrievalNote:
    def test_searched_sources_with_no_hits_tells_the_model(self):
        agent = _agent(retrieved_docs=[], sources_were_searched=True)
        user = agent._build_messages("SYSTEM", "What is the rebate?")[-1]["content"]

        assert "were searched" in user
        assert user.rstrip().endswith("What is the rebate?")

    def test_no_sources_attached_stays_silent(self):
        """Nothing was searched, so there is nothing to report."""
        agent = _agent(retrieved_docs=[], sources_were_searched=False)
        user = agent._build_messages("SYSTEM", "What is the rebate?")[-1]["content"]

        assert user == "What is the rebate?"

    def test_documents_found_suppresses_the_note(self):
        agent = _agent(
            retrieved_docs=[{"filename": "a.pdf", "text": "the rebate is 4250"}],
            sources_were_searched=True,
        )
        user = agent._build_messages("SYSTEM", "What is the rebate?")[-1]["content"]

        assert "were searched" not in user
        assert "<documents>" in user
