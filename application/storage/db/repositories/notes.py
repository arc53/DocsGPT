"""Repository for the ``notes`` table.

Covers the operations in ``application/agents/tools/notes.py``.
Note: the Mongo schema stores a single ``note`` text field per (user_id, tool_id),
while the Postgres schema has ``title`` + ``content``. During dual-write,
title is set to a default and content holds the note text.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import looks_like_uuid, row_to_dict


class NotesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(self, user_id: str, tool_id: str, title: str, content: str) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO notes (user_id, tool_id, title, content)
                VALUES (:user_id, CAST(:tool_id AS uuid), :title, :content)
                ON CONFLICT (user_id, tool_id)
                DO UPDATE SET content = EXCLUDED.content, title = EXCLUDED.title, updated_at = now()
                RETURNING *
                """
            ),
            {"user_id": user_id, "tool_id": tool_id, "title": title, "content": content},
        )
        return row_to_dict(result.fetchone())

    def get_for_user_tool(self, user_id: str, tool_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM notes WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid)"
            ),
            {"user_id": user_id, "tool_id": tool_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, note_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM notes WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": note_id, "user_id": user_id},
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

    def get_by_legacy_id(self, legacy_mongo_id: str) -> Optional[dict]:
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        result = self._conn.execute(
            text("SELECT * FROM notes WHERE legacy_mongo_id = :legacy"),
            {"legacy": legacy_mongo_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_any(self, identifier: str, user_id: str) -> Optional[dict]:
        """Resolve a note by PG UUID or legacy Mongo ObjectId.

        Picks the lookup path from the id shape so non-UUID input never
        reaches ``CAST(:id AS uuid)`` — that cast raises on the server
        and poisons the enclosing transaction, making any subsequent
        query on the same connection fail.
        """
        if looks_like_uuid(identifier):
            doc = self.get(identifier, user_id)
            if doc is not None:
                return doc
        legacy = self.get_by_legacy_id(identifier)
        if legacy and legacy.get("user_id") == user_id:
            return legacy
        return None
