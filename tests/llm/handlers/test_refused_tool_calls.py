"""A call the server refuses instead of pausing is kept on the message, worded for the turn it happened in."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.llm.handlers.base import LLMHandler, LLMResponse, ToolCall

SECRET_REFUSAL = (
    "This call contains {{link_secret:X3SWZB}}, a link secret reference, and memory never receives secrets. "
    "Nothing ran."
)


class _Handler(LLMHandler):
    def parse_response(self, response):
        return LLMResponse(content=str(response), tool_calls=[], finish_reason="stop", raw_response=response)

    def create_tool_message(self, tool_call, result):
        return {"role": "tool", "tool_call_id": tool_call.id, "content": result}

    def _iterate_stream(self, response):
        yield from response


def _refusal(**extra: Any) -> Dict[str, Any]:
    pause = {
        "call_id": "call-mem",
        "name": "memory_create",
        "tool_name": "memory",
        "tool_id": "t-mem",
        "action_name": "memory_create",
        "llm_name": "memory_create",
        "arguments": {"path": "/notes.md", "file_text": "secret {{link_secret:X3SWZB}}"},
        "pause_type": "headless_denied",
        "deny_reason": SECRET_REFUSAL,
        "error_type": "tool_not_allowed",
    }
    pause.update(extra)
    return pause


def _agent(executor: ToolExecutor, pause: Dict[str, Any]) -> Mock:
    agent = Mock()
    agent._check_context_limit = Mock(return_value=False)
    agent.context_limit_reached = False
    agent.llm.__class__.__name__ = "MockLLM"
    executor.check_pause = Mock(return_value=pause)
    agent.tool_executor = executor
    return agent


def _run(agent, call) -> tuple[List[Dict], List[Dict]]:
    gen = _Handler().handle_tool_calls(agent, [call], {"t-mem": {"name": "memory"}}, [])
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as stop:
            messages, _pending = stop.value
            return events, messages


@pytest.fixture()
def journal(monkeypatch):
    """Capture what the refusal journals instead of writing to Postgres."""
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr("docsgpt.agents.tool_executor._record_proposed", lambda *a, **k: True)
    monkeypatch.setattr(
        "docsgpt.agents.tool_executor._mark_failed",
        lambda call_id, error, **kwargs: rows.append({"call_id": call_id, "error": error}),
    )
    return rows


def _executor(*, headless: bool = False) -> ToolExecutor:
    executor = ToolExecutor(user="u-1", headless=headless)
    executor.message_id = "11111111-1111-1111-1111-111111111111"
    return executor


class TestRefusedCallInAnInteractiveTurn:
    def test_the_refused_call_is_kept_on_the_message_as_failed(self, journal):
        executor = _executor()
        call = ToolCall(id="call-mem", name="memory_create", arguments='{"path": "/notes.md"}')

        events, _ = _run(_agent(executor, _refusal()), call)

        (event,) = [e for e in events if e.get("type") == "tool_call"]
        assert event["data"]["status"] == "error"
        assert event["data"]["error"] == SECRET_REFUSAL
        (stored,) = executor.get_truncated_tool_calls()
        assert stored["call_id"] == "call-mem"
        assert stored["tool_name"] == "memory"
        assert stored["action_name"] == "memory_create"
        assert stored["status"] == "error"
        assert stored["error"] == SECRET_REFUSAL
        # The reference stays a reference: the arguments are kept as the model wrote them.
        assert stored["arguments"]["file_text"] == "secret {{link_secret:X3SWZB}}"
        assert stored["result"] == f"Tool denied: {SECRET_REFUSAL}"

    def test_no_headless_wording_in_an_interactive_turn(self, journal):
        executor = _executor()
        call = ToolCall(id="call-mem", name="memory_create", arguments="{}")

        _, messages = _run(_agent(executor, _refusal()), call)

        (row,) = journal
        assert row["error"] == f"denied: {SECRET_REFUSAL}"
        tool_message = messages[-1]
        assert tool_message["content"] == f"Tool denied: {SECRET_REFUSAL}"
        assert "headless" not in tool_message["content"]
        # Only a headless run collects denials for its run record.
        assert executor.headless_denials == []

    def test_the_trace_still_reads_denied(self, journal, monkeypatch):
        traced: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            "docsgpt.llm.handlers.base.trace_unexecuted_tool_call", lambda call, data, **kw: traced.append(data)
        )
        executor = _executor()

        _run(_agent(executor, _refusal()), ToolCall(id="call-mem", name="memory_create", arguments="{}"))

        (data,) = traced
        assert data["status"] == "denied"
        assert data["error"] == SECRET_REFUSAL


class TestRefusedCallInAHeadlessRun:
    def test_headless_wording_and_record(self, journal):
        executor = _executor(headless=True)
        reason = "This tool requires approval and is not in the run's tool_allowlist."
        call = ToolCall(id="call-mem", name="memory_create", arguments="{}")

        _, messages = _run(_agent(executor, _refusal(deny_reason=reason)), call)

        (row,) = journal
        assert row["error"] == f"headless: {reason}"
        assert messages[-1]["content"] == f"Tool denied (headless): {reason}"
        assert [d["call_id"] for d in executor.headless_denials] == ["call-mem"]
        (stored,) = executor.get_truncated_tool_calls()
        assert stored["status"] == "error"
        assert stored["error"] == reason


class TestRefusedCallInAResearchStep:
    def test_a_refused_step_call_is_kept_on_the_message(self, journal):
        from docsgpt.agents.research_agent import ResearchAgent

        executor = _executor()
        executor.check_pause = Mock(return_value=_refusal())
        agent = ResearchAgent.__new__(ResearchAgent)
        agent.llm = Mock()

        result, call_id = agent._refuse_paused_call(
            {"t-mem": {"name": "memory"}}, ToolCall(id="call-mem", name="memory_create", arguments="{}"), executor
        )

        assert call_id == "call-mem"
        assert result == f"Tool denied: {SECRET_REFUSAL}"
        (row,) = journal
        assert row["error"] == f"denied: {SECRET_REFUSAL}"
        (stored,) = executor.get_truncated_tool_calls()
        assert stored["status"] == "error"
        assert stored["error"] == SECRET_REFUSAL

    def test_an_approval_a_step_cannot_ask_for_is_kept_too(self, journal):
        from docsgpt.agents.research_agent import ResearchAgent

        executor = _executor()
        executor.check_pause = Mock(return_value=_refusal(pause_type="awaiting_approval", deny_reason=None))
        agent = ResearchAgent.__new__(ResearchAgent)
        agent.llm = Mock()

        result, _ = agent._refuse_paused_call(
            {"t-mem": {"name": "memory"}}, ToolCall(id="call-mem", name="memory_create", arguments="{}"), executor
        )

        (stored,) = executor.get_truncated_tool_calls()
        assert stored["status"] == "error"
        assert stored["result"] == result
        assert "approval" in stored["error"]

    @pytest.mark.parametrize(
        "pause",
        [
            {"pause_type": "awaiting_approval", "connection_required": {"connector_key": "github"}},
            {"pause_type": "requires_client_execution"},
        ],
    )
    def test_a_call_a_step_cannot_wait_for_is_kept_too(self, journal, pause):
        from docsgpt.agents.research_agent import ResearchAgent

        executor = _executor()
        executor.check_pause = Mock(return_value=_refusal(deny_reason=None, **pause))
        agent = ResearchAgent.__new__(ResearchAgent)
        agent.llm = Mock()

        result, _ = agent._refuse_paused_call(
            {"t-mem": {"name": "memory"}}, ToolCall(id="call-mem", name="memory_create", arguments="{}"), executor
        )

        assert result.startswith("Tool not run:")
        (stored,) = executor.get_truncated_tool_calls()
        assert stored["status"] == "error"
        assert stored["result"] == result
        assert stored["error"]
