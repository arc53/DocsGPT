import datetime
import uuid
from typing import Any, Dict, List, Optional
from application.core.mongo_db import MongoDB
from application.core.settings import settings

from .base import Tool


class TodoListTool(Tool):
    """
    Todo List Tool
    A simple MongoDB-backed todo list tool for agents to create, list, update, retrieve and delete todo items.
    Constructor accepts optional `tool_config` (may include `tool_id`) and
    optional `user_id` (decoded_token['sub']).
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None):
        self.user_id: Optional[str] = user_id
        self.tool_config = tool_config or {}

        if self.tool_config and "tool_id" in self.tool_config:
            self.tool_id = self.tool_config["tool_id"]
        elif self.user_id:
            self.tool_id = f"default_{self.user_id}"
        else:
            self.tool_id = str(uuid.uuid4())

        self.database_name = settings.MONGO_DB_NAME
        self.collection_name = "todos"
        self._client = None
        self._db = None
        self._col = None
        self._connect()

    def _connect(self):
        try:
            self._client = MongoDB.get_client()
            self._db = self._client[self.database_name]
            self._col = self._db[self.collection_name]
            self._col.create_index([("todo_id", 1)], unique=True)
            self._col.create_index([("user_id", 1), ("tool_id", 1)])
        except Exception:
            self._client = None
            self._db = None
            self._col = None

    def _ensure_connection(self):
        if self._col is None:
            self._connect()
            if self._col is None:
                raise RuntimeError("TodoListTool: no MongoDB connection available")

    def execute_action(self, action_name: str, **kwargs):
        actions = {
            "todo_create": self._create_todo,
            "todo_get": self._get_todo,
            "todo_list": self._get_todos,
            "todo_update": self._update_todo,
            "todo_delete": self._delete_todo,
        }
        if action_name not in actions:
            raise ValueError(f"Unknown action: {action_name}")
        if not self.user_id:
            return {"status_code": 401, "message": "user_id required"}

        return actions[action_name](**kwargs)

    # -----------------------------
    # Auto-incrementing todo_id
    # -----------------------------
    def _get_next_todo_id(self) -> int:
        latest = self._col.find(
            {"user_id": self.user_id, "tool_id": self.tool_id}
        ).sort("todo_id", -1).limit(1)

        try:
            max_id = int(next(latest)["todo_id"])
        except (StopIteration, KeyError, ValueError):
            max_id = 0

        return max_id + 1

    # -----------------------------
    # Actions
    # -----------------------------
    def _create_todo(self, title: str, description: str = "", due_date: Optional[str] = None, metadata: Optional[Dict] = None):
        self._ensure_connection()
        now = datetime.datetime.utcnow()
        todo_id = self._get_next_todo_id()

        doc = {
            "todo_id": todo_id,
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "title": title,
            "description": description,
            "status": "open",
            "metadata": metadata or {},
            "due_date": due_date,
            "created_at": now,
            "updated_at": now,
        }
        self._col.insert_one(doc)
        return {"status_code": 201, "message": "Todo created", "todo_id": todo_id}

    def _get_todo(self, todo_id: int):
        self._ensure_connection()
        doc = self._col.find_one({
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "todo_id": todo_id
        })
        if not doc:
            return {"status_code": 404, "message": "Todo not found"}
        doc.pop("_id", None)
        self._format_timestamps(doc)
        return {"status_code": 200, "todo": doc}

    def _get_todos(self):
        self._ensure_connection()
        cursor = self._col.find({"user_id": self.user_id, "tool_id": self.tool_id})
        todos = []
        for doc in cursor:
            doc.pop("_id", None)
            self._format_timestamps(doc)
            todos.append(doc)
        return {"status_code": 200, "todos": todos}

    def _update_todo(self, todo_id: int, updates: Dict[str, Any]):
        self._ensure_connection()
        allowed = {"title", "description", "status", "due_date", "metadata"}
        set_fields = {k: v for k, v in updates.items() if k in allowed}
        if not set_fields:
            return {"status_code": 400, "message": "No valid fields to update"}
        set_fields["updated_at"] = datetime.datetime.utcnow()
        result = self._col.update_one(
            {"user_id": self.user_id, "tool_id": self.tool_id, "todo_id": todo_id},
            {"$set": set_fields}
        )
        if result.matched_count == 0:
            return {"status_code": 404, "message": "Todo not found"}
        return {"status_code": 200, "message": "Todo updated"}

    def _delete_todo(self, todo_id: int):
        self._ensure_connection()
        result = self._col.delete_one({
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "todo_id": todo_id
        })
        if result.deleted_count == 0:
            return {"status_code": 404, "message": "Todo not found"}
        return {"status_code": 200, "message": "Todo deleted"}

    def _format_timestamps(self, doc: Dict[str, Any]):
        for field in ["created_at", "updated_at"]:
            if field in doc and isinstance(doc[field], datetime.datetime):
                utc_dt = doc[field].astimezone(datetime.timezone.utc)
                doc[field] = utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "todo_create",
                "description": "Create a new todo item for the user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "due_date": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_get",
                "description": "Get a specific todo by todo_id",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {"type": "integer"},
                    },
                    "required": ["todo_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_list",
                "description": "List all todos for this tool",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_update",
                "description": "Update a todo's fields by todo_id",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {"type": "integer"},
                        "updates": {"type": "object"},
                    },
                    "required": ["todo_id", "updates"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_delete",
                "description": "Delete a specific todo by todo_id",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {"type": "integer"},
                    },
                    "required": ["todo_id"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        return {}