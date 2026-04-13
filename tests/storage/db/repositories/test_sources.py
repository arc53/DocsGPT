"""Tests for SourcesRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.sources import SourcesRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> SourcesRepository:
    return SourcesRepository(conn)


class TestCreate:
    def test_creates_source_with_user(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("my-source", user_id="user-1", type="url")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "my-source"
        assert doc["type"] == "url"
        assert doc["id"] is not None

    def test_creates_source_with_metadata(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("src", user_id="u", metadata={"url": "https://example.com"})
        assert doc["metadata"] == {"url": "https://example.com"}

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("s", user_id="u")
        assert doc["_id"] == doc["id"]


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="user-1")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="user-1")
        assert repo.get(created["id"], "user-other") is None


class TestListForUser:
    def test_lists_only_own_sources(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("s1", user_id="alice")
        repo.create("s2", user_id="alice")
        repo.create("s3", user_id="bob")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("old", user_id="u")
        repo.update(created["id"], "u", {"name": "new"})
        fetched = repo.get(created["id"], "u")
        assert fetched["name"] == "new"

    def test_updates_metadata(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u", metadata={"a": 1})
        repo.update(created["id"], "u", {"metadata": {"a": 2, "b": 3}})
        fetched = repo.get(created["id"], "u")
        assert fetched["metadata"] == {"a": 2, "b": 3}

    def test_update_disallowed_field_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u")
        repo.update(created["id"], "u", {"id": "00000000-0000-0000-0000-000000000000"})
        fetched = repo.get(created["id"], "u")
        assert fetched["id"] == created["id"]

    def test_update_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("old", user_id="u")
        repo.update(created["id"], "other-user", {"name": "new"})
        fetched = repo.get(created["id"], "u")
        assert fetched["name"] == "old"


class TestDelete:
    def test_deletes_source(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u")
        deleted = repo.delete(created["id"], "u")
        assert deleted is True
        assert repo.get(created["id"], "u") is None

    def test_delete_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        deleted = repo.delete("00000000-0000-0000-0000-000000000000", "u")
        assert deleted is False

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u")
        deleted = repo.delete(created["id"], "other-user")
        assert deleted is False
        assert repo.get(created["id"], "u") is not None
