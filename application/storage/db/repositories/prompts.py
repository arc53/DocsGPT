"""Repository for the ``prompts`` table.

Covers every operation the legacy Mongo code performs on
``prompts_collection``:

1. ``insert_one`` in prompts/routes.py (create)
2. ``find`` by user in prompts/routes.py (list)
3. ``find_one`` by id+user in prompts/routes.py (get single)
4. ``find_one`` by id only in stream_processor.py (get content for rendering)
5. ``update_one`` in prompts/routes.py (update name+content)
6. ``delete_one`` in prompts/routes.py (delete)
7. ``find_one`` + ``insert_one`` in seeder.py (upsert by user+name+content)
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class PromptsRepository:
    """Postgres-backed replacement for Mongo ``prompts_collection``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, name: str, content: str) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO prompts (user_id, name, content)
                VALUES (:user_id, :name, :content)
                RETURNING *
                """
            ),
            {"user_id": user_id, "name": name, "content": content},
        )
        return row_to_dict(result.fetchone())

    def get(self, prompt_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        if user_id is not None:
            result = self._conn.execute(
                text("SELECT * FROM prompts WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
                {"id": prompt_id, "user_id": user_id},
            )
        else:
            result = self._conn.execute(
                text("SELECT * FROM prompts WHERE id = CAST(:id AS uuid)"),
                {"id": prompt_id},
            )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM prompts WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, prompt_id: str, user_id: str, name: str, content: str) -> None:
        self._conn.execute(
            text(
                """
                UPDATE prompts
                SET name = :name, content = :content, updated_at = now()
                WHERE id = CAST(:id AS uuid) AND user_id = :user_id
                """
            ),
            {"id": prompt_id, "user_id": user_id, "name": name, "content": content},
        )

    def delete(self, prompt_id: str, user_id: str) -> None:
        self._conn.execute(
            text("DELETE FROM prompts WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": prompt_id, "user_id": user_id},
        )

    def find_or_create(self, user_id: str, name: str, content: str) -> dict:
        """Return existing prompt matching (user, name, content), or create one.

        Used by the seeder to avoid duplicating template prompts.
        """
        result = self._conn.execute(
            text(
                "SELECT * FROM prompts WHERE user_id = :user_id AND name = :name AND content = :content"
            ),
            {"user_id": user_id, "name": name, "content": content},
        )
        row = result.fetchone()
        if row is not None:
            return row_to_dict(row)
        return self.create(user_id, name, content)
