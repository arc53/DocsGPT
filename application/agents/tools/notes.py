from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Tool
from application.core.mongo_db import MongoDB
from application.core.settings import settings


class NotesTool(Tool):
    """MongoDB-backed notes tool with a single note per user.

    Actions:
        - add_note(note: str) -> str
            Create or replace the user's single note (upsert).
        - get_note() -> str
            Return the user's note text, or 'No note found.' if absent.
        - get_notes() -> str
            Alias of get_note() for backwards/LLM friendliness.
        - edit_note(note: str) -> str
            Update the note only if it exists (no upsert).
        - delete_note() -> str
            Delete the user's note if present.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Initialize the tool.

        Args:
            tool_config: Optional tool configuration (unused for now).
            user_id: The authenticated user's id (should come from decoded_token["sub"]).

        """


        self.user_id: str = user_id
        db = MongoDB.get_client()[settings.MONGO_DB_NAME]
        self.collection = db["notes"]

    # -----------------------------
    # Action implementations
    # -----------------------------
    def execute_action(self, action_name: str, **kwargs: Any) -> str:
        """Execute an action by name.

        Args:
            action_name: One of add_note, get_note, get_notes, edit_note, delete_note.
            **kwargs: Parameters for the action.

        Returns:
            A human-readable string result.
        """
        if not self.user_id:
             return "Error: NotesTool requires a valid user_id."
        if action_name == "add_note":
            return self._add_or_replace(kwargs.get("note", ""))

        if action_name == "get_note":
            return self._get_note()

        if action_name == "get_notes":  # alias
            return self._get_note()

        if action_name == "edit_note":
            return self._edit_existing(kwargs.get("note", ""))

        if action_name == "delete_note":
            return self._delete_note()

        return f"Unknown action: {action_name}"

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing supported actions for tool schemas."""
        return [
            {
                "name": "add_note",
                "description": "Create or replace the single note for this user.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {"type": "string", "description": "Note content."}
                    },
                    "required": ["note"],
                },
            },
            {
                "name": "get_note",
                "description": "Retrieve the user's note (single-note design).",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_notes",
                "description": "Alias of get_note (single-note design).",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "edit_note",
                "description": "Edit the existing note (fails if it does not exist).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {"type": "string", "description": "New note content."}
                    },
                    "required": ["note"],
                },
            },
            {
                "name": "delete_note",
                "description": "Delete the user's note.",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Return configuration requirements (none for now)."""
        return {}

    # -----------------------------
    # Internal helpers (single-note)
    # -----------------------------
    def _add_or_replace(self, content: str) -> str:
        content = (content or "").strip()
        if not content:
            return "Note content required."
        self.collection.update_one(
            {"user_id": self.user_id},
            {"$set": {"note": content, "updated_at": datetime.utcnow()}},
            upsert=True,  # ✅ single note per user
        )
        return "Note saved."

    def _get_note(self) -> str:
        doc = self.collection.find_one({"user_id": self.user_id})
        if not doc or not doc.get("note"):
            return "No note found."
        return str(doc["note"])

    def _edit_existing(self, content: str) -> str:
        content = (content or "").strip()
        if not content:
            return "Note content required."
        res = self.collection.update_one(
            {"user_id": self.user_id},
            {"$set": {"note": content, "updated_at": datetime.utcnow()}},
            upsert=False,  # ✅ do not create if missing
        )
        return "Note updated." if res.modified_count else "Note not found."

    def _delete_note(self) -> str:
        res = self.collection.delete_one({"user_id": self.user_id})
        return "Note deleted." if res.deleted_count else "No note found to delete."
