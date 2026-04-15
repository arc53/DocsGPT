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
from unittest.mock import MagicMock, Mock, patch

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

    def test_dual_write_called_when_mongo_insert_succeeds(self):
        agent = _make_agent(workflow_id=_fake_oid())
        agent._engine = self._make_engine()
        _, mock_db = _stub_mongo(agent)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings, \
             patch("application.agents.workflow_agent.dual_write") as mock_dw:
            mock_settings.MONGO_DB_NAME = "test"
            MockMongo.get_client.return_value = {"test": mock_db}
            agent._save_workflow_run("query text")

        mock_dw.assert_called_once()
        # The first positional arg should be the WorkflowRunsRepository class.
        from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository

        assert mock_dw.call_args[0][0] is WorkflowRunsRepository

    # ------------------------------------------------------------------
    # Inner _pg_write skips create when workflow not in PG
    # ------------------------------------------------------------------

    def test_pg_write_skips_when_workflow_not_found_in_pg(self):
        """_pg_write returns early if WorkflowsRepository.get_by_legacy_id is None."""
        agent = _make_agent(workflow_id=_fake_oid())
        agent._engine = self._make_engine()
        mongo_insert_id = _fake_oid()
        _, mock_db = _stub_mongo(agent, insert_id=mongo_insert_id)

        captured_pg_write = {}

        def capture_dual_write(repo_cls, fn):
            captured_pg_write["fn"] = fn

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings, \
             patch("application.agents.workflow_agent.dual_write", side_effect=capture_dual_write):
            mock_settings.MONGO_DB_NAME = "test"
            MockMongo.get_client.return_value = {"test": mock_db}
            agent._save_workflow_run("query text")

        # Now call the captured closure directly with a mock repo.
        mock_runs_repo = Mock()
        mock_runs_repo._conn = Mock()

        # WorkflowsRepository.get_by_legacy_id returns None → workflow missing.
        with patch(
            "application.agents.workflow_agent.WorkflowsRepository"
        ) as MockWfRepo:
            mock_wf_repo_instance = Mock()
            mock_wf_repo_instance.get_by_legacy_id.return_value = None
            MockWfRepo.return_value = mock_wf_repo_instance
            captured_pg_write["fn"](mock_runs_repo)

        mock_runs_repo.create.assert_not_called()

    # ------------------------------------------------------------------
    # Inner _pg_write calls create when workflow IS found in PG
    # ------------------------------------------------------------------

    def test_pg_write_calls_create_when_workflow_found(self):
        """_pg_write calls WorkflowRunsRepository.create with correct kwargs."""
        wf_legacy_id = _fake_oid()
        agent = _make_agent(workflow_id=wf_legacy_id)
        agent._engine = self._make_engine()
        mongo_insert_id = _fake_oid()
        _, mock_db = _stub_mongo(agent, insert_id=mongo_insert_id)

        captured_pg_write = {}

        def capture_dual_write(repo_cls, fn):
            captured_pg_write["fn"] = fn

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings, \
             patch("application.agents.workflow_agent.dual_write", side_effect=capture_dual_write):
            mock_settings.MONGO_DB_NAME = "test"
            MockMongo.get_client.return_value = {"test": mock_db}
            agent._save_workflow_run("query text")

        pg_workflow_uuid = str(uuid.uuid4())
        mock_runs_repo = Mock()
        mock_runs_repo._conn = Mock()

        with patch(
            "application.agents.workflow_agent.WorkflowsRepository"
        ) as MockWfRepo:
            mock_wf_repo_instance = Mock()
            mock_wf_repo_instance.get_by_legacy_id.return_value = {"id": pg_workflow_uuid}
            MockWfRepo.return_value = mock_wf_repo_instance
            captured_pg_write["fn"](mock_runs_repo)

        mock_runs_repo.create.assert_called_once()
        create_kwargs = mock_runs_repo.create.call_args
        # Positional: workflow_id, user_id, status
        args = create_kwargs[0]
        assert args[0] == pg_workflow_uuid
        assert args[1] == "user1"  # decoded_token["sub"]

    # ------------------------------------------------------------------
    # pg_write skips entirely when workflow_id is empty
    # ------------------------------------------------------------------

    def test_pg_write_skips_when_no_workflow_id(self):
        """If workflow_id is not set, the inner _pg_write returns immediately."""
        agent = _make_agent()  # no workflow_id
        agent._engine = self._make_engine()
        _, mock_db = _stub_mongo(agent)

        captured_pg_write = {}

        def capture_dual_write(repo_cls, fn):
            captured_pg_write["fn"] = fn

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings, \
             patch("application.agents.workflow_agent.dual_write", side_effect=capture_dual_write):
            mock_settings.MONGO_DB_NAME = "test"
            MockMongo.get_client.return_value = {"test": mock_db}
            agent._save_workflow_run("query text")

        if "fn" not in captured_pg_write:
            # dual_write was not called; that is also acceptable behaviour.
            return

        mock_runs_repo = Mock()
        mock_runs_repo._conn = Mock()
        with patch("application.agents.workflow_agent.WorkflowsRepository"):
            captured_pg_write["fn"](mock_runs_repo)

        mock_runs_repo.create.assert_not_called()

    # ------------------------------------------------------------------
    # Mongo insert failure prevents pg_write from being called
    # ------------------------------------------------------------------

    def test_mongo_exception_prevents_dual_write(self):
        """If Mongo insert_one raises, dual_write is never called."""
        agent = _make_agent(workflow_id=_fake_oid())
        agent._engine = self._make_engine()

        mock_coll = MagicMock()
        mock_coll.insert_one.side_effect = Exception("mongo down")
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings, \
             patch("application.agents.workflow_agent.dual_write") as mock_dw:
            mock_settings.MONGO_DB_NAME = "test"
            MockMongo.get_client.return_value = {"test": mock_db}
            agent._save_workflow_run("query text")  # must not propagate

        mock_dw.assert_not_called()


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
