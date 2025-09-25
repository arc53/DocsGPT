import pytest
from application.agents.tools.notes import NotesTool
from bson import ObjectId
@pytest.fixture
def notes_tool(mocker):
    # patch MongoDB client so you don't hit real DB
    mock_collection = mocker.MagicMock()
    mock_db = {"notes": mock_collection}
    mock_client = {"docsgpt": mock_db}  # replace "docsgpt" with your settings.MONGO_DB_NAME
    mocker.patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client)

    return NotesTool({}, user_id="test_user")


def test_add_and_get_notes(notes_tool):
    notes_tool.collection.insert_one.return_value.inserted_id = "123"
    result = notes_tool.execute_action("add_note", note="test")
    assert "Note saved" in result

    notes_tool.collection.find.return_value = [{"_id": "123", "user_id": "test_user", "note": "test"}]
    result = notes_tool.execute_action("get_notes")
    assert "test" in result



def test_edit_and_delete(notes_tool):
    valid_id = str(ObjectId())  # generate a valid ID

    notes_tool.collection.update_one.return_value.modified_count = 1
    result = notes_tool.execute_action("edit_note", id=valid_id, note="updated")
    assert "updated" in result.lower() or "note updated" in result.lower()

    notes_tool.collection.delete_one.return_value.deleted_count = 1
    result = notes_tool.execute_action("delete_note", id=valid_id)
    assert "deleted" in result.lower()

