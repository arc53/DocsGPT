import pytest
from application.agents.tools.notes import NotesTool
from application.core.settings import settings



@pytest.fixture
def notes_tool(monkeypatch) -> NotesTool:
    """Provide a NotesTool with a fake Mongo collection and fixed user_id."""
    class FakeCollection:
        def __init__(self) -> None:
            self.doc = None  # single note per user

        def update_one(self, q, u, upsert=False):
            # emulate single-note storage with optional upsert
            if self.doc is None and not upsert:
                return type("res", (), {"modified_count": 0})
            if self.doc is None and upsert:
                self.doc = {"user_id": q["user_id"], "note": ""}
            if "$set" in u and "note" in u["$set"]:
                self.doc["note"] = u["$set"]["note"]
            return type("res", (), {"modified_count": 1})

        def find_one(self, q):
            if self.doc and self.doc.get("user_id") == q.get("user_id"):
                return self.doc
            return None

        def delete_one(self, q):
            if self.doc and self.doc.get("user_id") == q.get("user_id"):
                self.doc = None
                return type("res", (), {"deleted_count": 1})
            return type("res", (), {"deleted_count": 0})

    fake_collection = FakeCollection()
    fake_db = {"notes": fake_collection}
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    # Patch MongoDB client globally for the tool
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)

    # ToolManager will pass user_id in production; in tests we pass it directly
    return NotesTool({}, user_id="test_user")


def test_view(notes_tool: NotesTool) -> None:
    # Manually insert a note to test retrieval
    notes_tool.collection.update_one(
        {"user_id": "test_user"},
        {"$set": {"note": "hello"}},
        upsert=True
    )
    assert "hello" in notes_tool.execute_action("view")


def test_overwrite_and_delete(notes_tool: NotesTool) -> None:
    # Overwrite creates a new note
    assert "saved" in notes_tool.execute_action("overwrite", text="first").lower()
    assert "first" in notes_tool.execute_action("view")

    # Overwrite replaces existing note
    assert "saved" in notes_tool.execute_action("overwrite", text="second").lower()
    assert "second" in notes_tool.execute_action("view")

    assert "deleted" in notes_tool.execute_action("delete").lower()
    assert "no note" in notes_tool.execute_action("view").lower()

def test_init_without_user_id(monkeypatch):
    """Should fail gracefully if no user_id is provided."""
    notes_tool = NotesTool(tool_config={})
    result = notes_tool.execute_action("view")
    assert "user_id" in str(result).lower()


def test_view_not_found(notes_tool: NotesTool) -> None:
    """Should return 'No note found.' when no note exists"""
    result = notes_tool.execute_action("view")
    assert "no note found" in result.lower()


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


def test_str_replace_not_found(notes_tool: NotesTool) -> None:
    """Test string replacement when string not found"""
    notes_tool.execute_action("overwrite", text="Hello world")
    result = notes_tool.execute_action("str_replace", old_str="goodbye", new_str="hi")
    assert "not found" in result.lower()


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


def test_delete_nonexistent_note(monkeypatch):
    class FakeResult:
        deleted_count = 0

    class FakeCollection:
        def delete_one(self, *args, **kwargs):
            return FakeResult()

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client",
        lambda: {"docsgpt": {"notes": FakeCollection()}}
    )

    notes_tool = NotesTool(tool_config={}, user_id="user123")
    result = notes_tool.execute_action("delete")
    assert "no note found" in result.lower()
