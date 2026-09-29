"""MCP helpers for connections: re-scanning a server's actions, switching GitHub's writes."""

from __future__ import annotations

from typing import Optional

from docsgpt.agents.tool_pins import carry_pins
from docsgpt.connectors import catalog, service
from docsgpt.connectors.catalog import ConnectorDefinition
from docsgpt.connectors.permissions import ACCESS_READ, ACCESS_WRITE, apply_default_permissions
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.session import db_readonly, db_session


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


def discover_builtin_actions(user_id: str, connection: dict, writes: bool = False) -> list[dict]:
    """The actions of a built-in connector's MCP server (GitHub's), read with the connection.

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
    config = service.builtin_mcp_config(_builtin_definition(connection), writes=writes)
    if config is None:
        raise ValueError("This connector has no MCP server")
    return _classified(connection, config, _discover(user_id, connection, {"config": config}))


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
    fresh = apply_default_permissions("mcp_tool", service._transform_actions(discovered))
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
