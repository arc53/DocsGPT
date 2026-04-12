"""Repository for the ``connector_sessions`` table.

Covers operations across connector routes and tools:
- upsert session data
- find session by user + provider
- find session by token
- delete session
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class ConnectorSessionsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(self, user_id: str, provider: str, session_data: dict) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO connector_sessions (user_id, provider, session_data)
                VALUES (:user_id, :provider, CAST(:session_data AS jsonb))
                ON CONFLICT DO NOTHING
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "provider": provider,
                "session_data": json.dumps(session_data),
            },
        )
        row = result.fetchone()
        if row is not None:
            return row_to_dict(row)
        # Conflict — update existing row.
        self._conn.execute(
            text(
                "UPDATE connector_sessions SET session_data = CAST(:session_data AS jsonb) "
                "WHERE user_id = :user_id AND provider = :provider"
            ),
            {"user_id": user_id, "provider": provider, "session_data": json.dumps(session_data)},
        )
        return self.get_by_user_provider(user_id, provider) or {}

    def get_by_user_provider(self, user_id: str, provider: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM connector_sessions WHERE user_id = :user_id AND provider = :provider"
            ),
            {"user_id": user_id, "provider": provider},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM connector_sessions WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def delete(self, user_id: str, provider: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM connector_sessions WHERE user_id = :user_id AND provider = :provider"),
            {"user_id": user_id, "provider": provider},
        )
        return result.rowcount > 0
