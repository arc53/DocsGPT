"""Tests for TodosRepository against a real Postgres instance.

Todos have a FK to user_tools, so each test creates a tool row first.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from application.storage.db.repositories.todos import TodosRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> TodosRepository:
    return TodosRepository(conn)


def _make_tool(conn, user_id: str = "test-user", name: str = "todo-tool") -> str:
    """Insert a user_tools row and return its UUID as a string."""
    return str(
        conn.execute(
            text("INSERT INTO user_tools (user_id, name) VALUES (:uid, :name) RETURNING id"),
            {"uid": user_id, "name": name},
        ).scalar()
    )


class TestCreate:
    def test_creates_todo(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        doc = repo.create("test-user", tool_id, "Buy milk")
        assert doc["title"] == "Buy milk"
        assert doc["completed"] is False
        assert doc["id"] is not None

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        doc = repo.create("test-user", tool_id, "t")
        assert doc["_id"] == doc["id"]


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000") is None


class TestListForUserTool:
    def test_lists_todos_for_user_tool(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.create("u", tool_id, "t1")
        repo.create("u", tool_id, "t2")
        results = repo.list_for_user_tool("u", tool_id)
        assert len(results) == 2

    def test_different_tools_are_isolated(self, pg_conn):
        repo = _repo(pg_conn)
        tool_a = _make_tool(pg_conn, name="tool-a")
        tool_b = _make_tool(pg_conn, name="tool-b")
        repo.create("u", tool_a, "a-todo")
        repo.create("u", tool_b, "b-todo")
        assert len(repo.list_for_user_tool("u", tool_a)) == 1
        assert len(repo.list_for_user_tool("u", tool_b)) == 1


class TestUpdateTitle:
    def test_updates_title(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "old")
        updated = repo.update_title(created["id"], "new")
        assert updated is True
        fetched = repo.get(created["id"])
        assert fetched["title"] == "new"

    def test_update_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.update_title("00000000-0000-0000-0000-000000000000", "x") is False


class TestSetCompleted:
    def test_marks_completed(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        repo.set_completed(created["id"], True)
        fetched = repo.get(created["id"])
        assert fetched["completed"] is True

    def test_unmarks_completed(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        repo.set_completed(created["id"], True)
        repo.set_completed(created["id"], False)
        fetched = repo.get(created["id"])
        assert fetched["completed"] is False


class TestDelete:
    def test_deletes_todo(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        deleted = repo.delete(created["id"])
        assert deleted is True
        assert repo.get(created["id"]) is None

    def test_delete_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.delete("00000000-0000-0000-0000-000000000000") is False
