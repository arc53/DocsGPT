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

    def create_index(self, *args, **kwargs):
        pass

    def insert_one(self, doc):
        key = (doc["user_id"], doc["tool_id"], int(doc["todo_id"]))
        self.docs[key] = doc
        return type("res", (), {"inserted_id": key})

    def find_one(self, query):
        key = (query.get("user_id"), query.get("tool_id"), int(query.get("todo_id")))
        return self.docs.get(key)

    def find(self, query):
        user_id = query.get("user_id")
        tool_id = query.get("tool_id")
        filtered = [
            doc for (uid, tid, _), doc in self.docs.items()
            if uid == user_id and tid == tool_id
        ]
        return FakeCursor(filtered)

    def update_one(self, query, update, upsert=False):
        key = (query.get("user_id"), query.get("tool_id"), int(query.get("todo_id")))
        if key in self.docs:
            self.docs[key].update(update.get("$set", {}))
            return type("res", (), {"matched_count": 1})
        elif upsert:
            new_doc = {**query, **update.get("$set", {})}
            self.docs[key] = new_doc
            return type("res", (), {"matched_count": 1})
        else:
            return type("res", (), {"matched_count": 0})

    def delete_one(self, query):
        key = (query.get("user_id"), query.get("tool_id"), int(query.get("todo_id")))
        if key in self.docs:
            del self.docs[key]
            return type("res", (), {"deleted_count": 1})
        return type("res", (), {"deleted_count": 0})


@pytest.fixture
def todo_tool(monkeypatch) -> TodoListTool:
    """Provides a TodoListTool with a fake MongoDB backend."""
    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)
    return TodoListTool({"tool_id": "test_tool"}, user_id="test_user")


def test_create_and_get(todo_tool: TodoListTool):
    res = todo_tool.execute_action("todo_create", title="Write tests", description="Write pytest cases")
    assert res["status_code"] == 201
    todo_id = res["todo_id"]

    get_res = todo_tool.execute_action("todo_get", todo_id=todo_id)
    assert get_res["status_code"] == 200
    assert get_res["todo"]["title"] == "Write tests"
    assert get_res["todo"]["description"] == "Write pytest cases"


def test_get_all_todos(todo_tool: TodoListTool):
    todo_tool.execute_action("todo_create", title="Task 1")
    todo_tool.execute_action("todo_create", title="Task 2")

    list_res = todo_tool.execute_action("todo_list")
    assert list_res["status_code"] == 200
    titles = [todo["title"] for todo in list_res["todos"]]
    assert "Task 1" in titles
    assert "Task 2" in titles


def test_update_todo(todo_tool: TodoListTool):
    create_res = todo_tool.execute_action("todo_create", title="Initial Title")
    todo_id = create_res["todo_id"]

    update_res = todo_tool.execute_action("todo_update", todo_id=todo_id, updates={"title": "Updated Title", "status": "done"})
    assert update_res["status_code"] == 200

    get_res = todo_tool.execute_action("todo_get", todo_id=todo_id)
    assert get_res["todo"]["title"] == "Updated Title"
    assert get_res["todo"]["status"] == "done"


def test_delete_todo(todo_tool: TodoListTool):
    create_res = todo_tool.execute_action("todo_create", title="To Delete")
    todo_id = create_res["todo_id"]

    delete_res = todo_tool.execute_action("todo_delete", todo_id=todo_id)
    assert delete_res["status_code"] == 200

    get_res = todo_tool.execute_action("todo_get", todo_id=todo_id)
    assert get_res["status_code"] == 404


def test_isolation_and_default_tool_id(monkeypatch):
    """Ensure todos are isolated by tool_id and user_id."""
    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)

    # Same user, different tool_id
    tool1 = TodoListTool({"tool_id": "tool_1"}, user_id="u1")
    tool2 = TodoListTool({"tool_id": "tool_2"}, user_id="u1")

    r1_create = tool1.execute_action("todo_create", title="from tool 1")
    r2_create = tool2.execute_action("todo_create", title="from tool 2")

    r1 = tool1.execute_action("todo_get", todo_id=r1_create["todo_id"])
    r2 = tool2.execute_action("todo_get", todo_id=r2_create["todo_id"])

    assert r1["status_code"] == 200
    assert r1["todo"]["title"] == "from tool 1"

    assert r2["status_code"] == 200
    assert r2["todo"]["title"] == "from tool 2"

    # Same user, no tool_id → should default to same value
    t3 = TodoListTool({}, user_id="default_user")
    t4 = TodoListTool({}, user_id="default_user")

    assert t3.tool_id == "default_default_user"
    assert t4.tool_id == "default_default_user"

    create_res = t3.execute_action("todo_create", title="shared default")
    r = t4.execute_action("todo_get", todo_id=create_res["todo_id"])

    assert r["status_code"] == 200
    assert r["todo"]["title"] == "shared default"
