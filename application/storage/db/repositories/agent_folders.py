"""Repository for the ``agent_folders`` table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class AgentFoldersRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, name: str, *, description: Optional[str] = None) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO agent_folders (user_id, name, description)
                VALUES (:user_id, :name, :description)
                RETURNING *
                """
            ),
            {"user_id": user_id, "name": name, "description": description},
        )
        return row_to_dict(result.fetchone())

    def get(self, folder_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agent_folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": folder_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agent_folders WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, folder_id: str, user_id: str, fields: dict) -> bool:
        allowed = {"name", "description"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False
        params: dict = {"id": folder_id, "user_id": user_id}
        if "name" in filtered and "description" in filtered:
            params["name"] = filtered["name"]
            params["description"] = filtered["description"]
            result = self._conn.execute(
                text(
                    "UPDATE agent_folders "
                    "SET name = :name, description = :description, updated_at = now() "
                    "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
                ),
                params,
            )
        elif "name" in filtered:
            params["name"] = filtered["name"]
            result = self._conn.execute(
                text(
                    "UPDATE agent_folders "
                    "SET name = :name, updated_at = now() "
                    "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
                ),
                params,
            )
        else:
            params["description"] = filtered["description"]
            result = self._conn.execute(
                text(
                    "UPDATE agent_folders "
                    "SET description = :description, updated_at = now() "
                    "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
                ),
                params,
            )
        return result.rowcount > 0

    def delete(self, folder_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM agent_folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": folder_id, "user_id": user_id},
        )
        return result.rowcount > 0
