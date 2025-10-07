import pytest
from application.agents.tools.todo_list import TodoListTool
from application.core.settings import settings

@pytest.fixture
def todo_tool(monkeypatch) -> TodoListTool:
    """Provides a TodoListTool with fake MongoDB and fixed user/tool IDs."""

    class FakeCollection:
        def __init__(self):
            self.doc = None

        def create_index(self, *args, **kwargs):
            pass

        def insert_one(self, doc):
            self.doc = doc
            return type("res", (), {"inserted_id": doc.get("_id", "fake_id")})

        def find_one(self, query):
            if not self.doc:
                return None
            if self.doc.get("user_id") == query.get("user_id") and self.doc.get("tool_id") == query.get("tool_id"):
                return self.doc
            return None

        def update_one(self, query, update, upsert=False):
            if self.doc is None and upsert:
                # Create new doc by merging query and update["$set"]
                self.doc = {**query, **update.get("$set", {})}
                return type("res", (), {"matched_count": 1})
            elif self.doc and self.doc.get("user_id") == query.get("user_id") and self.doc.get("tool_id") == query.get("tool_id"):
                self.doc.update(update.get("$set", {}))
                return type("res", (), {"matched_count": 1})
            else:
                return type("res", (), {"matched_count": 0})

        def delete_one(self, query):
            if not self.doc:
                return type("res", (), {"deleted_count": 0})
            if self.doc.get("user_id") == query.get("user_id") and self.doc.get("tool_id") == query.get("tool_id"):
                self.doc = None
                return type("res", (), {"deleted_count": 1})
            return type("res", (), {"deleted_count": 0})

    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}

    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)

    return TodoListTool({"tool_id": "test_tool"}, user_id="test_user")


def test_create_and_get(todo_tool: TodoListTool):
    res = todo_tool.execute_action("todo_create", title="Write tests", description="Write pytest cases")
    assert res["status_code"] == 201

    get_res = todo_tool.execute_action("todo_get")
    assert get_res["status_code"] == 200
    assert get_res["todo"]["title"] == "Write tests"


def test_update_todo(todo_tool: TodoListTool):
    todo_tool.execute_action("todo_create", title="Initial Title")

    update_res = todo_tool.execute_action("todo_update", updates={"title": "Updated Title", "status": "done"})
    assert update_res["status_code"] == 200

    get_res = todo_tool.execute_action("todo_get")
    assert get_res["todo"]["title"] == "Updated Title"
    assert get_res["todo"]["status"] == "done"


def test_delete_todo(todo_tool: TodoListTool):
    todo_tool.execute_action("todo_create", title="To Delete")

    delete_res = todo_tool.execute_action("todo_delete")
    assert delete_res["status_code"] == 200

    get_res = todo_tool.execute_action("todo_get")
    assert get_res["status_code"] == 404


def test_isolation_and_default_tool_id(monkeypatch):
    class FakeCollection:
        def __init__(self):
            self.docs = {}

        def create_index(self, *args, **kwargs):
            pass

        def insert_one(self, doc):
            key = (doc["user_id"], doc["tool_id"])
            self.docs[key] = doc
            return type("res", (), {"inserted_id": doc.get("_id", "fake_id")})

        def find_one(self, query):
            key = (query["user_id"], query["tool_id"])
            return self.docs.get(key)

        def update_one(self, query, update, upsert=False):
            key = (query["user_id"], query["tool_id"])
            if key not in self.docs and upsert:
                self.docs[key] = {**query, **update.get("$set", {})}
                return type("res", (), {"matched_count": 1})
            if key not in self.docs:
                return type("res", (), {"matched_count": 0})
            self.docs[key].update(update.get("$set", {}))
            return type("res", (), {"matched_count": 1})

        def delete_one(self, query):
            key = (query["user_id"], query["tool_id"])
            if key in self.docs:
                del self.docs[key]
                return type("res", (), {"deleted_count": 1})
            return type("res", (), {"deleted_count": 0})

    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}

    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)

    # Same user, different tool_id
    tool1 = TodoListTool({"tool_id": "tool_1"}, user_id="u1")
    tool2 = TodoListTool({"tool_id": "tool_2"}, user_id="u1")

    tool1.execute_action("todo_create", title="from tool 1")
    tool2.execute_action("todo_create", title="from tool 2")

    r1 = tool1.execute_action("todo_get")
    r2 = tool2.execute_action("todo_get")

    assert r1["todo"]["title"] == "from tool 1"
    assert r2["todo"]["title"] == "from tool 2"

    # Same user, no tool_id → should default to same value
    t3 = TodoListTool({}, user_id="default_user")
    t4 = TodoListTool({}, user_id="default_user")

    assert t3.tool_id == "default_default_user"
    assert t4.tool_id == "default_default_user"

    t3.execute_action("todo_create", title="shared default")
    r = t4.execute_action("todo_get")

    assert r["status_code"] == 200
    assert r["todo"]["title"] == "shared default"
