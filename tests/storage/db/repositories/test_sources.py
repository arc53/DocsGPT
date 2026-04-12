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

    def test_creates_system_source_without_user(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("system-src")
        assert doc["user_id"] is None
        assert doc["name"] == "system-src"

    def test_creates_source_with_metadata(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("src", user_id="u", metadata={"url": "https://example.com"})
        assert doc["metadata"] == {"url": "https://example.com"}

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("s")
        assert doc["_id"] == doc["id"]


class TestGet:
    def test_get_by_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s")
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000") is None


class TestGetForUser:
    def test_get_for_correct_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="user-1")
        fetched = repo.get_for_user(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_for_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="user-1")
        assert repo.get_for_user(created["id"], "user-other") is None


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
        repo.update(created["id"], {"name": "new"})
        fetched = repo.get(created["id"])
        assert fetched["name"] == "new"

    def test_updates_metadata(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", metadata={"a": 1})
        repo.update(created["id"], {"metadata": {"a": 2, "b": 3}})
        fetched = repo.get(created["id"])
        assert fetched["metadata"] == {"a": 2, "b": 3}

    def test_update_disallowed_field_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s")
        repo.update(created["id"], {"id": "00000000-0000-0000-0000-000000000000"})
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]


class TestDelete:
    def test_deletes_source(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s")
        deleted = repo.delete(created["id"])
        assert deleted is True
        assert repo.get(created["id"]) is None

    def test_delete_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        deleted = repo.delete("00000000-0000-0000-0000-000000000000")
        assert deleted is False
