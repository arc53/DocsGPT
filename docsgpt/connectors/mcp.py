"""MCP helpers for connections: re-scanning a server's actions."""

from __future__ import annotations

from docsgpt.connectors import service
from docsgpt.connectors.permissions import apply_default_permissions
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.session import db_readonly, db_session


def _discover(user_id: str, connection: dict, tool: dict) -> list[dict]:
    from docsgpt.agents.tools.mcp_tool import MCPTool

    config = {k: v for k, v in (tool.get("config") or {}).items() if k != "encrypted_credentials"}
    if (connection.get("auth_kind") or "") in ("api_key", "none"):
        config["auth_credentials"] = service.get_credentials(connection)
    elif service.normalize_status(connection) != service.STATUS_CONNECTED:
        raise service.ConnectionUnavailable("Reconnect to continue", connection_id=str(connection["id"]))
    config["connection_id"] = str(connection["id"])
    config["query_mode"] = True
    mcp_tool = MCPTool(config, user_id)
    mcp_tool.discover_tools()
    return mcp_tool.get_actions_metadata()


def refresh_mcp_tools(user_id: str, connection: dict) -> dict:
    """Re-read the actions of every MCP tool on a connection.

    Actions that still exist keep the permissions the user chose; new ones
    get the defaults from their annotations (reads always allowed, writes
    need approval); removed ones disappear.

    Returns:
        ``{"added": [...], "removed": [...], "tools": [...]}``.
    """
    with db_readonly() as conn:
        tools = [t for t in ConnectorSessionsRepository(conn).list_tools(str(connection["id"]))
                 if t.get("name") == "mcp_tool"]
    added: set[str] = set()
    removed: set[str] = set()
    refreshed = []
    for tool in tools:
        fresh = apply_default_permissions("mcp_tool", service._transform_actions(_discover(user_id, connection, tool)))
        previous = {a.get("name"): a for a in (tool.get("actions") or []) if isinstance(a, dict)}
        merged = []
        for action in fresh:
            old = previous.get(action.get("name"))
            if old is not None:
                action = {
                    **action,
                    "active": old.get("active", True),
                    "require_approval": bool(old.get("require_approval")),
                }
            merged.append(action)
        names = {a.get("name") for a in merged}
        added |= names - set(previous)
        removed |= set(previous) - names
        with db_session() as conn:
            repo = UserToolsRepository(conn)
            repo.update(str(tool["id"]), user_id, {"actions": merged})
            refreshed.append(service.serialize_tool(repo.get_any(str(tool["id"]), user_id)))
    return {"added": sorted(added), "removed": sorted(removed), "tools": refreshed}
