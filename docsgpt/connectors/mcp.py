"""MCP helpers for connections: re-scanning a server's actions, switching GitHub's
writes, and calling a server's tools.

Agents call an MCP server's tools through ``MCPTool``. Server-side work that
reads a service through its MCP server (syncing Linear into Knowledge) opens
one session with :func:`run_connection_session` and makes all its calls in
it, signed in with the connection's own OAuth tokens.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any, Awaitable, Callable, Optional, TypeVar

from docsgpt.agents.tool_pins import carry_pins
from docsgpt.connectors import catalog, service
from docsgpt.connectors.catalog import ConnectorDefinition
from docsgpt.connectors.permissions import ACCESS_READ, ACCESS_WRITE, apply_default_permissions
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.session import db_readonly, db_session

T = TypeVar("T")


class NoMcpTool(LookupError):
    """The connection has no MCP tool yet (it was set up without tools)."""


def _builtin_definition(connection: dict) -> Optional[ConnectorDefinition]:
    """The connection's built-in connector when its tool is that service's MCP server."""
    definition = catalog.get_definition(catalog.connector_key_for_row(connection))
    return definition if service.builtin_mcp_config(definition) is not None else None


def _write_endpoint_access(action: dict) -> dict:
    """Stamp an action of a write endpoint: a read only when the server marks it read-only.

    GitHub marks its read tools, so a name is no evidence there: from the name
    alone ``mark_all_notifications_read`` would pass for a read.
    """
    annotations = action.get("annotations") if isinstance(action.get("annotations"), dict) else {}
    return {**action, "access": ACCESS_READ if annotations.get("readOnlyHint") is True else ACCESS_WRITE}


def _discover(user_id: str, connection: dict, tool: dict) -> list[dict]:
    from docsgpt.agents.tools.mcp_tool import MCPTool

    config = {k: v for k, v in (tool.get("config") or {}).items() if k != "encrypted_credentials"}
    if (connection.get("auth_kind") or "") in ("api_key", "none", "oauth"):
        # Pasted keys, or the access token of a built-in OAuth sign-in (GitHub's App).
        config["auth_credentials"] = service.access_credentials(connection)
    elif service.normalize_status(connection) != service.STATUS_CONNECTED:
        raise service.ConnectionUnavailable("Reconnect to continue", connection_id=str(connection["id"]))
    config["connection_id"] = str(connection["id"])
    config["query_mode"] = True
    mcp_tool = MCPTool(config, user_id)
    mcp_tool.discover_tools()
    return mcp_tool.get_actions_metadata()


def _classified(connection: dict, config: dict, actions: list[dict]) -> list[dict]:
    """``actions`` as read from ``config``'s server, stamped strictly when it is a write endpoint."""
    definition = _builtin_definition(connection)
    if definition is None or not definition.mcp_write_url or config.get("server_url") != definition.mcp_write_url:
        return actions
    return [_write_endpoint_access(action) for action in actions]


def discover_connection_actions(user_id: str, connection: dict, writes: bool = False) -> list[dict]:
    """The actions of the MCP server a connection's tool is: a built-in's (GitHub's) or a preset's.

    Read with the connection's own sign-in: its pasted key or token, or for
    an MCP preset (Notion, Linear…) its stored OAuth tokens, renewed when
    they expired. A sign-in the server rejects and that cannot be renewed
    flags the connection for reconnecting.

    Args:
        user_id: The connection's owner.
        connection: The connection row.
        writes: Read the endpoint that also offers write actions; the caller
            checked that an admin allows them.

    Raises:
        ValueError: The connector has no MCP server of its own.
        service.ConnectionUnavailable: The connection needs reconnecting.
        Exception: The server could not be reached or listed.
    """
    definition = catalog.get_definition(catalog.connector_key_for_row(connection))
    config = service.connection_mcp_config(definition, writes=writes)
    if config is None:
        raise ValueError("This connector has no MCP server")
    try:
        return _classified(connection, config, _discover(user_id, connection, {"config": config}))
    except service.ConnectionUnavailable:
        raise
    except Exception as exc:
        if _needs_sign_in(exc):
            service.mark_reconnect_needed(str(connection["id"]), SIGN_IN_EXPIRED)
            raise service.ConnectionUnavailable(SIGN_IN_EXPIRED, connection_id=str(connection["id"])) from exc
        raise


