"""Tests for WorkflowNodesRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.workflows import WorkflowsRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _wf(conn) -> dict:
    return WorkflowsRepository(conn).create("user-1", "test wf")


def _repo(conn) -> WorkflowNodesRepository:
    return WorkflowNodesRepository(conn)


class TestCreate:
    def test_creates_node(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        node = repo.create(wf["id"], 1, "node-start", "start", title="Start")
        assert node["node_id"] == "node-start"
        assert node["node_type"] == "start"
        assert node["title"] == "Start"
        assert node["graph_version"] == 1

    def test_create_with_config(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        node = repo.create(
            wf["id"], 1, "node-agent", "agent",
            config={"agent_type": "classic", "system_prompt": "You are helpful"},
            position={"x": 100, "y": 200},
        )
        assert node["config"]["agent_type"] == "classic"
        assert node["position"]["x"] == 100

    def test_create_with_legacy_mongo_id(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        node = repo.create(
            wf["id"],
            1,
            "node-agent",
            "agent",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        assert node["legacy_mongo_id"] == "507f1f77bcf86cd799439011"


class TestBulkCreate:
    def test_bulk_creates_nodes(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        nodes = repo.bulk_create(wf["id"], 1, [
            {"node_id": "n1", "node_type": "start", "title": "Start"},
            {"node_id": "n2", "node_type": "agent", "config": {"agent_type": "react"}},
            {"node_id": "n3", "node_type": "end"},
        ])
        assert len(nodes) == 3
        node_ids = {n["node_id"] for n in nodes}
        assert node_ids == {"n1", "n2", "n3"}

    def test_bulk_create_empty(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        assert repo.bulk_create(wf["id"], 1, []) == []

    def test_bulk_create_with_legacy_mongo_ids(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        nodes = repo.bulk_create(wf["id"], 1, [
            {
                "node_id": "n1",
                "node_type": "start",
                "legacy_mongo_id": "507f1f77bcf86cd799439011",
            },
            {
                "node_id": "n2",
                "node_type": "end",
                "legacy_mongo_id": "507f1f77bcf86cd799439012",
            },
        ])
        assert {n["legacy_mongo_id"] for n in nodes} == {
            "507f1f77bcf86cd799439011",
            "507f1f77bcf86cd799439012",
        }


class TestFindByVersion:
    def test_finds_nodes(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        repo.bulk_create(wf["id"], 1, [
            {"node_id": "n1", "node_type": "start"},
            {"node_id": "n2", "node_type": "end"},
        ])
        repo.bulk_create(wf["id"], 2, [
            {"node_id": "n1", "node_type": "start"},
        ])
        v1_nodes = repo.find_by_version(wf["id"], 1)
        v2_nodes = repo.find_by_version(wf["id"], 2)
        assert len(v1_nodes) == 2
        assert len(v2_nodes) == 1


class TestFindNode:
    def test_finds_specific_node(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        repo.create(wf["id"], 1, "node-start", "start")
        found = repo.find_node(wf["id"], 1, "node-start")
        assert found is not None
        assert found["node_type"] == "start"

    def test_not_found(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        assert repo.find_node(wf["id"], 1, "nonexistent") is None

    def test_get_by_legacy_id(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        created = repo.create(
            wf["id"],
            1,
            "node-start",
            "start",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        found = repo.get_by_legacy_id("507f1f77bcf86cd799439011")
        assert found["id"] == created["id"]


class TestDelete:
    def test_delete_by_workflow(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        repo.bulk_create(wf["id"], 1, [
            {"node_id": "n1", "node_type": "start"},
            {"node_id": "n2", "node_type": "end"},
        ])
        deleted = repo.delete_by_workflow(wf["id"])
        assert deleted == 2
        assert repo.find_by_version(wf["id"], 1) == []

    def test_delete_by_version(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        repo.bulk_create(wf["id"], 1, [{"node_id": "n1", "node_type": "start"}])
        repo.bulk_create(wf["id"], 2, [{"node_id": "n1", "node_type": "start"}])
        repo.delete_by_version(wf["id"], 1)
        assert repo.find_by_version(wf["id"], 1) == []
        assert len(repo.find_by_version(wf["id"], 2)) == 1

    def test_delete_other_versions(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        repo.bulk_create(wf["id"], 1, [{"node_id": "n1", "node_type": "start"}])
        repo.bulk_create(wf["id"], 2, [{"node_id": "n1", "node_type": "start"}])
        repo.bulk_create(wf["id"], 3, [{"node_id": "n1", "node_type": "start"}])
        repo.delete_other_versions(wf["id"], 2)
        assert repo.find_by_version(wf["id"], 1) == []
        assert len(repo.find_by_version(wf["id"], 2)) == 1
        assert repo.find_by_version(wf["id"], 3) == []
