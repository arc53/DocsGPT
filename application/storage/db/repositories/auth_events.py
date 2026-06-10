"""Repository for the ``auth_events`` audit table."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class AuthEventsRepository:
    """Append-only audit trail of login / logout / provisioning events."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(
        self,
        user_id: str,
        event: str,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Record one auth event and return the inserted row."""
        result = self._conn.execute(
            text(
                """
                INSERT INTO auth_events (user_id, event, ip, user_agent, metadata)
                VALUES (:user_id, :event, :ip, :user_agent, CAST(:metadata AS jsonb))
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
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
