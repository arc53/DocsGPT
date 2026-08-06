"""``run_agent_headless`` must not swallow the agent's error event.

Regression (prod 2026-08-06): ``Agent.gen`` signals a failed stream by
yielding ``{"type": "error", "error": ...}``. The activity logger consumes
that event (it is what produces ``activity_finished status=error
error_class=StreamError``), but the headless runner's event loop only looked
at the ``answer``/``sources``/``tool_calls``/``thought`` keys and dropped it.
A failed stream therefore returned normally with an empty answer and
``error_type=None``, and the scheduler recorded the run as ``success``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _run(events, monkeypatch):
    """Drive ``run_agent_headless`` over a canned agent event stream."""
    from application.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter(events)
    agent.llm.token_usage = {"prompt_tokens": 7, "generated_tokens": 0}

    retriever = MagicMock(name="retriever")
    retriever.search.return_value = []

    tool_executor = MagicMock(name="tool_executor")
    tool_executor.headless_denials = []

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(
        hr.RetrieverCreator, "create_retriever",
        classmethod(lambda cls, *a, **kw: retriever),
    )
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
    monkeypatch.setattr(
        hr.AgentCreator, "create_agent",
        classmethod(lambda cls, *a, **kw: agent),
    )

    with patch("application.core.model_utils.validate_model_id", return_value=True), \
         patch("application.core.model_utils.get_default_model_id", return_value="m"), \
         patch(
             "application.core.model_utils.get_provider_from_model_id",
             return_value="openai",
         ), \
         patch("application.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("application.utils.calculate_doc_token_budget", return_value=1000):
        return hr.run_agent_headless(
            {"user_id": "u1", "id": "agent-1", "default_model_id": "m"},
            "do the thing",
        )


@pytest.mark.unit
class TestHeadlessRunnerStreamError:
    def test_error_event_is_surfaced_as_error_type(self, monkeypatch):
        outcome = _run(
            [{"type": "error", "error": "Fallback LLM also failed mid-stream"}],
            monkeypatch,
        )

        assert outcome["error_type"] == "stream_error"
        assert "Fallback LLM also failed" in (outcome.get("error") or "")
        assert outcome["answer"] == ""

    def test_error_event_with_no_message_still_flags_failure(self, monkeypatch):
        """An empty message must not read as falsy and report success."""
        outcome = _run([{"type": "error"}], monkeypatch)

        assert outcome["error_type"] == "stream_error"
        assert outcome.get("error")

    def test_partial_answer_before_error_still_fails(self, monkeypatch):
        """Text already streamed does not make a broken run a success."""
        outcome = _run(
            [
                {"answer": "here is half an ans"},
                {"type": "error", "error": "peer closed"},
            ],
            monkeypatch,
        )

        assert outcome["answer"] == "here is half an ans"
        assert outcome["error_type"] == "stream_error"

    def test_clean_run_reports_no_error(self, monkeypatch):
        outcome = _run(
            [{"answer": "all good"}, {"sources": [{"title": "s"}]}],
            monkeypatch,
        )

        assert outcome["error_type"] is None
        assert outcome.get("error") is None
        assert outcome["answer"] == "all good"
        assert outcome["sources"] == [{"title": "s"}]
