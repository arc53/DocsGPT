"""Tool sources: replaying one tool call, unattended, as the monitor's owner.

A ``tool`` source names any tool the chat has (an MCP action, an API tool,
``read_webpage``, ``remote_device.run_command``, a connector) and the exact
arguments to call it with. Every check replays that call with no LLM,
through a headless ``ToolExecutor`` built for the owner (and the
conversation's agent), so it gets the same tool resolution, credentials,
connections, fixed values and result sanitizing as a chat turn.

Approval is decided once, when the monitor is created (:func:`gate`): a call
that would need approval in chat makes ``monitor_create`` itself ask for it,
and the approval is bound to ``(tool, action, arguments-template hash)``.
A check may run that exact call unattended; the executor still re-decides
everything else on every check (a remote device's denylist and status, a
connection, an admin's write switch), and anything it refuses pauses the
monitor.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from docsgpt.monitors.checks import Content
from docsgpt.monitors.fetch import SourceError, SourceRevoked, SourceUnreachable, content_from_tool_result
from docsgpt.monitors.spec import SpecError, canonical_args_hash, split_tool_name, substitute

logger = logging.getLogger(__name__)

#: Tools a monitor can't use as its source: the scheduling and background
#: machinery itself, turn-scoped tools, and sandbox code (out of scope).
EXCLUDED_SOURCE_TOOLS = frozenset(
    {
        "monitor", "scheduler", "check_job", "view_image", "attachments",
        "code_executor", "artifact_generator", "read_document",
    }
)

_LLM_CLASS = "OpenAILLM"

_UNREACHABLE = re.compile(
    r"timed?\s?out|timeout|connection (refused|reset|error|aborted|closed)|could not connect|failed to connect|"
    r"unreachable|temporarily unavailable|service unavailable|bad gateway|gateway time|\b50[234]\b|\b429\b|"
    r"too many requests|did not respond|offline|name or service not known|max retries|remote end closed|"
    r"connecterror|readtimeout|network is",
    re.IGNORECASE,
)
_REVOKED = re.compile(r"device status: revoked|device not found|no longer available|not connected", re.IGNORECASE)


@dataclass
class ResolvedTool:
    """The tool call a source names, resolved in the owner's toolset."""

    key: str
    tool_data: Dict[str, Any]
    action: str
    llm_name: str

    @property
    def tool_id(self) -> str:
        return str(self.tool_data.get("id") or self.key)

    @property
    def tool_name(self) -> str:
        return str(self.tool_data.get("name") or "")


@dataclass
class Gate:
    """Whether a source call needs approval, or can't be a monitor source at all."""

    requires_approval: bool
    refusal: Optional[str] = None


def build_executor(
    user_id: str, agent_id: Optional[str], *, headless: bool, allowlist: Iterable[str] = ()
) -> Tuple[Any, Dict[str, Dict[str, Any]]]:
    """A ``ToolExecutor`` for the monitor's owner with the tools a source may name.

    Args:
        user_id: The owner.
        agent_id: The conversation's agent (its tools), or None for the user's own.
        headless: True for checks (nobody can approve); False at creation.
        allowlist: Tool ids whose approval-gated calls are pre-approved.

    Returns:
        ``(executor, tools)``, with the LLM names assigned.
    """
    from docsgpt.agents.tool_executor import ToolExecutor

    executor = ToolExecutor(
        user=user_id,
        decoded_token={"sub": user_id},
        agent_id=str(agent_id) if agent_id else None,
        headless=headless,
        tool_allowlist=list(allowlist),
    )
    tools = {
        key: data
        for key, data in executor.get_tools().items()
        if isinstance(data, dict) and data.get("name") not in EXCLUDED_SOURCE_TOOLS and not data.get("client_side")
    }
    executor.prepare_tools_for_llm(tools)
    return executor, tools


def _active_actions(tool_data: Dict[str, Any]) -> list:
    if tool_data.get("name") == "api_tool":
        actions = (tool_data.get("config") or {}).get("actions") or {}
        return [name for name, action in actions.items() if (action or {}).get("active", True)]
    return [a["name"] for a in tool_data.get("actions") or [] if isinstance(a, dict) and a.get("active", True)]


