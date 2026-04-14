"""Repository for the ``todos`` table.

Covers the operations in ``application/agents/tools/todo_list.py``.

The Mongo schema uses ``todo_id`` (a per-tool monotonic integer that the
LLM uses as its handle) and ``status`` ("open"/"completed"). The Postgres
schema mirrors that with a dedicated ``todo_id INTEGER`` column (unique
per ``tool_id`` via a partial index) for the LLM-facing handle, while the
primary key remains a UUID, and ``status`` is collapsed to a ``completed``
boolean. ``legacy_mongo_id`` lets the backfill stay idempotent across
reruns.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class TodosRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        tool_id: str,
        title: str,
        *,
        todo_id: Optional[int] = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        """Insert a todo row.

        Allocates the per-tool monotonic ``todo_id`` inside the same
        transaction when the caller does not supply one. The allocation
        is ``COALESCE(MAX(todo_id), 0) + 1`` scoped to ``tool_id``; the
        partial unique index ``todos_tool_todo_id_uidx`` enforces
        correctness if two callers race.
        """
        if todo_id is None:
            todo_id = self._conn.execute(
                text(
                    "SELECT COALESCE(MAX(todo_id), 0) + 1 FROM todos "
                    "WHERE tool_id = CAST(:tool_id AS uuid)"
                ),
                {"tool_id": tool_id},
            ).scalar_one()

        result = self._conn.execute(
            text(
                """
                INSERT INTO todos (user_id, tool_id, todo_id, title, legacy_mongo_id)
                VALUES (:user_id, CAST(:tool_id AS uuid), :todo_id, :title, :legacy_mongo_id)
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "tool_id": tool_id,
                "todo_id": todo_id,
                "title": title,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, todo_uuid: str, user_id: str) -> Optional[dict]:
        """Look up a todo by its UUID primary key."""
        result = self._conn.execute(
            text("SELECT * FROM todos WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": todo_uuid, "user_id": user_id},
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

    def list_for_tool(self, user_id: str, tool_id: str) -> list[dict]:
        """Return all todos for a (user, tool) ordered by ``todo_id``."""
        result = self._conn.execute(
            text(
                "SELECT * FROM todos WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) "
                "ORDER BY todo_id NULLS LAST, created_at"
            ),
            {"user_id": user_id, "tool_id": tool_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def get_by_tool_and_todo_id(
        self, user_id: str, tool_id: str, todo_id: int
    ) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM todos WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) AND todo_id = :todo_id"
            ),
            {"user_id": user_id, "tool_id": tool_id, "todo_id": todo_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def update_title(self, todo_uuid: str, user_id: str, title: str) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE todos SET title = :title, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": todo_uuid, "user_id": user_id, "title": title},
        )
        return result.rowcount > 0

    def update_title_by_tool_and_todo_id(
        self, user_id: str, tool_id: str, todo_id: int, title: str
    ) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE todos SET title = :title, updated_at = now() "
                "WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid) "
                "AND todo_id = :todo_id"
            ),
            {
                "user_id": user_id,
                "tool_id": tool_id,
                "todo_id": todo_id,
                "title": title,
            },
        )
        return result.rowcount > 0

    def set_completed(
        self,
        user_id_or_uuid: str,
        tool_id_or_user_id: str,
        todo_id_or_completed: Any,
        completed: Optional[bool] = None,
    ) -> bool:
        """Mark a todo's ``completed`` flag.

        Two call shapes are supported during the migration window:

        * Legacy UUID form (kept for existing tests):
          ``set_completed(todo_uuid, user_id, completed: bool)``.
        * Per-tool integer-handle form (used by the tool's dual-write):
          ``set_completed(user_id, tool_id, todo_id: int, completed: bool)``.
        """
        if completed is None:
            # Legacy three-arg form: (todo_uuid, user_id, completed)
            todo_uuid = user_id_or_uuid
            user_id = tool_id_or_user_id
            completed_value = bool(todo_id_or_completed)
            result = self._conn.execute(
                text(
                    "UPDATE todos SET completed = :completed, updated_at = now() "
                    "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
                ),
                {"id": todo_uuid, "user_id": user_id, "completed": completed_value},
            )
            return result.rowcount > 0

        # New form: (user_id, tool_id, todo_id, completed)
        user_id = user_id_or_uuid
        tool_id = tool_id_or_user_id
        todo_id = int(todo_id_or_completed)
        result = self._conn.execute(
            text(
                "UPDATE todos SET completed = :completed, updated_at = now() "
                "WHERE user_id = :user_id AND tool_id = CAST(:tool_id AS uuid) "
                "AND todo_id = :todo_id"
            ),
            {
                "user_id": user_id,
                "tool_id": tool_id,
                "todo_id": todo_id,
                "completed": bool(completed),
            },
        )
        return result.rowcount > 0

    def delete(self, todo_uuid: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM todos WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": todo_uuid, "user_id": user_id},
        )
        return result.rowcount > 0

    def delete_by_tool_and_todo_id(
        self, user_id: str, tool_id: str, todo_id: int
    ) -> bool:
        result = self._conn.execute(
            text(
                "DELETE FROM todos WHERE user_id = :user_id "
                "AND tool_id = CAST(:tool_id AS uuid) AND todo_id = :todo_id"
            ),
            {"user_id": user_id, "tool_id": tool_id, "todo_id": todo_id},
        )
        return result.rowcount > 0

    def get_by_legacy_id(self, legacy_mongo_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM todos WHERE legacy_mongo_id = :legacy"),
            {"legacy": legacy_mongo_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def update_by_legacy_id(
        self,
        legacy_mongo_id: str,
        *,
        title: Optional[str] = None,
        completed: Optional[bool] = None,
    ) -> bool:
        sets = []
        params: dict[str, Any] = {"legacy": legacy_mongo_id}
        if title is not None:
            sets.append("title = :title")
            params["title"] = title
        if completed is not None:
            sets.append("completed = :completed")
            params["completed"] = bool(completed)
        if not sets:
            return False
        sets.append("updated_at = now()")
        sql = "UPDATE todos SET " + ", ".join(sets) + " WHERE legacy_mongo_id = :legacy"
        result = self._conn.execute(text(sql), params)
        return result.rowcount > 0
