import pytest
from application.agents.tools.memory import MemoryTool
from application.core.settings import settings


@pytest.fixture
def memory_tool(monkeypatch) -> MemoryTool:
    """Provide a MemoryTool with a fake Mongo collection and fixed user_id."""

    class FakeCollection:
        def __init__(self) -> None:
            self.docs = {}  # path -> document

        def insert_one(self, doc):
            user_id = doc.get("user_id")
            tool_id = doc.get("tool_id")
            path = doc.get("path")
            key = f"{user_id}:{tool_id}:{path}"
            # Add _id to document if not present

            if "_id" not in doc:
                doc["_id"] = key
            self.docs[key] = doc
            return type("res", (), {"inserted_id": key})

        def update_one(self, q, u, upsert=False):
            # Handle query by _id

            if "_id" in q:
                doc_id = q["_id"]
                if doc_id not in self.docs:
                    return type("res", (), {"modified_count": 0})
                if "$set" in u:
                    old_doc = self.docs[doc_id].copy()
                    old_doc.update(u["$set"])

                    # If path changed, update the dictionary key

                    if "path" in u["$set"]:
                        new_path = u["$set"]["path"]
                        user_id = old_doc.get("user_id")
                        tool_id = old_doc.get("tool_id")
                        new_key = f"{user_id}:{tool_id}:{new_path}"

                        # Remove old key and add with new key

                        del self.docs[doc_id]
                        old_doc["_id"] = new_key
                        self.docs[new_key] = old_doc
                    else:
                        self.docs[doc_id] = old_doc
                return type("res", (), {"modified_count": 1})
            # Handle query by user_id, tool_id, path

            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            path = q.get("path")
            key = f"{user_id}:{tool_id}:{path}"

            if key not in self.docs and not upsert:
                return type("res", (), {"modified_count": 0})
            if key not in self.docs and upsert:
                self.docs[key] = {
                    "user_id": user_id,
                    "tool_id": tool_id,
                    "path": path,
                    "content": "",
                    "_id": key,
                }
            if "$set" in u:
                self.docs[key].update(u["$set"])
            return type("res", (), {"modified_count": 1})

        def find_one(self, q, projection=None):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            path = q.get("path")

            if path:
                key = f"{user_id}:{tool_id}:{path}"
                return self.docs.get(key)
            return None

        def find(self, q, projection=None):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            results = []

            # Handle regex queries for directory listing

            if "path" in q and isinstance(q["path"], dict) and "$regex" in q["path"]:
                regex_pattern = q["path"]["$regex"]
                # Remove regex escape characters and ^ anchor for simple matching

                pattern = regex_pattern.replace("\\", "").lstrip("^")

                for key, doc in self.docs.items():
                    if doc.get("user_id") == user_id and doc.get("tool_id") == tool_id:
                        doc_path = doc.get("path", "")
                        if doc_path.startswith(pattern):
                            results.append(doc)
            else:
                for key, doc in self.docs.items():
                    if doc.get("user_id") == user_id and doc.get("tool_id") == tool_id:
                        results.append(doc)
            return results

        def delete_one(self, q):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            path = q.get("path")
            key = f"{user_id}:{tool_id}:{path}"

            if key in self.docs:
                del self.docs[key]
                return type("res", (), {"deleted_count": 1})
            return type("res", (), {"deleted_count": 0})

        def delete_many(self, q):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            deleted = 0

            # Handle regex queries for directory deletion

            if "path" in q and isinstance(q["path"], dict) and "$regex" in q["path"]:
                regex_pattern = q["path"]["$regex"]
                pattern = regex_pattern.replace("\\", "").lstrip("^")

                keys_to_delete = []
                for key, doc in self.docs.items():
                    if doc.get("user_id") == user_id and doc.get("tool_id") == tool_id:
                        doc_path = doc.get("path", "")
                        if doc_path.startswith(pattern):
                            keys_to_delete.append(key)
                for key in keys_to_delete:
                    del self.docs[key]
                    deleted += 1
            else:
                # Delete all for user and tool

                keys_to_delete = [
                    key
                    for key, doc in self.docs.items()
                    if doc.get("user_id") == user_id and doc.get("tool_id") == tool_id
                ]
                for key in keys_to_delete:
                    del self.docs[key]
                    deleted += 1
            return type("res", (), {"deleted_count": deleted})

    fake_collection = FakeCollection()
    fake_db = {"memories": fake_collection}
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", lambda: fake_client
    )

    # Return tool with a fixed tool_id for consistency in tests

    return MemoryTool({"tool_id": "test_tool_id"}, user_id="test_user")


