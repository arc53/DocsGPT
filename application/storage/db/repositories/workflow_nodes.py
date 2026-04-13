"""Repository for the ``workflow_nodes`` table.

Covers bulk insert, find by version, and delete operations that the
workflow routes perform on ``workflow_nodes_collection`` in Mongo.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import workflow_nodes_table


class WorkflowNodesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        workflow_id: str,
        graph_version: int,
        node_id: str,
        node_type: str,
        *,
        title: str | None = None,
        description: str | None = None,
        position: dict | None = None,
        config: dict | None = None,
        legacy_mongo_id: str | None = None,
    ) -> dict:
        values: dict = {
            "workflow_id": workflow_id,
            "graph_version": graph_version,
            "node_id": node_id,
            "node_type": node_type,
        }
        if title is not None:
            values["title"] = title
        if description is not None:
            values["description"] = description
        if position is not None:
            values["position"] = position
        if config is not None:
            values["config"] = config
        if legacy_mongo_id is not None:
            values["legacy_mongo_id"] = legacy_mongo_id

        stmt = pg_insert(workflow_nodes_table).values(**values).returning(workflow_nodes_table)
        result = self._conn.execute(stmt)
        return row_to_dict(result.fetchone())

    def bulk_create(
        self,
        workflow_id: str,
        graph_version: int,
        nodes: list[dict],
    ) -> list[dict]:
        """Insert multiple nodes in one statement.

        Each element of ``nodes`` should have at least ``node_id`` and
        ``node_type``; optional keys: ``title``, ``description``,
        ``position``, ``config``.
        """
        if not nodes:
            return []

        rows = []
        for n in nodes:
            rows.append({
                "workflow_id": workflow_id,
                "graph_version": graph_version,
                "node_id": n["node_id"],
                "node_type": n["node_type"],
                "title": n.get("title"),
                "description": n.get("description"),
                "position": n.get("position", {"x": 0, "y": 0}),
                "config": n.get("config", {}),
                "legacy_mongo_id": n.get("legacy_mongo_id"),
            })

        stmt = pg_insert(workflow_nodes_table).values(rows).returning(workflow_nodes_table)
        result = self._conn.execute(stmt)
        return [row_to_dict(r) for r in result.fetchall()]

    def find_by_version(
        self, workflow_id: str, graph_version: int,
    ) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM workflow_nodes "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "AND graph_version = :ver "
                "ORDER BY node_id"
            ),
            {"wf_id": workflow_id, "ver": graph_version},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def find_node(
        self, workflow_id: str, graph_version: int, node_id: str,
    ) -> Optional[dict]:
        """Find a single node by its user-provided ``node_id``."""
        result = self._conn.execute(
            text(
                "SELECT * FROM workflow_nodes "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "AND graph_version = :ver AND node_id = :nid"
            ),
            {"wf_id": workflow_id, "ver": graph_version, "nid": node_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(self, legacy_mongo_id: str) -> Optional[dict]:
        """Find a node by the original Mongo ObjectId string."""
        result = self._conn.execute(
            text("SELECT * FROM workflow_nodes WHERE legacy_mongo_id = :legacy_id"),
            {"legacy_id": legacy_mongo_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def delete_by_workflow(self, workflow_id: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM workflow_nodes "
                "WHERE workflow_id = CAST(:wf_id AS uuid)"
            ),
            {"wf_id": workflow_id},
        )
        return result.rowcount

    def delete_by_version(self, workflow_id: str, graph_version: int) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM workflow_nodes "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "AND graph_version = :ver"
            ),
            {"wf_id": workflow_id, "ver": graph_version},
        )
        return result.rowcount

    def delete_other_versions(self, workflow_id: str, keep_version: int) -> int:
        """Delete all nodes for a workflow except the specified version."""
        result = self._conn.execute(
            text(
                "DELETE FROM workflow_nodes "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "AND graph_version != :ver"
            ),
            {"wf_id": workflow_id, "ver": keep_version},
        )
        return result.rowcount
