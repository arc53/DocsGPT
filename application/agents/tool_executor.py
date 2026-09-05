import logging
import re
import uuid
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from application.agents.default_tools import (
    BUILTIN_AGENT_TOOLS,
    is_headless_excluded_tool,
    is_synthesized_tool,
)
from application.agents.tools import tool_manager
from application.error_types import ValidationError
from application.storage.db.repositories.agent import AgentRepository
from application.storage.db.repositories.connector_sessions import (
    ConnectorSessionsRepository,
)
from application.storage.db.repositories.shared_conversations import (
    SharedConversationsRepository,
)
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.session import db_readonly

logger = logging.getLogger(__name__)


class GuardrailStage:
    TOOL_RESULT = "tool_result"
    DOCUMENT = "document"
    USER_INPUT = "user_input"


def _requires_approval(tool: Dict, action: Optional[Dict] = None) -> bool:
    """Return True if this tool call needs human approval before execution."""
    if action is not None:
        if bool(action.get("require_approval")):
            return True
    return bool((tool.get("config") or {}).get("require_approval"))


class ToolExecutor:
    """Executor that resolves, validates, and calls tools on behalf of an LLM agent."""

    _PRESERVED_TOOL_CALL_KEYS = ("id", "function", "type")

    def __init__(
        self,
        user: Optional[str] = None,
        agent_id: Optional[str] = None,
        headless: bool = False,
        guardrail_engine=None,
    ):
        self.user = user
        self.agent_id = agent_id
        self.headless = headless
        self.guardrail_engine = guardrail_engine
        self._tools_cache: Optional[Dict] = None

    # ------------------------------------------------------------------
    # Tool resolution
    # ------------------------------------------------------------------

    def get_tools(self) -> Dict:
        """Return the resolved tool map for this executor (cached)."""
        if self._tools_cache is not None:
            return self._tools_cache
        self._tools_cache = self._resolve_tools()
        return self._tools_cache

    def invalidate_cache(self) -> None:
        self._tools_cache = None

    def _resolve_tools(self) -> Dict:
        tools: Dict[str, Any] = {}

        if self.agent_id:
            tools.update(self._load_agent_tools())
        elif self.user:
            tools.update(self._load_user_tools())

        tools.update(self._load_builtin_tools())
        return tools

    def _load_builtin_tools(self) -> Dict:
        result = {}
        for name, tool_cls in BUILTIN_AGENT_TOOLS.items():
            if self.headless and is_headless_excluded_tool(name):
                continue
            result[name] = {"name": name, "instance": tool_cls(), "builtin": True}
        return result

    def _load_user_tools(self) -> Dict:
        result: Dict[str, Any] = {}
        with db_readonly() as conn:
            repo = UserToolsRepository(conn)
            rows = repo.list_for_user(self.user)

        for row in rows:
            if not row.get("status", True):
                continue
            if self.headless and is_headless_excluded_tool(row.get("name")):
                continue
            name = row.get("name", "")
            if name in tool_manager.tools:
                result[row["id"]] = {
                    **row,
                    "instance": tool_manager.tools[name],
                }
        return result

    def _load_agent_tools(self) -> Dict:
        result: Dict[str, Any] = {}
        with db_readonly() as conn:
            agent_repo = AgentRepository(conn)
            agent_data = agent_repo.get(self.agent_id)
            if not agent_data:
                return result

            tool_ids = agent_data.get("tools", []) if agent_data else []
            owner = (agent_data.get("user_id") or agent_data.get("user")) if agent_data else None
            if not owner:
                return result

            repo = UserToolsRepository(conn)
            all_tools = repo.list_for_user(owner)

        user_tools_by_id = {str(t["id"]): t for t in all_tools}

        for tid in tool_ids:
            row = user_tools_by_id.get(str(tid))
            if not row:
                continue
            if not row.get("status", True):
                continue
            if self.headless and is_headless_excluded_tool(row.get("name")):
                continue
            name = row.get("name", "")
            if name in tool_manager.tools:
                result[str(row["id"])] = {
                    **row,
                    "instance": tool_manager.tools[name],
                }
        return result

    # ------------------------------------------------------------------
    # Tool schema for the LLM
    # ------------------------------------------------------------------

    def get_tool_names(self) -> set:
        return {str(tool["name"]) for tool in self.get_tools().values() if isinstance(tool, dict) and tool.get("name")}

    def get_tools_info(self) -> List[Dict]:
        """Return OpenAI-style function-calling schema for all active tools."""
        result = []
        tools = self.get_tools()

        for tool_id, tool in tools.items():
            if not isinstance(tool, dict):
                continue

            is_api = not tool.get("builtin", False)
            is_client = tool.get("client_side", False)

            if is_api and "actions" not in tool.get("config", {}):
                actions = tool.get("actions") or []
            else:
                actions = (tool.get("config") or {}).get("actions") or tool.get("actions") or []

            for action in actions:
                if not action.get("active", True):
                    continue
                tool_name = tool.get("name", "")
                action_name = action.get("name", "")

                if is_synthesized_tool(tool_name):
                    llm_name = action_name
                elif is_client:
                    llm_name = action_name
                else:
                    llm_name = f"{tool_name}__{action_name}"

                params = self._build_tool_parameters(action)
                result.append(
                    {
                        "type": "function",
                        "function": {
                            "name": llm_name,
                            "description": action.get("description", ""),
                            "parameters": params,
                        },
                    }
                )

        # Merge client tools from the conversation context (if any)
        client_tools = getattr(self, "_client_tools", [])
        for i, ct in enumerate(client_tools):
            func = ct.get("function", ct)
            name = func.get("name", f"clienttool{i}")
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {}),
                    },
                }
            )
        return result

    def _build_tool_parameters(self, action: Dict) -> Dict:
        params = {"type": "object", "properties": {}, "required": []}
        for param_type in ["query_params", "headers", "body", "parameters"]:
            if param_type in action and action[param_type].get("properties"):
                for k, v in action[param_type]["properties"].items():
                    if not isinstance(v, dict):
                        continue
                    if v.get("filled_by_llm", True):
                        params["properties"][k] = {
                            key: value for key, value in v.items() if key not in ("filled_by_llm", "value", "required")
                        }
                        if v.get("required", False):
                            params["required"].append(k)
        return params

    def _guardrail_tool_result(self, result: Any, tool_name: str, action_name: str) -> Any:
        """Scan a tool result before it fans out to the LLM, UI and journal."""
        engine = getattr(self, "guardrail_engine", None)
        if engine is None or not engine.has_stage(GuardrailStage.TOOL_RESULT):
            return result
        if not isinstance(result, str) or not result:
            return result
        try:
            engine.context.tool_name = tool_name
            engine.context.action_name = action_name
            return engine.scan(result, stage=GuardrailStage.TOOL_RESULT)
        except Exception:
            logger.warning("Guardrail scan failed for tool result", exc_info=True)
            return result

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def execute(
        self,
        tool_calls: List[Dict],
        conversation_id: Optional[str] = None,
        shared_token: Optional[str] = None,
    ) -> List[Dict]:
        """Execute a list of tool calls and return results."""
        results = []
        for tc in tool_calls:
            result = self._execute_one(tc, conversation_id=conversation_id, shared_token=shared_token)
            results.append(result)
        return results

    def _execute_one(
        self,
        tool_call: Dict,
        conversation_id: Optional[str] = None,
        shared_token: Optional[str] = None,
    ) -> Dict:
        func = tool_call.get("function", {})
        raw_name: str = func.get("name", "")
        tool_call_id = tool_call.get("id") or str(uuid.uuid4())

        # Parse tool_name__action_name
        if "__" in raw_name:
            tool_name, action_name = raw_name.split("__", 1)
        else:
            tool_name = raw_name
            action_name = raw_name

        try:
            args_str = func.get("arguments", "{}")
            args = _safe_parse_args(args_str)
        except Exception as e:
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": raw_name,
                "content": f"Error parsing arguments: {e}",
            }

        tools = self.get_tools()
        tool = self._find_tool(tools, tool_name, action_name)
        if tool is None:
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": raw_name,
                "content": f"Tool '{raw_name}' not found",
            }

        action = self._find_action(tool, action_name)
        if action is None:
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": raw_name,
                "content": f"Action '{action_name}' not found in tool '{tool_name}'",
            }

        if _requires_approval(tool, action):
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": raw_name,
                "content": "APPROVAL_REQUIRED",
                "requires_approval": True,
                "action": action,
                "args": args,
            }

        try:
            instance = tool.get("instance")
            if instance is None:
                return {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": raw_name,
                    "content": f"Tool instance not available for '{tool_name}'",
                }

            config = tool.get("config") or {}
            result_raw = instance.call_action(
                action_name=action_name,
                args=args,
                config=config,
                user=self.user,
                conversation_id=conversation_id,
            )
            result_str = _format_result(result_raw)
            result_str = self._guardrail_tool_result(result_str, tool_name, action_name)
        except ValidationError as e:
            result_str = f"Validation error: {e}"
        except Exception as e:
            logger.error(
                "Tool execution error: tool=%s action=%s error=%s",
                tool_name, action_name, e, exc_info=True,
            )
            result_str = f"Tool execution failed: {e}"

        return {
            "tool_call_id": tool_call_id,
            "role": "tool",
            "name": raw_name,
            "content": result_str,
        }

    def _find_tool(self, tools: Dict, tool_name: str, action_name: str) -> Optional[Dict]:
        for tool_id, tool in tools.items():
            if not isinstance(tool, dict):
                continue
            if tool.get("name") == tool_name:
                return tool
        return None

    def _find_action(self, tool: Dict, action_name: str) -> Optional[Dict]:
        is_api = not tool.get("builtin", False)
        if is_api and "actions" not in tool.get("config", {}):
            actions = tool.get("actions") or []
        else:
            actions = (tool.get("config") or {}).get("actions") or tool.get("actions") or []
        for action in actions:
            if action.get("name") == action_name:
                return action
        return None

    # ------------------------------------------------------------------
    # Duplicate / hallucination detection
    # ------------------------------------------------------------------

    def detect_duplicate_calls(self, tool_calls: List[Dict]) -> List[str]:
        """Return names of tools called more than once in the same turn."""
        counter: Counter = Counter()
        for tc in tool_calls:
            name = (tc.get("function") or {}).get("name", "")
            if name:
                counter[name] += 1
        return [name for name, cnt in counter.items() if cnt > 1]

    def detect_hallucinated_calls(self, tool_calls: List[Dict]) -> List[str]:
        """Return tool call names that don't exist in the known tool set."""
        known = {f["function"]["name"] for f in self.get_tools_info()}
        hallucinated = []
        for tc in tool_calls:
            name = (tc.get("function") or {}).get("name", "")
            if name and name not in known:
                hallucinated.append(name)
        return hallucinated

    # ------------------------------------------------------------------
    # Shared conversation support
    # ------------------------------------------------------------------

    def get_shared_agent_tools(self, shared_token: str) -> Dict:
        with db_readonly() as conn:
            repo = SharedConversationsRepository(conn)
            shared = repo.get_by_token(shared_token)
        if not shared:
            return {}
        agent_id = shared.get("agent_id")
        if not agent_id:
            return {}
        old_agent_id = self.agent_id
        self.agent_id = agent_id
        self.invalidate_cache()
        tools = self.get_tools()
        self.agent_id = old_agent_id
        self.invalidate_cache()
        return tools

    # ------------------------------------------------------------------
    # Tool call projection (strip internal keys before sending to client)
    # ------------------------------------------------------------------

    def project_tool_calls(self, tool_calls: List[Dict]) -> List[Dict]:
        projected = []
        for tool_call in tool_calls:
            entry = {}
            for key in self._PRESERVED_TOOL_CALL_KEYS:
                value = tool_call.get(key)
                if value:
                    entry[key] = value
            projected.append(entry)
        return projected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_parse_args(args_str: str) -> Dict:
    """Parse JSON tool arguments, tolerating minor formatting issues."""
    import json

    if not args_str or args_str.strip() == "":
        return {}
    try:
        return json.loads(args_str)
    except json.JSONDecodeError:
        # Try to extract JSON object
        match = re.search(r"\{.*\}", args_str, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


def _format_result(result: Any) -> str:
    """Convert a tool result to a string for the LLM."""
    import json

    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, ensure_ascii=False)
        except Exception:
            return str(result)
    return str(result)
