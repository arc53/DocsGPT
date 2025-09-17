import asyncio
import base64
import time
from typing import Any, Dict, List, Optional

from application.agents.tools.base import Tool
from application.security.encryption import decrypt_credentials

from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.client.transports import (
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)

_mcp_clients_cache = {}


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
                - transport_type: Transport type (auto, sse, http, stdio)
                - auth_type: Type of authentication (bearer, oauth, api_key, basic, none)
                - encrypted_credentials: Encrypted credentials (if available)
                - timeout: Request timeout in seconds (default: 30)
                - headers: Custom headers for requests
                - command: Command for STDIO transport
                - args: Arguments for STDIO transport
            user_id: User ID for decrypting credentials (required if encrypted_credentials exist)
        """
        self.config = config
        self.server_url = config.get("server_url", "")
        self.transport_type = config.get("transport_type", "auto")
        self.auth_type = config.get("auth_type", "none")
        self.timeout = config.get("timeout", 30)
        self.custom_headers = config.get("headers", {})

        self.auth_credentials = {}
        if config.get("encrypted_credentials") and user_id:
            self.auth_credentials = decrypt_credentials(
                config["encrypted_credentials"], user_id
            )
        else:
            self.auth_credentials = config.get("auth_credentials", {})
        self.available_tools = []
        self._cache_key = self._generate_cache_key()
        self._client = None

        # Only validate and setup if server_url is provided

        if self.server_url:
            self._setup_client()

    def _generate_cache_key(self) -> str:
        """Generate a unique cache key for this MCP server configuration."""
        auth_key = ""
        if self.auth_type in ["bearer", "oauth"]:
            token = self.auth_credentials.get(
                "bearer_token", ""
            ) or self.auth_credentials.get("access_token", "")
            auth_key = f"bearer:{token[:10]}..." if token else "bearer:none"
        elif self.auth_type == "api_key":
            api_key = self.auth_credentials.get("api_key", "")
            auth_key = f"apikey:{api_key[:10]}..." if api_key else "apikey:none"
        elif self.auth_type == "basic":
            username = self.auth_credentials.get("username", "")
            auth_key = f"basic:{username}"
        else:
            auth_key = "none"
        return f"{self.server_url}#{self.transport_type}#{auth_key}"

    def _setup_client(self):
        """Setup FastMCP client with proper transport and authentication."""
        global _mcp_clients_cache
        if self._cache_key in _mcp_clients_cache:
            cached_data = _mcp_clients_cache[self._cache_key]
            if time.time() - cached_data["created_at"] < 1800:
                self._client = cached_data["client"]
                return
            else:
                del _mcp_clients_cache[self._cache_key]
        transport = self._create_transport()

        if self.auth_type in ["bearer", "oauth"]:
            token = self.auth_credentials.get(
                "bearer_token", ""
            ) or self.auth_credentials.get("access_token", "")
            if token:
                self._client = Client(transport, auth=BearerAuth(token))
            else:
                self._client = Client(transport)
        else:
            self._client = Client(transport)
        _mcp_clients_cache[self._cache_key] = {
            "client": self._client,
            "created_at": time.time(),
        }

    def _create_transport(self):
        """Create appropriate transport based on configuration."""
        headers = {"Content-Type": "application/json", "User-Agent": "DocsGPT-MCP/1.0"}
        headers.update(self.custom_headers)

        if self.auth_type == "api_key":
            api_key = self.auth_credentials.get("api_key", "")
            header_name = self.auth_credentials.get("api_key_header", "X-API-Key")
            if api_key:
                headers[header_name] = api_key
        elif self.auth_type == "basic":
            username = self.auth_credentials.get("username", "")
            password = self.auth_credentials.get("password", "")
            if username and password:
                credentials = base64.b64encode(
                    f"{username}:{password}".encode()
                ).decode()
                headers["Authorization"] = f"Basic {credentials}"
        if self.transport_type == "auto":
            if "sse" in self.server_url.lower() or self.server_url.endswith("/sse"):
                transport_type = "sse"
            else:
                transport_type = "http"
        else:
            transport_type = self.transport_type
        if transport_type == "sse":
            headers.update({"Accept": "text/event-stream", "Cache-Control": "no-cache"})
            return SSETransport(url=self.server_url, headers=headers)
        elif transport_type == "http":
            return StreamableHttpTransport(url=self.server_url, headers=headers)
        elif transport_type == "stdio":
            command = self.config.get("command", "python")
            args = self.config.get("args", [])
            env = self.auth_credentials if self.auth_credentials else None
            return StdioTransport(command=command, args=args, env=env)
        else:
            return StreamableHttpTransport(url=self.server_url, headers=headers)

    async def _execute_with_client(self, operation: str, *args, **kwargs):
        """Execute operation with FastMCP client."""
        if not self._client:
            raise Exception("FastMCP client not initialized")
        async with self._client:
            if operation == "ping":
                return await self._client.ping()
            elif operation == "list_tools":
                tools_response = await self._client.list_tools()

                if hasattr(tools_response, "tools"):
                    tools = tools_response.tools
                elif isinstance(tools_response, list):
                    tools = tools_response
                else:
                    tools = []
                tools_dict = []
                for tool in tools:
                    if hasattr(tool, "name"):
                        tool_dict = {
                            "name": tool.name,
                            "description": tool.description,
                        }
                        if hasattr(tool, "inputSchema"):
                            tool_dict["inputSchema"] = tool.inputSchema
                        tools_dict.append(tool_dict)
                    elif isinstance(tool, dict):
                        tools_dict.append(tool)
                    else:

                        if hasattr(tool, "model_dump"):
                            tools_dict.append(tool.model_dump())
                        else:
                            tools_dict.append({"name": str(tool), "description": ""})
                return tools_dict
            elif operation == "call_tool":
                tool_name = args[0]
                tool_args = kwargs
                return await self._client.call_tool(tool_name, tool_args)
            elif operation == "list_resources":
                return await self._client.list_resources()
            elif operation == "list_prompts":
                return await self._client.list_prompts()
            else:
                raise Exception(f"Unknown operation: {operation}")

    def _run_async_operation(self, operation: str, *args, **kwargs):
        """Run async operation in sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            self._execute_with_client(operation, *args, **kwargs)
                        )
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    return future.result(timeout=self.timeout)
            else:
                return loop.run_until_complete(
                    self._execute_with_client(operation, *args, **kwargs)
                )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self._execute_with_client(operation, *args, **kwargs)
                )
            finally:
                loop.close()

    def discover_tools(self) -> List[Dict]:
        """
        Discover available tools from the MCP server using FastMCP.

        Returns:
            List of tool definitions from the server
        """
        if not self.server_url:
            return []
        if not self._client:
            self._setup_client()
        try:
            tools = self._run_async_operation("list_tools")
            self.available_tools = tools
            return self.available_tools
        except Exception as e:
            raise Exception(f"Failed to discover tools from MCP server: {str(e)}")

    def execute_action(self, action_name: str, **kwargs) -> Any:
        """
        Execute an action on the remote MCP server using FastMCP.

        Args:
            action_name: Name of the action to execute
            **kwargs: Parameters for the action

        Returns:
            Result from the MCP server
        """
        if not self.server_url:
            raise Exception("No MCP server configured")
        if not self._client:
            self._setup_client()
        cleaned_kwargs = {}
        for key, value in kwargs.items():
            if value == "" or value is None:
                continue
            cleaned_kwargs[key] = value
        try:
            result = self._run_async_operation(
                "call_tool", action_name, **cleaned_kwargs
            )
            return self._format_result(result)
        except Exception as e:
            raise Exception(f"Failed to execute action '{action_name}': {str(e)}")

    def _format_result(self, result) -> Dict:
        """Format FastMCP result to match expected format."""
        if hasattr(result, "content"):
            content_list = []
            for content_item in result.content:
                if hasattr(content_item, "text"):
                    content_list.append({"type": "text", "text": content_item.text})
                elif hasattr(content_item, "data"):
                    content_list.append({"type": "data", "data": content_item.data})
                else:
                    content_list.append(
                        {"type": "unknown", "content": str(content_item)}
                    )
            return {
                "content": content_list,
                "isError": getattr(result, "isError", False),
            }
        else:
            return result

    def test_connection(self) -> Dict:
        """
        Test the connection to the MCP server and validate functionality.

        Returns:
            Dictionary with connection test results including tool count
        """
        if not self.server_url:
            return {
                "success": False,
                "message": "No MCP server URL configured",
                "tools_count": 0,
                "transport_type": self.transport_type,
                "auth_type": self.auth_type,
                "error_type": "ConfigurationError",
            }
        if not self._client:
            self._setup_client()
        try:
            try:
                self._run_async_operation("ping")
                ping_success = True
            except Exception:
                ping_success = False
            tools = self.discover_tools()

            message = f"Successfully connected to MCP server. Found {len(tools)} tools."
            if not ping_success:
                message += " (Ping not supported, but tool discovery worked)"
            return {
                "success": True,
                "message": message,
                "tools_count": len(tools),
                "transport_type": self.transport_type,
                "auth_type": self.auth_type,
                "ping_supported": ping_success,
                "tools": [tool.get("name", "unknown") for tool in tools[:5]],
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "tools_count": 0,
                "transport_type": self.transport_type,
                "auth_type": self.auth_type,
                "error_type": type(e).__name__,
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
                        parameters_schema["properties"] = input_schema
            action = {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": parameters_schema,
            }
            actions.append(action)
        return actions

    def get_config_requirements(self) -> Dict:
        """Get configuration requirements for the MCP tool."""
        return {
            "server_url": {
                "type": "string",
                "description": "URL of the remote MCP server (e.g., https://api.example.com/mcp or https://docs.mcp.cloudflare.com/sse)",
                "required": True,
            },
            "transport_type": {
                "type": "string",
                "description": "Transport type for connection",
                "enum": ["auto", "sse", "http", "stdio"],
                "default": "auto",
                "required": False,
                "help": {
                    "auto": "Automatically detect best transport",
                    "sse": "Server-Sent Events (for real-time streaming)",
                    "http": "HTTP streaming (recommended for production)",
                    "stdio": "Standard I/O (for local servers)",
                },
            },
            "auth_type": {
                "type": "string",
                "description": "Authentication type",
                "enum": ["none", "bearer", "oauth", "api_key", "basic"],
                "default": "none",
                "required": True,
                "help": {
                    "none": "No authentication",
                    "bearer": "Bearer token authentication",
                    "oauth": "OAuth 2.0 authentication",
                    "api_key": "API key authentication",
                    "basic": "Basic authentication",
                },
            },
            "auth_credentials": {
                "type": "object",
                "description": "Authentication credentials (varies by auth_type)",
                "required": False,
                "properties": {
                    "bearer_token": {
                        "type": "string",
                        "description": "Bearer token for bearer/oauth auth",
                    },
                    "access_token": {
                        "type": "string",
                        "description": "Access token for OAuth",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for api_key auth",
                    },
                    "api_key_header": {
                        "type": "string",
                        "description": "Header name for API key (default: X-API-Key)",
                    },
                    "username": {
                        "type": "string",
                        "description": "Username for basic auth",
                    },
                    "password": {
                        "type": "string",
                        "description": "Password for basic auth",
                    },
                },
            },
            "headers": {
                "type": "object",
                "description": "Custom headers to send with requests",
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
            "command": {
                "type": "string",
                "description": "Command to run for STDIO transport (e.g., 'python')",
                "required": False,
            },
            "args": {
                "type": "array",
                "description": "Arguments for STDIO command",
                "items": {"type": "string"},
                "required": False,
            },
        }
