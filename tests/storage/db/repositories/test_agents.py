"""Tests for AgentsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.agents import AgentsRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> AgentsRepository:
    return AgentsRepository(conn)


class TestCreate:
    def test_creates_agent_minimal(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "My Agent", "draft")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "My Agent"
        assert doc["status"] == "draft"
        assert doc["id"] is not None

    def test_create_with_kwargs(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "user-1", "Agent2", "active",
            description="A test agent",
            chunks=5,
            tools=[{"name": "search"}],
            shared=True,
        )
        assert doc["description"] == "A test agent"
        assert doc["chunks"] == 5
        assert doc["tools"] == [{"name": "search"}]
        assert doc["shared"] is True

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft")
        assert doc["_id"] == doc["id"]


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft")
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000") is None


class TestGetForUser:
    def test_get_for_correct_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        fetched = repo.get_for_user(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_for_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        assert repo.get_for_user(created["id"], "user-other") is None


class TestFindByKey:
    def test_finds_agent_by_key(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft", key="my-unique-key")
        fetched = repo.find_by_key("my-unique-key")
        assert fetched["id"] == created["id"]

    def test_find_by_key_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.find_by_key("nonexistent-key") is None


class TestListForUser:
    def test_lists_only_own_agents(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1", "draft")
        repo.create("alice", "a2", "active")
        repo.create("bob", "b1", "draft")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "draft")
        updated = repo.update(created["id"], "user-1", {"name": "new"})
        assert updated is True
        fetched = repo.get(created["id"])
        assert fetched["name"] == "new"

    def test_update_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "draft")
        updated = repo.update(created["id"], "user-other", {"name": "new"})
        assert updated is False
        fetched = repo.get(created["id"])
        assert fetched["name"] == "old"

    def test_update_disallowed_field_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        updated = repo.update(created["id"], "user-1", {"id": "bad"})
        assert updated is False


class TestDelete:
    def test_deletes_agent(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        deleted = repo.delete(created["id"], "user-1")
        assert deleted is True
        assert repo.get(created["id"]) is None

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        deleted = repo.delete(created["id"], "user-other")
        assert deleted is False
        assert repo.get(created["id"]) is not None


class TestSetFolder:
    def test_assigns_folder(self, pg_conn):
        from application.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        agent = repo.create("user-1", "a", "draft")
        repo.set_folder(agent["id"], "user-1", folder["id"])
        fetched = repo.get(agent["id"])
        assert str(fetched["folder_id"]) == str(folder["id"])

    def test_clear_folder(self, pg_conn):
        from application.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        agent = repo.create("user-1", "a", "draft", folder_id=folder["id"])
        repo.set_folder(agent["id"], "user-1", None)
        fetched = repo.get(agent["id"])
        assert fetched["folder_id"] is None


class TestClearFolderForAll:
    def test_clears_folder_from_all_agents(self, pg_conn):
        from application.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        a1 = repo.create("user-1", "a1", "draft", folder_id=folder["id"])
        a2 = repo.create("user-1", "a2", "draft", folder_id=folder["id"])
        repo.clear_folder_for_all(folder["id"], "user-1")
        assert repo.get(a1["id"])["folder_id"] is None
        assert repo.get(a2["id"])["folder_id"] is None
