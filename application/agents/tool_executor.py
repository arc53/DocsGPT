import logging
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from application.agents.tools.tool_action_parser import ToolActionParser
from application.agents.tools.tool_manager import ToolManager
from application.security.encryption import decrypt_credentials
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.tool_call_attempts import (
    ToolCallAttemptsRepository,
)
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)


def _record_proposed(
    call_id: str,
    tool_name: str,
    action_name: str,
    arguments: Any,
    *,
    tool_id: Optional[str] = None,
) -> bool:
    """Insert a ``proposed`` row; swallow infra failures so tool calls
    still run when the journal is unreachable. Returns True iff the row
    is now journaled (newly created or already present).
    """
    try:
        with db_session() as conn:
            inserted = ToolCallAttemptsRepository(conn).record_proposed(
                call_id,
                tool_name,
                action_name,
                arguments,
                tool_id=tool_id if tool_id and looks_like_uuid(tool_id) else None,
            )
        if not inserted:
            logger.warning(
                "tool_call_attempts duplicate call_id=%s; existing row left in place",
                call_id,
                extra={"alert": "tool_call_id_collision", "call_id": call_id},
            )
        return True
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
) -> None:
    """Flip the row to ``executed``. If ``proposed_ok`` is False (the
    proposed write failed earlier), upsert a fresh row in ``executed`` so
    the reconciler can still see the attempt — without this, the side
    effect would be invisible to the journal.
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
            )
    except Exception:
        logger.exception("tool_call_attempts executed write failed for %s", call_id)


def _mark_failed(call_id: str, error: str) -> None:
    try:
        with db_session() as conn:
            ToolCallAttemptsRepository(conn).mark_failed(call_id, error)
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
    ):
        self.user_api_key = user_api_key
        self.user = user
        self.decoded_token = decoded_token
        self.tool_calls: List[Dict] = []
        self._loaded_tools: Dict[str, object] = {}
        self.conversation_id: Optional[str] = None
        self.message_id: Optional[str] = None
        self.client_tools: Optional[List[Dict]] = None
        self._name_to_tool: Dict[str, Tuple[str, str]] = {}
        self._tool_to_name: Dict[Tuple[str, str], str] = {}

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
        # Per-operation session: the answer pipeline spans a long-lived
        # generator; wrapping it in a single connection would pin a PG
        # conn for the whole stream. Open, fetch, close.
        with db_readonly() as conn:
            agent_data = AgentsRepository(conn).find_by_key(api_key)
            tool_ids = agent_data.get("tools", []) if agent_data else []
            if not tool_ids:
                return {}
            tools_repo = UserToolsRepository(conn)
            tools: List[Dict] = []
            owner = (agent_data.get("user_id") or agent_data.get("user")) if agent_data else None
            for tid in tool_ids:
                row = None
                if owner:
                    row = tools_repo.get_any(str(tid), owner)
                if row is not None:
                    tools.append(row)
        return {str(tool["id"]): tool for tool in tools} if tools else {}

    def _get_user_tools(self, user: str = "local") -> Dict[str, Dict]:
        with db_readonly() as conn:
            user_tools = UserToolsRepository(conn).list_active_for_user(user)
        return {str(i): tool for i, tool in enumerate(user_tools)}

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
        - Duplicate action names get numbered suffixes (e.g. ``search_1``,
          ``search_2``).

        A reverse mapping is stored in ``_name_to_tool`` so that tool calls
        can be routed back to the correct ``(tool_id, action_name)`` without
        brittle string splitting.
        """
        # Pass 1: collect entries and count action name occurrences
        entries: List[Tuple[str, str, Dict, bool]] = []  # (tool_id, action_name, action, is_client)
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
                entries.append((tool_id, action["name"], action, is_client))
                name_counts[action["name"]] += 1

        # Pass 2: assign LLM-visible names and build mappings
        self._name_to_tool = {}
        self._tool_to_name = {}
        collision_counters: Dict[str, int] = {}
        all_llm_names: set = set()

        result = []
        for tool_id, action_name, action, is_client in entries:
            if name_counts[action_name] == 1:
                llm_name = action_name
            else:
                counter = collision_counters.get(action_name, 1)
                candidate = f"{action_name}_{counter}"
                # Skip if candidate collides with a unique action name
                while candidate in all_llm_names or (
                    candidate in name_counts and name_counts[candidate] == 1
                ):
                    counter += 1
                    candidate = f"{action_name}_{counter}"
                collision_counters[action_name] = counter + 1
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
        """Check if a tool call requires pausing for approval or client execution.

        Returns a dict describing the pending action if pause is needed, None otherwise.
        """
        parser = ToolActionParser(llm_class_name, name_mapping=self._name_to_tool)
        tool_id, action_name, call_args = parser.parse_args(call)
        call_id = getattr(call, "id", None) or str(uuid.uuid4())
        llm_name = getattr(call, "name", "")

        if tool_id is None or action_name is None or tool_id not in tools_dict:
            return None  # Will be handled as error by execute()

        tool_data = tools_dict[tool_id]

        # Client-side tools
        if tool_data.get("client_side"):
            return {
                "call_id": call_id,
                "name": llm_name,
                "tool_name": tool_data.get("name", "unknown"),
                "tool_id": tool_id,
                "action_name": action_name,
                "llm_name": llm_name,
                "arguments": call_args if isinstance(call_args, dict) else {},
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

        if action_data.get("require_approval"):
            return {
                "call_id": call_id,
                "name": llm_name,
                "tool_name": tool_data.get("name", "unknown"),
                "tool_id": tool_id,
                "action_name": action_name,
                "llm_name": llm_name,
                "arguments": call_args if isinstance(call_args, dict) else {},
                "pause_type": "awaiting_approval",
                "thought_signature": getattr(call, "thought_signature", None),
            }

        return None

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
        # Journal first so the reconciler sees malformed calls and any
        # subsequent ``_mark_failed`` actually updates a real row.
        proposed_ok = _record_proposed(
            call_id,
            tool_data["name"],
            action_name,
            call_args if isinstance(call_args, dict) else {},
            tool_id=tool_data.get("id"),
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
            _mark_failed(call_id, error_message)
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
            _mark_failed(call_id, error_message)
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
                    f"Executing api: {action_name} with query_params: {query_params}, headers: {headers}, body: {body}"
                )
                result = tool.execute_action(action_name, **body)
            else:
                logger.debug(f"Executing tool: {action_name} with args: {call_args}")
                result = tool.execute_action(action_name, **parameters)
        except Exception as exc:
            _mark_failed(call_id, str(exc))
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
            return self._loaded_tools[cache_key]

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
            if tool_config.get("encrypted_credentials") and self.user:
                decrypted = decrypt_credentials(
                    tool_config["encrypted_credentials"], self.user
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
