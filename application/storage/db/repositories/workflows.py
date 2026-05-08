"""Repository for the ``workflows`` table.

Covers CRUD on workflow metadata:

- create / get / list / update / delete
- graph version management
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import workflows_table


class WorkflowsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        name: str,
        description: str | None = None,
        *,
        legacy_mongo_id: str | None = None,
    ) -> dict:
        values: dict = {"user_id": user_id, "name": name}
        if description is not None:
            values["description"] = description
        if legacy_mongo_id is not None:
            values["legacy_mongo_id"] = legacy_mongo_id

        stmt = pg_insert(workflows_table).values(**values).returning(workflows_table)
        result = self._conn.execute(stmt)
        return row_to_dict(result.fetchone())

    def get(self, workflow_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM workflows "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": workflow_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_id(self, workflow_id: str) -> Optional[dict]:
        """Fetch a workflow by ID without user check (for internal use)."""
        result = self._conn.execute(
            text("SELECT * FROM workflows WHERE id = CAST(:id AS uuid)"),
            {"id": workflow_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: str | None = None,
    ) -> Optional[dict]:
        """Fetch a workflow by its original Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM workflows WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM workflows "
                "WHERE user_id = :user_id ORDER BY created_at DESC"
            ),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, workflow_id: str, user_id: str, fields: dict) -> bool:
        allowed = {"name", "description", "current_graph_version"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False

        set_parts = [f"{col} = :{col}" for col in filtered]
        set_parts.append("updated_at = now()")
        params = {**filtered, "id": workflow_id, "user_id": user_id}

        sql = (
            f"UPDATE workflows SET {', '.join(set_parts)} "
            "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
        )
        result = self._conn.execute(text(sql), params)
        return result.rowcount > 0

    def increment_graph_version(self, workflow_id: str, user_id: str) -> Optional[int]:
        """Atomically increment ``current_graph_version`` and return the new value."""
        result = self._conn.execute(
            text(
                "UPDATE workflows "
                "SET current_graph_version = current_graph_version + 1, "
                "    updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id "
                "RETURNING current_graph_version"
            ),
            {"id": workflow_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row[0] if row else None

    def delete(self, workflow_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text(
                "DELETE FROM workflows "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": workflow_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def delete_by_legacy_id(self, legacy_mongo_id: str, user_id: str) -> bool:
        """Delete a workflow addressed by the Mongo ObjectId string.

        The ``workflow_nodes`` and ``workflow_edges`` rows are removed
        automatically via ``ON DELETE CASCADE``.
        """
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        result = self._conn.execute(
            text(
                "DELETE FROM workflows "
                "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
            ),
            {"legacy_id": legacy_mongo_id, "user_id": user_id},
        )
        return result.rowcount > 0
