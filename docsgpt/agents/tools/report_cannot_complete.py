"""report_cannot_complete: a scheduled run says its task, or a step of it, can't be done.

A synthetic tool (no ``user_tools`` row), added only to scheduled runs whose
model can call tools. The executor notes a call's reason on itself
(``ToolExecutor.cannot_complete``) and the scheduler records the run as
failed with ``cannot_complete``, so a schedule that can never work pauses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from docsgpt.agents.tools.base import Tool

REPORT_CANNOT_COMPLETE_TOOL_ID = "report_cannot_complete"
REPORT_CANNOT_COMPLETE = "report_cannot_complete"


def add_report_cannot_complete_tool(tools_dict: Dict[str, Any]) -> bool:
    """Add the tool to a scheduled run's tools unless another tool already uses its name."""
    if REPORT_CANNOT_COMPLETE_TOOL_ID in tools_dict:
        return True
    tools = [t for t in tools_dict.values() if isinstance(t, dict)]
    if any(REPORT_CANNOT_COMPLETE in _action_names(t) for t in tools):
        return False
    actions = [{**meta, "active": True} for meta in ReportCannotCompleteTool().get_actions_metadata()]
    tools_dict[REPORT_CANNOT_COMPLETE_TOOL_ID] = {
        "id": REPORT_CANNOT_COMPLETE_TOOL_ID,
        "name": REPORT_CANNOT_COMPLETE,
        "actions": actions,
        "config": {},
    }
    return True


def _action_names(tool: Dict[str, Any]) -> List[str]:
    """A tool's action names; an API tool keeps its actions in its config."""
    names = [a.get("name") for a in tool.get("actions") or [] if isinstance(a, dict)]
    if tool.get("name") == "api_tool":
        names.extend((tool.get("config") or {}).get("actions") or {})
    return names


class ReportCannotCompleteTool(Tool):
    """Report Cannot Complete

    Tells the scheduler that this run's task, or a step it needs, cannot be done.
    """

    internal = True

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """The one action, with its reason argument."""
        return [
            {
                "name": REPORT_CANNOT_COMPLETE,
                "description": (
                    "Report that this scheduled task, or a step it needs, cannot be done with the tools, "
                    "accounts and access you have, so the schedule is marked as failing. Call it once, "
                    "only when a required step is impossible here, never for a step that merely found "
                    "nothing or a task you did."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "One line: the step that cannot be done and what is missing.",
                        }
                    },
                    "required": ["reason"],
                    "additionalProperties": False,
                },
            }
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """No configuration."""
        return {}

    def execute_action(self, action_name: str, **kwargs: Any) -> str:
        """Acknowledge the report; the executor records it."""
        if action_name != REPORT_CANNOT_COMPLETE:
            return f"Error: unknown action '{action_name}'."
        if not str(kwargs.get("reason") or "").strip():
            return "Error: reason is required."
        return (
            "Recorded: this run will be marked as not done. Now give your answer: say which step "
            "could not be done and why, and include anything you could still do."
        )
