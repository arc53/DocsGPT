from unittest.mock import Mock

import pytest
from application.core.settings import settings


@pytest.fixture
def mock_llm():
    llm = Mock()
    llm.gen_stream = Mock()
    llm._supports_tools = True
    llm._supports_structured_output = Mock(return_value=False)
    llm.__class__.__name__ = "MockLLM"
    return llm


@pytest.fixture
def mock_llm_handler():
    handler = Mock()
    handler.process_message_flow = Mock()
    return handler


@pytest.fixture
def mock_retriever():
    retriever = Mock()
    retriever.search = Mock(
        return_value=[
            {"text": "Test document 1", "filename": "doc1.txt", "source": "test"},
            {"text": "Test document 2", "title": "doc2.txt", "source": "test"},
        ]
    )
    return retriever


@pytest.fixture
def mock_mongo_db(monkeypatch):
    fake_collection = FakeMongoCollection()
    fake_db = {
        "agents": fake_collection,
        "user_tools": fake_collection,
        "memories": fake_collection,
    }
    fake_client = {settings.MONGO_DB_NAME: fake_db}

    monkeypatch.setattr(
        "application.core.mongo_db.MongoDB.get_client", lambda: fake_client
    )
    return fake_client


@pytest.fixture
def sample_chat_history():
    return [
        {"prompt": "What is Python?", "response": "Python is a programming language."},
        {"prompt": "Tell me more.", "response": "Python is known for simplicity."},
    ]


@pytest.fixture
def sample_tool_call():
    return {
        "tool_name": "test_tool",
        "call_id": "123",
        "action_name": "test_action",
        "arguments": {"arg1": "value1"},
        "result": "Tool executed successfully",
    }


@pytest.fixture
def decoded_token():
    return {"sub": "test_user", "email": "test@example.com"}


@pytest.fixture
def log_context():
    from application.logging import LogContext

    context = LogContext(
        endpoint="test_endpoint",
        activity_id="test_activity",
        user="test_user",
        api_key="test_key",
        query="test query",
    )
    return context


class FakeMongoCollection:
    def __init__(self):
        self.docs = {}

    def find_one(self, query, projection=None):
        if "key" in query:
            return self.docs.get(query["key"])
        if "_id" in query:
            return self.docs.get(str(query["_id"]))
        if "user" in query:
            for doc in self.docs.values():
                if doc.get("user") == query["user"]:
                    return doc
        return None

    def find(self, query, projection=None):
        results = []
        if "_id" in query and "$in" in query["_id"]:
            for doc_id in query["_id"]["$in"]:
                doc = self.docs.get(str(doc_id))
                if doc:
                    results.append(doc)
        elif "user" in query:
            for doc in self.docs.values():
                if doc.get("user") == query["user"]:
                    if "status" in query:
                        if doc.get("status") == query["status"]:
                            results.append(doc)
                    else:
                        results.append(doc)
        return results

    def insert_one(self, doc):
        doc_id = doc.get("_id", len(self.docs))
        self.docs[str(doc_id)] = doc
        return Mock(inserted_id=doc_id)

    def update_one(self, query, update, upsert=False):
        return Mock(modified_count=1)

    def delete_one(self, query):
        return Mock(deleted_count=1)

    def delete_many(self, query):
        return Mock(deleted_count=0)


@pytest.fixture
def mock_llm_creator(mock_llm, monkeypatch):
    monkeypatch.setattr(
        "application.llm.llm_creator.LLMCreator.create_llm", Mock(return_value=mock_llm)
    )
    return mock_llm


@pytest.fixture
def mock_llm_handler_creator(mock_llm_handler, monkeypatch):
    monkeypatch.setattr(
        "application.llm.handlers.handler_creator.LLMHandlerCreator.create_handler",
        Mock(return_value=mock_llm_handler),
    )
    return mock_llm_handler


@pytest.fixture
def agent_base_params(decoded_token):
    return {
        "endpoint": "https://api.example.com",
        "llm_name": "openai",
        "gpt_model": "gpt-4",
        "api_key": "test_api_key",
        "user_api_key": None,
        "prompt": "You are a helpful assistant.",
        "chat_history": [],
        "decoded_token": decoded_token,
        "attachments": [],
        "json_schema": None,
    }


@pytest.fixture
def mock_tool():
    tool = Mock()
    tool.execute_action = Mock(return_value="Tool result")
    tool.get_actions_metadata = Mock(
        return_value=[
            {
                "name": "test_action",
                "description": "A test action",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string", "description": "Test parameter"}
                    },
                    "required": ["param1"],
                },
            }
        ]
    )
    return tool


@pytest.fixture
def mock_tool_manager(mock_tool, monkeypatch):
    manager = Mock()
    manager.load_tool = Mock(return_value=mock_tool)
    monkeypatch.setattr(
        "application.agents.base.ToolManager", Mock(return_value=manager)
    )
    return manager
