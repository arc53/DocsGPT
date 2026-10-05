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

    def list_recent(
        self,
        user_id: str,
        limit: int = 50,
        *,
        exclude_events_like: Optional[Sequence[str]] = None,
    ) -> list[dict]:
        """Return the newest events for ``user_id``, newest first.

        Args:
            user_id: The subject whose trail to read.
            limit: How many rows to return.
            exclude_events_like: Event-name prefixes to drop, e.g.
                ``("source.", "agent.")``. Data-plane events are filed under
                the actor, so on an active account they would otherwise push
                a denied login or a role grant out of a short window within
                minutes.

        Returns:
            Matching rows, newest first.
        """
        clauses = ["user_id = :user_id"]
        params: dict = {"user_id": user_id, "limit": limit}
        for index, prefix in enumerate(exclude_events_like or ()):
            key = f"excl_{index}"
            clauses.append(f"event NOT LIKE :{key}")
            params[key] = f"{prefix}%"
        where = " AND ".join(clauses)
        result = self._conn.execute(
            text(
                f"""
                SELECT * FROM auth_events
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [row_to_dict(row) for row in result.fetchall()]

    @staticmethod
    def _filter_clauses(
        event: Optional[str],
        user_id: Optional[str],
        since: Any,
    ) -> tuple[str, dict]:
        clauses: list[str] = []
        params: dict = {}
        if event:
            clauses.append("event = :event")
            params["event"] = event
        if user_id:
            clauses.append("(user_id = :user_id OR target_id = :user_id)")
            params["user_id"] = user_id
        if since is not None:
            clauses.append("created_at >= :since")
            params["since"] = since
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def list_all(
        self,
        *,
        event: Optional[str] = None,
        user_id: Optional[str] = None,
        since=None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Single-journal audit feed for ``GET /api/admin/audit``, newest first.

        The admin UI reads the merged feed instead; richer filtering lives on
        :class:`~docsgpt.storage.db.repositories.activity.ActivityRepository`
        rather than being implemented twice here.
        """
        where, params = self._filter_clauses(event, user_id, since)
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
        user_id: Optional[str] = None,
        since=None,
    ) -> int:
        """Total matching the same filters as :meth:`list_all` (for pagination)."""
        where, params = self._filter_clauses(event, user_id, since)
        return int(
            self._conn.execute(
                text(f"SELECT count(*) FROM auth_events {where}"), params
            ).scalar()
            or 0
        )
