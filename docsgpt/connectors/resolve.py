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
    """

    row: Optional[dict]
    available: bool
    connector_key: Optional[str]
    connector_name: Optional[str]
    delegated: bool = False
    writes_allowed: bool = True

    @property
    def connection_id(self) -> Optional[str]:
        return str(self.row["id"]) if self.row else None


def _name_for(row: Optional[dict], fallback_key: Optional[str]) -> Optional[str]:
    if row is not None:
        return service.serialize_connection(row)["name"]
    definition = catalog.get_definition(fallback_key)
    return definition.name if definition else None


def resolve_connection(resource: dict, invoker_user_id: Optional[str]) -> Optional[ResolvedConnection]:
    """Pick the connection a tool or source uses for ``invoker_user_id``.

    ``owner`` mode uses ``resource.connection_id``. ``member`` mode uses the
    invoker's own connection to the same service (and, for MCP, the same
    server), falling back to the owner's when the invoker is the owner.

    Args:
        resource: A ``user_tools`` or ``sources`` row.
        invoker_user_id: Who is running it.

    Returns:
        None when the resource has no connection at all; otherwise the
        resolution, possibly with ``available=False``.
    """
    connection_id = resource.get("connection_id")
    if not connection_id:
        return None
    mode = resource.get("credential_mode") or MODE_OWNER
    owner = resource.get("user_id")
    with db_readonly() as conn:
        repo = ConnectorSessionsRepository(conn)
        owned = repo.get(str(connection_id))
        owned_key = catalog.connector_key_for_row(owned) if owned else None
        policies = service.load_policies(conn)
        policy = (policies.get(owned_key) or {}) if owned_key else {}
        if policy.get("credential_mode") in (MODE_OWNER, MODE_MEMBER):
            # An admin forces whose account every share of this connector uses.
            mode = policy["credential_mode"]
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
    available = (
        row is not None
        and service.normalize_status(row) == service.STATUS_CONNECTED
        and service.connector_is_enabled(policies, key)
    )
    return ResolvedConnection(
        row=row,
        available=available,
        connector_key=key,
        connector_name=_name_for(row or owned, key),
        delegated=bool(row and invoker_user_id and row.get("user_id") != invoker_user_id),
        writes_allowed=_writes_allowed(policies, key),
    )


def _writes_allowed(policies: dict, key: Optional[str]) -> bool:
    definition = catalog.get_definition(key) if key else None
    if definition is None or not definition.mcp_write_url:
        return True
    return service.writes_allowed(policies, key)


def _member_connection(repo: ConnectorSessionsRepository, owned: Optional[dict], invoker: str) -> Optional[dict]:
    """The invoker's own connection to the service the owner's connection is for.

    A member with several connected accounts of that service gets the one
    they used most recently (then the most recently connected): the account
    they are working in, and the one a "Connect to continue" just added.
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
        return tuple(when(row.get(field)) for field in ("last_used_at", "updated_at", "created_at"))

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
