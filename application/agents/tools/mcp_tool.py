import asyncio
import base64
import concurrent.futures
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

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

from application.agents.tools.base import Tool
from application.api.user.tasks import mcp_oauth_task
from application.cache import get_redis_instance
from application.core.settings import settings
from application.core.url_validation import SSRFError, validate_url
from application.events.keys import stream_key
from application.security.encryption import decrypt_credentials

logger = logging.getLogger(__name__)

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
                - query_mode: If True, use non-interactive OAuth (fail-fast on 401)
            user_id: User ID for decrypting credentials (required if encrypted_credentials exist)
        """
        self.config = config
        self.user_id = user_id
        raw_url = config.get("server_url", "")
        self.server_url = self._validate_server_url(raw_url) if raw_url else ""
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
        self.redirect_uri = self._resolve_redirect_uri(config.get("redirect_uri"))
        # Pulled out of ``config`` (rather than left in ``self.config``)
        # because it is a callable supplied by the OAuth worker — not
        # something the rest of the tool plumbing should marshal or
        # serialize. ``DocsGPTOAuth`` invokes it from ``redirect_handler``
        # so the SSE envelope can carry ``authorization_url``.
        self.oauth_redirect_publish = config.pop("oauth_redirect_publish", None)

        self.available_tools = []
        self._cache_key = self._generate_cache_key()
        self._client = None
        self.query_mode = config.get("query_mode", False)

        if self.server_url and self.auth_type != "oauth":
            self._setup_client()

    @staticmethod
    def _validate_server_url(server_url: str) -> str:
        """Validate server_url to prevent SSRF to internal networks.

        Raises:
            ValueError: If the URL points to a private/internal address.
        """
        try:
            return validate_url(server_url)
        except SSRFError as exc:
            raise ValueError(f"Invalid MCP server URL: {exc}") from exc

    def _resolve_redirect_uri(self, configured_redirect_uri: Optional[str]) -> str:
        if configured_redirect_uri:
            return configured_redirect_uri.rstrip("/")

        explicit = getattr(settings, "MCP_OAUTH_REDIRECT_URI", None)
        if explicit:
            return explicit.rstrip("/")

        connector_base = getattr(settings, "CONNECTOR_REDIRECT_BASE_URI", None)
        if connector_base:
            parsed = urlparse(connector_base)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}/api/mcp_server/callback"

        return f"{settings.API_URL.rstrip('/')}/api/mcp_server/callback"

    def _generate_cache_key(self) -> str:
        """Generate a unique cache key for this MCP server configuration."""
        auth_key = ""
        if self.auth_type == "oauth":
            scopes_str = ",".join(self.oauth_scopes) if self.oauth_scopes else "none"
            oauth_identity = self.user_id or self.oauth_task_id or "anonymous"
            auth_key = (
                f"oauth:{oauth_identity}:{self.oauth_client_name}:{scopes_str}:{self.redirect_uri}"
            )
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
        global _mcp_clients_cache
        if self._cache_key in _mcp_clients_cache:
            cached_data = _mcp_clients_cache[self._cache_key]
            if time.time() - cached_data["created_at"] < 300:
                self._client = cached_data["client"]
                return
            else:
                del _mcp_clients_cache[self._cache_key]
        transport = self._create_transport()
        auth = None

        if self.auth_type == "oauth":
            redis_client = get_redis_instance()
            if self.query_mode:
                auth = NonInteractiveOAuth(
                    mcp_url=self.server_url,
                    scopes=self.oauth_scopes,
                    redis_client=redis_client,
                    redirect_uri=self.redirect_uri,
                    user_id=self.user_id,
                )
            else:
                auth = DocsGPTOAuth(
                    mcp_url=self.server_url,
                    scopes=self.oauth_scopes,
                    redis_client=redis_client,
                    redirect_uri=self.redirect_uri,
                    task_id=self.oauth_task_id,
                    user_id=self.user_id,
                    redirect_publish=self.oauth_redirect_publish,
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

    _ERROR_MAP = [
        (concurrent.futures.TimeoutError, lambda op, t, _: f"Timed out after {t}s"),
        (ConnectionRefusedError, lambda *_: "Connection refused"),
    ]

    _ERROR_PATTERNS = {
        ("403", "Forbidden"): "Access denied (403 Forbidden)",
        ("401", "Unauthorized"): "Authentication failed (401 Unauthorized)",
        ("ECONNREFUSED",): "Connection refused",
        ("SSL", "certificate"): "SSL/TLS error",
    }

    def _run_async_operation(self, operation: str, *args, **kwargs):
        try:
            try:
                asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        self._run_in_new_loop, operation, *args, **kwargs
                    )
                    return future.result(timeout=self.timeout)
            except RuntimeError:
                return self._run_in_new_loop(operation, *args, **kwargs)
        except Exception as e:
            raise self._map_error(operation, e) from e
            raise self._map_error(operation, e) from e

    def _run_in_new_loop(self, operation, *args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self._execute_with_client(operation, *args, **kwargs)
            )
        finally:
            loop.close()

    def _map_error(self, operation: str, exc: Exception) -> Exception:
        for exc_type, msg_fn in self._ERROR_MAP:
            if isinstance(exc, exc_type):
                return Exception(msg_fn(operation, self.timeout, exc))
        error_msg = str(exc)
        for patterns, friendly in self._ERROR_PATTERNS.items():
            if any(p.lower() in error_msg.lower() for p in patterns):
                return Exception(friendly)
        logger.error("MCP %s failed: %s", operation, exc)
        return exc

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
            error_msg = str(e)
            lower_msg = error_msg.lower()
            is_auth_error = (
                "401" in error_msg
                or "unauthorized" in lower_msg
                or "session expired" in lower_msg
                or "re-authorize" in lower_msg
            )
            if is_auth_error:
                if self.auth_type == "oauth":
                    raise Exception(
                        f"Action '{action_name}' failed: OAuth session expired. "
                        "Please re-authorize this MCP server in tool settings."
                    ) from e
                global _mcp_clients_cache
                _mcp_clients_cache.pop(self._cache_key, None)
                self._client = None
                self._setup_client()
                try:
                    result = self._run_async_operation(
                        "call_tool", action_name, **cleaned_kwargs
                    )
                    return self._format_result(result)
                except Exception as retry_e:
                    raise Exception(
                        f"Action '{action_name}' failed after re-auth attempt: {retry_e}. "
                        "Your credentials may have expired — please re-authorize in tool settings."
                    ) from retry_e
            raise Exception(
                f"Failed to execute action '{action_name}': {error_msg}"
            ) from e

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
        if not self.server_url:
            return {
                "success": False,
                "message": "No server URL configured",
                "tools_count": 0,
            }
        try:
            parsed = urlparse(self.server_url)
            if parsed.scheme not in ("http", "https"):
                return {
                    "success": False,
                    "message": f"Invalid URL scheme '{parsed.scheme}' — use http:// or https://",
                    "tools_count": 0,
                }
        except Exception:
            return {
                "success": False,
                "message": "Invalid URL format",
                "tools_count": 0,
            }
        if not self._client:
            try:
                self._setup_client()
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Client init failed: {str(e)}",
                    "tools_count": 0,
                }
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
            }

    def _test_regular_connection(self) -> Dict:
        ping_ok = False
        ping_error = None
        try:
            self._run_async_operation("ping")
            ping_ok = True
        except Exception as e:
            ping_error = str(e)

        try:
            tools = self.discover_tools()
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {ping_error or str(e)}",
                "tools_count": 0,
            }

        if not tools and not ping_ok:
            return {
                "success": False,
                "message": f"Connection failed: {ping_error or 'No tools found'}",
                "tools_count": 0,
            }

        return {
            "success": True,
            "message": f"Connected — found {len(tools)} tool{'s' if len(tools) != 1 else ''}.",
            "tools_count": len(tools),
            "tools": [
                {
                    "name": tool.get("name", "unknown"),
                    "description": tool.get("description", ""),
                }
                for tool in tools
            ],
        }

    def _test_oauth_connection(self) -> Dict:
        storage = DBTokenStorage(
            server_url=self.server_url, user_id=self.user_id,
        )
        loop = asyncio.new_event_loop()
        try:
            tokens = loop.run_until_complete(storage.get_tokens())
        finally:
            loop.close()

        if tokens and tokens.access_token:
            self.query_mode = True
            _mcp_clients_cache.pop(self._cache_key, None)
            self._client = None
            self._setup_client()
            try:
                tools = self.discover_tools()
                return {
                    "success": True,
                    "message": f"Connected — found {len(tools)} tool{'s' if len(tools) != 1 else ''}.",
                    "tools_count": len(tools),
                    "tools": [
                        {
                            "name": t.get("name", "unknown"),
                            "description": t.get("description", ""),
                        }
                        for t in tools
                    ],
                }
            except Exception as e:
                logger.warning("OAuth token validation failed: %s", e)
                _mcp_clients_cache.pop(self._cache_key, None)
                self._client = None

        return self._start_oauth_task()

    def _start_oauth_task(self) -> Dict:
        task_config = self.config.copy()
        task_config.pop("query_mode", None)
        result = mcp_oauth_task.delay(task_config, self.user_id)
        return {
            "success": False,
            "requires_oauth": True,
            "task_id": result.id,
            "message": "OAuth authorization required.",
            "tools_count": 0,
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
                "default": "none",
                "required": True,
                "secret": False,
                "order": 2,
            },
            "api_key": {
                "type": "string",
                "label": "API Key",
                "description": "API key for authentication",
                "required": False,
                "secret": True,
                "order": 3,
                "depends_on": {"auth_type": "api_key"},
            },
            "api_key_header": {
                "type": "string",
                "label": "API Key Header",
                "description": "Header name for API key (default: X-API-Key)",
                "default": "X-API-Key",
                "required": False,
                "secret": False,
                "order": 4,
                "depends_on": {"auth_type": "api_key"},
            },
            "bearer_token": {
                "type": "string",
                "label": "Bearer Token",
                "description": "Bearer token for authentication",
                "required": False,
                "secret": True,
                "order": 3,
                "depends_on": {"auth_type": "bearer"},
            },
            "username": {
                "type": "string",
                "label": "Username",
                "description": "Username for basic authentication",
                "required": False,
                "secret": False,
                "order": 3,
                "depends_on": {"auth_type": "basic"},
            },
            "password": {
                "type": "string",
                "label": "Password",
                "description": "Password for basic authentication",
                "required": False,
                "secret": True,
                "order": 4,
                "depends_on": {"auth_type": "basic"},
            },
            "oauth_scopes": {
                "type": "string",
                "label": "OAuth Scopes",
                "description": "Comma-separated OAuth scopes to request",
                "required": False,
                "secret": False,
                "order": 3,
                "depends_on": {"auth_type": "oauth"},
            },
            "timeout": {
                "type": "number",
                "label": "Timeout (seconds)",
                "description": "Request timeout in seconds (1-300)",
                "default": 30,
                "required": False,
                "secret": False,
                "order": 10,
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
        additional_client_metadata: dict[str, Any] | None = None,
        skip_redirect_validation: bool = False,
        redirect_publish=None,
    ):
        self.redirect_uri = redirect_uri
        self.redis_client = redis_client
        self.redis_prefix = redis_prefix
        self.task_id = task_id
        self.user_id = user_id
        # Worker-supplied callback. Invoked from ``redirect_handler``
        # once the authorization URL is known so the SSE envelope can
        # carry it. ``None`` for any non-worker entrypoint.
        self.redirect_publish = redirect_publish

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
            server_url=self.server_base_url,
            user_id=self.user_id,
            expected_redirect_uri=None if skip_redirect_validation else redirect_uri,
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
        logger.info("Processed auth_url: %s, state: %s", auth_url, state)
        self.auth_url = auth_url
        self.extracted_state = state

        if self.redis_client and self.extracted_state:
            key = f"{self.redis_prefix}auth_url:{self.extracted_state}"
            self.redis_client.setex(key, 600, auth_url)
            logger.info("Stored auth_url in Redis: %s", key)

        if self.redirect_publish is not None:
            # Best-effort: a publish failure must not abort the OAuth
            # handshake — the user can still authorize via the popup
            # opened from the legacy polling fallback if the SSE
            # envelope is lost.
            try:
                self.redirect_publish(auth_url)
            except Exception:
                logger.warning(
                    "redirect_publish callback raised for task_id=%s",
                    self.task_id,
                    exc_info=True,
                )

    async def callback_handler(self) -> tuple[str, str | None]:
        """Wait for auth code from Redis using the state value."""
        if not self.redis_client or not self.extracted_state:
            raise Exception("Redis client or state not configured for OAuth")
        poll_interval = 1
        max_wait_time = 300
        code_key = f"{self.redis_prefix}code:{self.extracted_state}"

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
        raise Exception("OAuth timeout: no code received within 5 minutes")


class NonInteractiveOAuth(DocsGPTOAuth):
    """OAuth provider that fails fast on 401 instead of starting interactive auth.

    Used during query execution to prevent the streaming response from blocking
    while waiting for user authorization that will never come.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("task_id", None)
        kwargs["skip_redirect_validation"] = True
        super().__init__(**kwargs)

    async def redirect_handler(self, authorization_url: str) -> None:
        raise Exception(
            "OAuth session expired — please re-authorize this MCP server in tool settings."
        )

    async def callback_handler(self) -> tuple[str, str | None]:
        raise Exception(
            "OAuth session expired — please re-authorize this MCP server in tool settings."
        )