def _labels(tool_data: Dict[str, Any]) -> set:
    return {
        str(value).strip().lower()
        for value in (tool_data.get("name"), tool_data.get("display_name"), tool_data.get("custom_name"))
        if value
    }


def resolve_tool(executor: Any, tools: Dict[str, Dict[str, Any]], tool: str, action: Optional[str]) -> ResolvedTool:
    """Find the call a source names: a function name the chat sees, or a tool name plus action.

    Args:
        executor: The executor ``tools`` were prepared on.
        tools: The owner's source-eligible tools.
        tool: ``read_webpage``, ``remote_device.run_command``, ``remote_device`` + ``action`` ...
        action: The action, when ``tool`` names a tool.

    Returns:
        The resolved call.

    Raises:
        SpecError: Nothing (or more than one thing) matches.
    """
    tool_part, dotted_action = split_tool_name(tool)
    action = action or dotted_action
    for name in (tool, tool_part):
        mapped = executor._name_to_tool.get(name)
        if mapped and mapped[0] in tools and (name == tool or action is None or action == mapped[1]):
            return ResolvedTool(mapped[0], tools[mapped[0]], mapped[1], executor._tool_to_name[mapped])
    wanted = tool_part.lower()
    matches = [
        (key, act)
        for key, data in tools.items()
        if wanted in _labels(data)
        for act in _active_actions(data)
        if (action is None or act == action) and (key, act) in executor._tool_to_name
    ]
    if len(matches) == 1:
        key, act = matches[0]
        return ResolvedTool(key, tools[key], act, executor._tool_to_name[(key, act)])
    available = ", ".join(sorted(executor._name_to_tool)[:40]) or "(none)"
    if len(matches) > 1:
        names = ", ".join(sorted(executor._tool_to_name[m] for m in matches))
        raise SpecError(f"`source.tool` {tool!r} is ambiguous; use one of these function names: {names}.")
    raise SpecError(
        f"`source.tool` {tool!r} is not a tool this chat can call. Use the exact function name you would call "
        f"(available: {available})."
    )


def gate(executor: Any, tools: Dict[str, Dict[str, Any]], resolved: ResolvedTool, args: Dict[str, Any]) -> Gate:
    """Decide, as a chat turn would, whether the source call needs approval.

    Args:
        executor: A non-headless executor for the owner.
        tools: Its tools.
        resolved: The call.
        args: The arguments with placeholders substituted.

    Returns:
        The gate: approval needed, not needed, or refused outright (client
        tools, an unconnected service, writes an admin turned off, a
        command on the device's safety denylist).
    """
    from docsgpt.llm.handlers.base import ToolCall

    pause = executor.check_pause(tools, ToolCall(id="monitor-gate", name=resolved.llm_name, arguments=args), _LLM_CLASS)
    if pause is None:
        return Gate(False)
    kind = pause.get("pause_type")
    if kind == "headless_denied":
        return Gate(False, pause.get("deny_reason") or "this call is not allowed here")
    if kind == "requires_client_execution":
        return Gate(False, "a tool that runs in the client can't be watched; pick a server-side tool")
    if pause.get("connection_required"):
        name = (pause.get("connection_required") or {}).get("connector_name") or "the service"
        return Gate(False, f"{name} is not connected; ask the user to connect it in Settings > Connectors first")
    if resolved.tool_name == "remote_device":
        _requires, forced = executor._remote_device_requires_approval(resolved.tool_data, resolved.action, args)
        if forced:
            return Gate(False, "this command is on the device's safety denylist, so it can never run unattended")
    return Gate(True)


def binding(resolved: ResolvedTool, args_template: Dict[str, Any], decision: Gate, *, now_iso: str) -> Dict[str, Any]:
    """The stored ``approval``: which call a check may run, and whether that needed (and got) approval."""
    return {
        "tool_id": resolved.tool_id,
        "tool_name": resolved.tool_name,
        "action": resolved.action,
        "args_hash": canonical_args_hash(resolved.tool_id, resolved.action, args_template),
        "required": bool(decision.requires_approval),
        "approved_at": now_iso if decision.requires_approval else None,
    }


def _drive(generator) -> Any:
    """Run an ``execute`` generator to its return value, dropping its stream events."""
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            value = stop.value
            return value[0] if isinstance(value, tuple) else value


