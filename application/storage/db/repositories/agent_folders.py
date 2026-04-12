"""Repository for the ``agent_folders`` table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class AgentFoldersRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, name: str, *, parent_id: Optional[str] = None) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO agent_folders (user_id, name, description)
                VALUES (:user_id, :name, :parent_id)
                RETURNING *
                """
            ),
            {"user_id": user_id, "name": name, "parent_id": parent_id},
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
        set_clauses = [f"{col} = :val_{col}" for col in filtered]
        set_clauses.append("updated_at = now()")
        params: dict = {"id": folder_id, "user_id": user_id}
        for col, val in filtered.items():
            params[f"val_{col}"] = val
        sql = f"UPDATE agent_folders SET {', '.join(set_clauses)} WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
        result = self._conn.execute(text(sql), params)
        return result.rowcount > 0

    def delete(self, folder_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM agent_folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": folder_id, "user_id": user_id},
        )
        return result.rowcount > 0
