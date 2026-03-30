import logging
import uuid
from typing import Dict, List, Optional

from bson.objectid import ObjectId

from application.agents.tools.tool_action_parser import ToolActionParser
from application.agents.tools.tool_manager import ToolManager
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.security.encryption import decrypt_credentials

logger = logging.getLogger(__name__)


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

    def get_tools(self) -> Dict[str, Dict]:
        """Load tool configs from DB based on user context."""
        if self.user_api_key:
            return self._get_tools_by_api_key(self.user_api_key)
        return self._get_user_tools(self.user or "local")

    def _get_tools_by_api_key(self, api_key: str) -> Dict[str, Dict]:
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]
        tools_collection = db["user_tools"]

        agent_data = agents_collection.find_one({"key": api_key})
        tool_ids = agent_data.get("tools", []) if agent_data else []

        tools = (
            tools_collection.find(
                {"_id": {"$in": [ObjectId(tool_id) for tool_id in tool_ids]}}
            )
            if tool_ids
            else []
        )
        tools = list(tools)
        return {str(tool["_id"]): tool for tool in tools} if tools else {}

    def _get_user_tools(self, user: str = "local") -> Dict[str, Dict]:
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        user_tools_collection = db["user_tools"]
        user_tools = user_tools_collection.find({"user": user, "status": True})
        user_tools = list(user_tools)
        return {str(i): tool for i, tool in enumerate(user_tools)}

    def prepare_tools_for_llm(self, tools_dict: Dict) -> List[Dict]:
        """Convert tool configs to LLM function schemas."""
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{action['name']}_{tool_id}",
                    "description": action["description"],
                    "parameters": self._build_tool_parameters(action),
                },
            }
            for tool_id, tool in tools_dict.items()
            if (
                (tool["name"] == "api_tool" and "actions" in tool.get("config", {}))
                or (tool["name"] != "api_tool" and "actions" in tool)
            )
            for action in (
                tool["config"]["actions"].values()
                if tool["name"] == "api_tool"
                else tool["actions"]
            )
            if action.get("active", True)
        ]

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

    def execute(self, tools_dict: Dict, call, llm_class_name: str):
        """Execute a tool call. Yields status events, returns (result, call_id)."""
        parser = ToolActionParser(llm_class_name)
        tool_id, action_name, call_args = parser.parse_args(call)

        call_id = getattr(call, "id", None) or str(uuid.uuid4())

        if tool_id is None or action_name is None:
            error_message = f"Error: Failed to parse LLM tool call. Tool name: {getattr(call, 'name', 'unknown')}"
            logger.error(error_message)

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": getattr(call, "name", "unknown"),
                "arguments": call_args or {},
                "result": f"Failed to parse tool call. Invalid tool name format: {getattr(call, 'name', 'unknown')}",
            }
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return "Failed to parse tool call.", call_id

        if tool_id not in tools_dict:
            error_message = f"Error: Tool ID '{tool_id}' extracted from LLM call not found in available tools_dict. Available IDs: {list(tools_dict.keys())}"
            logger.error(error_message)

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": f"{action_name}_{tool_id}",
                "arguments": call_args,
                "result": f"Tool with ID {tool_id} not found. Available tools: {list(tools_dict.keys())}",
            }
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return f"Tool with ID {tool_id} not found.", call_id

        tool_call_data = {
            "tool_name": tools_dict[tool_id]["name"],
            "call_id": call_id,
            "action_name": f"{action_name}_{tool_id}",
            "arguments": call_args,
        }
        yield {"type": "tool_call", "data": {**tool_call_data, "status": "pending"}}

        tool_data = tools_dict[tool_id]
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

        resolved_arguments = (
            {"query_params": query_params, "headers": headers, "body": body}
            if tool_data["name"] == "api_tool"
            else parameters
        )
        if tool_data["name"] == "api_tool":
            logger.debug(
                f"Executing api: {action_name} with query_params: {query_params}, headers: {headers}, body: {body}"
            )
            result = tool.execute_action(action_name, **body)
        else:
            logger.debug(f"Executing tool: {action_name} with args: {call_args}")
            result = tool.execute_action(action_name, **parameters)

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
            tool_config["tool_id"] = str(tool_data.get("_id", tool_id))
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
