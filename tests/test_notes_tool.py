"""Unit tests for NotesTool.

Same approach as ``test_todo_tool.py``: patch ``NotesRepository`` with
an in-memory fake and replace ``db_session`` / ``db_readonly`` with a
no-op context manager.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from application.agents.tools.notes import NotesTool


class _FakeNotesRepo:
    _store: dict[tuple[str, str], dict] = {}

    def __init__(self, conn=None) -> None:
        self._conn = conn

    @classmethod
    def reset(cls) -> None:
        cls._store = {}

    def upsert(self, user_id, tool_id, title, content):
        key = (user_id, tool_id)
        if key in self._store:
            self._store[key].update({"title": title, "content": content})
        else:
            self._store[key] = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "tool_id": tool_id,
                "title": title,
                "content": content,
            }
        return self._store[key]

    def get_for_user_tool(self, user_id, tool_id):
        return self._store.get((user_id, tool_id))

    def delete(self, user_id, tool_id):
        return self._store.pop((user_id, tool_id), None) is not None


@contextmanager
def _noop_conn():
    yield None


@pytest.fixture
def notes_tool(monkeypatch):
    _FakeNotesRepo.reset()
    monkeypatch.setattr(
        "application.agents.tools.notes.NotesRepository", _FakeNotesRepo
    )
    monkeypatch.setattr(
        "application.agents.tools.notes.db_session", _noop_conn
    )
    monkeypatch.setattr(
        "application.agents.tools.notes.db_readonly", _noop_conn
    )
    return NotesTool({"tool_id": str(uuid.uuid4())}, user_id="test_user")


@pytest.mark.unit
def test_overwrite_and_view(notes_tool):
    assert "saved" in notes_tool.execute_action("overwrite", text="first").lower()
    assert "first" in notes_tool.execute_action("view")

    assert "saved" in notes_tool.execute_action("overwrite", text="second").lower()
    assert "second" in notes_tool.execute_action("view")


@pytest.mark.unit
def test_delete_note(notes_tool):
    notes_tool.execute_action("overwrite", text="hello")
    assert "deleted" in notes_tool.execute_action("delete").lower()
    assert "no note" in notes_tool.execute_action("view").lower()


@pytest.mark.unit
def test_view_not_found(notes_tool):
    result = notes_tool.execute_action("view")
    assert "no note found" in result.lower()


@pytest.mark.unit
def test_str_replace(notes_tool):
    notes_tool.execute_action("overwrite", text="Hello world, hello universe")
    result = notes_tool.execute_action("str_replace", old_str="hello", new_str="hi")
    assert "updated" in result.lower()

    note = notes_tool.execute_action("view")
    assert "hi world, hi universe" in note.lower()


@pytest.mark.unit
def test_str_replace_not_found(notes_tool):
    notes_tool.execute_action("overwrite", text="Hello world")
    result = notes_tool.execute_action("str_replace", old_str="goodbye", new_str="hi")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_insert_line(notes_tool):
    notes_tool.execute_action("overwrite", text="Line 1\nLine 2\nLine 3")
    result = notes_tool.execute_action("insert", line_number=2, text="Inserted line")
    assert "inserted" in result.lower()

    note = notes_tool.execute_action("view")
    lines = note.split("\n")
    assert lines[1] == "Inserted line"
    assert lines[2] == "Line 2"


@pytest.mark.unit
def test_delete_nonexistent_note(notes_tool):
    result = notes_tool.execute_action("delete")
    assert "no note found" in result.lower()


@pytest.mark.unit
def test_isolation_per_tool_id(monkeypatch):
    _FakeNotesRepo.reset()
    monkeypatch.setattr(
        "application.agents.tools.notes.NotesRepository", _FakeNotesRepo
    )
    monkeypatch.setattr(
        "application.agents.tools.notes.db_session", _noop_conn
    )
    monkeypatch.setattr(
        "application.agents.tools.notes.db_readonly", _noop_conn
    )

    tool1 = NotesTool({"tool_id": str(uuid.uuid4())}, user_id="test_user")
    tool2 = NotesTool({"tool_id": str(uuid.uuid4())}, user_id="test_user")

    tool1.execute_action("overwrite", text="Content from tool 1")
    tool2.execute_action("overwrite", text="Content from tool 2")

    assert "Content from tool 1" in tool1.execute_action("view")
    assert "Content from tool 2" not in tool1.execute_action("view")

    assert "Content from tool 2" in tool2.execute_action("view")
    assert "Content from tool 1" not in tool2.execute_action("view")


@pytest.mark.unit
def test_init_without_user_id():
    """Should fail gracefully if no user_id is provided."""
    notes_tool = NotesTool(tool_config={})
    result = notes_tool.execute_action("view")
    assert "user_id" in str(result).lower()


@pytest.mark.unit
def test_sentinel_tool_id_short_circuits():
    """A ``default_{user_id}`` tool_id must no-op with a polite error."""
    tool = NotesTool({}, user_id="test_user")
    assert tool.tool_id == "default_test_user"
    result = tool.execute_action("view")
    assert "Error" in result
    assert "not configured" in result.lower() or "unavailable" in result.lower()


@pytest.mark.unit
def test_notes_tool_auto_generates_default_tool_id():
    """Without ``tool_id``, tool_id defaults to ``default_{user_id}``."""
    tool1 = NotesTool({}, user_id="test_user")
    tool2 = NotesTool({}, user_id="test_user")
    assert tool1.tool_id == "default_test_user"
    assert tool2.tool_id == "default_test_user"

    tool3 = NotesTool({}, user_id="another_user")
    assert tool3.tool_id == "default_another_user"
    assert tool3.tool_id != tool1.tool_id
