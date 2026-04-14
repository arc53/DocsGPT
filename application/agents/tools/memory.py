from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
import uuid

from .base import Tool
from application.storage.db.repositories.memories import MemoriesRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


class MemoryTool(Tool):
    """Memory

    Stores and retrieves information across conversations through a memory file directory.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Initialize the tool.

        Args:
            tool_config: Optional tool configuration. Should include:
                - tool_id: Unique identifier for this memory tool instance (from user_tools._id)
                           This ensures each user's tool configuration has isolated memories
            user_id: The authenticated user's id (should come from decoded_token["sub"]).
        """
        self.user_id: Optional[str] = user_id

        # Get tool_id from configuration (passed from user_tools._id in production)
        # In production, tool_id is the UUID string from user_tools.id.
        if tool_config and "tool_id" in tool_config:
            self.tool_id = tool_config["tool_id"]
        elif user_id:
            # Fallback for backward compatibility or testing
            self.tool_id = f"default_{user_id}"
        else:
            # Last resort fallback (shouldn't happen in normal use)
            self.tool_id = str(uuid.uuid4())

    def _pg_enabled(self) -> bool:
        """Return True if this MemoryTool's tool_id is a real ``user_tools.id``.

        The ``memories`` PG table has a UUID foreign key to ``user_tools``.
        The sentinel ``default_{uid}`` fallback tool_id is not a UUID and
        has no row in ``user_tools``, so any storage operation would fail
        the foreign-key check. After the Postgres cutover Postgres is the
        only store, so for the sentinel case there is nowhere to read or
        write — operations become no-ops and the tool returns an
        explanatory error to the caller.
        """
        tool_id = getattr(self, "tool_id", None)
        if not tool_id or not isinstance(tool_id, str):
            return False
        if tool_id.startswith("default_"):
            logger.debug(
                "Skipping Postgres operation for MemoryTool with sentinel tool_id=%s",
                tool_id,
            )
            return False
        return True

    # -----------------------------
    # Action implementations
    # -----------------------------
    def execute_action(self, action_name: str, **kwargs: Any) -> str:
        """Execute an action by name.

        Args:
            action_name: One of view, create, str_replace, insert, delete, rename.
            **kwargs: Parameters for the action.

        Returns:
            A human-readable string result.
        """
        if not self.user_id:
            return "Error: MemoryTool requires a valid user_id."

        if not self._pg_enabled():
            return (
                "Error: MemoryTool is not configured with a persistent tool_id; "
                "memory storage is unavailable for this session."
            )

        if action_name == "view":
            return self._view(
                kwargs.get("path", "/"),
                kwargs.get("view_range")
            )

        if action_name == "create":
            return self._create(
                kwargs.get("path", ""),
                kwargs.get("file_text", "")
            )

        if action_name == "str_replace":
            return self._str_replace(
                kwargs.get("path", ""),
                kwargs.get("old_str", ""),
                kwargs.get("new_str", "")
            )

        if action_name == "insert":
            return self._insert(
                kwargs.get("path", ""),
                kwargs.get("insert_line", 1),
                kwargs.get("insert_text", "")
            )

        if action_name == "delete":
            return self._delete(kwargs.get("path", ""))

        if action_name == "rename":
            return self._rename(
                kwargs.get("old_path", ""),
                kwargs.get("new_path", "")
            )

        return f"Unknown action: {action_name}"

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing supported actions for tool schemas."""
        return [
            {
                "name": "view",
                "description": "Shows directory contents or file contents with optional line ranges.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to file or directory (e.g., /notes.txt or /project/ or /)."
                        },
                        "view_range": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Optional [start_line, end_line] to view specific lines (1-indexed)."
                        }
                    },
                    "required": ["path"]
                },
            },
            {
                "name": "create",
                "description": "Create or overwrite a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path to create (e.g., /notes.txt or /project/task.txt)."
                        },
                        "file_text": {
                            "type": "string",
                            "description": "Content to write to the file."
                        }
                    },
                    "required": ["path", "file_text"]
                },
            },
            {
                "name": "str_replace",
                "description": "Replace text in a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path (e.g., /notes.txt)."
                        },
                        "old_str": {
                            "type": "string",
                            "description": "String to find."
                        },
                        "new_str": {
                            "type": "string",
                            "description": "String to replace with."
                        }
                    },
                    "required": ["path", "old_str", "new_str"]
                },
            },
            {
                "name": "insert",
                "description": "Insert text at a specific line in a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path (e.g., /notes.txt)."
                        },
                        "insert_line": {
                            "type": "integer",
                            "description": "Line number to insert at (1-indexed)."
                        },
                        "insert_text": {
                            "type": "string",
                            "description": "Text to insert."
                        }
                    },
                    "required": ["path", "insert_line", "insert_text"]
                },
            },
            {
                "name": "delete",
                "description": "Delete a file or directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to delete (e.g., /notes.txt or /project/)."
                        }
                    },
                    "required": ["path"]
                },
            },
            {
                "name": "rename",
                "description": "Rename or move a file/directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "old_path": {
                            "type": "string",
                            "description": "Current path (e.g., /old.txt)."
                        },
                        "new_path": {
                            "type": "string",
                            "description": "New path (e.g., /new.txt)."
                        }
                    },
                    "required": ["old_path", "new_path"]
                },
            },
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Return configuration requirements."""
        return {}

    # -----------------------------
    # Path validation
    # -----------------------------
    def _validate_path(self, path: str) -> Optional[str]:
        """Validate and normalize path.

        Args:
            path: User-provided path.

        Returns:
            Normalized path or None if invalid.
        """
        if not path:
            return None

        # Remove any leading/trailing whitespace
        path = path.strip()

        # Preserve whether path ends with / (indicates directory)
        is_directory = path.endswith("/")

        # Ensure path starts with / for consistency
        if not path.startswith("/"):
            path = "/" + path

        # Check for directory traversal patterns
        if ".." in path or path.count("//") > 0:
            return None

        # Normalize the path
        try:
            # Convert to Path object and resolve to canonical form
            normalized = str(Path(path).as_posix())

            # Ensure it still starts with /
            if not normalized.startswith("/"):
                return None

            # Preserve trailing slash for directories
            if is_directory and not normalized.endswith("/") and normalized != "/":
                normalized = normalized + "/"

            return normalized
        except Exception:
            return None

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _view(self, path: str, view_range: Optional[List[int]] = None) -> str:
        """View directory contents or file contents."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        # Check if viewing directory (ends with / or is root)
        if validated_path == "/" or validated_path.endswith("/"):
            return self._view_directory(validated_path)

        # Otherwise view file
        return self._view_file(validated_path, view_range)

    def _view_directory(self, path: str) -> str:
        """List files in a directory."""
        # Ensure path ends with / for proper prefix matching
        search_path = path if path.endswith("/") else path + "/"

        with db_readonly() as conn:
            docs = MemoriesRepository(conn).list_by_prefix(
                self.user_id, self.tool_id, search_path
            )

        if not docs:
            return f"Directory: {path}\n(empty)"

        # Extract filenames relative to the directory
        files = []
        for doc in docs:
            file_path = doc["path"]
            # Remove the directory prefix
            if file_path.startswith(search_path):
                relative = file_path[len(search_path):]
                if relative:
                    files.append(relative)

        files.sort()
        file_list = "\n".join(f"- {f}" for f in files)
        return f"Directory: {path}\n{file_list}"

    def _view_file(self, path: str, view_range: Optional[List[int]] = None) -> str:
        """View file contents with optional line range."""
        with db_readonly() as conn:
            doc = MemoriesRepository(conn).get_by_path(
                self.user_id, self.tool_id, path
            )

        if not doc or not doc.get("content"):
            return f"Error: File not found: {path}"

        content = str(doc["content"])

        # Apply view_range if specified
        if view_range and len(view_range) == 2:
            lines = content.split("\n")
            start, end = view_range
            # Convert to 0-indexed
            start_idx = max(0, start - 1)
            end_idx = min(len(lines), end)

            if start_idx >= len(lines):
                return f"Error: Line range out of bounds. File has {len(lines)} lines."

            selected_lines = lines[start_idx:end_idx]
            # Add line numbers (enumerate with 1-based start)
            numbered_lines = [f"{i}: {line}" for i, line in enumerate(selected_lines, start=start)]
            return "\n".join(numbered_lines)

        return content

    def _create(self, path: str, file_text: str) -> str:
        """Create or overwrite a file."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        if validated_path == "/" or validated_path.endswith("/"):
            return "Error: Cannot create a file at directory path."

        with db_session() as conn:
            MemoriesRepository(conn).upsert(
                self.user_id, self.tool_id, validated_path, file_text
            )

        return f"File created: {validated_path}"

    def _str_replace(self, path: str, old_str: str, new_str: str) -> str:
        """Replace text in a file."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        if not old_str:
            return "Error: old_str is required."

        with db_session() as conn:
            repo = MemoriesRepository(conn)
            doc = repo.get_by_path(self.user_id, self.tool_id, validated_path)

            if not doc or not doc.get("content"):
                return f"Error: File not found: {validated_path}"

            current_content = str(doc["content"])

            # Check if old_str exists (case-insensitive)
            if old_str.lower() not in current_content.lower():
                return f"Error: String '{old_str}' not found in file."

            # Case-insensitive replace
            import re as regex_module
            updated_content = regex_module.sub(
                regex_module.escape(old_str),
                new_str,
                current_content,
                flags=regex_module.IGNORECASE,
            )

            repo.upsert(self.user_id, self.tool_id, validated_path, updated_content)

        return f"File updated: {validated_path}"

    def _insert(self, path: str, insert_line: int, insert_text: str) -> str:
        """Insert text at a specific line."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        if not insert_text:
            return "Error: insert_text is required."

        with db_session() as conn:
            repo = MemoriesRepository(conn)
            doc = repo.get_by_path(self.user_id, self.tool_id, validated_path)

            if not doc or not doc.get("content"):
                return f"Error: File not found: {validated_path}"

            current_content = str(doc["content"])
            lines = current_content.split("\n")

            # Convert to 0-indexed
            index = insert_line - 1
            if index < 0 or index > len(lines):
                return f"Error: Invalid line number. File has {len(lines)} lines."

            lines.insert(index, insert_text)
            updated_content = "\n".join(lines)

            repo.upsert(self.user_id, self.tool_id, validated_path, updated_content)

        return f"Text inserted at line {insert_line} in {validated_path}"

    def _delete(self, path: str) -> str:
        """Delete a file or directory."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        if validated_path == "/":
            # Delete all files for this user and tool
            with db_session() as conn:
                deleted = MemoriesRepository(conn).delete_all(
                    self.user_id, self.tool_id
                )
            return f"Deleted {deleted} file(s) from memory."

        # Check if it's a directory (ends with /)
        if validated_path.endswith("/"):
            with db_session() as conn:
                deleted = MemoriesRepository(conn).delete_by_prefix(
                    self.user_id, self.tool_id, validated_path
                )
            return f"Deleted directory and {deleted} file(s)."

        # Try as directory first (without trailing slash)
        search_path = validated_path + "/"
        with db_session() as conn:
            repo = MemoriesRepository(conn)
            directory_deleted = repo.delete_by_prefix(
                self.user_id, self.tool_id, search_path
            )
            if directory_deleted > 0:
                return f"Deleted directory and {directory_deleted} file(s)."

            # Otherwise delete a single file
            file_deleted = repo.delete_by_path(
                self.user_id, self.tool_id, validated_path
            )

        if file_deleted:
            return f"Deleted: {validated_path}"
        return f"Error: File not found: {validated_path}"

    def _rename(self, old_path: str, new_path: str) -> str:
        """Rename or move a file/directory."""
        validated_old = self._validate_path(old_path)
        validated_new = self._validate_path(new_path)

        if not validated_old or not validated_new:
            return "Error: Invalid path."

        if validated_old == "/" or validated_new == "/":
            return "Error: Cannot rename root directory."

        # Directory rename: do all path updates inside one transaction so
        # the rename is atomic from the caller's perspective.
        if validated_old.endswith("/"):
            # Ensure validated_new also ends with / for proper path replacement
            if not validated_new.endswith("/"):
                validated_new = validated_new + "/"

            with db_session() as conn:
                repo = MemoriesRepository(conn)
                docs = repo.list_by_prefix(
                    self.user_id, self.tool_id, validated_old
                )

                if not docs:
                    return f"Error: Directory not found: {validated_old}"

                for doc in docs:
                    old_file_path = doc["path"]
                    new_file_path = old_file_path.replace(
                        validated_old, validated_new, 1
                    )
                    repo.update_path(
                        self.user_id, self.tool_id, old_file_path, new_file_path
                    )

            return f"Renamed directory: {validated_old} -> {validated_new} ({len(docs)} files)"

        # Single-file rename: lookup, collision check, and update in one txn.
        with db_session() as conn:
            repo = MemoriesRepository(conn)
            doc = repo.get_by_path(self.user_id, self.tool_id, validated_old)
            if not doc:
                return f"Error: File not found: {validated_old}"

            existing = repo.get_by_path(self.user_id, self.tool_id, validated_new)
            if existing:
                return f"Error: File already exists at {validated_new}"

            repo.update_path(
                self.user_id, self.tool_id, validated_old, validated_new
            )

        return f"Renamed: {validated_old} -> {validated_new}"
