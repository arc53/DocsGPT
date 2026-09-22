"""Repository for the ``auth_events`` audit table."""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import row_to_dict


# Actors that are not a person. Used where an automated system performs the
# action on a user's behalf, so the feed never reads as if the user did it.
SYSTEM_ACTOR_SCIM = "system:scim"
SYSTEM_ACTOR_OIDC = "system:oidc"


class AuthEventsRepository:
    """Append-only audit trail of identity, access and data-plane events.

    Every row carries three attribution columns:

    * ``actor_id`` — who performed the action. Never NULL.
    * ``target_id`` — the user the action was performed on, or NULL when the
      event is not about a user (a team change, an instance-wide policy).
    * ``user_id`` — the legacy subject column, kept as the key for the
      per-user feed (:meth:`list_recent`). Defaults to the target, falling
      back to the actor for actor-only events.

    See migration ``0034_auth_events_actor_target``.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(
        self,
        user_id: str,
        event: str,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
        *,
        actor_id: Optional[str] = None,
        target_id: Optional[str] = "",
    ) -> dict:
        """Record one audit event and return the inserted row.

        Args:
            user_id: The row's subject, kept for the per-user feed.
            event: Event name (``oidc_login``, ``source.deleted``, ...).
            ip: Client IP, when the event came from a request.
            user_agent: Client ``User-Agent``, when the event came from a request.
            metadata: Free-form JSON detail shown in the audit drill-down.
            actor_id: Who performed the action. Defaults to ``user_id``, which
                is correct for self-service events (login, PAT create).
            target_id: The user acted upon. Defaults to ``user_id``; pass
                ``None`` explicitly for events with no user target.

        Returns:
            The inserted row as a dict.
        """
        # Sentinel default: ``None`` is a meaningful value here ("no target"),
        # so it cannot double as "caller did not say".
        resolved_target = user_id if target_id == "" else target_id
        resolved_actor = actor_id or user_id
        result = self._conn.execute(
            text(
                """
                INSERT INTO auth_events
                    (user_id, actor_id, target_id, event, ip, user_agent, metadata)
                VALUES
                    (:user_id, :actor_id, :target_id, :event, :ip, :user_agent,
                     CAST(:metadata AS jsonb))
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "actor_id": resolved_actor,
                "target_id": resolved_target,
                "event": event,
                "ip": ip,
                "user_agent": user_agent,
                "metadata": json.dumps(metadata or {}),
            },
        )
        return row_to_dict(result.fetchone())

    def list_recent(self, user_id: str, limit: int = 50) -> list[dict]:
        """Return the newest events for ``user_id``, newest first."""
        result = self._conn.execute(
            text(
                """
                SELECT * FROM auth_events
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"user_id": user_id, "limit": limit},
        )
        return [row_to_dict(row) for row in result.fetchall()]

    @staticmethod
    def _filter_clauses(
        event: Optional[str],
        user_id: Optional[str],
        since: Any,
        *,
        events: Optional[Sequence[str]] = None,
        actor_id: Optional[str] = None,
        until: Any = None,
        search: Optional[str] = None,
    ) -> tuple[str, dict]:
        clauses: list[str] = []
        params: dict = {}
        if event:
            clauses.append("event = :event")
            params["event"] = event
        if events:
            clauses.append("event = ANY(:events)")
            params["events"] = list(events)
        if user_id:
            clauses.append("(user_id = :user_id OR target_id = :user_id)")
            params["user_id"] = user_id
        if actor_id:
            clauses.append("actor_id = :actor_id")
            params["actor_id"] = actor_id
        if since is not None:
            clauses.append("created_at >= :since")
            params["since"] = since
        if until is not None:
            clauses.append("created_at <= :until")
            params["until"] = until
        if search:
            # Substring match across the human-meaningful columns plus the
            # serialized metadata, so "ci-deploy-key" finds the PAT it named.
            clauses.append(
                "(user_id ILIKE :search OR actor_id ILIKE :search "
                "OR target_id ILIKE :search OR event ILIKE :search "
                "OR ip ILIKE :search OR metadata::text ILIKE :search)"
            )
            params["search"] = f"%{search}%"
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def list_all(
        self,
        *,
        event: Optional[str] = None,
        events: Optional[Sequence[str]] = None,
        user_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        since=None,
        until=None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Global audit feed (admin), newest first; see :meth:`_filter_clauses`."""
        where, params = self._filter_clauses(
            event,
            user_id,
            since,
            events=events,
            actor_id=actor_id,
            until=until,
            search=search,
        )
        params.update({"limit": int(limit), "offset": int(offset)})
        result = self._conn.execute(
            text(
                f"SELECT * FROM auth_events {where} "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        return [row_to_dict(row) for row in result.fetchall()]

    def count_all(
        self,
        *,
        event: Optional[str] = None,
        events: Optional[Sequence[str]] = None,
        user_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        since=None,
        until=None,
        search: Optional[str] = None,
    ) -> int:
        """Total matching the same filters as :meth:`list_all` (for pagination)."""
        where, params = self._filter_clauses(
            event,
            user_id,
            since,
            events=events,
            actor_id=actor_id,
            until=until,
            search=search,
        )
        return int(
            self._conn.execute(
                text(f"SELECT count(*) FROM auth_events {where}"), params
            ).scalar()
            or 0
        )

    def event_names(self) -> list[str]:
        """Distinct event names present in the table, alphabetically.

        Feeds the admin filter's event picker, so operators pick from what the
        instance actually recorded instead of typing a name from memory.
        """
        result = self._conn.execute(
            text("SELECT DISTINCT event FROM auth_events ORDER BY event")
        )
        return [row[0] for row in result.fetchall()]
