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

    def test_create_defaults(self, pg_conn):
        """Unspecified metadata fields fall back to safe defaults."""
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "t")
        assert doc["description"] is None
        assert doc["config_requirements"] == {}
        assert doc["actions"] == []
        assert doc["status"] is True

    def test_create_with_display_names(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "t", custom_name="Custom", display_name="Display")
        assert doc["custom_name"] == "Custom"
        assert doc["display_name"] == "Display"

    def test_create_with_metadata_fields(self, pg_conn):
        repo = _repo(pg_conn)
        actions = [{"name": "search", "active": True}]
        requirements = {"api_key": {"required": True, "secret": True}}
        doc = repo.create(
            "user-1", "web",
            description="Search the web",
            actions=actions,
            config_requirements=requirements,
            status=False,
        )
        assert doc["description"] == "Search the web"
        assert doc["actions"] == actions
        assert doc["config_requirements"] == requirements
        assert doc["status"] is False


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        assert repo.get(created["id"], "user-other") is None


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
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new_name"

    def test_updates_config(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t", config={"a": 1})
        repo.update(created["id"], "user-1", {"config": {"a": 2, "b": 3}})
        fetched = repo.get(created["id"], "user-1")
        assert fetched["config"] == {"a": 2, "b": 3}

    def test_update_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        repo.update(created["id"], "user-other", {"name": "new"})
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "old"

    def test_ignores_disallowed_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        repo.update(created["id"], "user-1", {"id": "00000000-0000-0000-0000-000000000000"})
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_updates_metadata_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t", status=True)
        updated_actions = [{"name": "new_action", "active": True}]
        result = repo.update(
            created["id"], "user-1",
            {
                "description": "updated",
                "actions": updated_actions,
                "config_requirements": {"token": {"secret": True}},
                "status": False,
            },
        )
        assert result is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["description"] == "updated"
        assert fetched["actions"] == updated_actions
        assert fetched["config_requirements"] == {"token": {"secret": True}}
        assert fetched["status"] is False

    def test_update_returns_false_when_no_row_matched(self, pg_conn):
        repo = _repo(pg_conn)
        result = repo.update(
            "00000000-0000-0000-0000-000000000000", "user-1", {"name": "x"}
        )
        assert result is False


class TestListActive:
    def test_filters_to_status_true(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "on_a", status=True)
        repo.create("u", "off", status=False)
        repo.create("u", "on_b", status=True)
        active = repo.list_active_for_user("u")
        assert {t["name"] for t in active} == {"on_a", "on_b"}

    def test_empty_when_all_inactive(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "t", status=False)
        assert repo.list_active_for_user("u") == []


class TestLegacyMongoId:
    def test_legacy_id_unique_index_blocks_dupes(self, pg_conn):
        """The partial unique index lets multiple NULLs coexist
        (it's `WHERE legacy_mongo_id IS NOT NULL`) but rejects collisions
        between two real IDs."""
        import sqlalchemy.exc
        from sqlalchemy import text

        # Two NULLs are fine
        pg_conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name) VALUES "
                "('u', 'a'), ('u', 'b')"
            )
        )
        # Same legacy_mongo_id twice is not
        pg_conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, legacy_mongo_id) "
                "VALUES ('u', 'c', 'oid-1')"
            )
        )
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            pg_conn.execute(
                text(
                    "INSERT INTO user_tools (user_id, name, legacy_mongo_id) "
                    "VALUES ('u', 'd', 'oid-1')"
                )
            )


class TestFindByUserAndName:
    def test_returns_match(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "unique_name")
        found = repo.find_by_user_and_name("u", "unique_name")
        assert found["id"] == created["id"]

    def test_returns_none_when_missing(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.find_by_user_and_name("u", "does-not-exist") is None

    def test_respects_user_scope(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "shared_name")
        assert repo.find_by_user_and_name("bob", "shared_name") is None


class TestDelete:
    def test_deletes_tool(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        deleted = repo.delete(created["id"], "user-1")
        assert deleted is True
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "t")
        deleted = repo.delete(created["id"], "user-other")
        assert deleted is False
        assert repo.get(created["id"], "user-1") is not None