def classify_exception(exc: BaseException) -> SourceError:
    """An exception from a source call, as unreachable (skipped) or an error (counted)."""
    text = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, (TimeoutError, ConnectionError)) or _UNREACHABLE.search(text):
        return SourceUnreachable(text[:300])
    return SourceError(text[:300])


def classify_result(tool_name: str, result: Any, status: str) -> None:
    """Raise when a tool's in-band result reports a failure (a non-zero exit code is content, not one).

    Raises:
        SourceRevoked: The device or tool is gone (revoked pairing, removed device).
        SourceUnreachable: Offline, timeout, 5xx, 429.
        SourceError: Any other reported failure.
    """
    message: Optional[str] = None
    if isinstance(result, dict):
        code = result.get("status_code")
        if isinstance(code, int) and not isinstance(code, bool):
            if code == 429 or code >= 500:
                raise SourceUnreachable(f"{tool_name} answered HTTP {code}")
            if code >= 400:
                raise SourceError(f"{tool_name} answered HTTP {code}")
        if result.get("error") or result.get("status") == "error":
            message = str(result.get("error") or result.get("message") or "the tool reported an error")
    elif isinstance(result, str) and re.match(r"\s*(error\b|failed to\b)", result, re.IGNORECASE):
        message = result.strip()
    elif status == "error":
        message = "the tool reported an error"
    if message is None:
        return
    message = message[:300]
    if _REVOKED.search(message):
        raise SourceRevoked(message)
    if _UNREACHABLE.search(message):
        raise SourceUnreachable(message)
    raise SourceError(message)


def run_call(
    *,
    user_id: str,
    agent_id: Optional[str],
    conversation_id: Optional[str],
    approval: Dict[str, Any],
    args_template: Dict[str, Any],
    placeholders: Dict[str, Any],
    call_tag: str,
) -> Content:
    """Replay a tool source's call once, unattended, and normalize its result.

    Args:
        user_id: The owner the call runs as.
        agent_id: The conversation's agent, or None.
        conversation_id: The conversation (tools that scope by it see it).
        approval: The stored binding (tool id, action, args hash, required).
        args_template: The source's arguments as created (placeholders unreplaced).
        placeholders: ``now`` / ``last_checked_at`` / ``last_changed_at`` for substitution.
        call_tag: A short tag for the call id (the monitor id).

    Returns:
        The normalized content.

    Raises:
        SourceRevoked: The tool, action or approval no longer covers this call.
        SourceUnreachable: The source could not be reached.
        SourceError: The call failed otherwise.
    """
    from docsgpt.llm.handlers.base import ToolCall

    tool_id = str(approval.get("tool_id") or "")
    action = str(approval.get("action") or "")
    expected = canonical_args_hash(tool_id, action, args_template)
    if approval.get("args_hash") != expected:
        raise SourceRevoked("the source's arguments no longer match what was approved")
    allowlist = [tool_id] if approval.get("required") else []
    executor, tools = build_executor(user_id, agent_id, headless=True, allowlist=allowlist)
    key = next((k for k, data in tools.items() if str(data.get("id") or k) == tool_id), None)
    if key is None:
        raise SourceRevoked(f"the tool {approval.get('tool_name') or tool_id} is no longer available")
    llm_name = executor._tool_to_name.get((key, action))
    if llm_name is None:
        raise SourceRevoked(f"the action {action} is no longer available")
    args = substitute(args_template, **placeholders)
    call = ToolCall(id=f"monitor-{call_tag[:8]}-{uuid.uuid4().hex[:12]}", name=llm_name, arguments=args)
    denied = executor.check_pause(tools, call, _LLM_CLASS)
    if denied is not None:
        raise SourceRevoked(denied.get("deny_reason") or "the call is no longer allowed unattended")
    if conversation_id:
        executor.conversation_id = str(conversation_id)
    tool_name = str(tools[key].get("name") or "")
    try:
        result = _drive(executor.execute(tools, call, _LLM_CLASS))
    except SourceError:
        raise
    except Exception as exc:
        logger.info("monitor %s: source call failed: %s", call_tag, type(exc).__name__)
        raise classify_exception(exc) from None
    status = (executor.tool_calls[-1].get("status") if executor.tool_calls else None) or "completed"
    classify_result(tool_name, result, status)
    return content_from_tool_result(tool_name, result)
