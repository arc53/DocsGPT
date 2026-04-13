"""Tests for WorkflowsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.workflows import WorkflowsRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> WorkflowsRepository:
    return WorkflowsRepository(conn)


class TestCreate:
    def test_creates_workflow(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "My Workflow")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "My Workflow"
        assert doc["current_graph_version"] == 1
        assert doc["id"] is not None
        assert doc["_id"] == doc["id"]

    def test_create_with_description(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "wf", description="A test workflow")
        assert doc["description"] == "A test workflow"


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_wrong_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        assert repo.get(created["id"], "user-other") is None

    def test_get_by_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        fetched = repo.get_by_id(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1", "wf", legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert fetched["id"] == created["id"]


class TestListForUser:
    def test_lists_own(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "wf1")
        repo.create("alice", "wf2")
        repo.create("bob", "wf3")
        results = repo.list_for_user("alice")
        assert len(results) == 2


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        assert repo.update(created["id"], "user-1", {"name": "new"}) is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"

    def test_update_wrong_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        assert repo.update(created["id"], "other", {"name": "new"}) is False

    def test_update_disallowed_field(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        assert repo.update(created["id"], "user-1", {"id": "bad"}) is False


class TestIncrementGraphVersion:
    def test_increments(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        assert created["current_graph_version"] == 1
        new_ver = repo.increment_graph_version(created["id"], "user-1")
        assert new_ver == 2
        fetched = repo.get(created["id"], "user-1")
        assert fetched["current_graph_version"] == 2

    def test_increment_wrong_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        assert repo.increment_graph_version(created["id"], "other") is None


class TestDelete:
    def test_deletes(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        assert repo.delete(created["id"], "user-1") is True
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "wf")
        assert repo.delete(created["id"], "other") is False
