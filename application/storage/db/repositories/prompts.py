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

    def create(
        self,
        user_id: str,
        name: str,
        content: str,
        *,
        legacy_mongo_id: str | None = None,
    ) -> dict:
        sql = """
            INSERT INTO prompts (user_id, name, content, legacy_mongo_id)
            VALUES (:user_id, :name, :content, :legacy_mongo_id)
            RETURNING *
        """
        result = self._conn.execute(
            text(sql),
            {
                "user_id": user_id,
                "name": name,
                "content": content,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, prompt_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM prompts WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": prompt_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(self, legacy_mongo_id: str, user_id: str | None = None) -> Optional[dict]:
        """Fetch a prompt by the original Mongo ObjectId string."""
        sql = "SELECT * FROM prompts WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_for_rendering(self, prompt_id: str) -> Optional[dict]:
        """Fetch prompt content by ID without user scoping.

        Used only by stream_processor to render a prompt whose owner is
        not known at call time. Do NOT use in user-facing routes.
        """
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

    def update_by_legacy_id(
        self,
        legacy_mongo_id: str,
        user_id: str,
        name: str,
        content: str,
    ) -> bool:
        """Update a prompt addressed by the Mongo ObjectId string."""
        result = self._conn.execute(
            text(
                """
                UPDATE prompts
                SET name = :name, content = :content, updated_at = now()
                WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id
                """
            ),
            {
                "legacy_id": legacy_mongo_id,
                "user_id": user_id,
                "name": name,
                "content": content,
            },
        )
        return result.rowcount > 0

    def delete(self, prompt_id: str, user_id: str) -> None:
        self._conn.execute(
            text("DELETE FROM prompts WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": prompt_id, "user_id": user_id},
        )

    def delete_by_legacy_id(self, legacy_mongo_id: str, user_id: str) -> bool:
        """Delete a prompt addressed by the Mongo ObjectId string."""
        result = self._conn.execute(
            text(
                "DELETE FROM prompts "
                "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
            ),
            {"legacy_id": legacy_mongo_id, "user_id": user_id},
        )
        return result.rowcount > 0

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
