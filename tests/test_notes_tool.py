import pytest
from application.agents.tools.notes import NotesTool
from application.core.settings import settings


@pytest.fixture
def notes_tool(monkeypatch) -> NotesTool:
    """Provide a NotesTool with a fake Mongo collection and fixed user_id."""

    class FakeCollection:
        def __init__(self) -> None:
            self.docs = {}  # key: user_id:tool_id -> doc

        def update_one(self, q, u, upsert=False):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            key = f"{user_id}:{tool_id}"

            # emulate single-note storage with optional upsert

            if key not in self.docs and not upsert:
                return type("res", (), {"modified_count": 0})
            if key not in self.docs and upsert:
                self.docs[key] = {"user_id": user_id, "tool_id": tool_id, "note": ""}
            if "$set" in u and "note" in u["$set"]:
                self.docs[key]["note"] = u["$set"]["note"]
            return type("res", (), {"modified_count": 1})

        def find_one(self, q):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            key = f"{user_id}:{tool_id}"
            return self.docs.get(key)

        def delete_one(self, q):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            key = f"{user_id}:{tool_id}"
            if key in self.docs:
                del self.docs[key]
                return type("res", (), {"deleted_count": 1})
            return type("res", (), {"deleted_count": 0})

    fake_collection = FakeCollection()
    fake_db = {"notes": fake_collection}
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    # Patch MongoDB client globally for the tool

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", lambda: fake_client
    )

    # Return tool with a fixed tool_id for consistency in tests

    return NotesTool({"tool_id": "test_tool_id"}, user_id="test_user")


@pytest.mark.unit
def test_view(notes_tool: NotesTool) -> None:
    # Manually insert a note to test retrieval

    notes_tool.collection.update_one(
        {"user_id": "test_user", "tool_id": "test_tool_id"},
        {"$set": {"note": "hello"}},
        upsert=True,
    )
    assert "hello" in notes_tool.execute_action("view")


@pytest.mark.unit
def test_overwrite_and_delete(notes_tool: NotesTool) -> None:
    # Overwrite creates a new note

    assert "saved" in notes_tool.execute_action("overwrite", text="first").lower()
    assert "first" in notes_tool.execute_action("view")

    # Overwrite replaces existing note

    assert "saved" in notes_tool.execute_action("overwrite", text="second").lower()
    assert "second" in notes_tool.execute_action("view")

    assert "deleted" in notes_tool.execute_action("delete").lower()
    assert "no note" in notes_tool.execute_action("view").lower()


@pytest.mark.unit
def test_init_without_user_id(monkeypatch):
    """Should fail gracefully if no user_id is provided."""
    notes_tool = NotesTool(tool_config={})
    result = notes_tool.execute_action("view")
    assert "user_id" in str(result).lower()


@pytest.mark.unit
def test_view_not_found(notes_tool: NotesTool) -> None:
    """Should return 'No note found.' when no note exists"""
    result = notes_tool.execute_action("view")
    assert "no note found" in result.lower()


@pytest.mark.unit
def test_str_replace(notes_tool: NotesTool) -> None:
    """Test string replacement in note"""
    # Create a note

    notes_tool.execute_action("overwrite", text="Hello world, hello universe")

    # Replace text

    result = notes_tool.execute_action("str_replace", old_str="hello", new_str="hi")
    assert "updated" in result.lower()

    # Verify replacement

    note = notes_tool.execute_action("view")
    assert "hi world, hi universe" in note.lower()


@pytest.mark.unit
def test_str_replace_not_found(notes_tool: NotesTool) -> None:
    """Test string replacement when string not found"""
    notes_tool.execute_action("overwrite", text="Hello world")
    result = notes_tool.execute_action("str_replace", old_str="goodbye", new_str="hi")
    assert "not found" in result.lower()


@pytest.mark.unit
def test_insert_line(notes_tool: NotesTool) -> None:
    """Test inserting text at a line number"""
    # Create a multiline note

    notes_tool.execute_action("overwrite", text="Line 1\nLine 2\nLine 3")

    # Insert at line 2

    result = notes_tool.execute_action("insert", line_number=2, text="Inserted line")
    assert "inserted" in result.lower()

    # Verify insertion

    note = notes_tool.execute_action("view")
    lines = note.split("\n")
    assert lines[1] == "Inserted line"
    assert lines[2] == "Line 2"


@pytest.mark.unit
def test_delete_nonexistent_note(monkeypatch):
    class FakeResult:
        deleted_count = 0

    class FakeCollection:
        def delete_one(self, *args, **kwargs):
            return FakeResult()

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client",
        lambda: {"docsgpt": {"notes": FakeCollection()}},
    )

    notes_tool = NotesTool(tool_config={}, user_id="user123")
    result = notes_tool.execute_action("delete")
    assert "no note found" in result.lower()


@pytest.mark.unit
def test_notes_tool_isolation(monkeypatch) -> None:
    """Test that different notes tool instances have isolated notes."""

    class FakeCollection:
        def __init__(self) -> None:
            self.docs = {}

        def update_one(self, q, u, upsert=False):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            key = f"{user_id}:{tool_id}"

            if key not in self.docs and not upsert:
                return type("res", (), {"modified_count": 0})
            if key not in self.docs and upsert:
                self.docs[key] = {"user_id": user_id, "tool_id": tool_id, "note": ""}
            if "$set" in u and "note" in u["$set"]:
                self.docs[key]["note"] = u["$set"]["note"]
            return type("res", (), {"modified_count": 1})

        def find_one(self, q):
            user_id = q.get("user_id")
            tool_id = q.get("tool_id")
            key = f"{user_id}:{tool_id}"
            return self.docs.get(key)

    fake_collection = FakeCollection()
    fake_db = {"notes": fake_collection}
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", lambda: fake_client
    )

    # Create two notes tools with different tool_ids for the same user

    tool1 = NotesTool({"tool_id": "tool_1"}, user_id="test_user")
    tool2 = NotesTool({"tool_id": "tool_2"}, user_id="test_user")

    # Create a note in tool1

    tool1.execute_action("overwrite", text="Content from tool 1")

    # Create a note in tool2

    tool2.execute_action("overwrite", text="Content from tool 2")

    # Verify that each tool sees only its own content

    result1 = tool1.execute_action("view")
    result2 = tool2.execute_action("view")

    assert "Content from tool 1" in result1
    assert "Content from tool 2" not in result1

    assert "Content from tool 2" in result2
    assert "Content from tool 1" not in result2


@pytest.mark.unit
def test_notes_tool_auto_generates_tool_id(monkeypatch) -> None:
    """Test that tool_id defaults to 'default_{user_id}' for persistence."""

    class FakeCollection:
        def __init__(self) -> None:
            self.docs = {}

        def update_one(self, q, u, upsert=False):
            return type("res", (), {"modified_count": 1})

    fake_collection = FakeCollection()
    fake_db = {"notes": fake_collection}
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", lambda: fake_client
    )

    # Create two tools without providing tool_id for the same user

    tool1 = NotesTool({}, user_id="test_user")
    tool2 = NotesTool({}, user_id="test_user")

    # Both should have the same default tool_id for persistence

    assert tool1.tool_id == "default_test_user"
    assert tool2.tool_id == "default_test_user"
    assert tool1.tool_id == tool2.tool_id

    # Different users should have different tool_ids

    tool3 = NotesTool({}, user_id="another_user")
    assert tool3.tool_id == "default_another_user"
    assert tool3.tool_id != tool1.tool_id