class DBTokenStorage(TokenStorage):
    def __init__(
        self,
        server_url: str,
        user_id: str,
        expected_redirect_uri: Optional[str] = None,
    ):
        self.server_url = server_url
        self.user_id = user_id
        self.expected_redirect_uri = expected_redirect_uri

    @staticmethod
    def get_base_url(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _pg_provider(self) -> str:
        return f"mcp:{self.get_base_url(self.server_url)}"

    def _fetch_session_data(self) -> dict:
        """Read the JSONB ``session_data`` blob for this MCP server row."""
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        from application.storage.db.session import db_readonly

        base_url = self.get_base_url(self.server_url)
        with db_readonly() as conn:
            row = ConnectorSessionsRepository(conn).get_by_user_and_server_url(
                self.user_id, base_url,
            )
        if not row:
            return {}
        data = row.get("session_data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                return {}
        return data if isinstance(data, dict) else {}

    async def get_tokens(self) -> OAuthToken | None:
        data = await asyncio.to_thread(self._fetch_session_data)
        if not data or "tokens" not in data:
            return None
        try:
            return OAuthToken.model_validate(data["tokens"])
        except ValidationError as e:
            logger.error("Could not load tokens: %s", e)
            return None

    def _merge(self, patch: dict) -> None:
        """Shallow-merge ``patch`` into this row's ``session_data``.

        Threads ``server_url`` through to the repository so it lands in
        the scalar column — ``get_by_user_and_server_url`` needs that to
        resolve the row (``NULL = 'https://...'`` is UNKNOWN in SQL).
        """
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        from application.storage.db.session import db_session

        base_url = self.get_base_url(self.server_url)
        with db_session() as conn:
            ConnectorSessionsRepository(conn).merge_session_data(
                self.user_id, self._pg_provider(), base_url, patch,
            )

    def _delete(self) -> None:
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        from application.storage.db.session import db_session

        with db_session() as conn:
            ConnectorSessionsRepository(conn).delete(
                self.user_id, self._pg_provider(),
            )

    async def set_tokens(self, tokens: OAuthToken) -> None:
        base_url = self.get_base_url(self.server_url)
        token_dump = tokens.model_dump()
        await asyncio.to_thread(self._merge, {"tokens": token_dump})
        logger.info("Saved tokens for %s", base_url)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = await asyncio.to_thread(self._fetch_session_data)
        base_url = self.get_base_url(self.server_url)
        if not data or "client_info" not in data:
            logger.debug("No client_info in DB for %s", base_url)
            return None
        try:
            client_info = OAuthClientInformationFull.model_validate(data["client_info"])
            if self.expected_redirect_uri:
                stored_uris = [
                    str(uri).rstrip("/") for uri in client_info.redirect_uris
                ]
                expected_uri = self.expected_redirect_uri.rstrip("/")
                if expected_uri not in stored_uris:
                    logger.warning(
                        "Redirect URI mismatch for %s: expected=%s stored=%s — clearing.",
                        base_url,
                        expected_uri,
                        stored_uris,
                    )
                    # Drop ``tokens`` and ``client_info`` from the JSONB
                    # blob via merge_session_data's ``None``-drops-key
                    # semantics — preserves the row + any other keys.
                    await asyncio.to_thread(
                        self._merge,
                        {"tokens": None, "client_info": None},
                    )
                    return None
            return client_info
        except ValidationError as e:
            logger.error("Could not load client info: %s", e)
            return None

    def _serialize_client_info(self, info: dict) -> dict:
        if "redirect_uris" in info and isinstance(info["redirect_uris"], list):
            info["redirect_uris"] = [str(u) for u in info["redirect_uris"]]
        return info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        serialized_info = self._serialize_client_info(client_info.model_dump())
        base_url = self.get_base_url(self.server_url)
        await asyncio.to_thread(
            self._merge, {"client_info": serialized_info},
        )
        logger.info("Saved client info for %s", base_url)

    async def clear(self) -> None:
        await asyncio.to_thread(self._delete)
        logger.info("Cleared OAuth cache for %s", self.get_base_url(self.server_url))

    @classmethod
    async def clear_all(cls, db_client=None) -> None:
        """Delete every MCP-tagged connector session row.

        ``db_client`` retained for call-site compatibility but unused —
        storage is Postgres-only now.
        """
        from sqlalchemy import text

        from application.storage.db.session import db_session

        def _delete_all() -> None:
            with db_session() as conn:
                conn.execute(
                    text(
                        "DELETE FROM connector_sessions "
                        "WHERE provider LIKE 'mcp:%'"
                    )
                )

        await asyncio.to_thread(_delete_all)
        logger.info("Cleared all OAuth client cache data.")


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
            logger.error("Error handling OAuth callback: %s", e)
            return False

    def get_oauth_status(self, task_id: str, user_id: str) -> Dict[str, Any]:
        """Return the latest OAuth status for ``task_id`` from the user's SSE journal.

        Mirrors the legacy polling contract: ``status`` derived from the
        ``mcp.oauth.*`` event-type suffix, with payload fields surfaced
        (e.g. ``tools``/``tools_count`` on ``completed``).
        """
        if not task_id:
            return {"status": "not_started", "message": "OAuth flow not started"}
        if not user_id:
            return {"status": "not_found", "message": "User not provided"}
        if self.redis_client is None:
            return {"status": "not_found", "message": "Redis unavailable"}

        try:
            # OAuth flows are short-lived but a concurrent source
            # ingest can flood the user channel between the OAuth
            # popup completing and the user clicking Save, pushing the
            # completion envelope outside the read window. Bound the
            # scan by the configured stream cap so we cover the full
            # journal — XADD MAXLEN keeps that bounded too.
            scan_count = max(settings.EVENTS_STREAM_MAXLEN, 200)
            entries = self.redis_client.xrevrange(
                stream_key(user_id), count=scan_count
            )
        except Exception:
            logger.exception(
                "xrevrange failed for oauth status: user_id=%s task_id=%s",
                user_id,
                task_id,
            )
            return {"status": "not_found", "message": "Status unavailable"}

        for _entry_id, fields in entries:
            if not isinstance(fields, dict):
                continue
            # decode_responses=False ⇒ bytes keys; the string-key fallback
            # covers a future flip of that default without a forced refactor.
            event_raw = fields.get(b"event")
            if event_raw is None:
                event_raw = fields.get("event")
            if event_raw is None:
                continue
            if isinstance(event_raw, bytes):
                try:
                    event_raw = event_raw.decode("utf-8")
                except Exception:
                    continue
            try:
                envelope = json.loads(event_raw)
            except Exception:
                continue
            if not isinstance(envelope, dict):
                continue
            event_type = envelope.get("type", "")
            if not isinstance(event_type, str) or not event_type.startswith(
                "mcp.oauth."
            ):
                continue
            scope = envelope.get("scope") or {}
            if scope.get("kind") != "mcp_oauth" or scope.get("id") != task_id:
                continue
            payload = envelope.get("payload") or {}
            return {
                "status": event_type[len("mcp.oauth."):],
                "task_id": task_id,
                **payload,
            }

        return {"status": "not_found", "message": "Status not found"}
