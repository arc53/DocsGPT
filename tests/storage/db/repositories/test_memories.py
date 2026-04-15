"""Tests for MemoriesRepository against a real Postgres instance.

Memories have a FK to user_tools, so each test creates a tool row first.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from application.storage.db.repositories.memories import MemoriesRepository


def _repo(conn) -> MemoriesRepository:
    return MemoriesRepository(conn)


def _make_tool(conn, user_id: str = "test-user", name: str = "mem-tool") -> str:
    """Insert a user_tools row and return its UUID as a string."""
    return str(
        conn.execute(
            text("INSERT INTO user_tools (user_id, name) VALUES (:uid, :name) RETURNING id"),
            {"uid": user_id, "name": name},
        ).scalar()
    )


class TestUpsert:
    def test_creates_memory(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        doc = repo.upsert("test-user", tool_id, "/docs/readme.md", "Hello world")
        assert doc["path"] == "/docs/readme.md"
        assert doc["content"] == "Hello world"
        assert doc["id"] is not None

    def test_upsert_overwrites_content(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("test-user", tool_id, "/a.txt", "v1")
        doc = repo.upsert("test-user", tool_id, "/a.txt", "v2")
        assert doc["content"] == "v2"

    def test_upsert_is_idempotent_on_same_content(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        first = repo.upsert("test-user", tool_id, "/a.txt", "same")
        second = repo.upsert("test-user", tool_id, "/a.txt", "same")
        assert first["id"] == second["id"]


class TestGetByPath:
    def test_finds_existing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/x", "content")
        fetched = repo.get_by_path("u", tool_id, "/x")
        assert fetched is not None
        assert fetched["content"] == "content"

    def test_returns_none_for_missing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.get_by_path("u", tool_id, "/nonexistent") is None


class TestListByPrefix:
    def test_lists_matching_prefix(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/docs/a.md", "a")
        repo.upsert("u", tool_id, "/docs/b.md", "b")
        repo.upsert("u", tool_id, "/other/c.md", "c")
        results = repo.list_by_prefix("u", tool_id, "/docs/")
        assert len(results) == 2
        assert {r["path"] for r in results} == {"/docs/a.md", "/docs/b.md"}


class TestDeleteByPath:
    def test_deletes_single(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/x", "c")
        count = repo.delete_by_path("u", tool_id, "/x")
        assert count == 1
        assert repo.get_by_path("u", tool_id, "/x") is None

    def test_delete_nonexistent_returns_zero(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.delete_by_path("u", tool_id, "/nope") == 0


class TestDeleteByPrefix:
    def test_deletes_matching_prefix(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/dir/a", "a")
        repo.upsert("u", tool_id, "/dir/b", "b")
        repo.upsert("u", tool_id, "/other/c", "c")
        count = repo.delete_by_prefix("u", tool_id, "/dir/")
        assert count == 2
        assert repo.get_by_path("u", tool_id, "/other/c") is not None


class TestDeleteAll:
    def test_deletes_all_for_user_tool(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/a", "a")
        repo.upsert("u", tool_id, "/b", "b")
        count = repo.delete_all("u", tool_id)
        assert count == 2
        assert repo.list_by_prefix("u", tool_id, "/") == []


class TestUpdatePath:
    def test_renames_path(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/old.txt", "content")
        renamed = repo.update_path("u", tool_id, "/old.txt", "/new.txt")
        assert renamed is True
        assert repo.get_by_path("u", tool_id, "/old.txt") is None
        assert repo.get_by_path("u", tool_id, "/new.txt")["content"] == "content"

    def test_rename_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.update_path("u", tool_id, "/nope", "/new") is False
