"""Repository for the ``sources`` table."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Connection, func, text

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import sources_table


class SourcesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, name: str, *, user_id: Optional[str] = None,
               type: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO sources (user_id, name, type, metadata)
                VALUES (:user_id, :name, :type, CAST(:metadata AS jsonb))
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "name": name,
                "type": type,
                "metadata": json.dumps(metadata or {}),
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, source_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM sources WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": source_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM sources WHERE user_id = :user_id ORDER BY created_at DESC"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, source_id: str, user_id: str, fields: dict) -> None:
        allowed = {"name", "type", "metadata"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return

        values: dict = {}
        for col, val in filtered.items():
            if col == "metadata":
                values[col] = json.dumps(val) if isinstance(val, dict) else val
            else:
                values[col] = val
        values["updated_at"] = func.now()

        t = sources_table
        stmt = (
            t.update()
            .where(t.c.id == source_id)
            .where(t.c.user_id == user_id)
            .values(**values)
        )
        self._conn.execute(stmt)

    def delete(self, source_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM sources WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": source_id, "user_id": user_id},
        )
        return result.rowcount > 0
