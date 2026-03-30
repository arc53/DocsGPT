"""Comprehensive tests for application/agents/tools/memory.py

Covers: MemoryTool initialization, path validation, all actions
(view, create, str_replace, insert, delete, rename), directory operations,
error handling, and metadata.
"""

import mongomock
import pytest


def _get_settings():
    from application.core.settings import settings
    return settings


@pytest.fixture
def mock_memory_db(monkeypatch):
    """Set up a mongomock-based memory collection."""
    settings = _get_settings()
    mock_client = mongomock.MongoClient()
    mock_db = mock_client[settings.MONGO_DB_NAME]

    def get_mock_client():
        return {settings.MONGO_DB_NAME: mock_db}

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", get_mock_client
    )
    return mock_db


@pytest.fixture
def memory_tool(mock_memory_db):
    from application.agents.tools.memory import MemoryTool

    return MemoryTool(
        tool_config={"tool_id": "test_tool_001"},
        user_id="test_user",
    )


# =====================================================================
# Initialization
# =====================================================================


@pytest.mark.unit
class TestMemoryToolInit:

    def test_init_with_config(self, mock_memory_db):
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool(
            tool_config={"tool_id": "custom_id"}, user_id="user1"
        )
        assert tool.tool_id == "custom_id"
        assert tool.user_id == "user1"

    def test_init_fallback_to_user_id(self, mock_memory_db):
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool(tool_config={}, user_id="user1")
        assert tool.tool_id == "default_user1"

    def test_init_no_user_no_config(self, mock_memory_db):
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

    def test_requires_user_id(self, mock_memory_db):
        from application.agents.tools.memory import MemoryTool

        tool = MemoryTool(tool_config={"tool_id": "t"}, user_id=None)
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
