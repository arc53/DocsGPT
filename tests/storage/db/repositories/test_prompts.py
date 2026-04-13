"""Tests for PromptsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.prompts import PromptsRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> PromptsRepository:
    return PromptsRepository(conn)


class TestCreate:
    def test_creates_prompt(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "greeting", "Hello {{name}}")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "greeting"
        assert doc["content"] == "Hello {{name}}"
        assert doc["id"] is not None

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "p", "c")
        assert doc["_id"] == doc["id"]


class TestGet:
    def test_get_by_id_and_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        assert repo.get(created["id"], "user-other") is None

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None


class TestGetForRendering:
    def test_returns_prompt_without_user_scoping(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        fetched = repo.get_for_rendering(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get_for_rendering("00000000-0000-0000-0000-000000000000") is None


class TestListForUser:
    def test_lists_only_own_prompts(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1", "c1")
        repo.create("alice", "a2", "c2")
        repo.create("bob", "b1", "c3")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)


class TestUpdate:
    def test_updates_name_and_content(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "old-content")
        repo.update(created["id"], "user-1", "new", "new-content")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"
        assert fetched["content"] == "new-content"

    def test_update_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "old-content")
        repo.update(created["id"], "user-other", "new", "new-content")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "old"


class TestDelete:
    def test_deletes_prompt(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        repo.delete(created["id"], "user-1")
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        repo.delete(created["id"], "user-other")
        assert repo.get(created["id"], "user-1") is not None


class TestFindOrCreate:
    def test_creates_when_missing(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.find_or_create("sys", "template", "content")
        assert doc["id"] is not None

    def test_returns_existing_on_match(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.find_or_create("sys", "template", "content")
        second = repo.find_or_create("sys", "template", "content")
        assert first["id"] == second["id"]

    def test_different_content_creates_new(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.find_or_create("sys", "template", "v1")
        second = repo.find_or_create("sys", "template", "v2")
        assert first["id"] != second["id"]
