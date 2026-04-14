"""Repository for the ``agent_folders`` table.

Folders are self-referential via ``parent_id`` to model nested folder
hierarchies — a folder can sit inside another folder, and on delete the
DB sets each child's ``parent_id`` to NULL (no cascade) so children
survive their parent's removal but flatten to the top level. The legacy
Mongo route used ``$unset: {parent_id: ""}`` against children before
deleting the parent; that pre-step is no longer needed because the FK
``ON DELETE SET NULL`` action does it automatically.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Connection, func, text

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import agent_folders_table


_ALLOWED_UPDATE_COLUMNS = {"name", "description", "parent_id"}


class AgentFoldersRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        name: str,
        *,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO agent_folders (
                    user_id, name, description, parent_id, legacy_mongo_id
                )
                VALUES (
                    :user_id, :name, :description,
                    CAST(:parent_id AS uuid), :legacy_mongo_id
                )
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "name": name,
                "description": description,
                "parent_id": str(parent_id) if parent_id else None,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, folder_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agent_folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": folder_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: Optional[str] = None
    ) -> Optional[dict]:
        sql = "SELECT * FROM agent_folders WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agent_folders WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def list_children(self, parent_id: str, user_id: str) -> list[dict]:
        """List immediate children of ``parent_id`` for nested-folder UIs."""
        result = self._conn.execute(
            text(
                "SELECT * FROM agent_folders "
                "WHERE parent_id = CAST(:parent_id AS uuid) AND user_id = :user_id "
                "ORDER BY created_at"
            ),
            {"parent_id": parent_id, "user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, folder_id: str, user_id: str, fields: dict[str, Any]) -> bool:
        """Partial update.

        The route validates that ``parent_id != folder_id`` (no self-parenting)
        before calling here; this layer does not re-check.
        """
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATE_COLUMNS}
        if not filtered:
            return False

        values: dict = {}
        for col, val in filtered.items():
            if col == "parent_id":
                values[col] = str(val) if val else None
            else:
                values[col] = val
        values["updated_at"] = func.now()

        t = agent_folders_table
        stmt = (
            t.update()
            .where(t.c.id == folder_id)
            .where(t.c.user_id == user_id)
            .values(**values)
        )
        result = self._conn.execute(stmt)
        return result.rowcount > 0

    def delete(self, folder_id: str, user_id: str) -> bool:
        """Delete a folder.

        The schema's ``ON DELETE SET NULL`` on the self-FK takes care of
        un-parenting any child folders, and the agents table's
        ``folder_id`` FK does the same for agents in the folder.
        """
        result = self._conn.execute(
            text("DELETE FROM agent_folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": folder_id, "user_id": user_id},
        )
        return result.rowcount > 0
