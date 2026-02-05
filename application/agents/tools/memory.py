from datetime import datetime
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
import re
import uuid

from .base import Tool
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.storage.storage_creator import StorageCreator
from application.utils import safe_filename


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

        if tool_config and "tool_id" in tool_config:
            self.tool_id = tool_config["tool_id"]
        elif user_id:
            self.tool_id = f"default_{user_id}"
        else:
            self.tool_id = str(uuid.uuid4())

        db = MongoDB.get_client()[settings.MONGO_DB_NAME]
        self.collection = db["memories"]
        self.storage = StorageCreator.get_storage()

    def _get_storage_path(self, path: str) -> str:
        """Get the storage path for a file.

        Constructs path: {UPLOAD_FOLDER}/{safe_user_id}/memories/{safe_tool_id}/{path}
        """
        safe_user = safe_filename(self.user_id)
        safe_tool = safe_filename(self.tool_id)
        upload_folder = getattr(settings, "UPLOAD_FOLDER", "uploads").rstrip("/")
        relative_path = path.lstrip("/")
        return f"{upload_folder}/{safe_user}/memories/{safe_tool}/{relative_path}"

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

        # Find all files that start with this directory path
        query = {
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "path": {"$regex": f"^{re.escape(search_path)}"}
        }

        docs = list(self.collection.find(query, {"path": 1}))

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
        storage_path = self._get_storage_path(path)

        if not self.storage.file_exists(storage_path):
            return f"Error: File not found: {path}"

        try:
            file_obj = self.storage.get_file(storage_path)
            content = file_obj.read().decode("utf-8")
        except Exception:
            return f"Error: File not found: {path}"

        if view_range and len(view_range) == 2:
            lines = content.split("\n")
            start, end = view_range
            start_idx = max(0, start - 1)
            end_idx = min(len(lines), end)

            if start_idx >= len(lines):
                return f"Error: Line range out of bounds. File has {len(lines)} lines."

            selected_lines = lines[start_idx:end_idx]
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

        storage_path = self._get_storage_path(validated_path)
        file_data = io.BytesIO(file_text.encode("utf-8"))
        self.storage.save_file(file_data, storage_path)

        self.collection.update_one(
            {"user_id": self.user_id, "tool_id": self.tool_id, "path": validated_path},
            {
                "$set": {
                    "storage_path": storage_path,
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )

        return f"File created: {validated_path}"

    def _str_replace(self, path: str, old_str: str, new_str: str) -> str:
        """Replace text in a file."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        if not old_str:
            return "Error: old_str is required."

        storage_path = self._get_storage_path(validated_path)

        if not self.storage.file_exists(storage_path):
            return f"Error: File not found: {validated_path}"

        try:
            file_obj = self.storage.get_file(storage_path)
            current_content = file_obj.read().decode("utf-8")
        except Exception:
            return f"Error: File not found: {validated_path}"

        if old_str.lower() not in current_content.lower():
            return f"Error: String '{old_str}' not found in file."

        import re as regex_module
        updated_content = regex_module.sub(
            regex_module.escape(old_str), new_str, current_content, flags=regex_module.IGNORECASE
        )

        file_data = io.BytesIO(updated_content.encode("utf-8"))
        self.storage.save_file(file_data, storage_path)

        self.collection.update_one(
            {"user_id": self.user_id, "tool_id": self.tool_id, "path": validated_path},
            {"$set": {"updated_at": datetime.now()}}
        )

        return f"File updated: {validated_path}"

    def _insert(self, path: str, insert_line: int, insert_text: str) -> str:
        """Insert text at a specific line."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        if not insert_text:
            return "Error: insert_text is required."

        storage_path = self._get_storage_path(validated_path)

        if not self.storage.file_exists(storage_path):
            return f"Error: File not found: {validated_path}"

        try:
            file_obj = self.storage.get_file(storage_path)
            current_content = file_obj.read().decode("utf-8")
        except Exception:
            return f"Error: File not found: {validated_path}"

        lines = current_content.split("\n")
        index = insert_line - 1
        if index < 0 or index > len(lines):
            return f"Error: Invalid line number. File has {len(lines)} lines."

        lines.insert(index, insert_text)
        updated_content = "\n".join(lines)

        file_data = io.BytesIO(updated_content.encode("utf-8"))
        self.storage.save_file(file_data, storage_path)

        self.collection.update_one(
            {"user_id": self.user_id, "tool_id": self.tool_id, "path": validated_path},
            {"$set": {"updated_at": datetime.now()}}
        )

        return f"Text inserted at line {insert_line} in {validated_path}"

    def _delete(self, path: str) -> str:
        """Delete a file or directory."""
        validated_path = self._validate_path(path)
        if not validated_path:
            return "Error: Invalid path."

        if validated_path == "/":
            docs = list(self.collection.find(
                {"user_id": self.user_id, "tool_id": self.tool_id}, {"path": 1}
            ))
            for doc in docs:
                storage_path = self._get_storage_path(doc["path"])
                self.storage.delete_file(storage_path)
            result = self.collection.delete_many({"user_id": self.user_id, "tool_id": self.tool_id})
            return f"Deleted {result.deleted_count} file(s) from memory."

        if validated_path.endswith("/"):
            docs = list(self.collection.find({
                "user_id": self.user_id,
                "tool_id": self.tool_id,
                "path": {"$regex": f"^{re.escape(validated_path)}"}
            }, {"path": 1}))
            for doc in docs:
                storage_path = self._get_storage_path(doc["path"])
                self.storage.delete_file(storage_path)
            result = self.collection.delete_many({
                "user_id": self.user_id,
                "tool_id": self.tool_id,
                "path": {"$regex": f"^{re.escape(validated_path)}"}
            })
            return f"Deleted directory and {result.deleted_count} file(s)."

        search_path = validated_path + "/"
        docs = list(self.collection.find({
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "path": {"$regex": f"^{re.escape(search_path)}"}
        }, {"path": 1}))

        if docs:
            for doc in docs:
                storage_path = self._get_storage_path(doc["path"])
                self.storage.delete_file(storage_path)
            directory_result = self.collection.delete_many({
                "user_id": self.user_id,
                "tool_id": self.tool_id,
                "path": {"$regex": f"^{re.escape(search_path)}"}
            })
            return f"Deleted directory and {directory_result.deleted_count} file(s)."

        storage_path = self._get_storage_path(validated_path)
        if self.storage.file_exists(storage_path):
            self.storage.delete_file(storage_path)
            self.collection.delete_one({
                "user_id": self.user_id,
                "tool_id": self.tool_id,
                "path": validated_path
            })
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

        if validated_old.endswith("/"):
            if not validated_new.endswith("/"):
                validated_new = validated_new + "/"

            docs = list(self.collection.find({
                "user_id": self.user_id,
                "tool_id": self.tool_id,
                "path": {"$regex": f"^{re.escape(validated_old)}"}
            }))

            if not docs:
                return f"Error: Directory not found: {validated_old}"

            for doc in docs:
                old_file_path = doc["path"]
                new_file_path = old_file_path.replace(validated_old, validated_new, 1)

                old_storage_path = self._get_storage_path(old_file_path)
                new_storage_path = self._get_storage_path(new_file_path)

                if self.storage.file_exists(old_storage_path):
                    file_obj = self.storage.get_file(old_storage_path)
                    content = file_obj.read()
                    file_data = io.BytesIO(content)
                    self.storage.save_file(file_data, new_storage_path)
                    self.storage.delete_file(old_storage_path)

                self.collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {
                        "path": new_file_path,
                        "storage_path": new_storage_path,
                        "updated_at": datetime.now()
                    }}
                )

            return f"Renamed directory: {validated_old} -> {validated_new} ({len(docs)} files)"

        old_storage_path = self._get_storage_path(validated_old)
        new_storage_path = self._get_storage_path(validated_new)

        if not self.storage.file_exists(old_storage_path):
            return f"Error: File not found: {validated_old}"

        if self.storage.file_exists(new_storage_path):
            return f"Error: File already exists at {validated_new}"

        file_obj = self.storage.get_file(old_storage_path)
        content = file_obj.read()
        file_data = io.BytesIO(content)
        self.storage.save_file(file_data, new_storage_path)
        self.storage.delete_file(old_storage_path)

        self.collection.delete_one({"user_id": self.user_id, "tool_id": self.tool_id, "path": validated_old})
        self.collection.insert_one({
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "path": validated_new,
            "storage_path": new_storage_path,
            "updated_at": datetime.now()
        })

        return f"Renamed: {validated_old} -> {validated_new}"
