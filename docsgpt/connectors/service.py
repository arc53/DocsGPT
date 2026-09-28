"""Connection lifecycle: listing, status, and what each connection provides.

A connection is one ``connector_sessions`` row: a signed-in OAuth account, an
MCP server or a set of API credentials. Sources and tools point at it through
``connection_id``. Everything the API returns about a connection goes through
:func:`serialize_connection`, which never includes credentials.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from docsgpt.connectors import catalog
from docsgpt.connectors.catalog import ConnectorDefinition
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

STATUS_CONNECTED = "connected"
STATUS_RECONNECT = "reconnect_needed"
STATUS_DISCONNECTED = "disconnected"
STATUS_ERROR = "error"
STATUS_PENDING = "pending"

# Worst first: a card shows the worst status among the user's accounts.
_STATUS_SEVERITY = {
    STATUS_RECONNECT: 4,
    STATUS_ERROR: 3,
    STATUS_DISCONNECTED: 2,
    STATUS_CONNECTED: 1,
    STATUS_PENDING: 0,
}


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def has_credentials(row: dict) -> bool:
    """Whether a connection holds usable credentials (without decrypting them)."""
    if row.get("encrypted_credentials"):
        return True
    token_info = _json(row.get("token_info")) or {}
    if isinstance(token_info, dict) and token_info.get("access_token"):
        return True
    session_data = _json(row.get("session_data")) or {}
    tokens = session_data.get("tokens") if isinstance(session_data, dict) else None
    return bool(isinstance(tokens, dict) and tokens.get("access_token"))


def normalize_status(row: dict) -> str:
    """Map a row's stored status onto the connection status set.

    Rows written before ``0038_connections`` use ``authorized`` for a
    finished OAuth sign-in, and MCP rows carry no status at all; both are
    read from whether the row holds credentials.
    """
    raw = (row.get("status") or "").lower()
    if raw in (STATUS_RECONNECT, STATUS_DISCONNECTED, STATUS_ERROR):
        return raw
    if raw == STATUS_PENDING and not has_credentials(row):
        return STATUS_PENDING
    if raw in ("authorized", STATUS_CONNECTED, "active") or has_credentials(row):
        return STATUS_CONNECTED
    return STATUS_PENDING


def worst_status(statuses: Iterable[str]) -> Optional[str]:
    """The status that needs the most attention, or None for an empty list."""
    ranked = sorted(statuses, key=lambda s: _STATUS_SEVERITY.get(s, 0), reverse=True)
    return ranked[0] if ranked else None


def account_label(row: dict) -> str:
    """What identifies the account to its owner: an email, a workspace or a host."""
    return (
        row.get("account_label")
        or row.get("user_email")
        or row.get("display_name")
        or catalog.base_url(row.get("server_url")).split("://")[-1]
        or ""
    )


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_connection(row: dict, counts: Optional[dict] = None) -> dict:
    """Public shape of a connection. Never includes tokens or secrets."""
    key = catalog.connector_key_for_row(row)
    definition = catalog.get_definition(key)
    counts = counts or {}
    return {
        "id": str(row["id"]),
        "connector_key": key,
        "name": (definition.name if definition and definition.publisher != "custom" else None)
        or row.get("display_name")
        or (definition.name if definition else key),
        "display_name": row.get("display_name"),
        "icon": definition.icon if definition else "tool_mcp_tool",
        "account_label": account_label(row),
        "auth_kind": row.get("auth_kind") or (definition.auth_kind if definition else None),
        "status": normalize_status(row),
        "server_url": row.get("server_url"),
        "last_error": row.get("last_error"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "last_used_at": _iso(row.get("last_used_at")),
        "source_count": counts.get("sources", 0),
        "tool_count": counts.get("tools", 0),
        "credential_mode": row.get("credential_mode"),
    }


def list_connections(conn, user_id: str) -> list[dict]:
    """The user's connections, finished sign-ins only, with resource counts."""
    repo = ConnectorSessionsRepository(conn)
    rows = [r for r in repo.list_for_user(user_id) if normalize_status(r) != STATUS_PENDING]
    counts = repo.resource_counts([str(r["id"]) for r in rows])
    return [serialize_connection(r, counts.get(str(r["id"]))) for r in rows]


