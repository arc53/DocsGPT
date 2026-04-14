"""Root pytest fixtures for the DocsGPT backend suite.

Postgres fixture strategy
-------------------------

Regular unit tests get a Postgres connection from the ``pg_conn`` fixture
below, which is backed by ``pytest-postgresql``. That plugin spins up an
ephemeral ``pg_ctl``-managed cluster in a temp directory and tears it
down at the end of the session, so CI only needs Postgres *binaries*
installed, not a running service.

Tests under ``tests/storage/db/`` intentionally override ``pg_conn`` in
their own conftest to point at a real, long-running Postgres instance
(DBngin locally, a service container in CI). Those are integration/e2e
tests and are marked with ``@pytest.mark.integration``.

No mongomock. The ``mock_mongo_db`` fixture that used to live here was
removed as part of the Phase 4/5 Mongo→Postgres cutover. Tests that
still reference it will fail with "fixture not found" until the
corresponding route handler is migrated to a repository read.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from pytest_postgresql import factories
from sqlalchemy import create_engine


# ---------------------------------------------------------------------------
# Postgres fixtures (ephemeral cluster via pytest-postgresql)
# ---------------------------------------------------------------------------

# ``postgresql_proc`` starts a fresh ``pg_ctl`` cluster once per session.
# ``postgresql`` hands out a per-test DB on top of it. We layer our own
# SQLAlchemy engine + rolled-back transaction on top for test isolation.
postgresql_proc = factories.postgresql_proc()
postgresql = factories.postgresql("postgresql_proc")


def _sqlalchemy_url(pg_conn_info) -> str:
    return (
        "postgresql+psycopg://"
        f"{pg_conn_info.user}:{pg_conn_info.password or ''}"
        f"@{pg_conn_info.host}:{pg_conn_info.port}/{pg_conn_info.dbname}"
    )


@pytest.fixture(scope="session")
def _alembic_ini_path() -> Path:
    return Path(__file__).resolve().parent.parent / "application" / "alembic.ini"


@pytest.fixture()
def pg_engine(postgresql, _alembic_ini_path, monkeypatch):
    """Per-test SQLAlchemy engine against a fresh ephemeral Postgres DB.

    Alembic is run from scratch against the per-test database so the full
    schema is present. ``POSTGRES_URI`` is patched in the environment for
    the duration of the test so any code that reads it via
    ``application.core.settings`` sees the ephemeral DB.
    """
    url = _sqlalchemy_url(postgresql.info)
    monkeypatch.setenv("POSTGRES_URI", url)

    # Reset the settings cache so the new POSTGRES_URI is picked up if the
    # settings module is already imported.
    from application.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "POSTGRES_URI", url, raising=False)

    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini_path), "upgrade", "head"],
        timeout=60,
        env={**__import__("os").environ, "POSTGRES_URI": url},
    )

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_conn(pg_engine):
    """Per-test connection wrapped in a transaction that always rolls back."""
    conn = pg_engine.connect()
    txn = conn.begin()
    yield conn
    txn.rollback()
    conn.close()


# ---------------------------------------------------------------------------
# Generic unit-test fixtures (no DB, no Mongo)
# ---------------------------------------------------------------------------


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
        "application.agents.tool_executor.ToolManager", Mock(return_value=manager)
    )
    return manager


@pytest.fixture
def flask_app():
    from flask import Flask

    app = Flask(__name__)
    return app
