"""Repository for the ``workflow_edges`` table.

Covers bulk insert, find by version, and delete operations that the
workflow routes perform on ``workflow_edges_collection`` in Mongo.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import workflow_edges_table


class WorkflowEdgesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        workflow_id: str,
        graph_version: int,
        edge_id: str,
        from_node_id: str,
        to_node_id: str,
        *,
        source_handle: str | None = None,
        target_handle: str | None = None,
        config: dict | None = None,
    ) -> dict:
        """Create a single edge.

        ``from_node_id`` and ``to_node_id`` are the Postgres **UUID PKs**
        of the workflow_nodes rows (not user-provided node_id strings).
        """
        values: dict = {
            "workflow_id": workflow_id,
            "graph_version": graph_version,
            "edge_id": edge_id,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
        }
        if source_handle is not None:
            values["source_handle"] = source_handle
        if target_handle is not None:
            values["target_handle"] = target_handle
        if config is not None:
            values["config"] = config

        stmt = pg_insert(workflow_edges_table).values(**values).returning(workflow_edges_table)
        result = self._conn.execute(stmt)
        return row_to_dict(result.fetchone())

    def bulk_create(
        self,
        workflow_id: str,
        graph_version: int,
        edges: list[dict],
    ) -> list[dict]:
        """Insert multiple edges in one statement.

        Each element must have ``edge_id``, ``from_node_id`` (UUID PK),
        ``to_node_id`` (UUID PK). Optional: ``source_handle``,
        ``target_handle``, ``config``.
        """
        if not edges:
            return []

        rows = []
        for e in edges:
            rows.append({
                "workflow_id": workflow_id,
                "graph_version": graph_version,
                "edge_id": e["edge_id"],
                "from_node_id": e["from_node_id"],
                "to_node_id": e["to_node_id"],
                "source_handle": e.get("source_handle"),
                "target_handle": e.get("target_handle"),
                "config": e.get("config", {}),
            })

        stmt = pg_insert(workflow_edges_table).values(rows).returning(workflow_edges_table)
        result = self._conn.execute(stmt)
        return [row_to_dict(r) for r in result.fetchall()]

    def find_by_version(
        self, workflow_id: str, graph_version: int,
    ) -> list[dict]:
        """List edges for a workflow/version, shaped to match the live API.

        Joins ``workflow_nodes`` twice so callers receive the user-provided
        node-id strings (``source_id``/``target_id``) that the Mongo code
        and the frontend use, not the internal node UUIDs. The raw UUID
        columns (``from_node_id``/``to_node_id``) are still included in
        case a caller needs them.
        """
        result = self._conn.execute(
            text(
                """
                SELECT e.*,
                       fn.node_id AS source_id,
                       tn.node_id AS target_id
                FROM workflow_edges e
                JOIN workflow_nodes fn ON fn.id = e.from_node_id
                JOIN workflow_nodes tn ON tn.id = e.to_node_id
                WHERE e.workflow_id = CAST(:wf_id AS uuid)
                AND e.graph_version = :ver
                ORDER BY e.edge_id
                """
            ),
            {"wf_id": workflow_id, "ver": graph_version},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def resolve_node_id(
        self, workflow_id: str, graph_version: int, node_id: str,
    ) -> Optional[str]:
        """Look up the UUID PK of a node by its user-provided ``node_id``.

        Callers that receive edges in the frontend shape (``source_id`` /
        ``target_id`` are user-provided strings) use this helper to
        translate to the UUID PK before calling :meth:`create` /
        :meth:`bulk_create`.
        """
        result = self._conn.execute(
            text(
                "SELECT id FROM workflow_nodes "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "AND graph_version = :ver AND node_id = :node_id"
            ),
            {"wf_id": workflow_id, "ver": graph_version, "node_id": node_id},
        )
        row = result.fetchone()
        return str(row[0]) if row else None

    def delete_by_workflow(self, workflow_id: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM workflow_edges "
                "WHERE workflow_id = CAST(:wf_id AS uuid)"
            ),
            {"wf_id": workflow_id},
        )
        return result.rowcount

    def delete_by_version(self, workflow_id: str, graph_version: int) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM workflow_edges "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "AND graph_version = :ver"
            ),
            {"wf_id": workflow_id, "ver": graph_version},
        )
        return result.rowcount

    def delete_other_versions(self, workflow_id: str, keep_version: int) -> int:
        """Delete all edges for a workflow except the specified version."""
        result = self._conn.execute(
            text(
                "DELETE FROM workflow_edges "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "AND graph_version != :ver"
            ),
            {"wf_id": workflow_id, "ver": keep_version},
        )
        return result.rowcount
