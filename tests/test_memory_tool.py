"""Unit tests for MemoryTool.

Same approach as ``test_todo_tool.py``: patch ``MemoriesRepository``
with an in-memory fake and replace ``db_session`` / ``db_readonly``
with a no-op context manager.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from application.agents.tools.memory import MemoryTool


class _FakeMemoriesRepo:
    _store: dict[tuple[str, str, str], dict] = {}

    def __init__(self, conn=None) -> None:
        self._conn = conn

    @classmethod
    def reset(cls) -> None:
        cls._store = {}

    def upsert(self, user_id, tool_id, path, content):
        key = (user_id, tool_id, path)
        if key in self._store:
            self._store[key].update({"content": content})
        else:
            self._store[key] = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "tool_id": tool_id,
                "path": path,
                "content": content,
            }
        return self._store[key]

    def get_by_path(self, user_id, tool_id, path):
        return self._store.get((user_id, tool_id, path))

    def list_by_prefix(self, user_id, tool_id, prefix):
        return [
            r for (u, t, p), r in self._store.items()
            if u == user_id and t == tool_id and p.startswith(prefix)
        ]

    def delete_by_path(self, user_id, tool_id, path):
        return 1 if self._store.pop((user_id, tool_id, path), None) else 0

    def delete_by_prefix(self, user_id, tool_id, prefix):
        keys = [
            k for k in self._store
            if k[0] == user_id and k[1] == tool_id and k[2].startswith(prefix)
        ]
        for k in keys:
            del self._store[k]
        return len(keys)

    def delete_all(self, user_id, tool_id):
        keys = [k for k in self._store if k[0] == user_id and k[1] == tool_id]
        for k in keys:
            del self._store[k]
        return len(keys)

    def update_path(self, user_id, tool_id, old_path, new_path):
        row = self._store.pop((user_id, tool_id, old_path), None)
        if row is None:
            return False
        row["path"] = new_path
        self._store[(user_id, tool_id, new_path)] = row
        return True


@contextmanager
def _noop_conn():
    yield None


def _patch(monkeypatch) -> None:
    _FakeMemoriesRepo.reset()
    monkeypatch.setattr(
        "application.agents.tools.memory.MemoriesRepository", _FakeMemoriesRepo
    )
    monkeypatch.setattr(
        "application.agents.tools.memory.db_session", _noop_conn
    )
    monkeypatch.setattr(
        "application.agents.tools.memory.db_readonly", _noop_conn
    )


@pytest.fixture
def memory_tool(monkeypatch):
    _patch(monkeypatch)
    return MemoryTool({"tool_id": str(uuid.uuid4())}, user_id="test_user")


@pytest.mark.unit
def test_init_without_user_id():
    memory_tool = MemoryTool(tool_config={})
    result = memory_tool.execute_action("view", path="/")
    assert "user_id" in result.lower()


@pytest.mark.unit
def test_view_empty_directory(memory_tool):
    result = memory_tool.execute_action("view", path="/")
    assert "empty" in result.lower()


@pytest.mark.unit
def test_create_and_view_file(memory_tool):
    result = memory_tool.execute_action(
        "create", path="/notes.txt", file_text="Hello world"
    )
    assert "created" in result.lower()

    result = memory_tool.execute_action("view", path="/notes.txt")
    assert "Hello world" in result


@pytest.mark.unit
def test_create_overwrite_file(memory_tool):
    memory_tool.execute_action("create", path="/test.txt", file_text="Original content")
    memory_tool.execute_action("create", path="/test.txt", file_text="New content")

    result = memory_tool.execute_action("view", path="/test.txt")
    assert "New content" in result
    assert "Original content" not in result


@pytest.mark.unit
def test_view_directory_with_files(memory_tool):
    memory_tool.execute_action("create", path="/file1.txt", file_text="Content 1")
    memory_tool.execute_action("create", path="/file2.txt", file_text="Content 2")
    memory_tool.execute_action(
        "create", path="/subdir/file3.txt", file_text="Content 3"
    )

    result = memory_tool.execute_action("view", path="/")
    assert "file1.txt" in result
    assert "file2.txt" in result
    assert "subdir/file3.txt" in result


@pytest.mark.unit
def test_view_file_with_line_range(memory_tool):
    content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    memory_tool.execute_action("create", path="/multiline.txt", file_text=content)

    result = memory_tool.execute_action(
        "view", path="/multiline.txt", view_range=[2, 4]
    )
    assert "Line 2" in result
    assert "Line 3" in result
    assert "Line 4" in result
    assert "Line 1" not in result
    assert "Line 5" not in result


@pytest.mark.unit
def test_str_replace(memory_tool):
    memory_tool.execute_action(
        "create", path="/replace.txt", file_text="Hello world, hello universe"
    )

    result = memory_tool.execute_action(
        "str_replace", path="/replace.txt", old_str="hello", new_str="hi"
    )
    assert "updated" in result.lower()

    content = memory_tool.execute_action("view", path="/replace.txt")
    assert "hi world, hi universe" in content


@pytest.mark.unit
def test_str_replace_not_found(memory_tool):
    memory_tool.execute_action("create", path="/test.txt", file_text="Hello world")
    result = memory_tool.execute_action(
        "str_replace", path="/test.txt", old_str="goodbye", new_str="hi"
    )
    assert "not found" in result.lower()


@pytest.mark.unit
def test_insert_line(memory_tool):
    memory_tool.execute_action(
        "create", path="/insert.txt", file_text="Line 1\nLine 2\nLine 3"
    )

    result = memory_tool.execute_action(
        "insert", path="/insert.txt", insert_line=2, insert_text="Inserted line"
    )
    assert "inserted" in result.lower()

    content = memory_tool.execute_action("view", path="/insert.txt")
    lines = content.split("\n")
    assert lines[1] == "Inserted line"
    assert lines[2] == "Line 2"


@pytest.mark.unit
def test_insert_invalid_line(memory_tool):
    memory_tool.execute_action("create", path="/test.txt", file_text="Line 1\nLine 2")
    result = memory_tool.execute_action(
        "insert", path="/test.txt", insert_line=100, insert_text="Text"
    )
    assert "invalid" in result.lower()


@pytest.mark.unit
def test_delete_file(memory_tool):
    memory_tool.execute_action("create", path="/delete_me.txt", file_text="Content")

    result = memory_tool.execute_action("delete", path="/delete_me.txt")
    assert "deleted" in result.lower()

    result = memory_tool.execute_action("view", path="/delete_me.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_delete_nonexistent_file(memory_tool):
    result = memory_tool.execute_action("delete", path="/nonexistent.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_delete_directory(memory_tool):
    memory_tool.execute_action(
        "create", path="/subdir/file1.txt", file_text="Content 1"
    )
    memory_tool.execute_action(
        "create", path="/subdir/file2.txt", file_text="Content 2"
    )

    result = memory_tool.execute_action("delete", path="/subdir/")
    assert "deleted" in result.lower()

    result = memory_tool.execute_action("view", path="/subdir/file1.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_rename_file(memory_tool):
    memory_tool.execute_action("create", path="/old_name.txt", file_text="Content")

    result = memory_tool.execute_action(
        "rename", old_path="/old_name.txt", new_path="/new_name.txt"
    )
    assert "renamed" in result.lower()

    result = memory_tool.execute_action("view", path="/old_name.txt")
    assert "not found" in result.lower()

    result = memory_tool.execute_action("view", path="/new_name.txt")
    assert "Content" in result


@pytest.mark.unit
def test_rename_nonexistent_file(memory_tool):
    result = memory_tool.execute_action(
        "rename", old_path="/nonexistent.txt", new_path="/new.txt"
    )
    assert "not found" in result.lower()


@pytest.mark.unit
def test_rename_to_existing_file(memory_tool):
    memory_tool.execute_action("create", path="/file1.txt", file_text="Content 1")
    memory_tool.execute_action("create", path="/file2.txt", file_text="Content 2")

    result = memory_tool.execute_action(
        "rename", old_path="/file1.txt", new_path="/file2.txt"
    )
    assert "already exists" in result.lower()


@pytest.mark.unit
def test_path_traversal_protection(memory_tool):
    invalid_paths = [
        "/../secrets.txt",
        "/../../etc/passwd",
        "..//file.txt",
        "/subdir/../../outside.txt",
    ]

    for path in invalid_paths:
        result = memory_tool.execute_action(
            "create", path=path, file_text="malicious content"
        )
        assert "invalid path" in result.lower()


@pytest.mark.unit
def test_paths_auto_prepend_slash(memory_tool):
    valid_paths = [
        "etc/passwd",
        "home/user/file.txt",
        "file.txt",
    ]
    for path in valid_paths:
        result = memory_tool.execute_action("create", path=path, file_text="content")
        assert "created" in result.lower()

        view_result = memory_tool.execute_action("view", path=path)
        assert "content" in view_result


@pytest.mark.unit
def test_cannot_create_directory_as_file(memory_tool):
    result = memory_tool.execute_action("create", path="/", file_text="content")
    assert "cannot create a file at directory path" in result.lower()


@pytest.mark.unit
def test_get_actions_metadata(memory_tool):
    metadata = memory_tool.get_actions_metadata()

    action_names = [action["name"] for action in metadata]
    assert "view" in action_names
    assert "create" in action_names
    assert "str_replace" in action_names
    assert "insert" in action_names
    assert "delete" in action_names
    assert "rename" in action_names

    for action in metadata:
        assert "name" in action
        assert "description" in action
        assert "parameters" in action


@pytest.mark.unit
def test_memory_tool_isolation(monkeypatch):
    _patch(monkeypatch)
    tool1 = MemoryTool({"tool_id": str(uuid.uuid4())}, user_id="test_user")
    tool2 = MemoryTool({"tool_id": str(uuid.uuid4())}, user_id="test_user")

    tool1.execute_action("create", path="/file.txt", file_text="Content from tool 1")
    tool2.execute_action("create", path="/file.txt", file_text="Content from tool 2")

    result1 = tool1.execute_action("view", path="/file.txt")
    result2 = tool2.execute_action("view", path="/file.txt")

    assert "Content from tool 1" in result1
    assert "Content from tool 2" not in result1
    assert "Content from tool 2" in result2
    assert "Content from tool 1" not in result2


@pytest.mark.unit
def test_memory_tool_auto_generates_default_tool_id():
    tool1 = MemoryTool({}, user_id="test_user")
    tool2 = MemoryTool({}, user_id="test_user")
    assert tool1.tool_id == "default_test_user"
    assert tool2.tool_id == "default_test_user"

    tool3 = MemoryTool({}, user_id="another_user")
    assert tool3.tool_id == "default_another_user"
    assert tool3.tool_id != tool1.tool_id


@pytest.mark.unit
def test_sentinel_tool_id_short_circuits():
    """A ``default_{user_id}`` tool_id must no-op with a polite error."""
    tool = MemoryTool({}, user_id="test_user")
    result = tool.execute_action("view", path="/")
    assert "Error" in result
    assert "not configured" in result.lower() or "unavailable" in result.lower()


@pytest.mark.unit
def test_paths_without_leading_slash(memory_tool):
    result = memory_tool.execute_action(
        "create",
        path="cat_breeds.txt",
        file_text="- Korat\n- Chartreux\n- British Shorthair\n- Nebelung",
    )
    assert "created" in result.lower()

    view_result = memory_tool.execute_action("view", path="cat_breeds.txt")
    assert "Korat" in view_result

    view_result2 = memory_tool.execute_action("view", path="/cat_breeds.txt")
    assert "Korat" in view_result2

    replace_result = memory_tool.execute_action(
        "str_replace", path="cat_breeds.txt", old_str="Korat", new_str="Maine Coon"
    )
    assert "updated" in replace_result.lower()

    nested_result = memory_tool.execute_action(
        "create", path="projects/tasks.txt", file_text="Task 1\nTask 2"
    )
    assert "created" in nested_result.lower()

    view_nested = memory_tool.execute_action("view", path="projects/tasks.txt")
    assert "Task 1" in view_nested


@pytest.mark.unit
def test_rename_directory(memory_tool):
    memory_tool.execute_action("create", path="/docs/file1.txt", file_text="Content 1")
    memory_tool.execute_action(
        "create", path="/docs/sub/file2.txt", file_text="Content 2"
    )

    result = memory_tool.execute_action(
        "rename", old_path="/docs/", new_path="/archive/"
    )
    assert "renamed" in result.lower()
    assert "2 files" in result.lower()

    result = memory_tool.execute_action("view", path="/docs/file1.txt")
    assert "not found" in result.lower()

    result = memory_tool.execute_action("view", path="/archive/file1.txt")
    assert "Content 1" in result

    result = memory_tool.execute_action("view", path="/archive/sub/file2.txt")
    assert "Content 2" in result


@pytest.mark.unit
def test_rename_directory_without_trailing_slash(memory_tool):
    memory_tool.execute_action("create", path="/docs/file1.txt", file_text="Content 1")
    memory_tool.execute_action(
        "create", path="/docs/sub/file2.txt", file_text="Content 2"
    )

    result = memory_tool.execute_action(
        "rename", old_path="/docs/", new_path="/archive"
    )
    assert "renamed" in result.lower()

    result = memory_tool.execute_action("view", path="/archive/file1.txt")
    assert "Content 1" in result

    result = memory_tool.execute_action("view", path="/archive/sub/file2.txt")
    assert "Content 2" in result

    result = memory_tool.execute_action("view", path="/archivesub/file2.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_view_file_line_numbers(memory_tool):
    content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    memory_tool.execute_action("create", path="/numbered.txt", file_text=content)

    result = memory_tool.execute_action("view", path="/numbered.txt", view_range=[2, 4])

    assert "2: Line 2" in result
    assert "3: Line 3" in result
    assert "4: Line 4" in result
    assert "1: Line 1" not in result
    assert "5: Line 5" not in result