def serialize_source(row: dict, connection_status: Optional[str] = None) -> dict:
    """A source linked to a connection, as the connection drawer lists it."""
    metadata = _json(row.get("metadata")) or {}
    sync_state = metadata.get("sync_state") if isinstance(metadata, dict) else None
    if connection_status in (STATUS_RECONNECT, STATUS_DISCONNECTED) and not sync_state:
        sync_state = "paused_reconnect"
    return {
        "id": str(row["id"]),
        "name": row.get("name"),
        "type": row.get("type"),
        "last_sync": _iso(row.get("date")),
        "sync_frequency": row.get("sync_frequency") or "never",
        "sync_state": sync_state or "active",
    }


def serialize_tool(row: dict) -> dict:
    """A tool linked to a connection, with its actions and their permissions."""
    from docsgpt.connectors.permissions import action_access, action_permission

    actions = []
    for action in _json(row.get("actions")) or []:
        if not isinstance(action, dict):
            continue
        access = action_access(row.get("name"), action)
        actions.append(
            {
                "name": action.get("name"),
                "description": action.get("description", ""),
                "access": access,
                "permission": action_permission(action),
            }
        )
    return {
        "id": str(row["id"]),
        "name": row.get("name"),
        "display_name": row.get("custom_name") or row.get("display_name") or row.get("name"),
        "status": bool(row.get("status")),
        "credential_mode": row.get("credential_mode") or "owner",
        "actions": actions,
    }


def connection_detail(conn, row: dict) -> dict:
    """A connection with the sources and tools it feeds."""
    repo = ConnectorSessionsRepository(conn)
    status = normalize_status(row)
    sources = [serialize_source(s, status) for s in repo.list_sources(str(row["id"]))]
    tools = [serialize_tool(t) for t in repo.list_tools(str(row["id"]))]
    detail = serialize_connection(row, {"sources": len(sources), "tools": len(tools)})
    detail["sources"] = sources
    detail["tools"] = tools
    return detail


def _card_state(definition: ConnectorDefinition, available: bool, disabled: bool, status: Optional[str]) -> str:
    if disabled:
        return "disabled"
    if status in (STATUS_RECONNECT, STATUS_ERROR):
        return "reconnect"
    if status == STATUS_CONNECTED:
        return "connected"
    if not available:
        return "needs_setup"
    if definition.publisher == "custom":
        return "custom"
    return "available"


def catalog_for_user(conn, user_id: str, *, is_admin: bool, policies: Optional[dict] = None) -> list[dict]:
    """Catalog entries with availability and the caller's connection summary.

    Args:
        conn: Open database connection.
        user_id: The caller.
        is_admin: Admins see the names of missing server settings; everyone
            else only learns that setup is needed.
        policies: ``connector_key`` to policy row, when admin policies exist.
    """
    policies = policies or {}
    by_key: dict[str, list[str]] = {}
    for connection in list_connections(conn, user_id):
        by_key.setdefault(connection["connector_key"], []).append(connection["status"])

    entries = []
    for definition in catalog.all_definitions():
        policy = policies.get(definition.key) or {}
        disabled = policy.get("enabled") is False
        missing = definition.missing_settings
        available = not missing and not disabled
        statuses = by_key.get(definition.key, [])
        status = worst_status(statuses)
        entries.append(
            {
                **definition.to_dict(),
                "available": available,
                "disabled": disabled,
                "needs_setup": bool(missing),
                "missing_settings": missing if is_admin else [],
                "connected_count": sum(1 for s in statuses if s == STATUS_CONNECTED),
                "connection_count": len(statuses),
                "status": status,
                "state": _card_state(definition, available, disabled, status),
                "credential_policy": policy.get("credential_mode") or "choose",
            }
        )
    return entries


def disconnect(conn, row: dict) -> dict:
    """Forget a connection's credentials but keep the row and what it feeds.

    Sources keep their indexed content and stop syncing; tools stop working
    until the account is reconnected. An MCP server's client registration is
    kept so reconnecting skips dynamic client registration.

    Args:
        conn: Open database connection inside a transaction.
        row: The connection row, already authorised for the caller.

    Returns:
        The connection's public shape after the change.
    """
    repo = ConnectorSessionsRepository(conn)
    session_data = _json(row.get("session_data")) or {}
    if isinstance(session_data, dict):
        session_data = {k: v for k, v in session_data.items() if k != "tokens"}
    repo.update(
        str(row["id"]),
        {
            "status": STATUS_DISCONNECTED,
            "token_info": None,
            "session_token": None,
            "session_data": session_data or {},
        },
    )
    return serialize_connection(repo.get(str(row["id"])))
