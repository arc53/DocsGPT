"""Repository for the ``todos`` table.

Covers the operations in ``application/agents/tools/todo_list.py``.
Note: the Mongo schema uses ``todo_id`` (sequential int) and ``status`` (text),
while the Postgres schema uses ``completed`` (boolean) and the UUID ``id`` as PK.
The repository bridges both shapes.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class TodosRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, tool_id: str, title: str) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO todos (user_id, tool_id, title)
                VALUES (:user_id, CAST(:tool_id AS uuid), :title)
                RETURNING *
                """
            ),
            {"user_id": user_id, "tool_id": tool_id, "title": title},
        )
        return row_to_dict(result.fetchone())

    def get(self, todo_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM todos WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": todo_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user_tool(self, user_id: str, tool_id: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM todos WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) ORDER BY created_at"
            ),
            {"user_id": user_id, "tool_id": tool_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update_title(self, todo_id: str, user_id: str, title: str) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE todos SET title = :title, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": todo_id, "user_id": user_id, "title": title},
        )
        return result.rowcount > 0

    def set_completed(self, todo_id: str, user_id: str, completed: bool = True) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE todos SET completed = :completed, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": todo_id, "user_id": user_id, "completed": completed},
        )
        return result.rowcount > 0

    def delete(self, todo_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM todos WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": todo_id, "user_id": user_id},
        )
        return result.rowcount > 0