@pytest.mark.unit
def test_init_without_user_id():
    """Should fail gracefully if no user_id is provided."""
    memory_tool = MemoryTool(tool_config={})
    result = memory_tool.execute_action("view", path="/")
    assert "user_id" in result.lower()


@pytest.mark.unit
def test_view_empty_directory(memory_tool: MemoryTool) -> None:
    """Should show empty directory when no files exist."""
    result = memory_tool.execute_action("view", path="/")
    assert "empty" in result.lower()


@pytest.mark.unit
def test_create_and_view_file(memory_tool: MemoryTool) -> None:
    """Test creating a file and viewing it."""
    # Create a file

    result = memory_tool.execute_action(
        "create", path="/notes.txt", file_text="Hello world"
    )
    assert "created" in result.lower()

    # View the file

    result = memory_tool.execute_action("view", path="/notes.txt")
    assert "Hello world" in result


@pytest.mark.unit
def test_create_overwrite_file(memory_tool: MemoryTool) -> None:
    """Test that create overwrites existing files."""
    # Create initial file

    memory_tool.execute_action("create", path="/test.txt", file_text="Original content")

    # Overwrite

    memory_tool.execute_action("create", path="/test.txt", file_text="New content")

    # Verify overwrite

    result = memory_tool.execute_action("view", path="/test.txt")
    assert "New content" in result
    assert "Original content" not in result


@pytest.mark.unit
def test_view_directory_with_files(memory_tool: MemoryTool) -> None:
    """Test viewing directory contents."""
    # Create multiple files

    memory_tool.execute_action("create", path="/file1.txt", file_text="Content 1")
    memory_tool.execute_action("create", path="/file2.txt", file_text="Content 2")
    memory_tool.execute_action(
        "create", path="/subdir/file3.txt", file_text="Content 3"
    )

    # View directory

    result = memory_tool.execute_action("view", path="/")
    assert "file1.txt" in result
    assert "file2.txt" in result
    assert "subdir/file3.txt" in result


@pytest.mark.unit
def test_view_file_with_line_range(memory_tool: MemoryTool) -> None:
    """Test viewing specific lines from a file."""
    # Create a multiline file

    content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    memory_tool.execute_action("create", path="/multiline.txt", file_text=content)

    # View lines 2-4

    result = memory_tool.execute_action(
        "view", path="/multiline.txt", view_range=[2, 4]
    )
    assert "Line 2" in result
    assert "Line 3" in result
    assert "Line 4" in result
    assert "Line 1" not in result
    assert "Line 5" not in result


@pytest.mark.unit
def test_str_replace(memory_tool: MemoryTool) -> None:
    """Test string replacement in a file."""
    # Create a file

    memory_tool.execute_action(
        "create", path="/replace.txt", file_text="Hello world, hello universe"
    )

    # Replace text

    result = memory_tool.execute_action(
        "str_replace", path="/replace.txt", old_str="hello", new_str="hi"
    )
    assert "updated" in result.lower()

    # Verify replacement

    content = memory_tool.execute_action("view", path="/replace.txt")
    assert "hi world, hi universe" in content


@pytest.mark.unit
def test_str_replace_not_found(memory_tool: MemoryTool) -> None:
    """Test string replacement when string not found."""
    memory_tool.execute_action("create", path="/test.txt", file_text="Hello world")

    result = memory_tool.execute_action(
        "str_replace", path="/test.txt", old_str="goodbye", new_str="hi"
    )
    assert "not found" in result.lower()


@pytest.mark.unit
def test_insert_line(memory_tool: MemoryTool) -> None:
    """Test inserting text at a line number."""
    # Create a multiline file

    memory_tool.execute_action(
        "create", path="/insert.txt", file_text="Line 1\nLine 2\nLine 3"
    )

    # Insert at line 2

    result = memory_tool.execute_action(
        "insert", path="/insert.txt", insert_line=2, insert_text="Inserted line"
    )
    assert "inserted" in result.lower()

    # Verify insertion

    content = memory_tool.execute_action("view", path="/insert.txt")
    lines = content.split("\n")
    assert lines[1] == "Inserted line"
    assert lines[2] == "Line 2"


