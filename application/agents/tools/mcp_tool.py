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
        """
        self.config = config
        self.user_id = user_id
        self.server_url = config.get("server_url", "")
        self.transport_type = config.get("transport_type", "auto")
        self.auth_type = config.get("auth_type", "none")
        self.timeout = config.get("timeout", 30)
        self.headers = config.get("headers", {})
        self.command = config.get("command", "")
        self.args = config.get("args", [])
        self.oauth_task_id = config.get("oauth_task_id", None)
        self.available_tools = []
        self.actions_metadata = []

    def _get_auth(self):
        """Get authentication handler based on auth_type."""
        auth_credentials = self.config.get("auth_credentials", {})

        if self.auth_type == "bearer":
            token = auth_credentials.get("bearer_token", "")
            if token:
                return BearerAuth(token)
        elif self.auth_type == "api_key":
            api_key = auth_credentials.get("api_key", "")
            header_name = auth_credentials.get("api_key_header", "X-API-Key")
            if api_key:
                return BearerAuth(api_key)
        elif self.auth_type == "basic":
            username = auth_credentials.get("username", "")
            password = auth_credentials.get("password", "")
            if username and password:
                import base64 as b64
                credentials = b64.b64encode(f"{username}:{password}".encode()).decode()
                return BearerAuth(credentials)

        return None

    def _get_transport(self, auth=None):
        """Get the appropriate transport based on transport_type."""
        if self.transport_type == "stdio":
            if not self.command:
                raise ValueError("Command is required for STDIO transport")
            return StdioTransport(
                command=self.command,
                args=self.args if self.args else [],
            )

        headers = dict(self.headers) if self.headers else {}

        if auth and hasattr(auth, 'token'):
            headers["Authorization"] = f"Bearer {auth.token}"

        transport_class = StreamableHttpTransport
        if self.transport_type == "sse":
            transport_class = SSETransport

        try:
            validate_url(self.server_url)
        except SSRFError as e:
            raise ValueError(f"Invalid server URL: {e}") from e

        return transport_class(
            url=self.server_url,
            headers=headers if headers else None,
        )

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result(timeout=self.timeout + 5)
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    async def _connect_and_list_tools(self):
        """Connect to MCP server and list available tools."""
        auth = self._get_auth()
        transport = self._get_transport(auth)

        async with Client(transport) as client:
            tools = await client.list_tools()
            return tools

    def discover_tools(self):
        """Discover tools from the MCP server."""
        try:
            tools = self._run_async(self._connect_and_list_tools())
            self.available_tools = tools if tools else []
            return True
        except Exception as e:
            logger.error(f"Failed to discover MCP tools: {e}")
            self.available_tools = []
            return False

    def get_actions_metadata(self):
        """Convert MCP tools to DocsGPT action metadata format."""
        actions = []
        for tool in self.available_tools:
            if isinstance(tool, dict):
                tool_name = tool.get("name", "")
                tool_description = tool.get("description", "")
                input_schema = (
                    tool.get("inputSchema")
                    or tool.get("input_schema")
                )
            else:
                tool_name = getattr(tool, "name", "")
                tool_description = getattr(tool, "description", "")
                input_schema = (
                    getattr(tool, "inputSchema", None)
                    or getattr(tool, "input_schema", None)
                )
                if input_schema and hasattr(input_schema, "model_dump"):
                    input_schema = input_schema.model_dump()

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
                    elif input_schema.get("type") == "object":
                        # Schema declares no properties — tool takes no arguments.
                        pass
                    else:
                        for key in ("type", "required"):
                            if key in input_schema:
                                parameters_schema[key] = input_schema[key]
                        parameters_schema["properties"] = input_schema.get("properties") or {}

            action = {
                "name": tool_name,
                "description": tool_description,
                "parameters": parameters_schema,
            }
            actions.append(action)

        return actions

    def _start_oauth_task(self, user_id: str):
        """Start an OAuth task for authentication."""
        try:
            redis_client = get_redis_instance()
            if not redis_client:
                return {
                    "success": False,
                    "requires_oauth": False,
                    "message": "Redis not available for OAuth",
                }

            task = mcp_oauth_task.delay(
                mcp_url=self.server_url,
                user_id=user_id,
            )

            return {
                "success": False,
                "requires_oauth": True,
                "task_id": task.id,
                "message": "OAuth authorization required",
            }
        except Exception as e:
            logger.error(f"Failed to start OAuth task: {e}")
            return {
                "success": False,
                "requires_oauth": False,
                "message": f"Failed to initiate OAuth: {str(e)}",
            }

    def _test_oauth_connection(self, user_id: str):
        """Test OAuth connection by checking existing tokens."""
        from application.security.encryption import decrypt_credentials

        encrypted_credentials = self.config.get("encrypted_credentials")
        if encrypted_credentials and user_id:
            credentials = decrypt_credentials(encrypted_credentials, user_id)
            if credentials.get("access_token"):
                try:
                    test_config = dict(self.config)
                    test_config["auth_type"] = "bearer"
                    test_config["auth_credentials"] = {
                        "bearer_token": credentials["access_token"]
                    }
                    test_tool = MCPTool(config=test_config, user_id=user_id)
                    if test_tool.discover_tools():
                        tools = test_tool.get_actions_metadata()
                        return {
                            "success": True,
                            "requires_oauth": False,
                            "message": f"Connected — found {len(tools)} tools.",
                            "tools": tools,
                            "tools_count": len(tools),
                        }
                except Exception as e:
                    logger.debug(f"Stored token test failed: {e}")

        return self._start_oauth_task(user_id)

    def test_connection(self):
        """Test the MCP server connection."""
        if self.auth_type == "oauth":
            user_id = self.user_id or ""
            return self._test_oauth_connection(user_id)

        try:
            if self.discover_tools():
                tools = self.get_actions_metadata()
                return {
                    "success": True,
                    "message": f"Connected — found {len(tools)} tools.",
                    "tools": tools,
                    "tools_count": len(tools),
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to connect to MCP server",
                    "tools_count": 0,
                }
        except Exception as e:
            logger.error(f"MCP connection test failed: {e}")
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "tools_count": 0,
            }

    def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        """Execute an MCP tool action."""
        try:
            result = self._run_async(
                self._execute_tool(action, kwargs)
            )
            return {"result": result, "success": True}
        except Exception as e:
            logger.error(f"MCP tool execution failed: {e}")
            return {"result": str(e), "success": False}

    async def _execute_tool(self, tool_name: str, arguments: dict):
        """Execute a specific MCP tool."""
        auth = self._get_auth()
        transport = self._get_transport(auth)

        async with Client(transport) as client:
            result = await client.call_tool(tool_name, arguments)
            if result and hasattr(result, '__iter__'):
                parts = []
                for item in result:
                    if hasattr(item, 'text'):
                        parts.append(item.text)
                    elif isinstance(item, dict) and 'text' in item:
                        parts.append(item['text'])
                    else:
                        parts.append(str(item))
                return "\n".join(parts) if parts else str(result)
            return str(result) if result is not None else ""


class DocsGPTOAuth(OAuthClientProvider):
    """OAuth provider for DocsGPT MCP connections."""

    def __init__(
        self,
        mcp_url: str,
        redirect_uri: str,
        client_name: str = "DocsGPT",
        scopes: Optional[list] = None,
        additional_client_metadata: Optional[dict] = None,
        skip_redirect_validation: bool = False,
        task_id: str = None,
        user_id: str = None,
        redirect_publish=None,
    ):
        self.task_id = task_id
        self.user_id = user_id
        # Worker-supplied callback. Invoked from ``redirect_handler``
        # once the authorization URL is known so the SSE envelope can
        # carry it. ``None`` for any non-worker entrypoint.
        self.redirect_publish = redirect_publish

        parsed_url = urlparse(mcp_url)
        self.server_base_url = mcp_url  # preserve path for path-scoped PRM resources

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

    def _get_redirect_uri(self, request_url: str) -> str:
        """Build the callback redirect URI from the incoming request URL."""
        parsed = urlparse(request_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/api/mcp_server/callback"
        return f"{settings.SERVER_URL}/api/mcp_server/callback"

    async def redirect_handler(self, url: str) -> None:
        """Handle redirect to OAuth authorization URL."""
        self.auth_url = url
        logger.info("MCP OAuth redirect URL: %s", url)
        if self.redirect_publish:
            try:
                await self.redirect_publish(
                    auth_url=url,
                    task_id=self.task_id,
                )
            except Exception as exc:
                logger.warning(
                    "redirect_publish callback raised for task_id=%s: %s",
                    self.task_id,
                    exc,
                )

    async def callback_handler(self, authorization_url: str) -> tuple:
        """Handle OAuth callback."""
        parsed_url = urlparse(authorization_url)
        query_params = parse_qs(parsed_url.query)
        code = query_params.get("code", [None])[0]
        state = query_params.get("state", [None])[0]
        return code, state


class DBTokenStorage(TokenStorage):
    """Token storage using database."""

    def __init__(self, server_url: str, user_id: str, expected_redirect_uri: str = None):
        self.server_url = server_url
        self.user_id = user_id
        self.expected_redirect_uri = expected_redirect_uri

    async def get_tokens(self) -> Optional[OAuthToken]:
        """Retrieve stored OAuth tokens."""
        try:
            from application.storage.db.repositories.connector_sessions import (
                ConnectorSessionsRepository,
            )
            from application.storage.db.session import db_readonly

            with db_readonly() as conn:
                repo = ConnectorSessionsRepository(conn)
                session = repo.get_by_user_and_server_url(self.user_id, self.server_url)
                if session:
                    token_data = session.get("token_info") or {}
                    if token_data.get("access_token"):
                        return OAuthToken(
                            access_token=token_data["access_token"],
                            token_type=token_data.get("token_type", "Bearer"),
                            refresh_token=token_data.get("refresh_token"),
                            expires_in=token_data.get("expires_in"),
                            scope=token_data.get("scope"),
                        )
        except Exception as e:
            logger.debug(f"Failed to retrieve stored tokens: {e}")
        return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store OAuth tokens."""
        try:
            from application.storage.db.repositories.connector_sessions import (
                ConnectorSessionsRepository,
            )
            from application.storage.db.session import db_session

            token_data = {
                "access_token": tokens.access_token,
                "token_type": tokens.token_type or "Bearer",
                "refresh_token": tokens.refresh_token,
                "expires_in": tokens.expires_in,
                "scope": tokens.scope,
            }

            with db_session() as conn:
                repo = ConnectorSessionsRepository(conn)
                existing = repo.get_by_user_and_server_url(self.user_id, self.server_url)
                if existing:
                    repo.update_token_info(str(existing["id"]), token_data)
                else:
                    repo.create(
                        user_id=self.user_id,
                        provider=f"mcp:{self.server_url}",
                        server_url=self.server_url,
                        token_info=token_data,
                    )
        except Exception as e:
            logger.error(f"Failed to store OAuth tokens: {e}")

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        """Retrieve stored client registration info."""
        try:
            from application.storage.db.repositories.connector_sessions import (
                ConnectorSessionsRepository,
            )
            from application.storage.db.session import db_readonly

            with db_readonly() as conn:
                repo = ConnectorSessionsRepository(conn)
                session = repo.get_by_user_and_server_url(self.user_id, self.server_url)
                if session:
                    client_data = session.get("session_data", {}) or {}
                    client_info = client_data.get("client_info")
                    if client_info:
                        return OAuthClientInformationFull(**client_info)
        except Exception as e:
            logger.debug(f"Failed to retrieve client info: {e}")
        return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store client registration info."""
        try:
            from application.storage.db.repositories.connector_sessions import (
                ConnectorSessionsRepository,
            )
            from application.storage.db.session import db_session

            client_data = client_info.model_dump() if hasattr(client_info, 'model_dump') else {}

            with db_session() as conn:
                repo = ConnectorSessionsRepository(conn)
                existing = repo.get_by_user_and_server_url(self.user_id, self.server_url)
                if existing:
                    current_data = existing.get("session_data", {}) or {}
                    current_data["client_info"] = client_data
                    repo.update_session_data(str(existing["id"]), current_data)
                else:
                    repo.create(
                        user_id=self.user_id,
                        provider=f"mcp:{self.server_url}",
                        server_url=self.server_url,
                        session_data={"client_info": client_data},
                    )
        except Exception as e:
            logger.error(f"Failed to store client info: {e}")


class MCPOAuthManager:
    """Manages OAuth flows for MCP servers via Redis-backed SSE."""

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    def get_oauth_status(self, task_id: str, user_id: str) -> Dict[str, Any]:
        """Return the latest OAuth status for ``task_id`` from the user's SSE journal.

        The SSE journal is written by ``mcp_oauth_task`` via
        ``application.events.keys.stream_key``.  Each entry is a dict
        with at minimum ``kind``, ``id`` and a ``status`` or ``auth_url``
        key.
        """
        if not task_id:
            return {"status": "error", "message": "task_id is required"}

        try:
            key = stream_key(user_id)
            # Read up to 100 recent events from the stream.
            entries = self.redis.xrevrange(key, count=100)
        except Exception as e:
            logger.warning(
                "xrevrange failed for oauth status: user_id=%s task_id=%s: %s",
                user_id,
                task_id,
                e,
            )
            return {"status": "error", "message": "Failed to read event stream"}

        for _stream_id, fields in entries:
            raw = fields.get(b"data") or fields.get("data")
            if not raw:
                continue
            try:
                scope = json.loads(raw if isinstance(raw, str) else raw.decode())
            except (json.JSONDecodeError, AttributeError):
                continue

            if scope.get("kind") != "mcp_oauth" or scope.get("id") != task_id:
                continue

            return {
                "task_id": task_id,
                "status": scope.get("status", "pending"),
                "auth_url": scope.get("auth_url"),
                "message": scope.get("message"),
                "tools": scope.get("tools", []),
            }

        return {"task_id": task_id, "status": "pending"}

    def handle_oauth_callback(self, state: str, code: str, error: Optional[str] = None) -> bool:
        """Route an OAuth callback to the waiting task via Redis pub/sub."""
        try:
            callback_data = json.dumps({
                "state": state,
                "code": code,
                "error": error,
            })
            channel = f"mcp_oauth_callback:{state}"
            self.redis.publish(channel, callback_data)
            return True
        except Exception as e:
            logger.error(f"Failed to handle OAuth callback: {e}")
            return False


def _get_or_create_mcp_client(
    server_url: str,
    transport_type: str = "auto",
    auth=None,
    headers: Optional[Dict] = None,
    timeout: int = 30,
    kwargs: Optional[Dict] = None,
):
    """Get or create a cached MCP client."""
    kwargs = kwargs or {}
    kwargs.setdefault("task_id", None)

    cache_key = f"{server_url}:{transport_type}"
    if cache_key in _mcp_clients_cache:
        return _mcp_clients_cache[cache_key]

    tool_config = {
        "server_url": server_url,
        "transport_type": transport_type,
        "headers": headers or {},
        "timeout": timeout,
        "auth_type": "bearer" if auth else "none",
        "auth_credentials": {"bearer_token": getattr(auth, "token", "")} if auth else {},
    }

    tool = MCPTool(config=tool_config)
    _mcp_clients_cache[cache_key] = tool
    return tool


def _get_server_base_url(server_url: str) -> str:
    """Extract base URL (scheme + netloc) from a server URL."""
    parsed = urlparse(server_url)
    return f"{parsed.scheme}://{parsed.netloc}"
