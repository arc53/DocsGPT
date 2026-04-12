"""Repository for the ``notes`` table.

Covers the operations in ``application/agents/tools/notes.py``.
Note: the Mongo schema stores a single ``note`` text field per (user_id, tool_id),
while the Postgres schema has ``title`` + ``content``. During dual-write,
title is set to a default and content holds the note text.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class NotesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(self, user_id: str, tool_id: str, title: str, content: str) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO notes (user_id, tool_id, title, content)
                VALUES (:user_id, CAST(:tool_id AS uuid), :title, :content)
                ON CONFLICT DO NOTHING
                RETURNING *
                """
            ),
            {"user_id": user_id, "tool_id": tool_id, "title": title, "content": content},
        )
        row = result.fetchone()
        if row is not None:
            return row_to_dict(row)
        # Row already existed — update instead.
        self._conn.execute(
            text(
                "UPDATE notes SET content = :content, updated_at = now() "
                "WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid)"
            ),
            {"user_id": user_id, "tool_id": tool_id, "content": content},
        )
        return self.get_for_user_tool(user_id, tool_id) or {}

    def get_for_user_tool(self, user_id: str, tool_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM notes WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid)"
            ),
            {"user_id": user_id, "tool_id": tool_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, note_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM notes WHERE id = CAST(:id AS uuid)"),
            {"id": note_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def delete(self, user_id: str, tool_id: str) -> bool:
        result = self._conn.execute(
            text(
                "DELETE FROM notes WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid)"
            ),
            {"user_id": user_id, "tool_id": tool_id},
        )
        return result.rowcount > 0
