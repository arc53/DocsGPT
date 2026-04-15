"""Tests for TodosRepository against a real Postgres instance.

Todos have a FK to user_tools, so each test creates a tool row first.
"""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.todos import TodosRepository


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
        fetched = repo.get(created["id"], "u")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "u") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        assert repo.get(created["id"], "other") is None


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
        updated = repo.update_title(created["id"], "u", "new")
        assert updated is True
        fetched = repo.get(created["id"], "u")
        assert fetched["title"] == "new"

    def test_update_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.update_title("00000000-0000-0000-0000-000000000000", "u", "x") is False

    def test_update_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "old")
        updated = repo.update_title(created["id"], "other", "new")
        assert updated is False
        fetched = repo.get(created["id"], "u")
        assert fetched["title"] == "old"


class TestSetCompleted:
    def test_marks_completed(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        repo.set_completed(created["id"], "u", True)
        fetched = repo.get(created["id"], "u")
        assert fetched["completed"] is True

    def test_unmarks_completed(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        repo.set_completed(created["id"], "u", True)
        repo.set_completed(created["id"], "u", False)
        fetched = repo.get(created["id"], "u")
        assert fetched["completed"] is False

    def test_set_completed_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        result = repo.set_completed(created["id"], "other", True)
        assert result is False
        fetched = repo.get(created["id"], "u")
        assert fetched["completed"] is False


class TestDelete:
    def test_deletes_todo(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        deleted = repo.delete(created["id"], "u")
        assert deleted is True
        assert repo.get(created["id"], "u") is None

    def test_delete_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.delete("00000000-0000-0000-0000-000000000000", "u") is False

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        deleted = repo.delete(created["id"], "other")
        assert deleted is False
        assert repo.get(created["id"], "u") is not None


class TestTodoIdAllocation:
    def test_create_allocates_sequential_todo_id(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        a = repo.create("u", tool_id, "first")
        b = repo.create("u", tool_id, "second")
        c = repo.create("u", tool_id, "third")
        assert a["todo_id"] == 1
        assert b["todo_id"] == 2
        assert c["todo_id"] == 3

    def test_create_respects_explicit_todo_id(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        doc = repo.create("u", tool_id, "explicit", todo_id=42)
        assert doc["todo_id"] == 42
        # Subsequent auto-allocation continues from MAX
        nxt = repo.create("u", tool_id, "auto")
        assert nxt["todo_id"] == 43

    def test_todo_id_unique_per_tool(self, pg_conn):
        """The partial unique index allows the same todo_id across tools."""
        repo = _repo(pg_conn)
        tool_a = _make_tool(pg_conn, name="t-a")
        tool_b = _make_tool(pg_conn, name="t-b")
        a = repo.create("u", tool_a, "x")
        b = repo.create("u", tool_b, "y")
        assert a["todo_id"] == 1
        assert b["todo_id"] == 1


class TestListForTool:
    def test_orders_by_todo_id(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.create("u", tool_id, "second", todo_id=2)
        repo.create("u", tool_id, "first", todo_id=1)
        repo.create("u", tool_id, "third", todo_id=3)
        rows = repo.list_for_tool("u", tool_id)
        assert [r["todo_id"] for r in rows] == [1, 2, 3]


class TestGetByToolAndTodoId:
    def test_returns_matching_row(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.create("u", tool_id, "hello", todo_id=7)
        fetched = repo.get_by_tool_and_todo_id("u", tool_id, 7)
        assert fetched is not None
        assert fetched["title"] == "hello"

    def test_returns_none_when_missing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.get_by_tool_and_todo_id("u", tool_id, 99) is None


class TestSetCompletedByToolAndTodoId:
    def test_marks_completed(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        ok = repo.set_completed("u", tool_id, created["todo_id"], True)
        assert ok is True
        fetched = repo.get_by_tool_and_todo_id("u", tool_id, created["todo_id"])
        assert fetched["completed"] is True

    def test_unmarks_completed(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        repo.set_completed("u", tool_id, created["todo_id"], True)
        repo.set_completed("u", tool_id, created["todo_id"], False)
        fetched = repo.get_by_tool_and_todo_id("u", tool_id, created["todo_id"])
        assert fetched["completed"] is False

    def test_returns_false_for_missing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.set_completed("u", tool_id, 99, True) is False


class TestDeleteByToolAndTodoId:
    def test_deletes(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t")
        ok = repo.delete_by_tool_and_todo_id("u", tool_id, created["todo_id"])
        assert ok is True
        assert repo.get_by_tool_and_todo_id("u", tool_id, created["todo_id"]) is None

    def test_returns_false_for_missing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.delete_by_tool_and_todo_id("u", tool_id, 99) is False


class TestLegacyMongoIdLookup:
    def test_get_and_update_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        created = repo.create("u", tool_id, "t", legacy_mongo_id="abc123")
        fetched = repo.get_by_legacy_id("abc123")
        assert fetched["id"] == created["id"]

        ok = repo.update_by_legacy_id("abc123", title="renamed", completed=True)
        assert ok is True
        again = repo.get_by_legacy_id("abc123")
        assert again["title"] == "renamed"
        assert again["completed"] is True

    def test_get_by_legacy_id_missing(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get_by_legacy_id("nope") is None