def _rediscover(user_id: str, connection: dict, tool: dict, config: dict) -> tuple[set, set, dict]:
    """Re-read one MCP tool's actions from ``config``'s server and store both.

    Actions that still exist keep the permissions the user chose and the
    fixed values of parameters they still have; new ones get the defaults
    from their annotations (reads always allowed, writes need approval);
    removed ones disappear.

    Returns:
        ``(added, removed, tool)``: action names, and the serialized tool.
    """
    discovered = _classified(connection, config, _discover(user_id, connection, {**tool, "config": config}))
    definition = catalog.get_definition(catalog.connector_key_for_row(connection))
    fresh = apply_default_permissions(
        "mcp_tool", service._transform_actions(discovered), definition.default_actions if definition else (),
    )
    previous = {a.get("name"): a for a in (tool.get("actions") or []) if isinstance(a, dict)}
    merged = []
    for action in fresh:
        old = previous.get(action.get("name"))
        if old is not None:
            action = {
                **carry_pins(old, action),
                "active": old.get("active", True),
                "require_approval": bool(old.get("require_approval")),
            }
        merged.append(action)
    names = {a.get("name") for a in merged}
    fields = {"actions": merged}
    if config != (tool.get("config") or {}):
        fields["config"] = config
    with db_session() as conn:
        repo = UserToolsRepository(conn)
        repo.update(str(tool["id"]), user_id, fields)
        serialized = service.serialize_tool(repo.get_any(str(tool["id"]), user_id))
    return names - set(previous), set(previous) - names, serialized


def refresh_mcp_tools(user_id: str, connection: dict) -> dict:
    """Re-read the actions of every MCP tool on a connection.

    A built-in connector's tool is re-read from its own endpoint: the write
    one while it is set up for writes and an admin allows them, the read-only
    one otherwise, which it then keeps.

    Returns:
        ``{"added": [...], "removed": [...], "tools": [...]}``.
    """
    with db_readonly() as conn:
        tools = [t for t in ConnectorSessionsRepository(conn).list_tools(str(connection["id"]))
                 if t.get("name") == "mcp_tool"]
        policies = service.load_policies(conn) if tools else {}
    definition = _builtin_definition(connection)
    added: set[str] = set()
    removed: set[str] = set()
    refreshed = []
    for tool in tools:
        config = dict(tool.get("config") or {})
        if definition is not None:
            config["server_url"] = service.builtin_mcp_url(
                definition, config.get("server_url"), service.writes_allowed(policies, definition.key),
            )
        tool_added, tool_removed, serialized = _rediscover(user_id, connection, tool, config)
        added |= tool_added
        removed |= tool_removed
        refreshed.append(serialized)
    return {"added": sorted(added), "removed": sorted(removed), "tools": refreshed}


def set_builtin_writes(user_id: str, connection: dict, allow: bool) -> dict:
    """Point a connection's built-in MCP tool (GitHub's) at its write or read-only endpoint.

    The tool's actions are re-read from the new endpoint, keeping the
    choices made for actions that exist on both.

    Args:
        user_id: The connection's owner.
        connection: The connection row.
        allow: Let agents make changes (the write endpoint) or only read.

    Returns:
        ``{"added", "removed", "tools", "writes"}``.

    Raises:
        ValueError: The connector offers no write access.
        NoMcpTool: The connection has no such tool yet.
        service.WritesForbidden: ``allow`` while an admin forbids writes.
        service.ConnectionUnavailable: The connection needs reconnecting.
    """
    definition = _builtin_definition(connection)
    if definition is None or not definition.mcp_write_url:
        raise ValueError("This connector has no write access to turn on")
    with db_readonly() as conn:
        tools = [t for t in ConnectorSessionsRepository(conn).list_tools(str(connection["id"]))
                 if t.get("name") == "mcp_tool"]
        allowed = service.writes_allowed(service.load_policies(conn), definition.key)
    if not tools:
        raise NoMcpTool("Add this connection's tools first")
    if allow and not allowed:
        raise service.WritesForbidden(f"An admin turned off changes through {definition.name}")
    added: set[str] = set()
    removed: set[str] = set()
    refreshed = []
    for tool in tools:
        config = {**(tool.get("config") or {}), **service.builtin_mcp_config(definition, writes=allow)}
        tool_added, tool_removed, serialized = _rediscover(user_id, connection, tool, config)
        added |= tool_added
        removed |= tool_removed
        refreshed.append(serialized)
    return {"added": sorted(added), "removed": sorted(removed), "tools": refreshed, "writes": allow}


# ---------------------------------------------------------------------------
# Calling a server's tools from the server side
# ---------------------------------------------------------------------------

SIGN_IN_EXPIRED = "The sign-in expired and could not be renewed. Reconnect to continue."
_TRANSIENT_WORDS = ("rate limit", "ratelimit", "too many requests", "temporarily", "timed out", "timeout")


class MCPToolError(Exception):
    """An MCP tool answered with an error (a missing issue, a refused argument)."""


class MCPSession:
    """One open MCP session: list the server's tools and call them.

    Made by :func:`run_connection_session`. Every call goes over the same
    session, so a sync of hundreds of items signs in once.
    """

    def __init__(self, client: Any):
        self._client = client
        self._schemas: Optional[dict[str, dict]] = None

    async def input_schema(self, name: str) -> Optional[dict]:
        """The input schema of tool ``name`` (``{}`` when it has none), or None when there is no such tool."""
        if self._schemas is None:
            tools = await self._client.list_tools()
            self._schemas = {tool.name: (getattr(tool, "inputSchema", None) or {}) for tool in tools}
        return self._schemas.get(name)

    async def call(self, name: str, arguments: dict) -> Any:
        """Call tool ``name`` and return what it answered.

        Returns:
            Its structured content when it sends some, else its text parsed
            as JSON, else the text itself.

        Raises:
            MCPToolError: The tool answered with an error.
            service.TransientConnectionError: The error says to try again later.
        """
        result = await self._client.call_tool(name, arguments, raise_on_error=False)
        if getattr(result, "is_error", False):
            message = _result_text(result) or "the tool failed"
            if any(word in message.lower() for word in _TRANSIENT_WORDS):
                raise service.TransientConnectionError(f"{name}: {message}")
            raise MCPToolError(f"{name}: {message}")
        return tool_result_data(result)


