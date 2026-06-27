import logging
import re
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from application.agents.default_tools import (
    is_headless_excluded_tool,
    resolve_tool_by_id,
    synthesized_default_tools,
)
from application.agents.tools.tool_action_parser import ToolActionParser
from application.agents.tools.tool_manager import ToolManager
from application.security.encryption import decrypt_credentials
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.tool_call_attempts import (
    ToolCallAttemptsRepository,
)
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)


# Tightest provider limit on function-call names (OpenAI: ^[a-zA-Z0-9_-]{1,64}$).
_MAX_LLM_NAME_LEN = 64


def _sanitize_tool_prefix(tool_name: Optional[str]) -> str:
    """Reduce a tool name to characters allowed in function-call names."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(tool_name or "")).strip("_")


# Longest string value rendered into a debug log line; longer values (e.g. an
# LLM-authored ``code`` body or an api_tool ``body``) are truncated so the full
# program/secret is never written to logs even at DEBUG level.
_LOG_VALUE_PREVIEW_LEN = 80


def _redact_args_for_log(args: Any) -> Any:
    """Truncate long string values so a code/body argument never lands in logs in full."""
    if not isinstance(args, dict):
        text = str(args)
        return text if len(text) <= _LOG_VALUE_PREVIEW_LEN else f"{text[:_LOG_VALUE_PREVIEW_LEN]}...(truncated)"
    redacted: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > _LOG_VALUE_PREVIEW_LEN:
            redacted[key] = f"{value[:_LOG_VALUE_PREVIEW_LEN]}...(truncated, {len(value)} chars)"
        elif isinstance(value, (dict, list)):
            redacted[key] = f"<{type(value).__name__} omitted>"
        else:
            redacted[key] = value
    return redacted


def _record_proposed(
    call_id: str,
    tool_name: str,
    action_name: str,
    arguments: Any,
    *,
    tool_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> bool:
    """Insert a ``proposed`` row; swallow infra failures so tool calls
    still run when the journal is unreachable. Returns True iff THIS call
    created the row.

    A duplicate ``call_id`` (LLMs reuse "call_0"-style ids) hits
    ``ON CONFLICT DO NOTHING`` and returns False: the existing row may
    belong to another in-flight request, so callers must not then flip it
    via ``_mark_failed`` / ``_mark_executed``.
    """
    try:
        with db_session() as conn:
            inserted = ToolCallAttemptsRepository(conn).record_proposed(
                call_id,
                tool_name,
                action_name,
                arguments,
                tool_id=tool_id if tool_id and looks_like_uuid(tool_id) else None,
                message_id=message_id,
                user_id=user_id,
                agent_id=(
                    str(agent_id)
                    if agent_id and looks_like_uuid(str(agent_id))
                    else None
                ),
            )
        if not inserted:
            logger.warning(
                "tool_call_attempts duplicate call_id=%s; existing row left in place",
                call_id,
                extra={"alert": "tool_call_id_collision", "call_id": call_id},
            )
        return inserted
    except Exception:
        logger.exception("tool_call_attempts proposed write failed for %s", call_id)
        return False


def _mark_executed(
    call_id: str,
    result: Any,
    *,
    message_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    proposed_ok: bool = True,
    tool_name: Optional[str] = None,
    action_name: Optional[str] = None,
    arguments: Any = None,
    tool_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> None:
    """Flip the row to ``executed``. If ``proposed_ok`` is False (the
    proposed write failed earlier), upsert a fresh row in ``executed`` so
    the reconciler can still see the attempt — without this, the side
    effect would be invisible to the journal. Both paths are scoped to
    the owning ``user_id`` so a reused ``call_id`` can't cross tenants.
    """
    try:
        with db_session() as conn:
            repo = ToolCallAttemptsRepository(conn)
            if proposed_ok:
                updated = repo.mark_executed(
                    call_id,
                    result,
                    message_id=message_id,
                    artifact_id=artifact_id,
                    user_id=user_id,
                )
                if updated:
                    return
            # Fallback synthesizes the row so the journal isn't lost.
            repo.upsert_executed(
                call_id,
                tool_name=tool_name or "unknown",
                action_name=action_name or "",
                arguments=arguments if arguments is not None else {},
                result=result,
                tool_id=tool_id if tool_id and looks_like_uuid(tool_id) else None,
                message_id=message_id,
                artifact_id=artifact_id,
                user_id=user_id,
                agent_id=(
                    str(agent_id)
                    if agent_id and looks_like_uuid(str(agent_id))
                    else None
                ),
            )
    except Exception:
        logger.exception("tool_call_attempts executed write failed for %s", call_id)


def _mark_failed(call_id: str, error: str, *, user_id: Optional[str] = None) -> None:
    try:
        with db_session() as conn:
            ToolCallAttemptsRepository(conn).mark_failed(
                call_id, error, user_id=user_id
            )
    except Exception:
        logger.exception("tool_call_attempts failed-write failed for %s", call_id)


class ToolExecutor:
    """Handles tool discovery, preparation, and execution.

    Extracted from BaseAgent to separate concerns and enable tool caching.
    """

    def __init__(
        self,
        user_api_key: Optional[str] = None,
        user: Optional[str] = None,
        decoded_token: Optional[Dict] = None,
        agent_id: Optional[str] = None,
        *,
        headless: bool = False,
        tool_allowlist: Optional[List[str]] = None,
    ):
        self.user_api_key = user_api_key
        self.user = user
        self.decoded_token = decoded_token
        self.agent_id = agent_id
        # Headless mode (scheduled / webhook): no human to resolve a pause,
        # so check_pause returns headless_denied sentinels instead.
        self.headless = bool(headless)
        # Tool-instance ids pre-authorized for headless approval-gated execution.
        self.tool_allowlist: set = (
            {str(x) for x in tool_allowlist} if tool_allowlist else set()
        )
        self.tool_calls: List[Dict] = []
        self._loaded_tools: Dict[str, object] = {}
        self.conversation_id: Optional[str] = None
        # Set by the workflow engine for agent nodes so run-scoped tools
        # (artifact_generator / code_executor) address artifacts by the
        # workflow run rather than a conversation.
        self.workflow_run_id: Optional[str] = None
        self.message_id: Optional[str] = None
        # The request's own (already user-scoped) chat attachments, stamped onto
        # sandbox tools so a referenced attachment can be lazily bridged to a
        # conversation-scoped artifact at tool-use time.
        self.attachments: List[Dict] = []
        self.client_tools: Optional[List[Dict]] = None
        self._name_to_tool: Dict[str, Tuple[str, str]] = {}
        self._tool_to_name: Dict[Tuple[str, str], str] = {}
        # Filled by the LLMHandler.handle_tool_calls headless loop.
        self.headless_denials: List[Dict] = []

    def get_tools(self) -> Dict[str, Dict]:
        """Load tool configs from DB based on user context.

        If *client_tools* have been set on this executor, they are
        automatically merged into the returned dict.
        """
        if self.user_api_key:
            tools = self._get_tools_by_api_key(self.user_api_key)
        else:
            tools = self._get_user_tools(self.user or "local")
        if self.client_tools:
            self.merge_client_tools(tools, self.client_tools)
        return tools

    def _get_tools_by_api_key(self, api_key: str) -> Dict[str, Dict]:
        """Resolve an agent's toolset — exactly ``agents.tools``, no defaults."""
        # Per-operation session: the answer pipeline spans a long-lived
        # generator; wrapping it in a single connection would pin a PG
        # conn for the whole stream. Open, fetch, close.
        with db_readonly() as conn:
            agent_data = AgentsRepository(conn).find_by_key(api_key)
            tool_ids = agent_data.get("tools", []) if agent_data else []
            tools_repo = UserToolsRepository(conn)
            owner = (
                (agent_data.get("user_id") or agent_data.get("user"))
                if agent_data
                else None
            )
            tools: List[Dict] = []
            for tid in tool_ids:
                row = resolve_tool_by_id(tid, owner, user_tools_repo=tools_repo)
                if row is None:
                    continue
                # Headless runs (scheduled / webhook) drop chat-only tools
                # like ``scheduler`` so a fire-time LLM can't chain schedules.
                if self.headless and is_headless_excluded_tool(row.get("name")):
                    continue
                tools.append(row)
        return {str(tool["id"]): tool for tool in tools}

    def _get_user_tools(self, user: str = "local") -> Dict[str, Dict]:
        """Resolve an agentless chat's toolset: explicit user tools plus defaults."""
        with db_readonly() as conn:
            user_tools = UserToolsRepository(conn).list_active_for_user(user)
            user_doc = (
                UsersRepository(conn).get(user) if self.agent_id is None else None
            )
        # Headless agentless runs (e.g. scheduled fire) drop chat-only
        # tools (``scheduler``) from explicit user_tools too.
        filtered_user_tools = [
            t for t in user_tools
            if not (self.headless and is_headless_excluded_tool(t.get("name")))
        ]
        # Index keys (ints) and synthetic uuid5 keys can't collide.
        tools: Dict[str, Dict] = {
            str(i): tool for i, tool in enumerate(filtered_user_tools)
        }
        if self.agent_id is None:
            for default_row in synthesized_default_tools(
                user_doc, headless=self.headless,
            ):
                tools[str(default_row["id"])] = default_row
        return tools

    def merge_client_tools(
        self, tools_dict: Dict, client_tools: List[Dict]
    ) -> Dict:
        """Merge client-provided tool definitions into tools_dict.

        Client tools use the standard function-calling format::

            [{"type": "function", "function": {"name": "get_weather",
              "description": "...", "parameters": {...}}}]

        They are stored in *tools_dict* with ``client_side: True`` so that
        :meth:`check_pause` returns a pause signal instead of trying to
        execute them server-side.

        Args:
            tools_dict: The mutable server tools dict (will be modified in place).
            client_tools: List of tool definitions in function-calling format.

        Returns:
            The updated *tools_dict* (same reference, for convenience).
        """
        for i, ct in enumerate(client_tools):
            func = ct.get("function", ct)  # tolerate bare {"name":..} too
            name = func.get("name", f"clienttool{i}")
            tool_id = f"ct{i}"

            tools_dict[tool_id] = {
                "name": name,
                "client_side": True,
                "actions": [
                    {
                        "name": name,
                        "description": func.get("description", ""),
                        "active": True,
                        "parameters": func.get("parameters", {}),
                    }
                ],
            }
        return tools_dict

    def prepare_tools_for_llm(self, tools_dict: Dict) -> List[Dict]:
        """Convert tool configs to LLM function schemas.

        Action names are kept clean for the LLM:
        - Unique action names appear as-is (e.g. ``get_weather``).
        - Duplicate action names are disambiguated with the owning tool's
          name (e.g. ``brave_search``, ``duckduckgo_search``); a numeric
          suffix only breaks ties between same-named tools.
        - Every name is clamped to the 64-character provider limit.

        A reverse mapping is stored in ``_name_to_tool`` so that tool calls
        can be routed back to the correct ``(tool_id, action_name)`` without
        brittle string splitting.
        """
        # Pass 1: collect entries and count action name occurrences
        # (tool_id, tool_name, action_name, action, is_client)
        entries: List[Tuple[str, str, str, Dict, bool]] = []
        name_counts: Counter = Counter()

        for tool_id, tool in tools_dict.items():
            is_api = tool["name"] == "api_tool"
            is_client = tool.get("client_side", False)

            if is_api and "actions" not in tool.get("config", {}):
                continue
            if not is_api and "actions" not in tool:
                continue

            actions = (
                tool["config"]["actions"].values()
                if is_api
                else tool["actions"]
            )

            for action in actions:
                if not action.get("active", True):
                    continue
                entries.append(
                    (tool_id, tool.get("name", ""), action["name"], action, is_client)
                )
                name_counts[action["name"]] += 1

        # Pass 2: assign LLM-visible names and build mappings
        self._name_to_tool = {}
        self._tool_to_name = {}
        all_llm_names: set = set()

        result = []
        for tool_id, tool_name, action_name, action, is_client in entries:
            if (
                name_counts[action_name] == 1
                and len(action_name) <= _MAX_LLM_NAME_LEN
            ):
                llm_name = action_name
            else:
                # An over-long unique name skips the prefix — it needs
                # truncation, not disambiguation.
                prefix = (
                    _sanitize_tool_prefix(tool_name)
                    if name_counts[action_name] > 1
                    else ""
                )
                base = (
                    f"{prefix}_{action_name}"
                    if prefix and not action_name.startswith(f"{prefix}_")
                    else action_name
                )
                base = base[:_MAX_LLM_NAME_LEN]
                # A duplicated bare name stays ambiguous, and a candidate
                # must not steal a unique action's name or one already taken.
                candidate = base
                counter = 1
                while (
                    candidate == action_name
                    or candidate in all_llm_names
                    or name_counts.get(candidate, 0) == 1
                ):
                    suffix = f"_{counter}"
                    candidate = base[: _MAX_LLM_NAME_LEN - len(suffix)] + suffix
                    counter += 1
                llm_name = candidate

            all_llm_names.add(llm_name)
            self._name_to_tool[llm_name] = (tool_id, action_name)
            self._tool_to_name[(tool_id, action_name)] = llm_name

            if is_client:
                params = action.get("parameters", {})
            else:
                params = self._build_tool_parameters(action)

            result.append({
                "type": "function",
                "function": {
                    "name": llm_name,
                    "description": action.get("description", ""),
                    "parameters": params,
                },
            })
        return result

    def _build_tool_parameters(self, action: Dict) -> Dict:
        params = {"type": "object", "properties": {}, "required": []}
        for param_type in ["query_params", "headers", "body", "parameters"]:
            if param_type in action and action[param_type].get("properties"):
                for k, v in action[param_type]["properties"].items():
                    if v.get("filled_by_llm", True):
                        params["properties"][k] = {
                            key: value
                            for key, value in v.items()
                            if key not in ("filled_by_llm", "value", "required")
                        }
                        if v.get("required", False):
                            params["required"].append(k)
        return params

    def check_pause(
        self, tools_dict: Dict, call, llm_class_name: str
    ) -> Optional[Dict]:
        """Return a pending-action dict (approval / client / headless_denied) or None.

        In headless mode the dict's pause_type is ``headless_denied`` so the
        upstream loop synthesizes a tool result instead of pausing (nothing can
        resume a scheduled / webhook run).
        """
        parser = ToolActionParser(llm_class_name, name_mapping=self._name_to_tool)
        tool_id, action_name, call_args = parser.parse_args(call)
        call_id = getattr(call, "id", None) or str(uuid.uuid4())
        llm_name = getattr(call, "name", "")

        if tool_id is None or action_name is None or tool_id not in tools_dict:
            return None  # Will be handled as error by execute()

        tool_data = tools_dict[tool_id]
        arguments = call_args if isinstance(call_args, dict) else {}

        # Client-side tools
        if tool_data.get("client_side"):
            if self.headless:
                return {
                    "call_id": call_id,
                    "name": llm_name,
                    "tool_name": tool_data.get("name", "unknown"),
                    "tool_id": tool_id,
                    "action_name": action_name,
                    "llm_name": llm_name,
                    "arguments": arguments,
                    "pause_type": "headless_denied",
                    "deny_reason": (
                        "Client-side tools cannot run in headless / scheduled runs."
                    ),
                    "error_type": "tool_not_allowed",
                    "thought_signature": getattr(call, "thought_signature", None),
                }
            return {
                "call_id": call_id,
                "name": llm_name,
                "tool_name": tool_data.get("name", "unknown"),
                "tool_id": tool_id,
                "action_name": action_name,
                "llm_name": llm_name,
                "arguments": arguments,
                "pause_type": "requires_client_execution",
                "thought_signature": getattr(call, "thought_signature", None),
            }

        # Approval required
        if tool_data["name"] == "api_tool":
            action_data = tool_data.get("config", {}).get("actions", {}).get(
                action_name, {}
            )
        else:
            action_data = next(
                (a for a in tool_data.get("actions", []) if a["name"] == action_name),
                {},
            )

        require_approval = bool(action_data.get("require_approval"))
        # ``denylist_forced`` marks a prompt the hard denylist mandates; a
        # headless allowlist must never bypass it (see below).
        denylist_forced = False
        # ``remote_device`` decides per-invocation based on the live device
        # state (``approval_mode``, sticky patterns, allow/denylist). The
        # cached ``user_tools.actions[].require_approval`` snapshot does
        # not reflect later approval-mode changes nor command-level
        # heuristics, so consult the tool directly.
        if tool_data.get("name") == "remote_device":
            require_approval, denylist_forced = (
                self._remote_device_requires_approval(
                    tool_data, action_name, arguments,
                )
            )
        elif tool_data.get("name") == "code_executor":
            # The deployment-level ``config.require_approval`` is authoritative
            # over the cached action snapshot, so consult the tool directly.
            require_approval = self._code_executor_requires_approval(
                tool_data, action_name, arguments,
            ) or require_approval

        if require_approval:
            if self.headless:
                tool_row_id = str(tool_data.get("id") or tool_id)
                # A denylist-forced prompt is never pre-authorizable: a
                # scheduled/headless run with the device allowlisted must
                # still be denied a denylisted command. Only non-forced
                # approvals honor the allowlist bypass.
                if tool_row_id in self.tool_allowlist and not denylist_forced:
                    # Pre-authorized for headless execution — fall through.
                    return None
                return {
                    "call_id": call_id,
                    "name": llm_name,
                    "tool_name": tool_data.get("name", "unknown"),
                    "tool_id": tool_id,
                    "action_name": action_name,
                    "llm_name": llm_name,
                    "arguments": arguments,
                    "pause_type": "headless_denied",
                    "deny_reason": (
                        "This tool requires approval and is not in the run's "
                        "tool_allowlist."
                    ),
                    "error_type": "tool_not_allowed",
                    "thought_signature": getattr(call, "thought_signature", None),
                }
            payload = {
                "call_id": call_id,
                "name": llm_name,
                "tool_name": tool_data.get("name", "unknown"),
                "tool_id": tool_id,
                "action_name": action_name,
                "llm_name": llm_name,
                "arguments": arguments,
                "pause_type": "awaiting_approval",
                "thought_signature": getattr(call, "thought_signature", None),
            }
            # Surface the device id so the approval UI can offer a
            # "don't ask again" sticky-pattern action for remote devices.
            if tool_data.get("name") == "remote_device":
                config = tool_data.get("config") or {}
                if config.get("device_id"):
                    payload["device_id"] = config["device_id"]
            return payload

        return None

    def _remote_device_requires_approval(
        self, tool_data: Dict, action_name: str, arguments: Dict,
    ) -> tuple[bool, bool]:
        """Live approval decision for a ``remote_device`` invocation.

        Instantiates ``RemoteDeviceTool`` with the cached config and the
        executor's user context, then asks it to evaluate the command.
        Returns ``(requires_approval, denylist_forced)``. Falls back to a
        denylist-forced prompt on any error so a misconfigured device never
        silently bypasses the prompt — not even via the headless allowlist.
        """
        try:
            from application.agents.tools.remote_device import RemoteDeviceTool

            tool = RemoteDeviceTool(
                config=tool_data.get("config") or {},
                user_id=self.user,
            )
            return tool.preview_decision(action_name, arguments)
        except Exception:
            logger.exception(
                "remote_device preview_decision failed; defaulting to a "
                "forced prompt",
            )
            return True, True

    def _code_executor_requires_approval(
        self, tool_data: Dict, action_name: str, arguments: Dict,
    ) -> bool:
        """Live approval decision for a ``code_executor`` invocation.

        Honors the deployment-level ``config.require_approval`` even when the
        cached action snapshot is stale. Fails closed (require approval) on any
        error so a misconfigured tool never silently runs untrusted code.
        """
        try:
            from application.agents.tools.code_executor import CodeExecutorTool

            tool = CodeExecutorTool(
                tool_config=tool_data.get("config") or {},
                user_id=self.user,
            )
            requires_approval, _forced = tool.preview_decision(action_name, arguments)
            return requires_approval
        except Exception:
            logger.exception(
                "code_executor preview_decision failed; defaulting to a prompt",
            )
            return True

    def execute(self, tools_dict: Dict, call, llm_class_name: str):
        """Execute a tool call. Yields status events, returns (result, call_id)."""
        parser = ToolActionParser(llm_class_name, name_mapping=self._name_to_tool)
        tool_id, action_name, call_args = parser.parse_args(call)
        llm_name = getattr(call, "name", "unknown")

        call_id = getattr(call, "id", None) or str(uuid.uuid4())

        if tool_id is None or action_name is None:
            error_message = f"Error: Failed to parse LLM tool call. Tool name: {llm_name}"
            logger.error(
                "tool_call_parse_failed",
                extra={
                    "llm_class_name": llm_class_name,
                    "llm_tool_name": llm_name,
                    "call_id": call_id,
                },
            )

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": llm_name,
                "arguments": call_args or {},
                "result": f"Failed to parse tool call. Invalid tool name format: {llm_name}",
            }
            # Journal the malformed call so it still shows up in tool analytics.
            if _record_proposed(
                call_id,
                "unknown",
                llm_name or "unknown",
                call_args if isinstance(call_args, dict) else {},
                message_id=self.message_id,
                user_id=self.user,
                agent_id=self.agent_id,
            ):
                _mark_failed(
                    call_id, tool_call_data["result"], user_id=self.user
                )
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return "Failed to parse tool call.", call_id

        if tool_id not in tools_dict:
            error_message = f"Error: Tool ID '{tool_id}' extracted from LLM call not found in available tools_dict. Available IDs: {list(tools_dict.keys())}"
            logger.error(
                "tool_id_not_found",
                extra={
                    "tool_id": tool_id,
                    "llm_tool_name": llm_name,
                    "call_id": call_id,
                    "available_tool_count": len(tools_dict),
                },
            )

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": llm_name,
                "arguments": call_args,
                "result": f"Tool with ID {tool_id} not found. Available tools: {list(tools_dict.keys())}",
            }
            # Journal the unresolvable call so it still shows up in tool analytics.
            if _record_proposed(
                call_id,
                "unknown",
                llm_name or "unknown",
                call_args if isinstance(call_args, dict) else {},
                message_id=self.message_id,
                user_id=self.user,
                agent_id=self.agent_id,
            ):
                _mark_failed(
                    call_id,
                    f"Tool with ID {tool_id} not found.",
                    user_id=self.user,
                )
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return f"Tool with ID {tool_id} not found.", call_id

        tool_call_data = {
            "tool_name": tools_dict[tool_id]["name"],
            "call_id": call_id,
            "action_name": llm_name,
            "arguments": call_args,
        }
        tool_data = tools_dict[tool_id]
        # Surface the device id on remote_device tool-call events so the
        # approval UI can wire up the sticky "don't ask again" button.
        if tool_data.get("name") == "remote_device":
            config = tool_data.get("config") or {}
            if config.get("device_id"):
                tool_call_data["device_id"] = config["device_id"]
        # Journal first so the reconciler sees malformed calls and any
        # subsequent ``_mark_failed`` actually updates a real row.
        proposed_ok = _record_proposed(
            call_id,
            tool_data["name"],
            action_name,
            call_args if isinstance(call_args, dict) else {},
            tool_id=tool_data.get("id"),
            message_id=self.message_id,
            user_id=self.user,
            agent_id=self.agent_id,
        )
        # Defensive guard: a non-dict ``call_args`` (e.g. malformed
        # JSON on the resume path) would crash the param walk below
        # with AttributeError on ``.items()``. Surface a clean error
        # event and flip the journal row to ``failed`` instead of
        # killing the stream.
        if not isinstance(call_args, dict):
            error_message = (
                f"Tool call arguments must be a JSON object, got "
                f"{type(call_args).__name__}."
            )
            tool_call_data["result"] = error_message
            tool_call_data["arguments"] = {}
            if proposed_ok:
                _mark_failed(call_id, error_message, user_id=self.user)
            yield {
                "type": "tool_call",
                "data": {**tool_call_data, "status": "error"},
            }
            self.tool_calls.append(tool_call_data)
            return error_message, call_id
        yield {"type": "tool_call", "data": {**tool_call_data, "status": "pending"}}
        action_data = (
            tool_data["config"]["actions"][action_name]
            if tool_data["name"] == "api_tool"
            else next(
                action
                for action in tool_data["actions"]
                if action["name"] == action_name
            )
        )

        query_params, headers, body, parameters = {}, {}, {}, {}
        param_types = {
            "query_params": query_params,
            "headers": headers,
            "body": body,
            "parameters": parameters,
        }

        for param_type, target_dict in param_types.items():
            if param_type in action_data and action_data[param_type].get("properties"):
                for param, details in action_data[param_type]["properties"].items():
                    if (
                        param not in call_args
                        and "value" in details
                        and details["value"]
                    ):
                        target_dict[param] = details["value"]
        for param, value in call_args.items():
            for param_type, target_dict in param_types.items():
                if param_type in action_data and param in action_data[param_type].get(
                    "properties", {}
                ):
                    target_dict[param] = value

        # Load tool (with caching)
        tool = self._get_or_load_tool(
            tool_data, tool_id, action_name,
            headers=headers, query_params=query_params,
        )

        if tool is None:
            error_message = (
                f"Failed to load tool '{tool_data.get('name')}' (tool_id key={tool_id}): "
                "missing 'id' on tool row."
            )
            logger.error(
                "tool_load_failed",
                extra={
                    "tool_name": tool_data.get("name"),
                    "tool_id": tool_id,
                    "action_name": action_name,
                    "call_id": call_id,
                },
            )
            tool_call_data["result"] = error_message
            if proposed_ok:
                _mark_failed(call_id, error_message, user_id=self.user)
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return error_message, call_id

        resolved_arguments = (
            {"query_params": query_params, "headers": headers, "body": body}
            if tool_data["name"] == "api_tool"
            else parameters
        )
        try:
            if tool_data["name"] == "api_tool":
                logger.debug(
                    "Executing api: %s with query_params: %s, headers: %s, body: %s",
                    action_name,
                    _redact_args_for_log(query_params),
                    _redact_args_for_log(headers),
                    _redact_args_for_log(body),
                )
                result = tool.execute_action(action_name, **body)
            else:
                logger.debug(
                    "Executing tool: %s with args: %s",
                    action_name,
                    _redact_args_for_log(call_args),
                )
                result = tool.execute_action(action_name, **parameters)
        except Exception as exc:
            if proposed_ok:
                _mark_failed(call_id, str(exc), user_id=self.user)
            raise

        get_artifact_id = (
            getattr(tool, "get_artifact_id", None)
            if tool_data["name"] != "api_tool"
            else None
        )

        artifact_id = None
        if callable(get_artifact_id):
            try:
                artifact_id = get_artifact_id(action_name, **parameters)
            except Exception:
                logger.exception(
                    "Failed to extract artifact_id from tool %s for action %s",
                    tool_data["name"],
                    action_name,
                )

        artifact_id = str(artifact_id).strip() if artifact_id is not None else ""
        if artifact_id:
            tool_call_data["artifact_id"] = artifact_id
        result_full = str(result)
        tool_call_data["resolved_arguments"] = resolved_arguments
        tool_call_data["result_full"] = result_full
        tool_call_data["result"] = (
            f"{result_full[:50]}..." if len(result_full) > 50 else result_full
        )

        # Tool side effect has run; flip the journal row so the
        # message-finalize path can later confirm it. If the proposed
        # write failed (DB outage), upsert a fresh row in ``executed`` so
        # the reconciler still sees the side effect.
        _mark_executed(
            call_id,
            result_full,
            message_id=self.message_id,
            artifact_id=artifact_id or None,
            proposed_ok=proposed_ok,
            tool_name=tool_data["name"],
            action_name=action_name,
            arguments=call_args,
            tool_id=tool_data.get("id"),
            user_id=self.user,
            agent_id=self.agent_id,
        )

        stream_tool_call_data = {
            key: value
            for key, value in tool_call_data.items()
            if key not in {"result_full", "resolved_arguments"}
        }
        yield {"type": "tool_call", "data": {**stream_tool_call_data, "status": "completed"}}
        self.tool_calls.append(tool_call_data)

        return result, call_id

    def _get_or_load_tool(
        self, tool_data: Dict, tool_id: str, action_name: str,
        headers: Optional[Dict] = None, query_params: Optional[Dict] = None,
    ):
        """Load a tool, using cache when possible."""
        cache_key = f"{tool_data['name']}:{tool_id}:{self.user or ''}"
        if cache_key in self._loaded_tools:
            cached = self._loaded_tools[cache_key]
            # A tool cached on an earlier turn carries that turn's attachments;
            # refresh them so a chat attachment added this turn is bridgeable.
            cached_config = getattr(cached, "config", None)
            if isinstance(cached_config, dict) and self.conversation_id:
                # Refresh unconditionally so a turn with no attachments clears the
                # prior turn's list (no stale carryover within the session).
                cached_config["attachments"] = self.attachments or []
            return cached

        tm = ToolManager(config={})

        if tool_data["name"] == "api_tool":
            action_config = tool_data["config"]["actions"][action_name]
            tool_config = {
                "url": action_config["url"],
                "method": action_config["method"],
                "headers": headers or {},
                "query_params": query_params or {},
            }
            if "body_content_type" in action_config:
                tool_config["body_content_type"] = action_config.get(
                    "body_content_type", "application/json"
                )
                tool_config["body_encoding_rules"] = action_config.get(
                    "body_encoding_rules", {}
                )
        else:
            tool_config = tool_data["config"].copy() if tool_data["config"] else {}
            # Credentials are PBKDF2-bound to the tool OWNER's sub, not the
            # invoker's. Decrypt with the tool row's user_id so a team member
            # running an owner's shared tool authenticates with the owner's
            # credentials (deliberate delegation — see teams-spec OQ2), and so
            # the long-standing agent-key path (tools resolved by owner) stops
            # silently decrypt-failing. Falls back to self.user for the
            # agentless path where the tool row carries no user_id.
            tool_owner = tool_data.get("user_id") or self.user
            if tool_config.get("encrypted_credentials") and tool_owner:
                if tool_owner != self.user:
                    # Credential delegation: the invoker is running a shared
                    # tool with the owner's secrets. Audit it (the agent-run
                    # authorization upstream is the access boundary).
                    logger.info(
                        "tool_credential_delegation",
                        extra={
                            "invoker": self.user,
                            "tool_owner": tool_owner,
                            "tool_id": str(tool_data.get("id") or tool_id),
                            "tool_name": tool_data.get("name"),
                            "agent_id": self.agent_id,
                        },
                    )
                decrypted = decrypt_credentials(
                    tool_config["encrypted_credentials"], tool_owner
                )
                tool_config.update(decrypted)
                tool_config["auth_credentials"] = decrypted
                tool_config.pop("encrypted_credentials", None)
            row_id = tool_data.get("id")
            if not row_id:
                logger.error(
                    "tool_missing_row_id",
                    extra={
                        "tool_name": tool_data.get("name"),
                        "tool_id": tool_id,
                        "action_name": action_name,
                    },
                )
                return None
            tool_config["tool_id"] = str(row_id)
            if self.conversation_id:
                tool_config["conversation_id"] = self.conversation_id
                # Carry the request's own attachments so sandbox tools can
                # lazily bridge a referenced chat attachment (conversation
                # scope only; workflow nodes bridge attachments up front).
                if self.attachments:
                    tool_config["attachments"] = self.attachments
            # Workflow agent nodes run-scope their artifact tools so a short
            # ref (A1) and edit_artifact resolve against the workflow run.
            if self.workflow_run_id:
                tool_config["workflow_run_id"] = self.workflow_run_id
            if tool_data["name"] == "scheduler":
                # Agent-bound: stamp schedules.agent_id. Agentless: the tool
                # falls back to ``origin_conversation_id`` as the schedule's
                # conversation home.
                tool_config["agent_id"] = (
                    str(self.agent_id) if self.agent_id else None
                )
            if tool_data["name"] == "mcp_tool":
                tool_config["query_mode"] = True

        tool = tm.load_tool(
            tool_data["name"],
            tool_config=tool_config,
            user_id=self.user,
        )

        # Don't cache api_tool since config varies by action
        if tool_data["name"] != "api_tool":
            self._loaded_tools[cache_key] = tool

        return tool

    def get_truncated_tool_calls(self) -> List[Dict]:
        return [
            {
                "tool_name": tool_call.get("tool_name"),
                "call_id": tool_call.get("call_id"),
                "action_name": tool_call.get("action_name"),
                "arguments": tool_call.get("arguments"),
                "artifact_id": tool_call.get("artifact_id"),
                "result": (
                    f"{str(tool_call['result'])[:50]}..."
                    if len(str(tool_call["result"])) > 50
                    else tool_call["result"]
                ),
                "status": "completed",
            }
            for tool_call in self.tool_calls
        ]
