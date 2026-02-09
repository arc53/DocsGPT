import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from application.agents.tools.base import Tool
from application.api.user.tasks import mcp_oauth_status_task, mcp_oauth_task
from application.cache import get_redis_instance

from application.core.mongo_db import MongoDB

from application.core.settings import settings

from application.security.encryption import decrypt_credentials
from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.client.transports import (
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from pydantic import AnyHttpUrl, ValidationError
from redis import Redis

mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]

_mcp_clients_cache = {}


class MCPTool(Tool):
    """
    MCP Tool
    Connect to remote Model Context Protocol (MCP) servers to access dynamic tools and resources.
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
                - oauth_scopes: OAuth scopes for oauth auth type
                - oauth_client_name: OAuth client name for oauth auth type
            user_id: User ID for decrypting credentials (required if encrypted_credentials exist)
        """
        self.config = config
        self.user_id = user_id
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
        self.oauth_scopes = config.get("oauth_scopes", [])
        self.oauth_task_id = config.get("oauth_task_id", None)
        self.oauth_client_name = config.get("oauth_client_name", "DocsGPT-MCP")
        self.redirect_uri = f"{settings.API_URL}/api/mcp_server/callback"

        self.available_tools = []
        self._cache_key = self._generate_cache_key()
        self._client = None

        # Only validate and setup if server_url is provided and not OAuth

        if self.server_url and self.auth_type != "oauth":
            self._setup_client()

    def _generate_cache_key(self) -> str:
        """Generate a unique cache key for this MCP server configuration."""
        auth_key = ""
        if self.auth_type == "oauth":
            scopes_str = ",".join(self.oauth_scopes) if self.oauth_scopes else "none"
            auth_key = f"oauth:{self.oauth_client_name}:{scopes_str}"
        elif self.auth_type in ["bearer"]:
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
        auth = None

        if self.auth_type == "oauth":
            redis_client = get_redis_instance()
            auth = DocsGPTOAuth(
                mcp_url=self.server_url,
                scopes=self.oauth_scopes,
                redis_client=redis_client,
                redirect_uri=self.redirect_uri,
                task_id=self.oauth_task_id,
                db=db,
                user_id=self.user_id,
            )
        elif self.auth_type == "bearer":
            token = self.auth_credentials.get(
                "bearer_token", ""
            ) or self.auth_credentials.get("access_token", "")
            if token:
                auth = BearerAuth(token)
        self._client = Client(transport, auth=auth)
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
        if transport_type == "stdio":
            raise ValueError("STDIO transport is disabled")
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

    def _format_tools(self, tools_response) -> List[Dict]:
        """Format tools response to match expected format."""
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

    async def _execute_with_client(self, operation: str, *args, **kwargs):
        """Execute operation with FastMCP client."""
        if not self._client:
            raise Exception("FastMCP client not initialized")
        async with self._client:
            if operation == "ping":
                return await self._client.ping()
            elif operation == "list_tools":
                tools_response = await self._client.list_tools()
                self.available_tools = self._format_tools(tools_response)
                return self.available_tools
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
            try:
                loop = asyncio.get_running_loop()
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
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(
                        self._execute_with_client(operation, *args, **kwargs)
                    )
                finally:
                    loop.close()
        except Exception as e:
            print(f"Error occurred while running async operation: {e}")
            raise

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
            if self.auth_type == "oauth":
                return self._test_oauth_connection()
            else:
                return self._test_regular_connection()
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "tools_count": 0,
                "transport_type": self.transport_type,
                "auth_type": self.auth_type,
                "error_type": type(e).__name__,
            }

    def _test_regular_connection(self) -> Dict:
        """Test connection for non-OAuth auth types."""
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
            "tools": [tool.get("name", "unknown") for tool in tools],
        }

    def _test_oauth_connection(self) -> Dict:
        """Test connection for OAuth auth type with proper async handling."""
        try:
            task = mcp_oauth_task.delay(config=self.config, user=self.user_id)
            if not task:
                raise Exception("Failed to start OAuth authentication")
            return {
                "success": True,
                "requires_oauth": True,
                "task_id": task.id,
                "status": "pending",
                "message": "OAuth flow started",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"OAuth connection failed: {str(e)}",
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
        transport_enum = ["auto", "sse", "http"]
        transport_help = {
            "auto": "Automatically detect best transport",
            "sse": "Server-Sent Events (for real-time streaming)",
            "http": "HTTP streaming (recommended for production)",
        }
        return {
            "server_url": {
                "type": "string",
                "description": "URL of the remote MCP server (e.g., https://api.example.com/mcp or https://docs.mcp.cloudflare.com/sse)",
                "required": True,
            },
            "transport_type": {
                "type": "string",
                "description": "Transport type for connection",
                "enum": transport_enum,
                "default": "auto",
                "required": False,
                "help": {
                    **transport_help,
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
                    "oauth": "OAuth 2.1 authentication (with frontend integration)",
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
                        "description": "Bearer token for bearer auth",
                    },
                    "access_token": {
                        "type": "string",
                        "description": "Access token for OAuth (if pre-obtained)",
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
            "oauth_scopes": {
                "type": "array",
                "description": "OAuth scopes to request (for oauth auth_type)",
                "items": {"type": "string"},
                "required": False,
                "default": [],
            },
            "oauth_client_name": {
                "type": "string",
                "description": "Client name for OAuth registration (for oauth auth_type)",
                "default": "DocsGPT-MCP",
                "required": False,
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


class DocsGPTOAuth(OAuthClientProvider):
    """
    Custom OAuth handler for DocsGPT that uses frontend redirect instead of browser.
    """

    def __init__(
        self,
        mcp_url: str,
        redirect_uri: str,
        redis_client: Redis | None = None,
        redis_prefix: str = "mcp_oauth:",
        task_id: str = None,
        scopes: str | list[str] | None = None,
        client_name: str = "DocsGPT-MCP",
        user_id=None,
        db=None,
        additional_client_metadata: dict[str, Any] | None = None,
    ):
        """
        Initialize custom OAuth client provider for DocsGPT.

        Args:
            mcp_url: Full URL to the MCP endpoint
            redirect_uri: Custom redirect URI for DocsGPT frontend
            redis_client: Redis client for storing auth state
            redis_prefix: Prefix for Redis keys
            task_id: Task ID for tracking auth status
            scopes: OAuth scopes to request
            client_name: Name for this client during registration
            user_id: User ID for token storage
            db: Database instance for token storage
            additional_client_metadata: Extra fields for OAuthClientMetadata
        """

        self.redirect_uri = redirect_uri
        self.redis_client = redis_client
        self.redis_prefix = redis_prefix
        self.task_id = task_id
        self.user_id = user_id
        self.db = db

        parsed_url = urlparse(mcp_url)
        self.server_base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        if isinstance(scopes, list):
            scopes = " ".join(scopes)
        client_metadata = OAuthClientMetadata(
            client_name=client_name,
            redirect_uris=[AnyHttpUrl(redirect_uri)],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=scopes,
            **(additional_client_metadata or {}),
        )

        storage = DBTokenStorage(
            server_url=self.server_base_url, user_id=self.user_id, db_client=self.db
        )

        super().__init__(
            server_url=self.server_base_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=self.redirect_handler,
            callback_handler=self.callback_handler,
        )

        self.auth_url = None
        self.extracted_state = None

    def _process_auth_url(self, authorization_url: str) -> tuple[str, str]:
        """Process authorization URL to extract state"""
        try:
            parsed_url = urlparse(authorization_url)
            query_params = parse_qs(parsed_url.query)

            state_params = query_params.get("state", [])
            if state_params:
                state = state_params[0]
            else:
                raise ValueError("No state in auth URL")
            return authorization_url, state
        except Exception as e:
            raise Exception(f"Failed to process auth URL: {e}")

    async def redirect_handler(self, authorization_url: str) -> None:
        """Store auth URL and state in Redis for frontend to use."""
        auth_url, state = self._process_auth_url(authorization_url)
        logging.info(
            "[DocsGPTOAuth] Processed auth_url: %s, state: %s", auth_url, state
        )
        self.auth_url = auth_url
        self.extracted_state = state

        if self.redis_client and self.extracted_state:
            key = f"{self.redis_prefix}auth_url:{self.extracted_state}"
            self.redis_client.setex(key, 600, auth_url)
            logging.info("[DocsGPTOAuth] Stored auth_url in Redis: %s", key)

            if self.task_id:
                status_key = f"mcp_oauth_status:{self.task_id}"
                status_data = {
                    "status": "requires_redirect",
                    "message": "OAuth authorization required",
                    "authorization_url": self.auth_url,
                    "state": self.extracted_state,
                    "requires_oauth": True,
                    "task_id": self.task_id,
                }
                self.redis_client.setex(status_key, 600, json.dumps(status_data))

    async def callback_handler(self) -> tuple[str, str | None]:
        """Wait for auth code from Redis using the state value."""
        if not self.redis_client or not self.extracted_state:
            raise Exception("Redis client or state not configured for OAuth")
        poll_interval = 1
        max_wait_time = 300
        code_key = f"{self.redis_prefix}code:{self.extracted_state}"

        if self.task_id:
            status_key = f"mcp_oauth_status:{self.task_id}"
            status_data = {
                "status": "awaiting_callback",
                "message": "Waiting for OAuth callback...",
                "authorization_url": self.auth_url,
                "state": self.extracted_state,
                "requires_oauth": True,
                "task_id": self.task_id,
            }
            self.redis_client.setex(status_key, 600, json.dumps(status_data))
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            code_data = self.redis_client.get(code_key)
            if code_data:
                code = code_data.decode()
                returned_state = self.extracted_state

                self.redis_client.delete(code_key)
                self.redis_client.delete(
                    f"{self.redis_prefix}auth_url:{self.extracted_state}"
                )
                self.redis_client.delete(
                    f"{self.redis_prefix}state:{self.extracted_state}"
                )

                if self.task_id:
                    status_data = {
                        "status": "callback_received",
                        "message": "OAuth callback received, completing authentication...",
                        "task_id": self.task_id,
                    }
                    self.redis_client.setex(status_key, 600, json.dumps(status_data))
                return code, returned_state
            error_key = f"{self.redis_prefix}error:{self.extracted_state}"
            error_data = self.redis_client.get(error_key)
            if error_data:
                error_msg = error_data.decode()
                self.redis_client.delete(error_key)
                self.redis_client.delete(
                    f"{self.redis_prefix}auth_url:{self.extracted_state}"
                )
                self.redis_client.delete(
                    f"{self.redis_prefix}state:{self.extracted_state}"
                )
                raise Exception(f"OAuth error: {error_msg}")
            await asyncio.sleep(poll_interval)
        self.redis_client.delete(f"{self.redis_prefix}auth_url:{self.extracted_state}")
        self.redis_client.delete(f"{self.redis_prefix}state:{self.extracted_state}")
        raise Exception("OAuth callback timeout: no code received within 5 minutes")


class DBTokenStorage(TokenStorage):
    def __init__(self, server_url: str, user_id: str, db_client):
        self.server_url = server_url
        self.user_id = user_id
        self.db_client = db_client
        self.collection = db_client["connector_sessions"]

    @staticmethod
    def get_base_url(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def get_db_key(self) -> dict:
        return {
            "server_url": self.get_base_url(self.server_url),
            "user_id": self.user_id,
        }

    async def get_tokens(self) -> OAuthToken | None:
        doc = await asyncio.to_thread(self.collection.find_one, self.get_db_key())
        if not doc or "tokens" not in doc:
            return None
        try:
            tokens = OAuthToken.model_validate(doc["tokens"])
            return tokens
        except ValidationError as e:
            logging.error(f"Could not load tokens: {e}")
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await asyncio.to_thread(
            self.collection.update_one,
            self.get_db_key(),
            {"$set": {"tokens": tokens.model_dump()}},
            True,
        )
        logging.info(f"Saved tokens for {self.get_base_url(self.server_url)}")

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        doc = await asyncio.to_thread(self.collection.find_one, self.get_db_key())
        if not doc or "client_info" not in doc:
            return None
        try:
            client_info = OAuthClientInformationFull.model_validate(doc["client_info"])
            tokens = await self.get_tokens()
            if tokens is None:
                logging.debug(
                    "No tokens found, clearing client info to force fresh registration."
                )
                await asyncio.to_thread(
                    self.collection.update_one,
                    self.get_db_key(),
                    {"$unset": {"client_info": ""}},
                )
                return None
            return client_info
        except ValidationError as e:
            logging.error(f"Could not load client info: {e}")
            return None

    def _serialize_client_info(self, info: dict) -> dict:
        if "redirect_uris" in info and isinstance(info["redirect_uris"], list):
            info["redirect_uris"] = [str(u) for u in info["redirect_uris"]]
        return info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        serialized_info = self._serialize_client_info(client_info.model_dump())
        await asyncio.to_thread(
            self.collection.update_one,
            self.get_db_key(),
            {"$set": {"client_info": serialized_info}},
            True,
        )
        logging.info(f"Saved client info for {self.get_base_url(self.server_url)}")

    async def clear(self) -> None:
        await asyncio.to_thread(self.collection.delete_one, self.get_db_key())
        logging.info(f"Cleared OAuth cache for {self.get_base_url(self.server_url)}")

    @classmethod
    async def clear_all(cls, db_client) -> None:
        collection = db_client["connector_sessions"]
        await asyncio.to_thread(collection.delete_many, {})
        logging.info("Cleared all OAuth client cache data.")


class MCPOAuthManager:
    """Manager for handling MCP OAuth callbacks."""

    def __init__(self, redis_client: Redis | None, redis_prefix: str = "mcp_oauth:"):
        self.redis_client = redis_client
        self.redis_prefix = redis_prefix

    def handle_oauth_callback(
        self, state: str, code: str, error: Optional[str] = None
    ) -> bool:
        """
        Handle OAuth callback from provider.

        Args:
            state: The state parameter from OAuth callback
            code: The authorization code from OAuth callback
            error: Error message if OAuth failed

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.redis_client or not state:
                raise Exception("Redis client or state not provided")
            if error:
                error_key = f"{self.redis_prefix}error:{state}"
                self.redis_client.setex(error_key, 300, error)
                raise Exception(f"OAuth error received: {error}")
            code_key = f"{self.redis_prefix}code:{state}"
            self.redis_client.setex(code_key, 300, code)

            state_key = f"{self.redis_prefix}state:{state}"
            self.redis_client.setex(state_key, 300, "completed")

            return True
        except Exception as e:
            logging.error(f"Error handling OAuth callback: {e}")
            return False

    def get_oauth_status(self, task_id: str) -> Dict[str, Any]:
        """Get current status of OAuth flow using provided task_id."""
        if not task_id:
            return {"status": "not_started", "message": "OAuth flow not started"}
        return mcp_oauth_status_task(task_id)
