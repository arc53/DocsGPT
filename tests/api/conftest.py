"""API-specific test fixtures."""

import pytest
from bson import ObjectId


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def mock_request_token(monkeypatch, decoded_token):
    def mock_decorator(f):
        def wrapper(*args, **kwargs):
            from flask import request

            request.decoded_token = decoded_token
            return f(*args, **kwargs)

        return wrapper

    monkeypatch.setattr("application.auth.api_key_required", lambda: mock_decorator)
    return decoded_token


@pytest.fixture
def sample_conversation():
    return {
        "_id": ObjectId(),
        "user": "test_user",
        "name": "Test Conversation",
        "queries": [
            {
                "prompt": "What is Python?",
                "response": "Python is a programming language",
            }
        ],
        "date": "2025-01-01T00:00:00",
    }


@pytest.fixture
def sample_prompt():
    return {
        "_id": ObjectId(),
        "user": "test_user",
        "name": "Helpful Assistant",
        "content": "You are a helpful assistant that provides clear and concise answers.",
        "type": "custom",
    }


@pytest.fixture
def sample_agent():
    return {
        "_id": ObjectId(),
        "user": "test_user",
        "name": "Test Agent",
        "type": "classic",
        "endpoint": "openai",
        "model": "gpt-4",
        "prompt_id": "default",
        "status": "active",
    }


@pytest.fixture
def sample_answer_request():
    return {
        "question": "What is Python?",
        "history": [],
        "conversation_id": None,
        "prompt_id": "default",
        "chunks": 2,
        "retriever": "classic_rag",
        "active_docs": "local/test/",
        "isNoneDoc": False,
        "save_conversation": True,
    }


@pytest.fixture
def flask_app():
    from flask import Flask

    app = Flask(__name__)
    return app
