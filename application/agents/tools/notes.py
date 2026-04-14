from typing import Any, Dict, List, Optional
import uuid

from .base import Tool
from application.storage.db.repositories.notes import NotesRepository
from application.storage.db.session import db_readonly, db_session


# Stable synthetic title used in the Postgres ``notes.title`` column.
# The notes tool stores one note per (user_id, tool_id); there is no
# user-facing title. PG requires ``title`` NOT NULL, so we write a stable
# constant alongside the actual note body in ``content``.
_NOTE_TITLE = "note"


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
        if tool_config and "tool_id" in tool_config:
            self.tool_id = tool_config["tool_id"]
        elif user_id:
            # Fallback for backward compatibility or testing
            self.tool_id = f"default_{user_id}"
        else:
            # Last resort fallback (shouldn't happen in normal use)
            self.tool_id = str(uuid.uuid4())

        self._last_artifact_id: Optional[str] = None

    def _pg_enabled(self) -> bool:
        """Return True only when ``tool_id`` is a real ``user_tools.id`` UUID.

        ``notes.tool_id`` is a UUID FK to ``user_tools``; repo queries
        ``CAST(:tool_id AS uuid)``. The sentinel ``default_{uid}``
        fallback is neither a UUID nor a ``user_tools`` row, so any DB
        operation would crash. Mirror MemoryTool's guard and no-op.
        """
        tool_id = getattr(self, "tool_id", None)
        if not tool_id or not isinstance(tool_id, str):
            return False
        if tool_id.startswith("default_"):
            return False
        return True

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

        if not self._pg_enabled():
            return (
                "Error: NotesTool is not configured with a persistent "
                "tool_id; note storage is unavailable for this session."
            )

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
    def _fetch_note(self) -> Optional[dict]:
        """Read the note row for this (user, tool) from Postgres."""
        with db_readonly() as conn:
            return NotesRepository(conn).get_for_user_tool(self.user_id, self.tool_id)

    def _get_note(self) -> str:
        doc = self._fetch_note()
        # ``content`` is the PG column; expose as ``note`` to callers via the
        # textual return value. Frontends that read the artifact via the
        # repo dict get ``content`` (PG-native) plus the artifact id below.
        body = (doc or {}).get("content")
        if not doc or not body:
            return "No note found."
        if doc.get("id") is not None:
            self._last_artifact_id = str(doc.get("id"))
        return str(body)

    def _overwrite_note(self, content: str) -> str:
        content = (content or "").strip()
        if not content:
            return "Note content required."
        with db_session() as conn:
            row = NotesRepository(conn).upsert(
                self.user_id, self.tool_id, _NOTE_TITLE, content
            )
        if row and row.get("id") is not None:
            self._last_artifact_id = str(row.get("id"))
        return "Note saved."

    def _str_replace(self, old_str: str, new_str: str) -> str:
        if not old_str:
            return "old_str is required."

        doc = self._fetch_note()
        existing = (doc or {}).get("content")
        if not doc or not existing:
            return "No note found."

        current_note = str(existing)

        # Case-insensitive search
        if old_str.lower() not in current_note.lower():
            return f"String '{old_str}' not found in note."

        # Case-insensitive replacement
        import re
        updated_note = re.sub(re.escape(old_str), new_str, current_note, flags=re.IGNORECASE)

        with db_session() as conn:
            row = NotesRepository(conn).upsert(
                self.user_id, self.tool_id, _NOTE_TITLE, updated_note
            )
        if row and row.get("id") is not None:
            self._last_artifact_id = str(row.get("id"))
        return "Note updated."

    def _insert(self, line_number: int, text: str) -> str:
        if not text:
            return "Text is required."

        doc = self._fetch_note()
        existing = (doc or {}).get("content")
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

        with db_session() as conn:
            row = NotesRepository(conn).upsert(
                self.user_id, self.tool_id, _NOTE_TITLE, updated_note
            )
        if row and row.get("id") is not None:
            self._last_artifact_id = str(row.get("id"))
        return "Text inserted."

    def _delete_note(self) -> str:
        # Capture the id (for artifact tracking) before deleting.
        existing = self._fetch_note()
        if not existing:
            return "No note found to delete."
        with db_session() as conn:
            deleted = NotesRepository(conn).delete(self.user_id, self.tool_id)
        if not deleted:
            return "No note found to delete."
        if existing.get("id") is not None:
            self._last_artifact_id = str(existing.get("id"))
        return "Note deleted."
