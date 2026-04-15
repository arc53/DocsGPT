"""API-specific test fixtures."""

import uuid

import pytest


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
        "_id": uuid.uuid4().hex,
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
        "_id": uuid.uuid4().hex,
        "user": "test_user",
        "name": "Helpful Assistant",
        "content": "You are a helpful assistant that provides clear and concise answers.",
        "type": "custom",
    }


@pytest.fixture
def sample_agent():
    return {
        "_id": uuid.uuid4().hex,
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


@pytest.fixture
def mock_mongo_db():
    """Compatibility shim for tests written against the old mongomock fixture.

    The canonical ``mock_mongo_db`` fixture was removed when the answer pipeline
    moved from Mongo to Postgres (see tests/conftest.py docstring). Most API
    tests that still request it only do so as a historical gate: they patch
    specific mongo collections (``agents_collection``, etc.) via
    ``unittest.mock.patch`` inside the test body and never touch the fixture's
    return value. Yielding ``None`` keeps those tests runnable without
    reintroducing mongomock. Tests that actually need a working Mongo client
    (e.g. ones that call ``MongoDB.get_client()``) will still fail; skip or
    rewrite those per-case rather than reviving a global fake.
    """
    yield None
