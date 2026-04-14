import datetime
from typing import Any, Dict, List, Optional
import uuid

from .base import Tool
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.storage.db.dual_write import dual_write
from application.storage.db.repositories.notes import NotesRepository


# Stable synthetic title used in the Postgres ``notes.title`` column.
# The notes tool stores one note per (user_id, tool_id); there is no
# user-facing title. PG requires ``title`` NOT NULL, so we write a stable
# constant alongside the actual note body in ``content``.
_NOTE_TITLE = "note"


def _utcnow() -> datetime.datetime:
    """Return a timezone-aware UTC ``datetime`` (replaces ``datetime.utcnow``)."""
    return datetime.datetime.now(datetime.timezone.utc)


class NotesTool(Tool):
    """Notepad

    Single note. Supports viewing, overwriting, string replacement.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Initialize the tool.

        Args:
            tool_config: Optional tool configuration. Should include:
                - tool_id: Unique identifier for this notes tool instance (from user_tools._id)
                           This ensures each user's tool configuration has isolated notes
            user_id: The authenticated user's id (should come from decoded_token["sub"]).
        """
        self.user_id: Optional[str] = user_id

        # Get tool_id from configuration (passed from user_tools._id in production)
        # In production, tool_id is the MongoDB ObjectId string from user_tools collection
        if tool_config and "tool_id" in tool_config:
            self.tool_id = tool_config["tool_id"]
        elif user_id:
            # Fallback for backward compatibility or testing
            self.tool_id = f"default_{user_id}"
        else:
            # Last resort fallback (shouldn't happen in normal use)
            self.tool_id = str(uuid.uuid4())

        db = MongoDB.get_client()[settings.MONGO_DB_NAME]
        self.collection = db["notes"]

        self._last_artifact_id: Optional[str] = None

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

        self._last_artifact_id = None

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

    def get_artifact_id(self, action_name: str, **kwargs: Any) -> Optional[str]:
        return self._last_artifact_id

    # -----------------------------
    # Internal helpers (single-note)
    # -----------------------------
    def _get_note(self) -> str:
        doc = self.collection.find_one({"user_id": self.user_id, "tool_id": self.tool_id})
        body = (doc or {}).get("content") or (doc or {}).get("note")
        if not doc or not body:
            return "No note found."
        if doc.get("_id") is not None:
            self._last_artifact_id = str(doc.get("_id"))
        return str(body)

    def _overwrite_note(self, content: str) -> str:
        content = (content or "").strip()
        if not content:
            return "Note content required."
        result = self.collection.find_one_and_update(
            {"user_id": self.user_id, "tool_id": self.tool_id},
            {
                "$set": {
                    "note": content,
                    "title": _NOTE_TITLE,
                    "content": content,
                    "updated_at": _utcnow(),
                }
            },
            upsert=True,
            return_document=True,
        )
        if result and result.get("_id") is not None:
            self._last_artifact_id = str(result.get("_id"))
        dual_write(
            NotesRepository,
            lambda r: r.upsert(self.user_id, self.tool_id, _NOTE_TITLE, content),
        )
        return "Note saved."

    def _str_replace(self, old_str: str, new_str: str) -> str:
        if not old_str:
            return "old_str is required."

        doc = self.collection.find_one({"user_id": self.user_id, "tool_id": self.tool_id})
        existing = (doc or {}).get("content") or (doc or {}).get("note")
        if not doc or not existing:
            return "No note found."

        current_note = str(existing)

        # Case-insensitive search
        if old_str.lower() not in current_note.lower():
            return f"String '{old_str}' not found in note."

        # Case-insensitive replacement
        import re
        updated_note = re.sub(re.escape(old_str), new_str, current_note, flags=re.IGNORECASE)

        result = self.collection.find_one_and_update(
            {"user_id": self.user_id, "tool_id": self.tool_id},
            {
                "$set": {
                    "note": updated_note,
                    "title": _NOTE_TITLE,
                    "content": updated_note,
                    "updated_at": _utcnow(),
                }
            },
            return_document=True,
        )
        if result and result.get("_id") is not None:
            self._last_artifact_id = str(result.get("_id"))
        dual_write(
            NotesRepository,
            lambda r: r.upsert(self.user_id, self.tool_id, _NOTE_TITLE, updated_note),
        )
        return "Note updated."

    def _insert(self, line_number: int, text: str) -> str:
        if not text:
            return "Text is required."

        doc = self.collection.find_one({"user_id": self.user_id, "tool_id": self.tool_id})
        existing = (doc or {}).get("content") or (doc or {}).get("note")
        if not doc or not existing:
            return "No note found."

        current_note = str(existing)
        lines = current_note.split("\n")

        # Convert to 0-indexed and validate
        index = line_number - 1
        if index < 0 or index > len(lines):
            return f"Invalid line number. Note has {len(lines)} lines."

        lines.insert(index, text)
        updated_note = "\n".join(lines)

        result = self.collection.find_one_and_update(
            {"user_id": self.user_id, "tool_id": self.tool_id},
            {
                "$set": {
                    "note": updated_note,
                    "title": _NOTE_TITLE,
                    "content": updated_note,
                    "updated_at": _utcnow(),
                }
            },
            return_document=True,
        )
        if result and result.get("_id") is not None:
            self._last_artifact_id = str(result.get("_id"))
        dual_write(
            NotesRepository,
            lambda r: r.upsert(self.user_id, self.tool_id, _NOTE_TITLE, updated_note),
        )
        return "Text inserted."

    def _delete_note(self) -> str:
        doc = self.collection.find_one_and_delete(
            {"user_id": self.user_id, "tool_id": self.tool_id}
        )
        if not doc:
            return "No note found to delete."
        if doc.get("_id") is not None:
            self._last_artifact_id = str(doc.get("_id"))
        dual_write(
            NotesRepository,
            lambda r: r.delete(self.user_id, self.tool_id),
        )
        return "Note deleted."
