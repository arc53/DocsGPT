"""Tests for NotesRepository against a real Postgres instance.

Notes have a FK to user_tools, so each test creates a tool row first.
"""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.notes import NotesRepository


def _repo(conn) -> NotesRepository:
    return NotesRepository(conn)


def _make_tool(conn, user_id: str = "test-user", name: str = "notes-tool") -> str:
    """Insert a user_tools row and return its UUID as a string."""
    return str(
        conn.execute(
            text("INSERT INTO user_tools (user_id, name) VALUES (:uid, :name) RETURNING id"),
            {"uid": user_id, "name": name},
        ).scalar()
    )


class TestUpsert:
    def test_creates_note(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        doc = repo.upsert("test-user", tool_id, "My Note", "Some content")
        assert doc["title"] == "My Note"
        assert doc["content"] == "Some content"
        assert doc["id"] is not None

    def test_second_upsert_also_returns_content(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        first = repo.upsert("test-user", tool_id, "title", "v1")
        assert first["content"] == "v1"
        # A second upsert for the same (user, tool) creates a new note
        # (no unique constraint on (user_id, tool_id) exists).
        second = repo.upsert("test-user", tool_id, "title2", "v2")
        assert second["content"] == "v2"


class TestGetForUserTool:
    def test_returns_note(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "t", "c")
        fetched = repo.get_for_user_tool("u", tool_id)
        assert fetched is not None
        assert fetched["content"] == "c"

    def test_returns_none_when_missing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.get_for_user_tool("u", tool_id) is None


class TestGetById:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.upsert("u", tool_id, "t", "c")
        fetched = repo.get(created["id"], "u")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "u") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.upsert("u", tool_id, "t", "c")
        assert repo.get(created["id"], "other") is None


class TestDelete:
    def test_deletes_note(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "t", "c")
        deleted = repo.delete("u", tool_id)
        assert deleted is True
        assert repo.get_for_user_tool("u", tool_id) is None

    def test_delete_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        deleted = repo.delete("u", tool_id)
        assert deleted is False
