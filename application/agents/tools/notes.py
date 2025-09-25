from bson.objectid import ObjectId
from .base import Tool
from application.core.mongo_db import MongoDB
from application.core.settings import settings



class NotesTool(Tool):
    """
    A MongoDB-backed notes tool for LLMs.
    Allows adding, editing, and retrieving notes.
    """

    def __init__(self, tool_config: dict | None = None, user_id: str | None = None):
        self.user_id = user_id or "anonymous"
        db = MongoDB.get_client()[settings.MONGO_DB_NAME]
        self.collection = db["notes"]

    def execute_action(self, action_name: str, **kwargs):
        if action_name == "add_note":
            content = kwargs.get("note", "").strip()
            if not content:
                return "Note content required."
            result = self.collection.insert_one(
                {"user_id": self.user_id, "note": content}
            )
            return f"Note saved with id {result.inserted_id}"

        elif action_name == "get_notes":
            docs = list(self.collection.find({"user_id": self.user_id}))
            if not docs:
                return "No notes found."
            return "\n".join([f"{i+1}. {d['note']} (id={d['_id']})" for i, d in enumerate(docs)])

        elif action_name == "edit_note":
            note_id = kwargs.get("id")
            new_content = kwargs.get("note", "").strip()
            if not note_id or not new_content:
                return "Both id and new note content are required."
            result = self.collection.update_one(
                {"_id": ObjectId(note_id), "user_id": self.user_id},
                {"$set": {"note": new_content}},
            )
            return "Note updated." if result.modified_count else "Note not found."

        elif action_name == "delete_note":
            note_id = kwargs.get("id")
            if not note_id:
                return "id required."
            result = self.collection.delete_one(
                {"_id": ObjectId(note_id), "user_id": self.user_id}
            )
            return "Note deleted." if result.deleted_count else "Note not found."

        else:
            return f"Unknown action: {action_name}"

    def get_actions_metadata(self):
        return [
            {
                "name": "add_note",
                "description": "Add a note",
                "parameters": {
                    "type": "object",
                    "properties": {"note": {"type": "string"}},
                    "required": ["note"],
                },
            },
            {
                "name": "get_notes",
                "description": "Retrieve all notes",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "edit_note",
                "description": "Edit a note by ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "MongoDB note id"},
                        "note": {"type": "string", "description": "New note content"},
                    },
                    "required": ["id", "note"],
                },
            },
            {
                "name": "delete_note",
                "description": "Delete a note by ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "MongoDB note id"}
                    },
                    "required": ["id"],
                },
            },
        ]

    def get_config_requirements(self):
        return {}  # nothing special for now
