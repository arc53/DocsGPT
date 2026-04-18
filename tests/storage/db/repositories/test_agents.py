"""Tests for AgentsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.agents import AgentsRepository


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

    def test_create_with_legacy_mongo_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "u",
            "a",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        assert doc["legacy_mongo_id"] == "507f1f77bcf86cd799439011"

    def test_create_normalizes_blank_key_to_null(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft", key="")
        assert doc["key"] is None


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        assert repo.get(created["id"], "user-other") is None

    def test_get_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1",
            "a",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert fetched["id"] == created["id"]


class TestFindByKey:
    def test_finds_agent_by_key(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft", key="my-unique-key")
        fetched = repo.find_by_key("my-unique-key")
        assert fetched["id"] == created["id"]

    def test_find_by_key_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.find_by_key("nonexistent-key") is None


class TestSharing:
    def test_create_with_share_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "u", "a", "published",
            shared=True,
            shared_token="share-abc",
            shared_metadata={"name": "public demo", "avatar": "🤖"},
        )
        assert created["shared"] is True
        assert created["shared_token"] == "share-abc"
        assert created["shared_metadata"] == {"name": "public demo", "avatar": "🤖"}

    def test_update_share_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft")
        repo.update(
            created["id"], "u",
            {"shared": True, "shared_token": "tok-xyz", "shared_metadata": {"k": 1}},
        )
        fetched = repo.get(created["id"], "u")
        assert fetched["shared"] is True
        assert fetched["shared_token"] == "tok-xyz"
        assert fetched["shared_metadata"] == {"k": 1}

    def test_find_by_shared_token_only_returns_shared_agents(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "u", "a", "published",
            shared=True, shared_token="tok-1",
        )
        found = repo.find_by_shared_token("tok-1")
        assert found is not None
        assert found["id"] == created["id"]

    def test_find_by_shared_token_skips_revoked(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "u", "a", "published",
            shared=False, shared_token="tok-revoked",
        )
        assert repo.find_by_shared_token("tok-revoked") is None
        # And revocation by flipping `shared` is immediately effective
        repo.update(created["id"], "u", {"shared": True})
        assert repo.find_by_shared_token("tok-revoked") is not None

    def test_share_token_is_unique(self, pg_conn):
        """CITEXT UNIQUE constraint blocks duplicate share tokens."""
        import sqlalchemy.exc

        repo = _repo(pg_conn)
        repo.create("u", "a1", "published", shared=True, shared_token="dup")
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            repo.create("u", "a2", "published", shared=True, shared_token="DUP")


class TestPart1bFields:
    """Coverage for image, workflow_id, allow_system_prompt_override,
    and FK round-trip via create()."""

    def test_create_with_image_and_override(self, pg_conn):
        repo = _repo(pg_conn)
        agent = repo.create(
            "u", "a", "draft",
            image="https://example.com/avatar.png",
            allow_system_prompt_override=True,
        )
        assert agent["image"] == "https://example.com/avatar.png"
        assert agent["allow_system_prompt_override"] is True

    def test_default_allow_override_is_false(self, pg_conn):
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft")
        assert agent["allow_system_prompt_override"] is False

    def test_extra_source_ids_round_trip(self, pg_conn):
        from application.storage.db.repositories.sources import SourcesRepository

        sources = SourcesRepository(pg_conn)
        s1 = sources.create("s1", user_id="u")
        s2 = sources.create("s2", user_id="u")
        repo = _repo(pg_conn)
        agent = repo.create(
            "u", "a", "draft",
            source_id=s1["id"],
            extra_source_ids=[s2["id"]],
        )
        # ARRAY(UUID) returns list of UUID objects
        assert [str(x) for x in agent["extra_source_ids"]] == [str(s2["id"])]
        assert str(agent["source_id"]) == str(s1["id"])

    def test_workflow_id_fk(self, pg_conn):
        from application.storage.db.repositories.workflows import WorkflowsRepository

        wf = WorkflowsRepository(pg_conn).create("u", "wf")
        repo = _repo(pg_conn)
        agent = repo.create(
            "u", "a", "draft",
            agent_type="workflow",
            workflow_id=wf["id"],
        )
        assert str(agent["workflow_id"]) == str(wf["id"])

    def test_workflow_id_set_null_on_workflow_delete(self, pg_conn):
        """ON DELETE SET NULL on agents.workflow_id."""
        from application.storage.db.repositories.workflows import WorkflowsRepository

        wfr = WorkflowsRepository(pg_conn)
        wf = wfr.create("u", "wf")
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft", workflow_id=wf["id"])
        wfr.delete(wf["id"], "u")
        survivor = repo.get(agent["id"], "u")
        assert survivor is not None
        assert survivor["workflow_id"] is None

    def test_update_image_and_override(self, pg_conn):
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft")
        repo.update(agent["id"], "u", {
            "image": "/new.png",
            "allow_system_prompt_override": True,
        })
        fetched = repo.get(agent["id"], "u")
        assert fetched["image"] == "/new.png"
        assert fetched["allow_system_prompt_override"] is True


class TestUpdateLastUsedAt:
    def test_update_last_used_at(self, pg_conn):
        import datetime

        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft")
        when = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        assert repo.update(created["id"], "u", {"last_used_at": when}) is True
        fetched = repo.get(created["id"], "u")
        assert fetched["last_used_at"] == when


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
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"

    def test_update_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "draft")
        updated = repo.update(created["id"], "user-other", {"name": "new"})
        assert updated is False
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "old"

    def test_update_disallowed_field_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        updated = repo.update(created["id"], "user-1", {"id": "bad"})
        assert updated is False

    def test_update_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create(
            "user-1",
            "old",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        updated = repo.update_by_legacy_id(
            "507f1f77bcf86cd799439011",
            "user-1",
            {"name": "new", "last_used_at": None},
        )
        assert updated is True
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert fetched["name"] == "new"

    def test_update_normalizes_blank_key_to_null(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "draft", key="my-unique-key")
        updated = repo.update(created["id"], "user-1", {"key": ""})
        assert updated is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["key"] is None


class TestDelete:
    def test_deletes_agent(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        deleted = repo.delete(created["id"], "user-1")
        assert deleted is True
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        deleted = repo.delete(created["id"], "user-other")
        assert deleted is False
        assert repo.get(created["id"], "user-1") is not None

    def test_delete_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1",
            "a",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        deleted = repo.delete_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert deleted is True
        assert repo.get(created["id"], "user-1") is None


class TestSetFolder:
    def test_assigns_folder(self, pg_conn):
        from application.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        agent = repo.create("user-1", "a", "draft")
        repo.set_folder(agent["id"], "user-1", folder["id"])
        fetched = repo.get(agent["id"], "user-1")
        assert str(fetched["folder_id"]) == str(folder["id"])

    def test_clear_folder(self, pg_conn):
        from application.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        agent = repo.create("user-1", "a", "draft", folder_id=folder["id"])
        repo.set_folder(agent["id"], "user-1", None)
        fetched = repo.get(agent["id"], "user-1")
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
        assert repo.get(a1["id"], "user-1")["folder_id"] is None
        assert repo.get(a2["id"], "user-1")["folder_id"] is None
