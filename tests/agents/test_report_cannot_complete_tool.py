"""The tool a scheduled run calls to say its task, or a step of it, can't be done."""

from types import SimpleNamespace

import pytest

from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.agents.tools.report_cannot_complete import (
    REPORT_CANNOT_COMPLETE,
    ReportCannotCompleteTool,
    add_report_cannot_complete_tool,
)
from docsgpt.background.handoff import NEVER_BACKGROUND_TOOLS


def _call(tool_name: str, status: str = "completed", **arguments) -> dict:
    """A recorded tool call."""
    return {"tool_name": tool_name, "action_name": tool_name, "arguments": arguments, "status": status}


@pytest.mark.unit
class TestAddTool:
    def test_it_joins_a_runs_tools_once(self):
        tools_dict = {}

        assert add_report_cannot_complete_tool(tools_dict) is True
        assert add_report_cannot_complete_tool(tools_dict) is True
        entry = tools_dict["report_cannot_complete"]
        assert entry["name"] == REPORT_CANNOT_COMPLETE
        assert [a["name"] for a in entry["actions"]] == [REPORT_CANNOT_COMPLETE]
        assert entry["actions"][0]["active"] is True
        assert entry["actions"][0]["parameters"]["required"] == ["reason"]

    def test_a_tool_with_an_action_of_that_name_keeps_it(self):
        tools_dict = {"mcp": {"name": "mcp_tool", "actions": [{"name": REPORT_CANNOT_COMPLETE}]}}

        assert add_report_cannot_complete_tool(tools_dict) is False
        assert list(tools_dict) == ["mcp"]

    def test_it_never_runs_in_the_background(self):
        assert REPORT_CANNOT_COMPLETE in NEVER_BACKGROUND_TOOLS


@pytest.mark.unit
class TestTool:
    def test_a_report_is_acknowledged(self):
        result = ReportCannotCompleteTool().execute_action(REPORT_CANNOT_COMPLETE, reason="no browser tool")

        assert result.startswith("Recorded")

    def test_a_report_needs_a_reason(self):
        assert ReportCannotCompleteTool().execute_action(REPORT_CANNOT_COMPLETE, reason=" ").startswith("Error")


@pytest.mark.unit
class TestExecutorNotesTheReport:
    def test_the_first_report_that_ran_is_kept(self):
        executor = ToolExecutor()

        executor._note_cannot_complete(_call("brave_search", query="status"))
        executor._note_cannot_complete(_call(REPORT_CANNOT_COMPLETE, status="error", reason="broken call"))
        executor._note_cannot_complete(_call(REPORT_CANNOT_COMPLETE, reason="Step 1 (open the site):\n no browser"))
        executor._note_cannot_complete(_call(REPORT_CANNOT_COMPLETE, reason="later report"))

        assert executor.cannot_complete == "Step 1 (open the site): no browser"

    def test_a_report_without_a_reason_is_not_kept(self):
        executor = ToolExecutor()

        executor._note_cannot_complete(_call(REPORT_CANNOT_COMPLETE, reason=""))

        assert executor.cannot_complete is None

    def test_a_call_run_through_the_executor_is_noted(self, monkeypatch):
        executor = ToolExecutor()

        def fake_execute(tools_dict, call, llm_class_name):
            executor.tool_calls.append(_call(REPORT_CANNOT_COMPLETE, reason="no email tool"))
            yield {"type": "tool_call", "data": {}}
            return "Recorded", call.id

        monkeypatch.setattr(executor, "_execute", fake_execute)
        list(executor.execute({}, SimpleNamespace(id="c1", name=REPORT_CANNOT_COMPLETE, arguments={}), "MockLLM"))

        assert executor.cannot_complete == "no email tool"
