import json
import time
from typing import Any, Dict, List, Optional

import requests

from application.agents.tools.base import Tool
from application.security.encryption import decrypt_credentials


_mcp_session_cache = {}


class MCPTool(Tool):
    """
    MCP Tool
    Connect to remote Model Context Protocol (MCP) servers to access dynamic tools and resources. Supports various authentication methods and provides secure access to external services through the MCP protocol.
    """

    def __init__(self, config: Dict[str, Any], user_id: Optional[str] = None):
        """
        Initialize the MCP Tool with configuration.

        Args:
            config: Dictionary containing MCP server configuration:
                - server_url: URL of the remote MCP server
                - auth_type: Type of authentication (api_key, bearer, basic, none)
                - encrypted_credentials: Encrypted credentials (if available)
                - timeout: Request timeout in seconds (default: 30)
            user_id: User ID for decrypting credentials (required if encrypted_credentials exist)
        """
        self.config = config
        self.server_url = config.get("server_url", "")
        self.auth_type = config.get("auth_type", "none")
        self.timeout = config.get("timeout", 30)

        self.auth_credentials = {}
        if config.get("encrypted_credentials") and user_id:
            self.auth_credentials = decrypt_credentials(
                config["encrypted_credentials"], user_id
            )
        else:
            self.auth_credentials = config.get("auth_credentials", {})
        self.available_tools = []
        self._session = requests.Session()
        self._mcp_session_id = None
        self._setup_authentication()
        self._cache_key = self._generate_cache_key()

    def _setup_authentication(self):
        """Setup authentication for the MCP server connection."""
        if self.auth_type == "api_key":
            api_key = self.auth_credentials.get("api_key", "")
            header_name = self.auth_credentials.get("api_key_header", "X-API-Key")
            if api_key:
                self._session.headers.update({header_name: api_key})
        elif self.auth_type == "bearer":
            token = self.auth_credentials.get("bearer_token", "")
            if token:
                self._session.headers.update({"Authorization": f"Bearer {token}"})
        elif self.auth_type == "basic":
            username = self.auth_credentials.get("username", "")
            password = self.auth_credentials.get("password", "")
            if username and password:
                self._session.auth = (username, password)

    def _generate_cache_key(self) -> str:
        """Generate a unique cache key for this MCP server configuration."""
        auth_key = ""
        if self.auth_type == "bearer":
            token = self.auth_credentials.get("bearer_token", "")
            auth_key = f"bearer:{token[:10]}..." if token else "bearer:none"
        elif self.auth_type == "api_key":
            api_key = self.auth_credentials.get("api_key", "")
            auth_key = f"apikey:{api_key[:10]}..." if api_key else "apikey:none"
        elif self.auth_type == "basic":
            username = self.auth_credentials.get("username", "")
            auth_key = f"basic:{username}"
        else:
            auth_key = "none"
        return f"{self.server_url}#{auth_key}"

    def _get_cached_session(self) -> Optional[str]:
        """Get cached session ID if available and not expired."""
        global _mcp_session_cache

        if self._cache_key in _mcp_session_cache:
            session_data = _mcp_session_cache[self._cache_key]
            if time.time() - session_data["created_at"] < 1800:
                return session_data["session_id"]
            else:
                del _mcp_session_cache[self._cache_key]
        return None

    def _cache_session(self, session_id: str):
        """Cache the session ID for reuse."""
        global _mcp_session_cache
        _mcp_session_cache[self._cache_key] = {
            "session_id": session_id,
            "created_at": time.time(),
        }

    def _initialize_mcp_connection(self) -> Dict:
        """
        Initialize MCP connection with the server, using cached session if available.

        Returns:
            Server capabilities and information
        """
        cached_session = self._get_cached_session()
        if cached_session:
            self._mcp_session_id = cached_session
            return {"cached": True}
        try:
            init_params = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
                "clientInfo": {"name": "DocsGPT", "version": "1.0.0"},
            }
            response = self._make_mcp_request("initialize", init_params)
            self._make_mcp_request("notifications/initialized")

            return response
        except Exception as e:
            return {"error": str(e), "fallback": True}

    def _ensure_valid_session(self):
        """Ensure we have a valid MCP session, reinitializing if needed."""
        if not self._mcp_session_id:
            self._initialize_mcp_connection()

    def _make_mcp_request(self, method: str, params: Optional[Dict] = None) -> Dict:
        """
        Make an MCP protocol request to the server with automatic session recovery.

        Args:
            method: MCP method name (e.g., "tools/list", "tools/call")
            params: Parameters for the MCP method

        Returns:
            Response data as dictionary

        Raises:
            Exception: If request fails after retry
        """
        mcp_message = {"jsonrpc": "2.0", "method": method}

        if not method.startswith("notifications/"):
            mcp_message["id"] = 1
        if params:
            mcp_message["params"] = params
        return self._execute_mcp_request(mcp_message, method)

    def _execute_mcp_request(
        self, mcp_message: Dict, method: str, is_retry: bool = False
    ) -> Dict:
        """Execute MCP request with optional retry on session failure."""
        try:
            final_headers = self._session.headers.copy()
            final_headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                }
            )

            if self._mcp_session_id:
                final_headers["Mcp-Session-Id"] = self._mcp_session_id
            response = self._session.post(
                self.server_url.rstrip("/"),
                json=mcp_message,
                headers=final_headers,
                timeout=self.timeout,
            )

            if "mcp-session-id" in response.headers:
                self._mcp_session_id = response.headers["mcp-session-id"]
                self._cache_session(self._mcp_session_id)
            response.raise_for_status()

            if method.startswith("notifications/"):
                return {}
            response_text = response.text.strip()
            if response_text.startswith("event:") and "data:" in response_text:
                lines = response_text.split("\n")
                data_line = None
                for line in lines:
                    if line.startswith("data:"):
                        data_line = line[5:].strip()
                        break
                if data_line:
                    try:
                        result = json.loads(data_line)
                    except json.JSONDecodeError:
                        raise Exception(f"Invalid JSON in SSE data: {data_line}")
                else:
                    raise Exception(f"No data found in SSE response: {response_text}")
            else:
                try:
                    result = response.json()
                except json.JSONDecodeError:
                    raise Exception(f"Invalid JSON response: {response.text}")
            if "error" in result:
                error_msg = result["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                raise Exception(f"MCP server error: {error_msg}")
            return result.get("result", result)
        except requests.exceptions.RequestException as e:
            if not is_retry and self._should_retry_with_new_session(e):
                self._invalidate_and_refresh_session()
                return self._execute_mcp_request(mcp_message, method, is_retry=True)
            raise Exception(f"MCP server request failed: {str(e)}")

    def _should_retry_with_new_session(self, error: Exception) -> bool:
        """Check if error indicates session invalidation and retry is warranted."""
        error_str = str(error).lower()
        return (
            any(
                indicator in error_str
                for indicator in [
                    "invalid session",
                    "session expired",
                    "unauthorized",
                    "401",
                    "403",
                ]
            )
            and self._mcp_session_id is not None
        )

    def _invalidate_and_refresh_session(self) -> None:
        """Invalidate current session and create a new one."""
        global _mcp_session_cache
        if self._cache_key in _mcp_session_cache:
            del _mcp_session_cache[self._cache_key]
        self._mcp_session_id = None
        self._initialize_mcp_connection()

    def discover_tools(self) -> List[Dict]:
        """
        Discover available tools from the MCP server using MCP protocol.

        Returns:
            List of tool definitions from the server
        """
        try:
            self._ensure_valid_session()

            response = self._make_mcp_request("tools/list")

            # Handle both formats: response with 'tools' key or response that IS the tools list

            if isinstance(response, dict):
                if "tools" in response:
                    self.available_tools = response["tools"]
                elif (
                    "result" in response
                    and isinstance(response["result"], dict)
                    and "tools" in response["result"]
                ):
                    self.available_tools = response["result"]["tools"]
                else:
                    self.available_tools = [response] if response else []
            elif isinstance(response, list):
                self.available_tools = response
            else:
                self.available_tools = []
            return self.available_tools
        except Exception as e:
            raise Exception(f"Failed to discover tools from MCP server: {str(e)}")

    def execute_action(self, action_name: str, **kwargs) -> Any:
        """
        Execute an action on the remote MCP server using MCP protocol.

        Args:
            action_name: Name of the action to execute
            **kwargs: Parameters for the action

        Returns:
            Result from the MCP server
        """
        self._ensure_valid_session()

        call_params = {"name": action_name, "arguments": kwargs}
        try:
            result = self._make_mcp_request("tools/call", call_params)
            return result
        except Exception as e:
            raise Exception(f"Failed to execute action '{action_name}': {str(e)}")

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
                        parameters_schema["properties"] = input_schema
            action = {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": parameters_schema,
            }
            actions.append(action)
        return actions

    def test_connection(self) -> Dict:
        """
        Test the connection to the MCP server and validate functionality.

        Returns:
            Dictionary with connection test results including tool count
        """
        try:
            self._mcp_session_id = None

            init_result = self._initialize_mcp_connection()

            tools = self.discover_tools()

            message = f"Successfully connected to MCP server. Found {len(tools)} tools."
            if init_result.get("cached"):
                message += " (Using cached session)"
            elif init_result.get("fallback"):
                message += " (No formal initialization required)"
            return {
                "success": True,
                "message": message,
                "tools_count": len(tools),
                "session_id": self._mcp_session_id,
                "tools": [tool.get("name", "unknown") for tool in tools[:5]],
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "tools_count": 0,
                "error_type": type(e).__name__,
            }

    def get_config_requirements(self) -> Dict:
        return {
            "server_url": {
                "type": "string",
                "description": "URL of the remote MCP server (e.g., https://api.example.com)",
                "required": True,
            },
            "auth_type": {
                "type": "string",
                "description": "Authentication type",
                "enum": ["none", "api_key", "bearer", "basic"],
                "default": "none",
                "required": True,
            },
            "auth_credentials": {
                "type": "object",
                "description": "Authentication credentials (varies by auth_type)",
                "required": False,
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds",
                "default": 30,
                "minimum": 1,
                "maximum": 300,
                "required": False,
            },
        }