def _result_text(result: Any) -> str:
    blocks = getattr(result, "content", None) or []
    return "\n".join(str(block.text) for block in blocks if getattr(block, "text", None)).strip()


def tool_result_data(result: Any) -> Any:
    """What an MCP tool answered: its structured content, its text parsed as JSON, or the text."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and structured:
        # A tool without an output schema has other values wrapped as ``{"result": ...}``.
        return structured["result"] if set(structured) == {"result"} else structured
    text = _result_text(result)
    try:
        return json.loads(text)
    except ValueError:
        return text


def _client_for(connection: dict, server_url: str, timeout: float) -> Any:
    """An MCP client for ``server_url`` that signs in with ``connection``'s stored OAuth tokens.

    The tokens are renewed with their refresh token when they expire; when
    that fails the client raises ``MCPReauthorizationRequired`` instead of
    starting an interactive sign-in.
    """
    from fastmcp import Client

    from docsgpt.agents.tools.mcp_tool import MCPTool, NonInteractiveOAuth

    tool = MCPTool(
        {"server_url": server_url, "auth_type": "oauth", "transport_type": "http", "timeout": timeout},
        connection["user_id"],
    )
    auth = NonInteractiveOAuth(
        mcp_url=tool.server_url,
        redirect_uri=tool.redirect_uri,
        user_id=connection["user_id"],
        connection_id=str(connection["id"]),
    )
    return Client(tool._create_transport(), auth=auth, timeout=timeout)


def _errors(exc: BaseException):
    """``exc`` and every exception it wraps: causes, contexts and group members."""
    seen: set[int] = set()
    pending: list[Optional[BaseException]] = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend(getattr(current, "exceptions", None) or ())
        pending.extend((current.__cause__, current.__context__))


def _needs_sign_in(exc: BaseException) -> bool:
    from docsgpt.agents.tools.mcp_tool import MCPReauthorizationRequired

    return any(
        isinstance(error, MCPReauthorizationRequired) or "oauth session expired" in str(error).lower()
        for error in _errors(exc)
    )


def _is_transient(exc: BaseException) -> bool:
    import httpx

    return any(
        isinstance(error, (ConnectionError, TimeoutError, httpx.TransportError)) for error in _errors(exc)
    )


def _run_coroutine(coroutine: Awaitable[T]) -> T:
    """Run ``coroutine`` to the end, on a thread of its own when this one already runs an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def run_connection_session(
    connection: dict,
    server_url: str,
    work: Callable[[MCPSession], Awaitable[T]],
    *,
    timeout: float = 60.0,
) -> T:
    """Open one MCP session signed in with ``connection`` and run ``work`` in it.

    Args:
        connection: An MCP OAuth connection (a Linear sign-in).
        server_url: The MCP endpoint. It must be the server the connection
            signed in to, so its tokens never go anywhere else.
        work: Async function given the open :class:`MCPSession`.
        timeout: Seconds allowed for each request.

    Returns:
        What ``work`` returned.

    Raises:
        ValueError: ``server_url`` is not the connection's server.
        service.ConnectionUnavailable: The connection needs reconnecting,
            also when its sign-in expired and could not be renewed (it is
            then flagged, which pauses its sources).
        service.TransientConnectionError: The server could not be reached,
            or asked to slow down.
        MCPToolError: A tool answered with an error.
    """
    connection_id = str(connection["id"])
    if catalog.base_url(connection.get("server_url")) != catalog.base_url(server_url):
        raise ValueError("A connection's sign-in only goes to its own server")
    if service.normalize_status(connection) != service.STATUS_CONNECTED:
        raise service.ConnectionUnavailable("Reconnect to continue", connection_id=connection_id)

    async def session_work() -> T:
        async with _client_for(connection, server_url, timeout) as client:
            return await work(MCPSession(client))

    try:
        return _run_coroutine(session_work())
    except (MCPToolError, service.TransientConnectionError, service.ConnectionUnavailable):
        raise
    except Exception as exc:
        if _needs_sign_in(exc):
            service.mark_reconnect_needed(connection_id, SIGN_IN_EXPIRED)
            raise service.ConnectionUnavailable(SIGN_IN_EXPIRED, connection_id=connection_id) from exc
        if _is_transient(exc):
            raise service.TransientConnectionError(f"The MCP server did not answer: {type(exc).__name__}") from exc
        raise
