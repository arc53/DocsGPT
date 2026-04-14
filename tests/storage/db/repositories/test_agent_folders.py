"""Tests for AgentFoldersRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.agent_folders import AgentFoldersRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> AgentFoldersRepository:
    return AgentFoldersRepository(conn)


class TestCreate:
    def test_creates_folder(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "My Folder")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "My Folder"
        assert doc["id"] is not None

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "f")
        assert doc["_id"] == doc["id"]


class TestNesting:
    def test_create_with_parent(self, pg_conn):
        repo = _repo(pg_conn)
        parent = repo.create("u", "Parent")
        child = repo.create("u", "Child", parent_id=parent["id"])
        assert str(child["parent_id"]) == str(parent["id"])

    def test_list_children(self, pg_conn):
        repo = _repo(pg_conn)
        parent = repo.create("u", "Parent")
        repo.create("u", "Child A", parent_id=parent["id"])
        repo.create("u", "Child B", parent_id=parent["id"])
        repo.create("u", "Top-level — not a child")
        children = repo.list_children(parent["id"], "u")
        assert {c["name"] for c in children} == {"Child A", "Child B"}

    def test_update_reparents(self, pg_conn):
        repo = _repo(pg_conn)
        a = repo.create("u", "A")
        b = repo.create("u", "B")
        c = repo.create("u", "C", parent_id=a["id"])
        repo.update(c["id"], "u", {"parent_id": b["id"]})
        assert str(repo.get(c["id"], "u")["parent_id"]) == str(b["id"])

    def test_update_clears_parent(self, pg_conn):
        repo = _repo(pg_conn)
        parent = repo.create("u", "P")
        child = repo.create("u", "C", parent_id=parent["id"])
        repo.update(child["id"], "u", {"parent_id": None})
        assert repo.get(child["id"], "u")["parent_id"] is None

    def test_delete_parent_unparents_children(self, pg_conn):
        """ON DELETE SET NULL on the self-FK keeps children alive."""
        repo = _repo(pg_conn)
        parent = repo.create("u", "P")
        child = repo.create("u", "C", parent_id=parent["id"])
        repo.delete(parent["id"], "u")
        survivor = repo.get(child["id"], "u")
        assert survivor is not None
        assert survivor["parent_id"] is None

    def test_get_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "F", legacy_mongo_id="abc123")
        found = repo.get_by_legacy_id("abc123", "u")
        assert found is not None
        assert found["name"] == "F"


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        assert repo.get(created["id"], "user-other") is None


class TestListForUser:
    def test_lists_only_own_folders(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "f1")
        repo.create("alice", "f2")
        repo.create("bob", "f3")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        updated = repo.update(created["id"], "user-1", {"name": "new"})
        assert updated is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"

    def test_update_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        updated = repo.update(created["id"], "user-other", {"name": "new"})
        assert updated is False
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "old"

    def test_update_disallowed_field_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        updated = repo.update(created["id"], "user-1", {"id": "00000000-0000-0000-0000-000000000000"})
        assert updated is False


class TestDelete:
    def test_deletes_folder(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        deleted = repo.delete(created["id"], "user-1")
        assert deleted is True
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        deleted = repo.delete(created["id"], "user-other")
        assert deleted is False
        assert repo.get(created["id"], "user-1") is not None


class TestTenantIsolation:
    def test_user_a_cannot_see_user_b_folders(self, pg_conn):
        repo = _repo(pg_conn)
        folder_a = repo.create("alice", "private")
        assert repo.get(folder_a["id"], "bob") is None

    def test_list_returns_only_own_folders(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1")
        repo.create("bob", "b1")
        alice_folders = repo.list_for_user("alice")
        bob_folders = repo.list_for_user("bob")
        assert len(alice_folders) == 1
        assert len(bob_folders) == 1
        assert alice_folders[0]["name"] == "a1"
        assert bob_folders[0]["name"] == "b1"
