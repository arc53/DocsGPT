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


def _run(events, monkeypatch, endpoint="headless", denied=None, executor_attrs=None, **agent_attrs):
    """Drive ``run_agent_headless`` over a canned agent event stream."""
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent", **agent_attrs)
    agent.gen.return_value = iter(events)
    agent.llm.token_usage = {"prompt_tokens": 7, "generated_tokens": 0}

    retriever = MagicMock(name="retriever")
    retriever.search.return_value = []

    tool_executor = MagicMock(name="tool_executor", **(executor_attrs or {}))
    tool_executor.headless_denials = list(denied or [])

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

    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
         patch("docsgpt.core.model_utils.get_default_model_id", return_value="m"), \
         patch(
             "docsgpt.core.model_utils.get_provider_from_model_id",
             return_value="openai",
         ), \
         patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        return hr.run_agent_headless(
            {"user_id": "u1", "id": "agent-1", "default_model_id": "m"},
            "do the thing",
            endpoint=endpoint,
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


_TOOL_CALL = {"type": "tool_call", "data": {"tool_name": "brave_search", "status": "completed"}}


@pytest.mark.unit
class TestHeadlessRunnerCannotComplete:
    def test_a_report_call_reaches_the_outcome(self, monkeypatch):
        outcome = _run(
            [{"answer": "I couldn't open the site: there is no browser tool."}],
            monkeypatch,
            endpoint="schedule",
            executor_attrs={"cannot_complete": "Step 1 (open the site): no browser tool"},
        )

        assert outcome["cannot_complete"] == "Step 1 (open the site): no browser tool"
        assert outcome["answer"] == "I couldn't open the site: there is no browser tool."
        assert outcome["error_type"] is None

    def test_a_marker_after_a_tool_call_is_read_from_the_last_round(self, monkeypatch):
        outcome = _run(
            [{"answer": "Let me check the site."}, _TOOL_CALL, {"answer": "CANNOT_COMPLETE: no browser tool"}],
            monkeypatch,
            endpoint="schedule",
        )

        assert outcome["cannot_complete"] == "no browser tool"
        assert outcome["answer"] == "Let me check the site.\n\nno browser tool"

    def test_a_marker_in_an_earlier_round_is_not_a_report(self, monkeypatch):
        outcome = _run(
            [{"answer": "CANNOT_COMPLETE: no data yet"}, _TOOL_CALL, {"answer": "Found it: all services are up."}],
            monkeypatch,
            endpoint="schedule",
        )

        assert outcome["cannot_complete"] is None
        assert outcome["answer"].startswith("CANNOT_COMPLETE: no data yet")

    def test_a_run_that_is_not_scheduled_reports_nothing(self, monkeypatch):
        outcome = _run(
            [{"answer": "CANNOT_COMPLETE: no browser tool"}],
            monkeypatch,
            executor_attrs={"cannot_complete": "no browser tool"},
        )

        assert outcome["cannot_complete"] is None
        assert outcome["answer"] == "CANNOT_COMPLETE: no browser tool"

    def test_a_refused_tool_is_recorded_rather_than_the_report(self, monkeypatch):
        outcome = _run(
            [{"answer": "I couldn't post the summary."}],
            monkeypatch,
            endpoint="schedule",
            denied=[{"tool_name": "telegram"}],
            executor_attrs={"cannot_complete": "no way to post the summary"},
        )

        assert outcome["error_type"] == "tool_not_allowed"
        assert "telegram" in outcome["error"]
        assert outcome["cannot_complete"] is None

    def test_a_refused_tool_with_a_full_answer_and_no_report_still_succeeds(self, monkeypatch):
        outcome = _run(
            [{"answer": "Posted nothing; here is the summary instead."}],
            monkeypatch,
            endpoint="schedule",
            denied=[{"tool_name": "telegram"}],
        )

        assert outcome["error_type"] is None

    def test_a_workflow_takes_what_its_engine_noted(self):
        from docsgpt.agents.headless_runner import _scheduled_cannot_complete

        agent = MagicMock(name="agent", cannot_complete="Mail: no email tool")
        executor = MagicMock(name="tool_executor", cannot_complete=None)

        assert _scheduled_cannot_complete(agent, executor, "workflow", "Prices fetched.", 0) == (
            "Mail: no email tool",
            "Prices fetched.",
        )
        # A workflow's answer is its nodes' text: a marker there was decided by the engine.
        quiet = MagicMock(name="agent", cannot_complete=None)
        assert _scheduled_cannot_complete(quiet, executor, "workflow", "CANNOT_COMPLETE: x", 0) == (
            None,
            "CANNOT_COMPLETE: x",
        )
