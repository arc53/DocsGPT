from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Tool
from application.core.mongo_db import MongoDB
from application.core.settings import settings


class NotesTool(Tool):
    """Notepad

    Single note. Supports viewing, overwriting, string replacement.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Initialize the tool.

        Args:
            tool_config: Optional tool configuration (unused for now).
            user_id: The authenticated user's id (should come from decoded_token["sub"]).

        """


        self.user_id: Optional[str] = user_id
        db = MongoDB.get_client()[settings.MONGO_DB_NAME]
        self.collection = db["notes"]

    # -----------------------------
    # Action implementations
    # -----------------------------
    def execute_action(self, action_name: str, **kwargs: Any) -> str:
        """Execute an action by name.

        Args:
            action_name: One of view, overwrite, str_replace, insert, delete.
            **kwargs: Parameters for the action.

        Returns:
            A human-readable string result.
        """
        if not self.user_id:
             return "Error: NotesTool requires a valid user_id."

        if action_name == "view":
            return self._get_note()

        if action_name == "overwrite":
            return self._overwrite_note(kwargs.get("text", ""))

        if action_name == "str_replace":
            return self._str_replace(kwargs.get("old_str", ""), kwargs.get("new_str", ""))

        if action_name == "insert":
            return self._insert(kwargs.get("line_number", 1), kwargs.get("text", ""))

        if action_name == "delete":
            return self._delete_note()

        return f"Unknown action: {action_name}"

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing supported actions for tool schemas."""
        return [
            {
                "name": "view",
                "description": "Retrieve the user's note.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "overwrite",
                "description": "Replace the entire note content (creates if doesn't exist).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "New note content."}
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "str_replace",
                "description": "Replace occurrences of old_str with new_str in the note.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "old_str": {"type": "string", "description": "String to find."},
                        "new_str": {"type": "string", "description": "String to replace with."}
                    },
                    "required": ["old_str", "new_str"],
                },
            },
            {
                "name": "insert",
                "description": "Insert text at the specified line number (1-indexed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "line_number": {"type": "integer", "description": "Line number to insert at (1-indexed)."},
                        "text": {"type": "string", "description": "Text to insert."}
                    },
                    "required": ["line_number", "text"],
                },
            },
            {
                "name": "delete",
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
    def _get_note(self) -> str:
        doc = self.collection.find_one({"user_id": self.user_id})
        if not doc or not doc.get("note"):
            return "No note found."
        return str(doc["note"])

    def _overwrite_note(self, content: str) -> str:
        content = (content or "").strip()
        if not content:
            return "Note content required."
        self.collection.update_one(
            {"user_id": self.user_id},
            {"$set": {"note": content, "updated_at": datetime.utcnow()}},
            upsert=True,  # ✅ create if missing
        )
        return "Note saved."

    def _str_replace(self, old_str: str, new_str: str) -> str:
        if not old_str:
            return "old_str is required."

        doc = self.collection.find_one({"user_id": self.user_id})
        if not doc or not doc.get("note"):
            return "No note found."

        current_note = str(doc["note"])

        # Case-insensitive search
        if old_str.lower() not in current_note.lower():
            return f"String '{old_str}' not found in note."

        # Case-insensitive replacement
        import re
        updated_note = re.sub(re.escape(old_str), new_str, current_note, flags=re.IGNORECASE)

        self.collection.update_one(
            {"user_id": self.user_id},
            {"$set": {"note": updated_note, "updated_at": datetime.utcnow()}},
        )
        return "Note updated."

    def _insert(self, line_number: int, text: str) -> str:
        if not text:
            return "Text is required."

        doc = self.collection.find_one({"user_id": self.user_id})
        if not doc or not doc.get("note"):
            return "No note found."

        current_note = str(doc["note"])
        lines = current_note.split("\n")

        # Convert to 0-indexed and validate
        index = line_number - 1
        if index < 0 or index > len(lines):
            return f"Invalid line number. Note has {len(lines)} lines."

        lines.insert(index, text)
        updated_note = "\n".join(lines)

        self.collection.update_one(
            {"user_id": self.user_id},
            {"$set": {"note": updated_note, "updated_at": datetime.utcnow()}},
        )
        return "Text inserted."

    def _delete_note(self) -> str:
        res = self.collection.delete_one({"user_id": self.user_id})
        return "Note deleted." if res.deleted_count else "No note found to delete."
