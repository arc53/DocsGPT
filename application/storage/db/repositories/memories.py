"""Repository for the ``memories`` table.

Covers the operations in ``application/agents/tools/memory.py``:
- upsert (create/overwrite file)
- find by path (view file)
- find by path prefix (view directory, regex scan)
- delete by path / path prefix
- rename (update path)
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class MemoriesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(self, user_id: str, tool_id: str, path: str, content: str) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO memories (user_id, tool_id, path, content)
                VALUES (:user_id, CAST(:tool_id AS uuid), :path, :content)
                ON CONFLICT (user_id, tool_id, path)
                DO UPDATE SET content = EXCLUDED.content, updated_at = now()
                RETURNING *
                """
            ),
            {"user_id": user_id, "tool_id": tool_id, "path": path, "content": content},
        )
        return row_to_dict(result.fetchone())

    def get_by_path(self, user_id: str, tool_id: str, path: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM memories WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) AND path = :path"
            ),
            {"user_id": user_id, "tool_id": tool_id, "path": path},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_by_prefix(self, user_id: str, tool_id: str, prefix: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM memories WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) AND path LIKE :prefix"
            ),
            {"user_id": user_id, "tool_id": tool_id, "prefix": prefix + "%"},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def delete_by_path(self, user_id: str, tool_id: str, path: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM memories WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) AND path = :path"
            ),
            {"user_id": user_id, "tool_id": tool_id, "path": path},
        )
        return result.rowcount

    def delete_by_prefix(self, user_id: str, tool_id: str, prefix: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM memories WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) AND path LIKE :prefix"
            ),
            {"user_id": user_id, "tool_id": tool_id, "prefix": prefix + "%"},
        )
        return result.rowcount

    def delete_all(self, user_id: str, tool_id: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM memories WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid)"
            ),
            {"user_id": user_id, "tool_id": tool_id},
        )
        return result.rowcount

    def update_path(self, user_id: str, tool_id: str, old_path: str, new_path: str) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE memories SET path = :new_path, updated_at = now() "
                "WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid) AND path = :old_path"
            ),
            {"user_id": user_id, "tool_id": tool_id, "old_path": old_path, "new_path": new_path},
        )
        return result.rowcount > 0
