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


def test_add_and_get_note(notes_tool: NotesTool) -> None:
    assert notes_tool.execute_action("add_note", note="hello") == "Note saved."
    assert "hello" in notes_tool.execute_action("get_note")
    # alias also returns the single note
    assert "hello" in notes_tool.execute_action("get_notes")


def test_edit_and_delete(notes_tool: NotesTool) -> None:
    notes_tool.execute_action("add_note", note="first")
    assert "updated" in notes_tool.execute_action("edit_note", note="second").lower()
    assert "second" in notes_tool.execute_action("get_note")
    assert "deleted" in notes_tool.execute_action("delete_note").lower()
    assert "no note" in notes_tool.execute_action("get_note").lower()
