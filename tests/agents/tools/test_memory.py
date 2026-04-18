"""Comprehensive tests for application/agents/tools/memory.py

Covers: MemoryTool initialization, path validation, all actions
(view, create, str_replace, insert, delete, rename), directory operations,
error handling, and metadata.

Replaces an older mongomock-based suite. The fake repository mirrors the
methods the tool calls; ``db_session`` / ``db_readonly`` are stubbed with
a no-op context manager so no real connection is opened.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest


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


@pytest.fixture
def patched_memory(monkeypatch):
    """Patch the memory tool to use the in-memory fake repo."""
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
def memory_tool(patched_memory):
    from application.agents.tools.memory import MemoryTool
    # Real UUID so ``_pg_enabled()`` returns True.
    return MemoryTool(
        tool_config={"tool_id": str(uuid.uuid4())},
        user_id="test_user",
    )


# =====================================================================
# Initialization
# =====================================================================


@pytest.mark.unit
class TestMemoryToolInit:

    def test_init_with_config(self, patched_memory):
        from application.agents.tools.memory import MemoryTool

        tid = str(uuid.uuid4())
        tool = MemoryTool(tool_config={"tool_id": tid}, user_id="user1")
        assert tool.tool_id == tid
        assert tool.user_id == "user1"

    def test_init_fallback_to_user_id(self, patched_memory):
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool(tool_config={}, user_id="user1")
        assert tool.tool_id == "default_user1"

    def test_init_no_user_no_config(self, patched_memory):
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool()
        assert tool.tool_id is not None  # UUID fallback
        assert tool.user_id is None


# =====================================================================
# Path Validation
# =====================================================================


@pytest.mark.unit
class TestPathValidation:

    def test_valid_path(self, memory_tool):
        assert memory_tool._validate_path("/notes.txt") == "/notes.txt"

    def test_adds_leading_slash(self, memory_tool):
        assert memory_tool._validate_path("notes.txt") == "/notes.txt"

    def test_empty_path_returns_none(self, memory_tool):
        assert memory_tool._validate_path("") is None

    def test_double_dots_rejected(self, memory_tool):
        assert memory_tool._validate_path("/../../etc/passwd") is None

    def test_double_slash_rejected(self, memory_tool):
        assert memory_tool._validate_path("//path") is None

    def test_preserves_trailing_slash(self, memory_tool):
        result = memory_tool._validate_path("/project/")
        assert result.endswith("/")

    def test_root_path(self, memory_tool):
        assert memory_tool._validate_path("/") == "/"

    def test_whitespace_stripped(self, memory_tool):
        result = memory_tool._validate_path("  /notes.txt  ")
        assert result == "/notes.txt"


# =====================================================================
# Execute Action - No User
# =====================================================================


@pytest.mark.unit
class TestNoUser:

    def test_requires_user_id(self, patched_memory):
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool(tool_config={"tool_id": str(uuid.uuid4())}, user_id=None)
        result = tool.execute_action("view", path="/")
        assert "Error" in result
        assert "user_id" in result

    def test_unknown_action(self, memory_tool):
        result = memory_tool.execute_action("fly")
        assert "Unknown action" in result


# =====================================================================
# View Action
# =====================================================================


@pytest.mark.unit
class TestViewAction:

    def test_view_empty_directory(self, memory_tool):
        result = memory_tool.execute_action("view", path="/")
        assert "Directory: /" in result
        assert "(empty)" in result

    def test_view_directory_with_files(self, memory_tool):
        memory_tool.execute_action("create", path="/notes.txt", file_text="content")
        memory_tool.execute_action("create", path="/todo.txt", file_text="tasks")

        result = memory_tool.execute_action("view", path="/")
        assert "notes.txt" in result
        assert "todo.txt" in result

    def test_view_file_content(self, memory_tool):
        memory_tool.execute_action("create", path="/hello.txt", file_text="Hello World")
        result = memory_tool.execute_action("view", path="/hello.txt")
        assert "Hello World" in result

    def test_view_nonexistent_file(self, memory_tool):
        result = memory_tool.execute_action("view", path="/missing.txt")
        assert "Error" in result
        assert "not found" in result.lower()

    def test_view_file_with_range(self, memory_tool):
        memory_tool.execute_action(
            "create", path="/lines.txt", file_text="line1\nline2\nline3\nline4"
        )
        result = memory_tool.execute_action(
            "view", path="/lines.txt", view_range=[2, 3]
        )
        assert "line2" in result
        assert "line3" in result

    def test_view_file_range_out_of_bounds(self, memory_tool):
        memory_tool.execute_action("create", path="/short.txt", file_text="only")
        result = memory_tool.execute_action(
            "view", path="/short.txt", view_range=[100, 200]
        )
        assert "out of bounds" in result.lower()

    def test_view_invalid_path(self, memory_tool):
        result = memory_tool.execute_action("view", path="")
        assert "Error" in result

    def test_view_subdirectory(self, memory_tool):
        memory_tool.execute_action(
            "create", path="/project/src/main.py", file_text="code"
        )
        result = memory_tool.execute_action("view", path="/project/")
        assert "src/main.py" in result


# =====================================================================
# Create Action
# =====================================================================


@pytest.mark.unit
class TestCreateAction:

    def test_create_file(self, memory_tool):
        result = memory_tool.execute_action(
            "create", path="/test.txt", file_text="content"
        )
        assert "File created" in result

        content = memory_tool.execute_action("view", path="/test.txt")
        assert "content" in content

    def test_overwrite_file(self, memory_tool):
        memory_tool.execute_action("create", path="/test.txt", file_text="old")
        memory_tool.execute_action("create", path="/test.txt", file_text="new")

        content = memory_tool.execute_action("view", path="/test.txt")
        assert "new" in content

    def test_create_at_directory_path(self, memory_tool):
        result = memory_tool.execute_action("create", path="/dir/", file_text="text")
        assert "Error" in result
        assert "directory path" in result.lower()

    def test_create_invalid_path(self, memory_tool):
        result = memory_tool.execute_action("create", path="", file_text="text")
        assert "Error" in result

    def test_create_nested_path(self, memory_tool):
        result = memory_tool.execute_action(
            "create", path="/a/b/c/file.txt", file_text="deep"
        )
        assert "File created" in result


# =====================================================================
# String Replace Action
# =====================================================================


@pytest.mark.unit
class TestStrReplaceAction:

    def test_replace_text(self, memory_tool):
        memory_tool.execute_action(
            "create", path="/doc.txt", file_text="Hello World"
        )
        result = memory_tool.execute_action(
            "str_replace", path="/doc.txt", old_str="Hello", new_str="Hi"
        )
        assert "File updated" in result

        content = memory_tool.execute_action("view", path="/doc.txt")
        assert "Hi World" in content

    def test_replace_not_found(self, memory_tool):
        memory_tool.execute_action("create", path="/doc.txt", file_text="Hello")
        result = memory_tool.execute_action(
            "str_replace", path="/doc.txt", old_str="Missing", new_str="X"
        )
        assert "not found" in result.lower()

    def test_replace_empty_old_str(self, memory_tool):
        memory_tool.execute_action("create", path="/doc.txt", file_text="Hello")
        result = memory_tool.execute_action(
            "str_replace", path="/doc.txt", old_str="", new_str="X"
        )
        assert "Error" in result

    def test_replace_file_not_found(self, memory_tool):
        result = memory_tool.execute_action(
            "str_replace", path="/missing.txt", old_str="a", new_str="b"
        )
        assert "not found" in result.lower()

    def test_replace_case_insensitive(self, memory_tool):
        memory_tool.execute_action(
            "create", path="/doc.txt", file_text="Hello World"
        )
        result = memory_tool.execute_action(
            "str_replace", path="/doc.txt", old_str="hello", new_str="Hi"
        )
        assert "File updated" in result


# =====================================================================
# Insert Action
# =====================================================================


@pytest.mark.unit
class TestInsertAction:

    def test_insert_text(self, memory_tool):
        memory_tool.execute_action(
            "create", path="/doc.txt", file_text="line1\nline2"
        )
        result = memory_tool.execute_action(
            "insert", path="/doc.txt", insert_line=2, insert_text="inserted"
        )
        assert "inserted" in result.lower()

        content = memory_tool.execute_action("view", path="/doc.txt")
        assert "inserted" in content

    def test_insert_empty_text(self, memory_tool):
        memory_tool.execute_action("create", path="/doc.txt", file_text="line1")
        result = memory_tool.execute_action(
            "insert", path="/doc.txt", insert_line=1, insert_text=""
        )
        assert "Error" in result

    def test_insert_file_not_found(self, memory_tool):
        result = memory_tool.execute_action(
            "insert", path="/missing.txt", insert_line=1, insert_text="text"
        )
        assert "not found" in result.lower()

    def test_insert_invalid_line_number(self, memory_tool):
        memory_tool.execute_action("create", path="/doc.txt", file_text="line1")
        result = memory_tool.execute_action(
            "insert", path="/doc.txt", insert_line=-5, insert_text="text"
        )
        assert "Error" in result


# =====================================================================
# Delete Action
# =====================================================================


@pytest.mark.unit
class TestDeleteAction:

    def test_delete_file(self, memory_tool):
        memory_tool.execute_action("create", path="/test.txt", file_text="data")
        result = memory_tool.execute_action("delete", path="/test.txt")
        assert "Deleted" in result

        content = memory_tool.execute_action("view", path="/test.txt")
        assert "not found" in content.lower()

    def test_delete_nonexistent_file(self, memory_tool):
        result = memory_tool.execute_action("delete", path="/missing.txt")
        assert "not found" in result.lower()

    def test_delete_root_clears_all(self, memory_tool):
        memory_tool.execute_action("create", path="/a.txt", file_text="a")
        memory_tool.execute_action("create", path="/b.txt", file_text="b")

        result = memory_tool.execute_action("delete", path="/")
        assert "Deleted" in result
        assert "2" in result

    def test_delete_directory(self, memory_tool):
        memory_tool.execute_action("create", path="/dir/f1.txt", file_text="1")
        memory_tool.execute_action("create", path="/dir/f2.txt", file_text="2")

        result = memory_tool.execute_action("delete", path="/dir/")
        assert "Deleted" in result

    def test_delete_directory_without_trailing_slash(self, memory_tool):
        memory_tool.execute_action("create", path="/dir/f1.txt", file_text="1")

        result = memory_tool.execute_action("delete", path="/dir")
        assert "Deleted" in result

    def test_delete_invalid_path(self, memory_tool):
        result = memory_tool.execute_action("delete", path="")
        assert "Error" in result


# =====================================================================
# Rename Action
# =====================================================================


@pytest.mark.unit
class TestRenameAction:

    def test_rename_file(self, memory_tool):
        memory_tool.execute_action("create", path="/old.txt", file_text="data")
        result = memory_tool.execute_action(
            "rename", old_path="/old.txt", new_path="/new.txt"
        )
        assert "Renamed" in result

        content = memory_tool.execute_action("view", path="/new.txt")
        assert "data" in content

    def test_rename_file_not_found(self, memory_tool):
        result = memory_tool.execute_action(
            "rename", old_path="/missing.txt", new_path="/new.txt"
        )
        assert "not found" in result.lower()

    def test_rename_target_exists(self, memory_tool):
        memory_tool.execute_action("create", path="/a.txt", file_text="a")
        memory_tool.execute_action("create", path="/b.txt", file_text="b")

        result = memory_tool.execute_action(
            "rename", old_path="/a.txt", new_path="/b.txt"
        )
        assert "already exists" in result.lower()

    def test_rename_root_rejected(self, memory_tool):
        result = memory_tool.execute_action(
            "rename", old_path="/", new_path="/new/"
        )
        assert "Cannot rename root" in result

    def test_rename_directory(self, memory_tool):
        memory_tool.execute_action("create", path="/old/f.txt", file_text="data")
        result = memory_tool.execute_action(
            "rename", old_path="/old/", new_path="/new/"
        )
        assert "Renamed" in result

        content = memory_tool.execute_action("view", path="/new/f.txt")
        assert "data" in content

    def test_rename_directory_not_found(self, memory_tool):
        result = memory_tool.execute_action(
            "rename", old_path="/missing/", new_path="/new/"
        )
        assert "not found" in result.lower()

    def test_rename_invalid_path(self, memory_tool):
        result = memory_tool.execute_action(
            "rename", old_path="", new_path="/new.txt"
        )
        assert "Error" in result


# =====================================================================
# Metadata
# =====================================================================


@pytest.mark.unit
class TestMemoryToolMetadata:

    def test_actions_metadata(self, memory_tool):
        meta = memory_tool.get_actions_metadata()
        action_names = [a["name"] for a in meta]
        assert "view" in action_names
        assert "create" in action_names
        assert "str_replace" in action_names
        assert "insert" in action_names
        assert "delete" in action_names
        assert "rename" in action_names
        assert len(meta) == 6

    def test_config_requirements(self, memory_tool):
        assert memory_tool.get_config_requirements() == {}


# =====================================================================
# _validate_path coverage
# =====================================================================


@pytest.mark.unit
class TestMemoryToolValidatePath:

    def test_validate_path_with_traversal_returns_none(self, memory_tool):
        result = memory_tool._validate_path("/some/../etc/passwd")
        assert result is None

    def test_validate_path_with_directory_trailing_slash(self, memory_tool):
        result = memory_tool._validate_path("/some/dir/")
        assert result is not None
        assert result.endswith("/")

    def test_validate_path_empty_returns_none(self, memory_tool):
        assert memory_tool._validate_path("") is None

    def test_validate_path_none_returns_none(self, memory_tool):
        assert memory_tool._validate_path(None) is None

    def test_validate_path_relative_gets_prefixed(self, memory_tool):
        result = memory_tool._validate_path("relative/path")
        assert result == "/relative/path"

    def test_validate_path_double_slash_returns_none(self, memory_tool):
        assert memory_tool._validate_path("//etc/passwd") is None


# =====================================================================
# _view coverage
# =====================================================================


@pytest.mark.unit
class TestMemoryToolViewDirectory:

    def test_view_with_directory_path(self, memory_tool):
        result = memory_tool._view("/")
        assert isinstance(result, str)

    def test_view_with_file_path(self, memory_tool):
        result = memory_tool._view("/nonexistent.txt")
        assert "Error" in result or "not found" in result.lower()

    def test_view_invalid_path_returns_error(self, memory_tool):
        result = memory_tool._view("//bad//path")
        assert "Error" in result


# =====================================================================
# Sentinel tool_id short-circuit
# =====================================================================


@pytest.mark.unit
class TestSentinelShortCircuit:

    def test_default_tool_id_short_circuits(self, patched_memory):
        """A ``default_{user_id}`` sentinel tool_id must no-op."""
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool(tool_config={}, user_id="user1")
        assert tool.tool_id == "default_user1"
        result = tool.execute_action("view", path="/")
        assert "Error" in result
        # The in-memory repo should never have been called.
        assert _FakeMemoriesRepo._store == {}

    def test_non_uuid_tool_id_short_circuits(self, patched_memory):
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool(tool_config={"tool_id": "not-a-uuid"}, user_id="user1")
        result = tool.execute_action("create", path="/x.txt", file_text="y")
        assert "Error" in result
