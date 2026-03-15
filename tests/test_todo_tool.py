import pytest
from application.agents.tools.todo_list import TodoListTool
from application.core.settings import settings


class FakeCursor(list):
    def sort(self, key, direction):
        reverse = direction == -1
        sorted_list = sorted(self, key=lambda d: d.get(key, 0), reverse=reverse)
        return FakeCursor(sorted_list)

    def limit(self, count):
        return FakeCursor(self[:count])

    def __iter__(self):
        return self

    def __next__(self):
        if not self:
            raise StopIteration
        return self.pop(0)


class FakeCollection:
    def __init__(self):
        self.docs = {}
        self._id_counter = 0

    def _generate_id(self):
        self._id_counter += 1
        return f"fake_id_{self._id_counter}"

    def create_index(self, *args, **kwargs):
        pass

    def insert_one(self, doc):
        key = (doc["user_id"], doc["tool_id"], doc["todo_id"])
        if "_id" not in doc:
            doc["_id"] = self._generate_id()
        self.docs[key] = doc
        return type("res", (), {"inserted_id": doc["_id"]})

    def find_one(self, query):
        key = (query.get("user_id"), query.get("tool_id"), query.get("todo_id"))
        return self.docs.get(key)

    def find(self, query, projection=None):
        user_id = query.get("user_id")
        tool_id = query.get("tool_id")
        filtered = [
            doc for (uid, tid, _), doc in self.docs.items()
            if uid == user_id and tid == tool_id
        ]
        return FakeCursor(filtered)

    def update_one(self, query, update, upsert=False):
        key = (query.get("user_id"), query.get("tool_id"), query.get("todo_id"))
        if key in self.docs:
            self.docs[key].update(update.get("$set", {}))
            return type("res", (), {"matched_count": 1})
        elif upsert:
            new_doc = {**query, **update.get("$set", {}), "_id": self._generate_id()}
            self.docs[key] = new_doc
            return type("res", (), {"matched_count": 1})
        else:
            return type("res", (), {"matched_count": 0})

    def find_one_and_update(self, query, update):
        key = (query.get("user_id"), query.get("tool_id"), query.get("todo_id"))
        if key in self.docs:
            self.docs[key].update(update.get("$set", {}))
            return self.docs[key]
        return None

    def find_one_and_delete(self, query):
        key = (query.get("user_id"), query.get("tool_id"), query.get("todo_id"))
        if key in self.docs:
            return self.docs.pop(key)
        return None

    def delete_one(self, query):
        key = (query.get("user_id"), query.get("tool_id"), query.get("todo_id"))
        if key in self.docs:
            del self.docs[key]
            return type("res", (), {"deleted_count": 1})
        return type("res", (), {"deleted_count": 0})


@pytest.fixture
def todo_tool(monkeypatch) -> TodoListTool:
    """Provides a TodoListTool with a fake MongoDB backend."""
    # Reset the MongoDB client cache to ensure our mock is used
    from application.core.mongo_db import MongoDB
    MongoDB._client = None

    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)
    return TodoListTool({"tool_id": "test_tool"}, user_id="test_user")


def test_create_and_get(todo_tool: TodoListTool):
    res = todo_tool.execute_action("create", title="Write tests")
    assert "Todo created with ID" in res
    # Extract todo_id from response like "Todo created with ID test_user_test_tool_1: Write tests"
    todo_id = res.split("ID ")[1].split(":")[0].strip()

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "Error" not in get_res
    assert "Write tests" in get_res


def test_get_all_todos(todo_tool: TodoListTool):
    todo_tool.execute_action("create", title="Task 1")
    todo_tool.execute_action("create", title="Task 2")

    list_res = todo_tool.execute_action("list")
    assert "Task 1" in list_res
    assert "Task 2" in list_res


def test_update_todo(todo_tool: TodoListTool):
    create_res = todo_tool.execute_action("create", title="Initial Title")
    todo_id = create_res.split("ID ")[1].split(":")[0].strip()

    update_res = todo_tool.execute_action("update", todo_id=todo_id, title="Updated Title")
    assert "updated" in update_res.lower()
    assert "Updated Title" in update_res

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "Updated Title" in get_res


def test_complete_todo(todo_tool: TodoListTool):
    create_res = todo_tool.execute_action("create", title="To Complete")
    todo_id = create_res.split("ID ")[1].split(":")[0].strip()

    # Check initial status is open
    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "open" in get_res

    # Mark as completed
    complete_res = todo_tool.execute_action("complete", todo_id=todo_id)
    assert "completed" in complete_res.lower()

    # Verify status changed to completed
    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "completed" in get_res


def test_delete_todo(todo_tool: TodoListTool):
    create_res = todo_tool.execute_action("create", title="To Delete")
    todo_id = create_res.split("ID ")[1].split(":")[0].strip()

    delete_res = todo_tool.execute_action("delete", todo_id=todo_id)
    assert "deleted" in delete_res.lower()

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "Error" in get_res
    assert "not found" in get_res


def test_isolation_and_default_tool_id(monkeypatch):
    """Ensure todos are isolated by tool_id and user_id."""
    # Reset the MongoDB client cache to ensure our mock is used
    from application.core.mongo_db import MongoDB
    MongoDB._client = None

    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)

    # Same user, different tool_id
    tool1 = TodoListTool({"tool_id": "tool_1"}, user_id="u1")
    tool2 = TodoListTool({"tool_id": "tool_2"}, user_id="u1")

    r1_create = tool1.execute_action("create", title="from tool 1")
    r2_create = tool2.execute_action("create", title="from tool 2")

    todo_id_1 = r1_create.split("ID ")[1].split(":")[0].strip()
    todo_id_2 = r2_create.split("ID ")[1].split(":")[0].strip()

    r1 = tool1.execute_action("get", todo_id=todo_id_1)
    r2 = tool2.execute_action("get", todo_id=todo_id_2)

    assert "Error" not in r1
    assert "from tool 1" in r1

    assert "Error" not in r2
    assert "from tool 2" in r2

    # Same user, no tool_id → should default to same value
    t3 = TodoListTool({}, user_id="default_user")
    t4 = TodoListTool({}, user_id="default_user")

    assert t3.tool_id == "default_default_user"
    assert t4.tool_id == "default_default_user"

    create_res = t3.execute_action("create", title="shared default")
    todo_id = create_res.split("ID ")[1].split(":")[0].strip()
    r = t4.execute_action("get", todo_id=todo_id)

    assert "Error" not in r
    assert "shared default" in r
