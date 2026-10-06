"""The ``background`` argument the model sees on tools that may run as background jobs.

Added to a tool's schema only in a turn that can hand calls off, and only on
tools where a long call is plausible, so ordinary tool schemas stay as they
were. Every server-side call is handed off on its own once it outlives the
yield window; ``background=true`` only frees the turn at once.
"""

from __future__ import annotations

from typing import Any, Dict

#: Tools offered an explicit ``background`` argument.
BACKGROUND_PARAM_TOOLS = frozenset({"code_executor", "mcp_tool", "api_tool", "read_webpage"})

_GENERIC = (
    "Run this call as a background job and return a job id at once; you are resumed with the result when it "
    "ends. Use it for work you expect to take more than a minute. A call that runs long becomes a background "
    "job on its own anyway."
)

_CODE = (
    "Run this code as a background job and return a job id at once; you are resumed with the result when it "
    "ends. Use it for long runs (renders, big conversions, OCR of many pages); without a `timeout` it may run up "
    "to the job maximum. A run that takes long becomes a background job on its own anyway. A background run is "
    "a separate process: on a session that keeps variables between calls it does not see them, only the files."
)


WATCH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": (
        "For a run that may go long: what its output may do before it ends. Completion and failure always "
        "resume you, so only add patterns for events worth acting on mid-run."
    ),
    "properties": {
        "patterns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Regexes (up to 5) that resume you while it runs, e.g. `Traceback|Killed`.",
        },
        "progress_regex": {
            "type": "string",
            "description": "Regex for progress lines shown to the user, e.g. `PROGRESS (\\d+)%` (group 1 = percent).",
        },
        "heartbeat_s": {
            "type": "integer",
            "description": "Every N seconds (0 = off, at least 60) resume you with the output printed since.",
        },
    },
}


def add_background_params(tool_name: str, params: Dict[str, Any]) -> None:
    """Offer ``background`` on a tool's parameter schema (in place).

    Args:
        tool_name: The tool's name.
        params: The JSON schema of one action's parameters.
    """
    if tool_name not in BACKGROUND_PARAM_TOOLS:
        return
    properties = params.setdefault("properties", {})
    if "background" in properties:
        return
    properties["background"] = {
        "type": "boolean",
        "description": _CODE if tool_name == "code_executor" else _GENERIC,
    }
    if tool_name == "code_executor" and "watch" not in properties:
        properties["watch"] = WATCH_SCHEMA
