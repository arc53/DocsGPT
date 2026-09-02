import json
import logging
import os
import re
import traceback
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from application.agents.tools.base import Tool
from application.core.settings import settings

logger = logging.getLogger(__name__)


MCP_OAUTH_TIMEOUT = 10


def _is_mcp_url_available(url: str, timeout: int = MCP_OAUTH_TIMEOUT) -> bool:
    """Check if an MCP server URL is reachable."""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
            return response.status_code < 500
    except Exception:
        return False


class MCPTool(Tool):
    """
    Tool for connecting to remote MCP (Model Context Protocol) servers.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.server_url = config.get("server_url", "")
        self.auth_type = config.get("auth_type", "none")
        self.bearer_token = config.get("bearer_token", "")
        self.api_key = config.get("api_key", "")
        self.api_key_header = config.get("api_key_header", "X-API-Key")
        self.basic_username = config.get("basic_username", "")
        self.basic_password = config.get("basic_password", "")
        self.timeout = config.get("timeout", 30)
        self.available_tools: List[Dict] = []
        self._headers: Dict[str, str] = {}
        self._setup_auth()

    def _setup_auth(self):
        """Configure authentication headers based on auth_type."""
        if self.auth_type == "bearer" and self.bearer_token:
            self._headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.auth_type == "api_key" and self.api_key:
            self._headers[self.api_key_header] = self.api_key
        elif self.auth_type == "basic" and self.basic_username:
            import base64

            credentials = base64.b64encode(
                f"{self.basic_username}:{self.basic_password}".encode()
            ).decode()
            self._headers["Authorization"] = f"Basic {credentials}"
        elif self.auth_type == "oauth":
            stored_token = self._get_stored_oauth_token()
            if stored_token:
                self._headers["Authorization"] = f"Bearer {stored_token}"

    def _get_stored_oauth_token(self) -> Optional[str]:
        """Retrieve stored OAuth token for this server."""
        try:
            from application.cache import get_redis_instance

            redis_client = get_redis_instance()
            if not redis_client:
                return None
            token_key = f"mcp_oauth_token:{self.server_url}"
            token_data = redis_client.get(token_key)
            if token_data:
                token_info = json.loads(token_data)
                return token_info.get("access_token")
        except Exception as e:
            logger.debug(f"Could not retrieve OAuth token: {e}")
        return None

    def _store_oauth_token(self, token_info: Dict):
        """Store OAuth token for this server."""
        try:
            from application.cache import get_redis_instance

            redis_client = get_redis_instance()
            if redis_client:
                token_key = f"mcp_oauth_token:{self.server_url}"
                expires_in = token_info.get("expires_in", 3600)
                redis_client.setex(token_key, expires_in, json.dumps(token_info))
        except Exception as e:
            logger.debug(f"Could not store OAuth token: {e}")

    def _make_mcp_request(
        self,
        method: str,
        params: Optional[Dict] = None,
        request_id: Optional[int] = None,
    ) -> Dict:
        """Make a JSON-RPC request to the MCP server."""
        if request_id is None:
            request_id = 1

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }

        if params:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            **self._headers,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.server_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error making MCP request: {e}")
            raise
        except Exception as e:
            logger.error(f"Error making MCP request: {e}")
            raise

    def _discover_tools(self) -> List[Dict]:
        """Discover available tools from the MCP server."""
        try:
            response = self._make_mcp_request("tools/list")

            if "error" in response:
                logger.error(f"Error from MCP server: {response['error']}")
                return []

            result = response.get("result", {})
            tools = result.get("tools", [])
            return tools
        except Exception as e:
            logger.error(f"Error discovering tools: {e}")
            return []

    def connect(self) -> Dict:
        """Connect to the MCP server and discover available tools."""
        try:
            if self.auth_type == "oauth":
                return self._test_oauth_connection()

            self.available_tools = self._discover_tools()

            if not self.available_tools:
                return {
                    "success": False,
                    "message": "Connected but no tools found on the server.",
                }

            return {
                "success": True,
                "message": f"Connected successfully. Found {len(self.available_tools)} tools.",
                "tools_count": len(self.available_tools),
            }
        except Exception as e:
            logger.error(f"Error connecting to MCP server: {e}")
            return {
                "success": False,
                "message": f"Failed to connect: {str(e)}",
            }

    def _test_oauth_connection(self) -> Dict:
        """Test connection with OAuth authentication."""
        stored_token = self._get_stored_oauth_token()
        if stored_token:
            self._headers["Authorization"] = f"Bearer {stored_token}"
            self.available_tools = self._discover_tools()
            if self.available_tools:
                return {
                    "success": True,
                    "message": f"Connected successfully using stored token. Found {len(self.available_tools)} tools.",
                    "tools_count": len(self.available_tools),
                }

        return self._start_oauth_task()

    def _start_oauth_task(self) -> Dict:
        """Start the OAuth authorization task."""
        try:
            from application.celery_app import app as celery_app

            result = celery_app.send_task(
                "application.agents.tools.mcp_oauth_task.start_oauth_flow",
                args=[self.server_url, self.config],
            )

            return {
                "success": False,
                "requires_oauth": True,
                "task_id": result.id,
                "message": "OAuth authorization required.",
                "tools_count": 0,
            }
        except Exception as e:
            logger.error(f"Error starting OAuth task: {e}")
            return {
                "success": False,
                "message": f"Failed to start OAuth flow: {str(e)}",
            }

    def get_actions_metadata(self) -> List[Dict]:
        """
        Get metadata for all available actions.

        Returns:
            List of action metadata dictionaries
        """
        actions = []
        for tool in self.available_tools:
            input_schema = (
                tool.get("inputSchema")
                or tool.get("input_schema")
                or tool.get("schema")
                or tool.get("parameters")
            )

            parameters_schema = {
                "type": "object",
                "properties": {},
                "required": [],
            }

            if input_schema:
                if isinstance(input_schema, dict):
                    if "properties" in input_schema:
                        parameters_schema = {
                            "type": input_schema.get("type", "object"),
                            "properties": input_schema.get("properties", {}),
                            "required": input_schema.get("required", []),
                        }

                        for key in ["additionalProperties", "description"]:
                            if key in input_schema:
                                parameters_schema[key] = input_schema[key]
                    else:
                        # input_schema exists but declares no properties (e.g. {"type": "object"}).
                        # Keep the default empty-properties schema; do not store the schema
                        # itself as a property definition.
                        pass
            action = {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": parameters_schema,
            }
            actions.append(action)
        return actions

    def get_config_requirements(self) -> Dict:
        return {
            "server_url": {
                "type": "string",
                "label": "Server URL",
                "description": "URL of the remote MCP server",
                "required": True,
                "secret": False,
                "order": 1,
            },
            "auth_type": {
                "type": "string",
                "label": "Authentication Type",
                "description": "Authentication method for the MCP server",
                "enum": ["none", "bearer", "oauth", "api_key", "basic"],
                "required": True,
                "secret": False,
                "order": 2,
            },
            "bearer_token": {
                "type": "string",
                "label": "Bearer Token",
                "description": "Bearer token for authentication (required when auth_type is 'bearer')",
                "required": False,
                "secret": True,
                "order": 3,
            },
            "api_key": {
                "type": "string",
                "label": "API Key",
                "description": "API key for authentication (required when auth_type is 'api_key')",
                "required": False,
                "secret": True,
                "order": 4,
            },
            "api_key_header": {
                "type": "string",
                "label": "API Key Header",
                "description": "Header name for the API key (default: X-API-Key)",
                "required": False,
                "secret": False,
                "order": 5,
            },
            "basic_username": {
                "type": "string",
                "label": "Username",
                "description": "Username for basic authentication",
                "required": False,
                "secret": False,
                "order": 6,
            },
            "basic_password": {
                "type": "string",
                "label": "Password",
                "description": "Password for basic authentication",
                "required": False,
                "secret": True,
                "order": 7,
            },
            "timeout": {
                "type": "number",
                "label": "Timeout",
                "description": "Request timeout in seconds",
                "required": False,
                "secret": False,
                "order": 8,
            },
        }

    def execute(self, action_name: str, action_input: Dict) -> str:
        """Execute a tool on the MCP server."""
        try:
            response = self._make_mcp_request(
                "tools/call",
                params={
                    "name": action_name,
                    "arguments": action_input,
                },
            )

            if "error" in response:
                error = response["error"]
                return f"Error executing tool: {error.get('message', 'Unknown error')}"

            result = response.get("result", {})
            content = result.get("content", [])

            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif "text" in item:
                            text_parts.append(item["text"])
                return "\n".join(text_parts) if text_parts else str(result)
            elif isinstance(content, str):
                return content
            else:
                return str(result)

        except Exception as e:
            logger.error(f"Error executing MCP tool {action_name}: {e}")
            return f"Error executing tool: {str(e)}"

    def _build_tool_parameters(
        self, tool_name: str, action_input: Dict
    ) -> Tuple[str, Dict]:
        """Build parameters for tool execution, handling type coercions."""
        tool_schema = None
        for tool in self.available_tools:
            if tool.get("name") == tool_name:
                tool_schema = tool
                break

        if not tool_schema:
            return tool_name, action_input

        input_schema = (
            tool_schema.get("inputSchema")
            or tool_schema.get("input_schema")
            or tool_schema.get("schema")
            or {}
        )

        properties = input_schema.get("properties", {})
        coerced_input = {}

        for key, value in action_input.items():
            prop_schema = properties.get(key, {})
            expected_type = prop_schema.get("type") if isinstance(prop_schema, dict) else None

            if expected_type == "integer" and isinstance(value, str):
                try:
                    coerced_input[key] = int(value)
                    continue
                except ValueError:
                    pass
            elif expected_type == "number" and isinstance(value, str):
                try:
                    coerced_input[key] = float(value)
                    continue
                except ValueError:
                    pass
            elif expected_type == "boolean" and isinstance(value, str):
                coerced_input[key] = value.lower() in ("true", "1", "yes")
                continue
            elif expected_type == "array" and isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        coerced_input[key] = parsed
                        continue
                except (json.JSONDecodeError, ValueError):
                    pass

            coerced_input[key] = value

        return tool_name, coerced_input

    def run(self, tool_name: str, tool_input: str) -> str:
        """
        Run a tool with the given input.

        Args:
            tool_name: Name of the tool to run
            tool_input: JSON string of tool parameters

        Returns:
            Tool execution result as string
        """
        try:
            if isinstance(tool_input, str):
                action_input = json.loads(tool_input)
            else:
                action_input = tool_input

            _, coerced_input = self._build_tool_parameters(tool_name, action_input)
            return self.execute(tool_name, coerced_input)
        except json.JSONDecodeError as e:
            return f"Error parsing tool input: {str(e)}"
        except Exception as e:
            logger.error(f"Error running MCP tool {tool_name}: {e}")
            return f"Error running tool: {str(e)}"
