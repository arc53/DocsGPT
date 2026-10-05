"""Which connection a shared tool or source uses at runtime.

A resource that points at a connection runs either with its owner's account
(``owner`` mode, the default for new shares) or with the invoking member's
own account for the same service (``member`` mode). Resolution never returns
credentials; callers read them from the resolved row through
``docsgpt.connectors.service``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from dataclasses import dataclass
from typing import Optional

from docsgpt.connectors import catalog, service
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

MODE_OWNER = "owner"
MODE_MEMBER = "member"

# Why a connection-backed tool can't run (``connection_stop_reason``).
CONNECTION_NEEDS_RECONNECT = "connection_needs_reconnect"
CONNECTION_REMOVED = "connection_removed"
CONNECTOR_DISABLED = "connector_disabled"

# Tool config key ``remove_connection`` sets when it keeps a connection's
# tools: the connector key, or True when the connection had none, so they can
# say what they lost. Only the server writes it (see
# :func:`carry_removed_connection`).
REMOVED_CONNECTION_KEY = "removed_connection"


def carry_removed_connection(new_config: dict, stored_config: Optional[dict]) -> dict:
    """``new_config`` with the stored removed-connection note, never a client's.

    A config save must neither fake the note nor clear it; every path that
    writes a tool config from a request passes it through here.

    Args:
        new_config: The config about to be stored.
        stored_config: The tool's stored config (None or ``{}`` when creating it).

    Returns:
        dict: A copy of ``new_config`` carrying the stored note, if any.
    """
    out = {k: v for k, v in (new_config or {}).items() if k != REMOVED_CONNECTION_KEY}
    marker = (stored_config or {}).get(REMOVED_CONNECTION_KEY)
    if marker:
        out[REMOVED_CONNECTION_KEY] = marker
    return out


@dataclass(frozen=True)
class ResolvedConnection:
    """The connection a call runs with, or why there is none.

    Attributes:
        row: The ``connector_sessions`` row, None when missing.
        available: Whether it can be used right now.
        connector_key: Catalog key of the service.
        connector_name: Name shown to the user ("Notion", or a custom label).
        delegated: The row belongs to someone other than the invoker.
        writes_allowed: Whether an admin lets agents make changes through a
            connector that offers them as an opt-in (GitHub); True elsewhere.
        enabled: Whether the connector is switched on (an admin can turn it off).
        mode: Whose account the resource runs with, after any mode an admin
            forces: :data:`MODE_OWNER` or :data:`MODE_MEMBER`.
    """

    row: Optional[dict]
    available: bool
    connector_key: Optional[str]
    connector_name: Optional[str]
    delegated: bool = False
    writes_allowed: bool = True
    enabled: bool = True
    mode: str = MODE_OWNER

    @property
    def connection_id(self) -> Optional[str]:
        return str(self.row["id"]) if self.row else None


def _name_for(row: Optional[dict], fallback_key: Optional[str]) -> Optional[str]:
    if row is not None:
        return service.serialize_connection(row)["name"]
    definition = catalog.get_definition(fallback_key)
    return definition.name if definition else None


def resolve_connection(
    resource: dict,
    invoker_user_id: Optional[str],
    *,
    conn=None,
    policies: Optional[dict] = None,
) -> Optional[ResolvedConnection]:
    """Pick the connection a tool or source uses for ``invoker_user_id``.

    ``owner`` mode uses ``resource.connection_id``. ``member`` mode uses the
    invoker's own connection to the same service (and, for MCP, the same
    server), falling back to the owner's when the invoker is the owner.

    Args:
        resource: A ``user_tools`` or ``sources`` row.
        invoker_user_id: Who is running it.
        conn: An open connection to reuse; a read-only one is opened when None.
        policies: Connector policies already loaded with ``service.load_policies``,
            so a caller resolving many resources loads them once.

    Returns:
        None when the resource has no connection at all; otherwise the
        resolution, possibly with ``available=False``.
    """
    if not resource.get("connection_id"):
        return None
    if conn is None:
        with db_readonly() as own_conn:
            return _resolve(own_conn, resource, invoker_user_id, policies)
    return _resolve(conn, resource, invoker_user_id, policies)


def effective_credential_mode(resource: dict, policies: dict, connector_key: Optional[str]) -> str:
    """Whose account a connection-backed resource runs with: ``owner`` or ``member``.

    The resource's own ``credential_mode``, unless an admin forces one mode
    for every share of its connector.

    Args:
        resource: A ``user_tools`` or ``sources`` row.
        policies: Connector policies from ``service.load_policies``.
        connector_key: Catalog key of the resource's connection.

    Returns:
        :data:`MODE_OWNER` or :data:`MODE_MEMBER`.
    """
    policy = (policies.get(connector_key) or {}) if connector_key else {}
    if policy.get("credential_mode") in (MODE_OWNER, MODE_MEMBER):
        return policy["credential_mode"]
    return MODE_MEMBER if resource.get("credential_mode") == MODE_MEMBER else MODE_OWNER


def _resolve(conn, resource: dict, invoker_user_id: Optional[str], policies: Optional[dict]) -> ResolvedConnection:
    connection_id = resource.get("connection_id")
    owner = resource.get("user_id")
    repo = ConnectorSessionsRepository(conn)
    owned = repo.get(str(connection_id))
    owned_key = catalog.connector_key_for_row(owned) if owned else None
    if policies is None:
        policies = service.load_policies(conn)
    mode = effective_credential_mode(resource, policies, owned_key)
    if owned is not None and owner and owned.get("user_id") != owner:
        # A resource may only point at its own owner's connection.
        logger.warning(
            "resource %s points at a connection it does not own", resource.get("id"),
        )
        owned = None
    row = owned
    if mode == MODE_MEMBER and invoker_user_id and invoker_user_id != owner:
        row = _member_connection(repo, owned, invoker_user_id)
    key = catalog.connector_key_for_row(row or owned or {})
    enabled = service.connector_is_enabled(policies, key)
    available = (
        row is not None
        and service.normalize_status(row) == service.STATUS_CONNECTED
        and enabled
    )
    return ResolvedConnection(
        row=row,
        available=available,
        connector_key=key,
        connector_name=_name_for(row or owned, key),
        delegated=bool(row and invoker_user_id and row.get("user_id") != invoker_user_id),
        writes_allowed=_writes_allowed(policies, key),
        enabled=enabled,
        mode=mode,
    )


def connection_stop_reason(tool: dict, resolved: Optional[ResolvedConnection]) -> Optional[str]:
    """Why an owner-mode tool's connection keeps it from running, or None.

    Only the connection the owner's account runs on is judged. A member-mode
    tool runs on each caller's own account, so the owner's account says
    nothing about whether it runs; only an admin turning the service off
    stops it for everyone.

    Args:
        tool: The ``user_tools`` row.
        resolved: What :func:`resolve_connection` returned for it, resolved
            for the tool's holder's owner.

    Returns:
        :data:`CONNECTION_REMOVED` when its connection was removed and the
        tool kept (``remove_connection`` notes it on the tool) with no
        credentials of its own, or points at
        one it may not use; :data:`CONNECTOR_DISABLED` when an admin turned
        the service off; :data:`CONNECTION_NEEDS_RECONNECT` when the account
        must sign in again; else None.
    """
    if resolved is None:
        # Only a tool that had a connection lost it: a tool that never had
        # one (a tokenless ntfy, a legacy tool) runs on its own config, and
        # so does a kept one its owner gave credentials of its own since.
        config = tool.get("config") or {}
        removed = config.get(REMOVED_CONNECTION_KEY) and not config.get("encrypted_credentials")
        return CONNECTION_REMOVED if removed and not tool.get("connection_id") else None
    if not resolved.enabled:
        return CONNECTOR_DISABLED
    if resolved.mode == MODE_MEMBER:
        return None
    if resolved.row is None:
        return CONNECTION_REMOVED
    if not resolved.available:
        return CONNECTION_NEEDS_RECONNECT
    return None


def _writes_allowed(policies: dict, key: Optional[str]) -> bool:
    definition = catalog.get_definition(key) if key else None
    if definition is None or not definition.mcp_write_url:
        return True
    return service.writes_allowed(policies, key)


def _member_connection(repo: ConnectorSessionsRepository, owned: Optional[dict], invoker: str) -> Optional[dict]:
    """The invoker's own connection to the service the owner's connection is for.

    A member with several connected accounts of that service gets the one
    most recently used or connected, whichever is later: the account they
    are working in, or the one a "Connect to continue" just added (never
    used yet). Ties go to the last used, then the last updated.
    """
    if owned is None:
        return None
    candidates = [
        row for row in repo.list_for_user(invoker)
        if row.get("provider") == owned.get("provider")
        and (row.get("server_url") or "") == (owned.get("server_url") or "")
        and service.normalize_status(row) == service.STATUS_CONNECTED
    ]
    if not candidates:
        return None

    def when(value) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            return datetime.min.replace(tzinfo=timezone.utc)
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def recency(row: dict) -> tuple:
        used, updated, created = (when(row.get(field)) for field in ("last_used_at", "updated_at", "created_at"))
        return max(used, created), used, updated, created

    return max(candidates, key=recency)


def audit_delegation(resolved: ResolvedConnection, *, invoker: Optional[str], resource_type: str,
                     resource_id: Optional[str], agent_id: Optional[str] = None) -> None:
    """Log a call that runs with someone else's account (``owner`` mode)."""
    if not resolved.delegated or resolved.row is None:
        return
    logger.info(
        "tool_credential_delegation",
        extra={
            "invoker": invoker,
            "tool_owner": resolved.row.get("user_id"),
            "connection_id": resolved.connection_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "agent_id": agent_id,
        },
    )
