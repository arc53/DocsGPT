from unittest.mock import Mock

import mongomock

import pytest


def get_settings():
    """Lazy load settings to avoid import-time errors."""
    from application.core.settings import settings

    return settings


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
    """Mock MongoDB using mongomock - industry standard MongoDB mocking library."""
    settings = get_settings()

    mock_client = mongomock.MongoClient()
    mock_db = mock_client[settings.MONGO_DB_NAME]

    def get_mock_client():
        return {settings.MONGO_DB_NAME: mock_db}

    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", get_mock_client)

    monkeypatch.setattr("application.api.user.base.users_collection", mock_db["users"])
    monkeypatch.setattr(
        "application.api.user.base.user_tools_collection", mock_db["user_tools"]
    )
    monkeypatch.setattr(
        "application.api.user.base.agents_collection", mock_db["agents"]
    )
    monkeypatch.setattr(
        "application.api.user.base.conversations_collection", mock_db["conversations"]
    )
    monkeypatch.setattr(
        "application.api.user.base.sources_collection", mock_db["sources"]
    )
    monkeypatch.setattr(
        "application.api.user.base.prompts_collection", mock_db["prompts"]
    )
    monkeypatch.setattr(
        "application.api.user.base.feedback_collection", mock_db["feedback"]
    )
    monkeypatch.setattr(
        "application.api.user.base.token_usage_collection", mock_db["token_usage"]
    )
    monkeypatch.setattr(
        "application.api.user.base.attachments_collection", mock_db["attachments"]
    )
    monkeypatch.setattr(
        "application.api.user.base.user_logs_collection", mock_db["user_logs"]
    )
    monkeypatch.setattr(
        "application.api.user.base.shared_conversations_collections",
        mock_db["shared_conversations"],
    )

    return get_mock_client()


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
        "model_id": "gpt-4",
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
