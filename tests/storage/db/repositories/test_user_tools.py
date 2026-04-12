"""Tests for UserToolsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.user_tools import UserToolsRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> UserToolsRepository:
    return UserToolsRepository(conn)


class TestCreate:
    def test_creates_tool(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "my_tool", config={"key": "val"})
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "my_tool"
        assert doc["config"] == {"key": "val"}
        assert doc["id"] is not None

    def test_create_with_display_names(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "t", custom_name="Custom", display_name="Display")
        assert doc["custom_name"] == "Custom"
        assert doc["display_name"] == "Display"


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000") is None


class TestListForUser:
    def test_lists_only_own_tools(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "t1")
        repo.create("alice", "t2")
        repo.create("bob", "t3")
        results = repo.list_for_user("alice")
        assert len(results) == 2


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old_name")
        repo.update(created["id"], "user-1", {"name": "new_name"})
        fetched = repo.get(created["id"])
        assert fetched["name"] == "new_name"

    def test_updates_config(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t", config={"a": 1})
        repo.update(created["id"], "user-1", {"config": {"a": 2, "b": 3}})
        fetched = repo.get(created["id"])
        assert fetched["config"] == {"a": 2, "b": 3}

    def test_update_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        repo.update(created["id"], "user-other", {"name": "new"})
        fetched = repo.get(created["id"])
        assert fetched["name"] == "old"

    def test_ignores_disallowed_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        repo.update(created["id"], "user-1", {"id": "00000000-0000-0000-0000-000000000000"})
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]


class TestDelete:
    def test_deletes_tool(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        assert repo.delete(created["id"], "user-1") is True
        assert repo.get(created["id"]) is None

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        assert repo.delete(created["id"], "user-other") is False
        assert repo.get(created["id"]) is not None
