"""Unit tests for TodoListTool.

These tests replace the old Mongo-coupled suite. They work by:

* Patching ``TodosRepository`` inside the tool module with a small
  in-memory fake that implements only the methods the tool calls.
* Patching ``db_session`` / ``db_readonly`` inside the tool module with
  a no-op context manager so the tool never tries to open a real
  connection.
* Exercising the tool with a real UUID ``tool_id`` so ``_pg_enabled()``
  returns True, plus a sentinel ``default_{uid}`` case so the short-
  circuit path is covered too.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from application.agents.tools.todo_list import TodoListTool


class _FakeTodosRepo:
    """In-memory stand-in for ``TodosRepository``.

    Implements only the methods called by ``TodoListTool``. Shared state
    lives on the class so multiple instances (one per ``with`` block)
    see the same data, mirroring a real DB.
    """

    _store: list[dict] = []
    _next_ids: dict[str, int] = {}

    def __init__(self, conn=None) -> None:
        self._conn = conn

    @classmethod
    def reset(cls) -> None:
        cls._store = []
        cls._next_ids = {}

    def create(self, user_id, tool_id, title, *, todo_id=None, legacy_mongo_id=None):
        if todo_id is None:
            todo_id = self._next_ids.get(tool_id, 0) + 1
        self._next_ids[tool_id] = max(self._next_ids.get(tool_id, 0), todo_id)
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "tool_id": tool_id,
            "todo_id": todo_id,
            "title": title,
            "completed": False,
            "legacy_mongo_id": legacy_mongo_id,
        }
        self._store.append(row)
        return row

    def list_for_tool(self, user_id, tool_id):
        return [
            r for r in self._store
            if r["user_id"] == user_id and r["tool_id"] == tool_id
        ]

    def get_by_tool_and_todo_id(self, user_id, tool_id, todo_id):
        for r in self._store:
            if (r["user_id"] == user_id
                    and r["tool_id"] == tool_id
                    and r["todo_id"] == todo_id):
                return r
        return None

    def update_title_by_tool_and_todo_id(self, user_id, tool_id, todo_id, title):
        row = self.get_by_tool_and_todo_id(user_id, tool_id, todo_id)
        if row is None:
            return False
        row["title"] = title
        return True

    def set_completed(self, user_id, tool_id, todo_id, completed):
        row = self.get_by_tool_and_todo_id(user_id, tool_id, todo_id)
        if row is None:
            return False
        row["completed"] = bool(completed)
        return True

    def delete_by_tool_and_todo_id(self, user_id, tool_id, todo_id):
        for idx, r in enumerate(self._store):
            if (r["user_id"] == user_id
                    and r["tool_id"] == tool_id
                    and r["todo_id"] == todo_id):
                self._store.pop(idx)
                return True
        return False


@contextmanager
def _noop_conn():
    yield None


@pytest.fixture
def todo_tool(monkeypatch):
    """Return a ``TodoListTool`` wired to the in-memory fake repo."""
    _FakeTodosRepo.reset()
    monkeypatch.setattr(
        "application.agents.tools.todo_list.TodosRepository", _FakeTodosRepo
    )
    monkeypatch.setattr(
        "application.agents.tools.todo_list.db_session", _noop_conn
    )
    monkeypatch.setattr(
        "application.agents.tools.todo_list.db_readonly", _noop_conn
    )
    # Real UUID so ``_pg_enabled()`` returns True.
    return TodoListTool({"tool_id": str(uuid.uuid4())}, user_id="test_user")


def test_create_and_get(todo_tool):
    res = todo_tool.execute_action("create", title="Write tests")
    assert "Todo created with ID" in res
    todo_id = res.split("ID ")[1].split(":")[0].strip()

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "Error" not in get_res
    assert "Write tests" in get_res


def test_get_all_todos(todo_tool):
    todo_tool.execute_action("create", title="Task 1")
    todo_tool.execute_action("create", title="Task 2")

    list_res = todo_tool.execute_action("list")
    assert "Task 1" in list_res
    assert "Task 2" in list_res


def test_update_todo(todo_tool):
    create_res = todo_tool.execute_action("create", title="Initial Title")
    todo_id = create_res.split("ID ")[1].split(":")[0].strip()

    update_res = todo_tool.execute_action("update", todo_id=todo_id, title="Updated Title")
    assert "updated" in update_res.lower()
    assert "Updated Title" in update_res

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "Updated Title" in get_res


def test_complete_todo(todo_tool):
    create_res = todo_tool.execute_action("create", title="To Complete")
    todo_id = create_res.split("ID ")[1].split(":")[0].strip()

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "open" in get_res

    complete_res = todo_tool.execute_action("complete", todo_id=todo_id)
    assert "completed" in complete_res.lower()

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "completed" in get_res


def test_delete_todo(todo_tool):
    create_res = todo_tool.execute_action("create", title="To Delete")
    todo_id = create_res.split("ID ")[1].split(":")[0].strip()

    delete_res = todo_tool.execute_action("delete", todo_id=todo_id)
    assert "deleted" in delete_res.lower()

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "Error" in get_res
    assert "not found" in get_res


def test_isolation_per_tool_id(monkeypatch):
    """Todos created under one tool_id are not visible to another tool_id."""
    _FakeTodosRepo.reset()
    monkeypatch.setattr(
        "application.agents.tools.todo_list.TodosRepository", _FakeTodosRepo
    )
    monkeypatch.setattr(
        "application.agents.tools.todo_list.db_session", _noop_conn
    )
    monkeypatch.setattr(
        "application.agents.tools.todo_list.db_readonly", _noop_conn
    )

    tool1 = TodoListTool({"tool_id": str(uuid.uuid4())}, user_id="u1")
    tool2 = TodoListTool({"tool_id": str(uuid.uuid4())}, user_id="u1")

    r1 = tool1.execute_action("create", title="from tool 1")
    tool2.execute_action("create", title="from tool 2")

    todo_id_1 = r1.split("ID ")[1].split(":")[0].strip()

    # tool2 cannot see tool1's todo even though same user_id + same todo_id=1.
    res = tool2.execute_action("get", todo_id=todo_id_1)
    # tool2 has its own todo_id=1 ("from tool 2"), so the right thing to
    # verify is isolation: tool1's title does not leak into tool2's view.
    assert "from tool 1" not in res


def test_sentinel_tool_id_short_circuits():
    """A ``default_{user_id}`` tool_id must no-op with a polite error."""
    tool = TodoListTool({}, user_id="default_user")
    assert tool.tool_id == "default_default_user"

    res = tool.execute_action("create", title="shared default")
    assert "Error" in res
    assert "not configured" in res.lower() or "unavailable" in res.lower()


def test_no_user_id_returns_error():
    tool = TodoListTool({"tool_id": str(uuid.uuid4())}, user_id=None)
    res = tool.execute_action("list")
    assert "Error" in res
    assert "user_id" in res
