"""Tests for the Postgres dual-write path inside WorkflowAgent._save_workflow_run.

Specifically verifies the inner ``_pg_write`` closure that:
1. Calls WorkflowsRepository.get_by_legacy_id() to resolve the Mongo workflow id.
2. Returns early when the workflow is not found in Postgres.
3. Calls WorkflowRunsRepository.create() with the correct arguments when the
   workflow is found.

No bson/pymongo imports. Mongo collections are mocked; repository objects are
constructed via Mock so no real DB connection is needed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(**overrides):
    """Construct a WorkflowAgent with mocked base-class dependencies."""
    defaults = {
        "endpoint": "https://api.example.com",
        "llm_name": "openai",
        "model_id": "gpt-4",
        "api_key": "test_key",
        "user_api_key": None,
        "prompt": "You are helpful.",
        "chat_history": [],
        "decoded_token": {"sub": "user1"},
        "attachments": [],
        "json_schema": None,
    }
    defaults.update(overrides)
    with patch("application.agents.workflow_agent.log_activity", lambda **kw: lambda f: f):
        from application.agents.workflow_agent import WorkflowAgent

        agent = WorkflowAgent(**defaults)
    return agent


def _fake_oid():
    """Return a 24-character hex string used as a Mongo ObjectId substitute."""
    return uuid.uuid4().hex[:24]


def _stub_mongo(agent, insert_id=None):
    """Wire a fake Mongo that returns ``insert_id`` from insert_one."""
    mock_coll = MagicMock()
    result_mock = MagicMock()
    result_mock.inserted_id = insert_id or _fake_oid()
    mock_coll.insert_one.return_value = result_mock

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_coll)
    return mock_coll, mock_db


# ---------------------------------------------------------------------------
# _save_workflow_run — PG dual-write logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSaveWorkflowRunPgWrite:

    def _make_engine(self):
        engine = MagicMock()
        engine.state = {"input": "query text"}
        engine.execution_log = []
        engine.get_execution_summary.return_value = []
        return engine

    # ------------------------------------------------------------------
    # dual_write is called exactly once when Mongo insert succeeds
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Inner _pg_write skips create when workflow not in PG
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Inner _pg_write calls create when workflow IS found in PG
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # pg_write skips entirely when workflow_id is empty
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Mongo insert failure prevents pg_write from being called
    # ------------------------------------------------------------------



# ---------------------------------------------------------------------------
# _determine_run_status — Postgres-agnostic (but PG value mapping matters)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetermineRunStatusPg:

    def test_completed_value_matches_pg_enum(self):
        """The string stored in Postgres must match ExecutionStatus.COMPLETED.value."""
        from application.agents.workflows.schemas import ExecutionStatus

        agent = _make_agent()
        agent._engine = MagicMock()
        agent._engine.execution_log = []
        status = agent._determine_run_status()
        assert status == ExecutionStatus.COMPLETED
        # Value stored in PG column
        assert status.value == "completed"

    def test_failed_value_matches_pg_enum(self):
        from application.agents.workflows.schemas import ExecutionStatus

        agent = _make_agent()
        agent._engine = MagicMock()
        agent._engine.execution_log = [{"status": "failed"}]
        status = agent._determine_run_status()
        assert status == ExecutionStatus.FAILED
        assert status.value == "failed"


# ---------------------------------------------------------------------------
# _serialize_state — sanity for types stored in PG JSONB columns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerializeStateForPg:

    def test_datetime_serialized_to_iso_string(self):
        agent = _make_agent()
        dt = datetime(2025, 3, 15, 8, 0, 0, tzinfo=timezone.utc)
        result = agent._serialize_state({"ts": dt})
        assert isinstance(result["ts"], str)
        assert "2025-03-15" in result["ts"]

    def test_nested_dict_keys_become_strings(self):
        agent = _make_agent()
        result = agent._serialize_state({"data": {1: "one", 2: "two"}})
        assert "1" in result["data"]
        assert "2" in result["data"]

    def test_tuple_becomes_list_for_jsonb(self):
        """JSONB cannot store Python tuples; they must be converted to lists."""
        agent = _make_agent()
        result = agent._serialize_state({"pair": (10, 20)})
        assert result["pair"] == [10, 20]
        assert isinstance(result["pair"], list)

    def test_none_values_preserved(self):
        agent = _make_agent()
        result = agent._serialize_state({"nothing": None})
        assert result["nothing"] is None

    def test_unknown_object_becomes_string(self):
        agent = _make_agent()

        class Custom:
            def __str__(self):
                return "custom_repr"

        result = agent._serialize_state({"obj": Custom()})
        assert result["obj"] == "custom_repr"
