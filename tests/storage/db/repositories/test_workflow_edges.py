"""Tests for WorkflowEdgesRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.workflows import WorkflowsRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from application.storage.db.repositories.workflow_edges import WorkflowEdgesRepository


def _setup(conn) -> tuple[dict, dict, dict]:
    """Create a workflow with two nodes and return (workflow, node1, node2)."""
    wf = WorkflowsRepository(conn).create("user-1", "test wf")
    node_repo = WorkflowNodesRepository(conn)
    n1 = node_repo.create(wf["id"], 1, "start-node", "start")
    n2 = node_repo.create(wf["id"], 1, "end-node", "end")
    return wf, n1, n2


def _repo(conn) -> WorkflowEdgesRepository:
    return WorkflowEdgesRepository(conn)


class TestCreate:
    def test_creates_edge(self, pg_conn):
        wf, n1, n2 = _setup(pg_conn)
        repo = _repo(pg_conn)
        edge = repo.create(
            wf["id"], 1, "edge-1", n1["id"], n2["id"],
            source_handle="out", target_handle="in",
        )
        assert edge["edge_id"] == "edge-1"
        assert str(edge["from_node_id"]) == n1["id"]
        assert str(edge["to_node_id"]) == n2["id"]
        assert edge["source_handle"] == "out"
        assert edge["target_handle"] == "in"


class TestBulkCreate:
    def test_bulk_creates_edges(self, pg_conn):
        wf, n1, n2 = _setup(pg_conn)
        repo = _repo(pg_conn)
        edges = repo.bulk_create(wf["id"], 1, [
            {"edge_id": "e1", "from_node_id": n1["id"], "to_node_id": n2["id"]},
            {"edge_id": "e2", "from_node_id": n2["id"], "to_node_id": n1["id"],
             "source_handle": "loop"},
        ])
        assert len(edges) == 2

    def test_bulk_create_empty(self, pg_conn):
        wf, _, _ = _setup(pg_conn)
        repo = _repo(pg_conn)
        assert repo.bulk_create(wf["id"], 1, []) == []


class TestBulkCreateOnConflict:
    """Overlapping graph PUTs at the same ``graph_version`` must not
    drift on edges either."""

    def test_bulk_create_overwrites_same_edge_id(self, pg_conn):
        wf, n1, n2 = _setup(pg_conn)
        repo = _repo(pg_conn)
        repo.bulk_create(wf["id"], 1, [
            {
                "edge_id": "e1", "from_node_id": n1["id"],
                "to_node_id": n2["id"], "source_handle": "first",
            },
        ])
        # Rewriting the same edge_id at the same version overwrites.
        repo.bulk_create(wf["id"], 1, [
            {
                "edge_id": "e1", "from_node_id": n1["id"],
                "to_node_id": n2["id"], "source_handle": "second",
                "config": {"weight": 2},
            },
        ])
        edges = repo.find_by_version(wf["id"], 1)
        assert len(edges) == 1
        assert edges[0]["source_handle"] == "second"
        assert edges[0]["config"] == {"weight": 2}


class TestFindByVersion:
    def test_finds_edges(self, pg_conn):
        wf, n1, n2 = _setup(pg_conn)
        repo = _repo(pg_conn)
        repo.create(wf["id"], 1, "e1", n1["id"], n2["id"])
        edges = repo.find_by_version(wf["id"], 1)
        assert len(edges) == 1
        assert edges[0]["edge_id"] == "e1"

    def test_no_edges_for_version(self, pg_conn):
        wf, _, _ = _setup(pg_conn)
        repo = _repo(pg_conn)
        assert repo.find_by_version(wf["id"], 99) == []


class TestDelete:
    def test_delete_by_workflow(self, pg_conn):
        wf, n1, n2 = _setup(pg_conn)
        repo = _repo(pg_conn)
        repo.create(wf["id"], 1, "e1", n1["id"], n2["id"])
        deleted = repo.delete_by_workflow(wf["id"])
        assert deleted == 1
        assert repo.find_by_version(wf["id"], 1) == []

    def test_delete_by_version(self, pg_conn):
        wf = WorkflowsRepository(pg_conn).create("user-1", "wf")
        node_repo = WorkflowNodesRepository(pg_conn)
        n1v1 = node_repo.create(wf["id"], 1, "n1", "start")
        n2v1 = node_repo.create(wf["id"], 1, "n2", "end")
        n1v2 = node_repo.create(wf["id"], 2, "n1", "start")
        n2v2 = node_repo.create(wf["id"], 2, "n2", "end")

        repo = _repo(pg_conn)
        repo.create(wf["id"], 1, "e1", n1v1["id"], n2v1["id"])
        repo.create(wf["id"], 2, "e1", n1v2["id"], n2v2["id"])

        repo.delete_by_version(wf["id"], 1)
        assert repo.find_by_version(wf["id"], 1) == []
        assert len(repo.find_by_version(wf["id"], 2)) == 1

    def test_delete_other_versions(self, pg_conn):
        wf = WorkflowsRepository(pg_conn).create("user-1", "wf")
        node_repo = WorkflowNodesRepository(pg_conn)
        n1v1 = node_repo.create(wf["id"], 1, "n1", "start")
        n2v1 = node_repo.create(wf["id"], 1, "n2", "end")
        n1v2 = node_repo.create(wf["id"], 2, "n1", "start")
        n2v2 = node_repo.create(wf["id"], 2, "n2", "end")

        repo = _repo(pg_conn)
        repo.create(wf["id"], 1, "e1", n1v1["id"], n2v1["id"])
        repo.create(wf["id"], 2, "e1", n1v2["id"], n2v2["id"])

        repo.delete_other_versions(wf["id"], 2)
        assert repo.find_by_version(wf["id"], 1) == []
        assert len(repo.find_by_version(wf["id"], 2)) == 1