@pytest.mark.unit
def test_insert_invalid_line(memory_tool: MemoryTool) -> None:
    """Test inserting at an invalid line number."""
    memory_tool.execute_action("create", path="/test.txt", file_text="Line 1\nLine 2")

    result = memory_tool.execute_action(
        "insert", path="/test.txt", insert_line=100, insert_text="Text"
    )
    assert "invalid" in result.lower()


@pytest.mark.unit
def test_delete_file(memory_tool: MemoryTool) -> None:
    """Test deleting a file."""
    # Create a file

    memory_tool.execute_action("create", path="/delete_me.txt", file_text="Content")

    # Delete it

    result = memory_tool.execute_action("delete", path="/delete_me.txt")
    assert "deleted" in result.lower()

    # Verify it's gone

    result = memory_tool.execute_action("view", path="/delete_me.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_delete_nonexistent_file(memory_tool: MemoryTool) -> None:
    """Test deleting a file that doesn't exist."""
    result = memory_tool.execute_action("delete", path="/nonexistent.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_delete_directory(memory_tool: MemoryTool) -> None:
    """Test deleting a directory with files."""
    # Create files in a directory

    memory_tool.execute_action(
        "create", path="/subdir/file1.txt", file_text="Content 1"
    )
    memory_tool.execute_action(
        "create", path="/subdir/file2.txt", file_text="Content 2"
    )

    # Delete the directory

    result = memory_tool.execute_action("delete", path="/subdir/")
    assert "deleted" in result.lower()

    # Verify files are gone

    result = memory_tool.execute_action("view", path="/subdir/file1.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_rename_file(memory_tool: MemoryTool) -> None:
    """Test renaming a file."""
    # Create a file

    memory_tool.execute_action("create", path="/old_name.txt", file_text="Content")

    # Rename it

    result = memory_tool.execute_action(
        "rename", old_path="/old_name.txt", new_path="/new_name.txt"
    )
    assert "renamed" in result.lower()

    # Verify old path doesn't exist

    result = memory_tool.execute_action("view", path="/old_name.txt")
    assert "not found" in result.lower()

    # Verify new path exists

    result = memory_tool.execute_action("view", path="/new_name.txt")
    assert "Content" in result


@pytest.mark.unit
def test_rename_nonexistent_file(memory_tool: MemoryTool) -> None:
    """Test renaming a file that doesn't exist."""
    result = memory_tool.execute_action(
        "rename", old_path="/nonexistent.txt", new_path="/new.txt"
    )
    assert "not found" in result.lower()


@pytest.mark.unit
def test_rename_to_existing_file(memory_tool: MemoryTool) -> None:
    """Test renaming to a path that already exists."""
    # Create two files

    memory_tool.execute_action("create", path="/file1.txt", file_text="Content 1")
    memory_tool.execute_action("create", path="/file2.txt", file_text="Content 2")

    # Try to rename file1 to file2

    result = memory_tool.execute_action(
        "rename", old_path="/file1.txt", new_path="/file2.txt"
    )
    assert "already exists" in result.lower()


@pytest.mark.unit
def test_path_traversal_protection(memory_tool: MemoryTool) -> None:
    """Test that directory traversal attacks are prevented."""
    # Try various path traversal attempts

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
def test_path_must_start_with_slash(memory_tool: MemoryTool) -> None:
    """Test that paths work with or without leading slash (auto-normalized)."""
    # These paths should all work now (auto-prepended with /)

    valid_paths = [
        "etc/passwd",  # Auto-prepended with /
        "home/user/file.txt",  # Auto-prepended with /
        "file.txt",  # Auto-prepended with /
    ]

    for path in valid_paths:
        result = memory_tool.execute_action("create", path=path, file_text="content")
        assert "created" in result.lower()

        # Verify the file can be accessed with or without leading slash

        view_result = memory_tool.execute_action("view", path=path)
        assert "content" in view_result


@pytest.mark.unit
def test_cannot_create_directory_as_file(memory_tool: MemoryTool) -> None:
    """Test that you cannot create a file at a directory path."""
    result = memory_tool.execute_action("create", path="/", file_text="content")
    assert "cannot create a file at directory path" in result.lower()


@pytest.mark.unit
def test_get_actions_metadata(memory_tool: MemoryTool) -> None:
    """Test that action metadata is properly defined."""
    metadata = memory_tool.get_actions_metadata()

    # Check that all expected actions are defined

    action_names = [action["name"] for action in metadata]
    assert "view" in action_names
    assert "create" in action_names
    assert "str_replace" in action_names
    assert "insert" in action_names
    assert "delete" in action_names
    assert "rename" in action_names

    # Check that each action has required fields

    for action in metadata:
        assert "name" in action
        assert "description" in action
        assert "parameters" in action


@pytest.mark.unit
def test_memory_tool_isolation(monkeypatch) -> None:
    """Test that different memory tool instances have isolated memories."""
    # Create fake collection

    class FakeCollection:
        def __init__(self) -> None:
            self.docs = {}

        def insert_one(self, doc):
            user_id = doc.get("user_id")
            tool_id = doc.get("tool_id")
            path = doc.get("path")
            key = f"{user_id}:{tool_id}:{path}"
            self.docs[key] = doc
            return type("res", (), {"inserted_id": key})

        def update_one(self, q, u, upsert=False):
            # Handle query by _id

            if "_id" in q:
                doc_id = q["_id"]
                if doc_id not in self.docs:
                    return type("res", (), {"modified_count": 0})
                if "$set" in u:
                    old_doc = self.docs[doc_id].copy()
                    old_doc.update(u["$set"])

                    # If path changed, update the dictionary key

                    if "path" in u["$set"]:
                        new_path = u["$set"]["path"]
                        user_id = old_doc.get("user_id")
                        tool_id = old_doc.get("tool_id")
                        new_key = f"{user_id}:{tool_id}:{new_path}"

                        # Remove old key and add with new key

                        del self.docs[doc_id]
                        old_doc["_id"] = new_key
                        self.docs[new_key] = old_doc
                    else:
                        self.docs[doc_id] = old_doc
                return type("res", (), {"modified_count": 1})
            # Handle query by user_id, tool_id, path

            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            path = q.get("path")
            key = f"{user_id}:{tool_id}:{path}"

            if key not in self.docs and not upsert:
                return type("res", (), {"modified_count": 0})
            if key not in self.docs and upsert:
                self.docs[key] = {
                    "user_id": user_id,
                    "tool_id": tool_id,
                    "path": path,
                    "content": "",
                    "_id": key,
                }
            if "$set" in u:
                self.docs[key].update(u["$set"])
            return type("res", (), {"modified_count": 1})

        def find_one(self, q, projection=None):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            path = q.get("path")

            if path:
                key = f"{user_id}:{tool_id}:{path}"
                return self.docs.get(key)
            return None

    fake_collection = FakeCollection()
    fake_db = {"memories": fake_collection}
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", lambda: fake_client
    )

    # Create two memory tools with different tool_ids for the same user

    tool1 = MemoryTool({"tool_id": "tool_1"}, user_id="test_user")
    tool2 = MemoryTool({"tool_id": "tool_2"}, user_id="test_user")

    # Create a file in tool1

    tool1.execute_action("create", path="/file.txt", file_text="Content from tool 1")

    # Create a file with the same path in tool2

    tool2.execute_action("create", path="/file.txt", file_text="Content from tool 2")

    # Verify that each tool sees only its own content

    result1 = tool1.execute_action("view", path="/file.txt")
    result2 = tool2.execute_action("view", path="/file.txt")

    assert "Content from tool 1" in result1
    assert "Content from tool 2" not in result1

    assert "Content from tool 2" in result2
    assert "Content from tool 1" not in result2


@pytest.mark.unit
def test_memory_tool_auto_generates_tool_id(monkeypatch) -> None:
    """Test that tool_id defaults to 'default_{user_id}' for persistence."""

    class FakeCollection:
        def __init__(self) -> None:
            self.docs = {}

        def update_one(self, q, u, upsert=False):
            return type("res", (), {"modified_count": 1})

    fake_collection = FakeCollection()
    fake_db = {"memories": fake_collection}
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", lambda: fake_client
    )

    # Create two tools without providing tool_id for the same user

    tool1 = MemoryTool({}, user_id="test_user")
    tool2 = MemoryTool({}, user_id="test_user")

    # Both should have the same default tool_id for persistence

    assert tool1.tool_id == "default_test_user"
    assert tool2.tool_id == "default_test_user"
    assert tool1.tool_id == tool2.tool_id

    # Different users should have different tool_ids

    tool3 = MemoryTool({}, user_id="another_user")
    assert tool3.tool_id == "default_another_user"
    assert tool3.tool_id != tool1.tool_id


@pytest.mark.unit
def test_paths_without_leading_slash(memory_tool) -> None:
    """Test that paths without leading slash work correctly."""
    # Create file without leading slash

    result = memory_tool.execute_action(
        "create",
        path="cat_breeds.txt",
        file_text="- Korat\n- Chartreux\n- British Shorthair\n- Nebelung",
    )
    assert "created" in result.lower()

    # View file without leading slash

    view_result = memory_tool.execute_action("view", path="cat_breeds.txt")
    assert "Korat" in view_result
    assert "Chartreux" in view_result

    # View same file with leading slash (should work the same)

    view_result2 = memory_tool.execute_action("view", path="/cat_breeds.txt")
    assert "Korat" in view_result2

    # Test str_replace without leading slash

    replace_result = memory_tool.execute_action(
        "str_replace", path="cat_breeds.txt", old_str="Korat", new_str="Maine Coon"
    )
    assert "updated" in replace_result.lower()

    # Test nested path without leading slash

    nested_result = memory_tool.execute_action(
        "create", path="projects/tasks.txt", file_text="Task 1\nTask 2"
    )
    assert "created" in nested_result.lower()

    view_nested = memory_tool.execute_action("view", path="projects/tasks.txt")
    assert "Task 1" in view_nested


@pytest.mark.unit
def test_rename_directory(memory_tool: MemoryTool) -> None:
    """Test renaming a directory with files."""
    # Create files in a directory

    memory_tool.execute_action("create", path="/docs/file1.txt", file_text="Content 1")
    memory_tool.execute_action(
        "create", path="/docs/sub/file2.txt", file_text="Content 2"
    )

    # Rename directory (with trailing slash)

    result = memory_tool.execute_action(
        "rename", old_path="/docs/", new_path="/archive/"
    )
    assert "renamed" in result.lower()
    assert "2 files" in result.lower()

    # Verify old paths don't exist

    result = memory_tool.execute_action("view", path="/docs/file1.txt")
    assert "not found" in result.lower()

    # Verify new paths exist

    result = memory_tool.execute_action("view", path="/archive/file1.txt")
    assert "Content 1" in result

    result = memory_tool.execute_action("view", path="/archive/sub/file2.txt")
    assert "Content 2" in result


@pytest.mark.unit
def test_rename_directory_without_trailing_slash(memory_tool: MemoryTool) -> None:
    """Test renaming a directory when new path is missing trailing slash."""
    # Create files in a directory

    memory_tool.execute_action("create", path="/docs/file1.txt", file_text="Content 1")
    memory_tool.execute_action(
        "create", path="/docs/sub/file2.txt", file_text="Content 2"
    )

    # Rename directory - old path has slash, new path doesn't

    result = memory_tool.execute_action(
        "rename", old_path="/docs/", new_path="/archive"  # Missing trailing slash
    )
    assert "renamed" in result.lower()

    # Verify paths are correct (not corrupted like "/archivesub/file2.txt")

    result = memory_tool.execute_action("view", path="/archive/file1.txt")
    assert "Content 1" in result

    result = memory_tool.execute_action("view", path="/archive/sub/file2.txt")
    assert "Content 2" in result

    # Verify corrupted path doesn't exist

    result = memory_tool.execute_action("view", path="/archivesub/file2.txt")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_view_file_line_numbers(memory_tool: MemoryTool) -> None:
    """Test that view_range displays correct line numbers."""
    # Create a multiline file

    content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    memory_tool.execute_action("create", path="/numbered.txt", file_text=content)

    # View lines 2-4

    result = memory_tool.execute_action("view", path="/numbered.txt", view_range=[2, 4])

    # Check that line numbers are correct (should be 2, 3, 4 not 3, 4, 5)

    assert "2: Line 2" in result
    assert "3: Line 3" in result
    assert "4: Line 4" in result
    assert "1: Line 1" not in result
    assert "5: Line 5" not in result

    # Verify no off-by-one error

    assert "3: Line 2" not in result  # Wrong line number
    assert "4: Line 3" not in result  # Wrong line number
    assert "5: Line 4" not in result  # Wrong line number
