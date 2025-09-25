import datetime
import uuid
from typing import Any, Dict, List, Optional
from application.core.mongo_db import MongoDB
from application.core.settings import settings

from application.agents.tools.base import Tool


class TodoListTool(Tool):
    """
    Todo List Tool
    A simple MongoDB-backed todo list tool for agents to create, list, update, retrieve and delete todo items.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.database_name = self.config.get("database", settings.MONGO_DB_NAME)
        self.collection_name = self.config.get("collection", "todos")
        self._client = None
        self._db = None
        self._col = None
        self._connect()

    def _connect(self):
        try:
            self._client = MongoDB.get_client()
            self._db = self._client[self.database_name]
            self._col = self._db[self.collection_name]
            # Ensure an index on user_id and created_at for common queries
            self._col.create_index([("user_id", 1)])
            self._col.create_index([("created_at", -1)])
        except Exception as e:
            # Lazy failure: keep attributes None and surface errors on operations
            self._client = None
            self._db = None
            self._col = None
            print(f"TodoListTool: failed to connect to MongoDB: {e}")

    def _ensure_connection(self):
        if not self._col:
            self._connect()
            if not self._col:
                raise RuntimeError("TodoListTool: no MongoDB connection available")

    def execute_action(self, action_name: str, **kwargs):
        actions = {
            "todo_create": self._create_todo,
            "todo_list": self._list_todos,
            "todo_get": self._get_todo,
            "todo_update": self._update_todo,
            "todo_delete": self._delete_todo,
            "todo_clear": self._clear_todos,
        }
        if action_name in actions:
            try:
                return actions[action_name](**kwargs)
            except Exception as e:
                return {"status_code": 500, "message": str(e)}
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _create_todo(
        self,
        user_id: str,
        title: str,
        description: str = "",
        due_date: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        """Create a new todo item for a user."""
        self._ensure_connection()
        todo_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)
        doc = {
            "_id": todo_id,
            "user_id": user_id,
            "title": title,
            "description": description,
            "status": "open",
            "metadata": metadata or {},
            "due_date": due_date,
            "created_at": now,
            "updated_at": now,
        }
        self._col.insert_one(doc)
        # Convert datetimes to ISO for returning
        doc["created_at"] = doc["created_at"].isoformat() + "Z"
        doc["updated_at"] = doc["updated_at"].isoformat() + "Z"
        return {"status_code": 201, "message": "Todo created", "todo": doc}

    def _list_todos(
        self,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        since: Optional[str] = None,
    ):
        """List todos for a user, optionally filtered by status or since a given ISO timestamp."""
        self._ensure_connection()
        query = {"user_id": user_id}
        if status:
            query["status"] = status
        if since:
            try:
                since_dt = datetime.datetime.fromisoformat(since.replace("Z", ""))
                query["updated_at"] = {"$gte": since_dt}
            except (ValueError, TypeError):
                pass
        cursor = self._col.find(query).sort("created_at", -1).limit(int(limit))
        results: List[Dict] = []
        for doc in cursor:
            doc["created_at"] = doc["created_at"].isoformat() + "Z"
            doc["updated_at"] = doc["updated_at"].isoformat() + "Z"
            results.append(doc)
        return {"status_code": 200, "todos": results}

    def _get_todo(self, user_id: str, todo_id: str):
        """Retrieve a single todo by id for a user."""
        self._ensure_connection()
        doc = self._col.find_one({"_id": todo_id, "user_id": user_id})
        if not doc:
            return {"status_code": 404, "message": "Todo not found"}
        doc["created_at"] = doc["created_at"].isoformat() + "Z"
        doc["updated_at"] = doc["updated_at"].isoformat() + "Z"
        return {"status_code": 200, "todo": doc}

    def _update_todo(self, user_id: str, todo_id: str, updates: Dict[str, Any]):
        """Update fields on a todo. Allowed fields: title, description, status, due_date, metadata."""
        self._ensure_connection()
        allowed = {"title", "description", "status", "due_date", "metadata"}
        set_fields = {k: v for k, v in updates.items() if k in allowed}
        if not set_fields:
            return {"status_code": 400, "message": "No valid fields to update"}
        set_fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        result = self._col.update_one(
            {"_id": todo_id, "user_id": user_id}, {"$set": set_fields}
        )
        if result.matched_count == 0:
            return {"status_code": 404, "message": "Todo not found"}
        doc = self._col.find_one({"_id": todo_id, "user_id": user_id})
        doc["created_at"] = doc["created_at"].isoformat() + "Z"
        doc["updated_at"] = doc["updated_at"].isoformat() + "Z"
        return {"status_code": 200, "message": "Todo updated", "todo": doc}

    def _delete_todo(self, user_id: str, todo_id: str):
        self._ensure_connection()
        result = self._col.delete_one({"_id": todo_id, "user_id": user_id})
        if result.deleted_count == 0:
            return {"status_code": 404, "message": "Todo not found"}
        return {"status_code": 200, "message": "Todo deleted"}

    def _clear_todos(self, user_id: str):
        """Delete all todos for a user. Use with caution."""
        self._ensure_connection()
        result = self._col.delete_many({"user_id": user_id})
        return {"status_code": 200, "message": f"Deleted {result.deleted_count} todos"}

    def get_actions_metadata(self):
        return [
            {
                "name": "todo_create",
                "description": "Create a new todo item for the user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "due_date": {
                            "type": "string",
                            "description": "ISO date string",
                        },
                        "metadata": {"type": "object"},
                    },
                    "required": ["user_id", "title"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_list",
                "description": "List todos for a user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "status": {"type": "string"},
                        "limit": {"type": "integer"},
                        "since": {"type": "string"},
                    },
                    "required": ["user_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_get",
                "description": "Get a single todo by id",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "todo_id": {"type": "string"},
                    },
                    "required": ["user_id", "todo_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_update",
                "description": "Update a todo's fields",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "todo_id": {"type": "string"},
                        "updates": {"type": "object"},
                    },
                    "required": ["user_id", "todo_id", "updates"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_delete",
                "description": "Delete a todo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "todo_id": {"type": "string"},
                    },
                    "required": ["user_id", "todo_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "todo_clear",
                "description": "Delete all todos for a user",
                "parameters": {
                    "type": "object",
                    "properties": {"user_id": {"type": "string"}},
                    "required": ["user_id"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        return {
            "mongo_uri": {"type": "string", "description": "MongoDB connection URI"},
            "database": {"type": "string", "description": "MongoDB database name"},
            "collection": {
                "type": "string",
                "description": "MongoDB collection name for todos",
            },
        }
