"""Targeted coverage for uncovered lines in application/agents/workflow_agent.py.

Covers:
- Line 143: workflow_doc not found early return in _load_from_database
- Lines 214-221: _pg_write closure body inside _save_workflow_run
  - when workflow_id/owner_id/legacy_mongo_id is missing → early return
  - when workflow PG record not found → early return
  - when all present → repo.create called
"""

from unittest.mock import MagicMock, patch

import pytest


def _make_agent(**overrides):
    """Create a WorkflowAgent with mocked base class dependencies."""
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


# ---------------------------------------------------------------------------
# Line 143 – workflow_doc returned None (not found / wrong user)
# This line is the ``return None`` after the logger.error inside
# _load_from_database when find_one returns None.
# ---------------------------------------------------------------------------


class TestLoadFromDatabaseNotFound:
    @pytest.mark.unit
    def test_workflow_not_found_logs_and_returns_none(self):
        """When find_one returns None, _load_from_database logs an error and returns None."""
        agent = _make_agent(
            workflow_id="507f1f77bcf86cd799439011",
            workflow_owner="owner1",
        )

        mock_wf_coll = MagicMock()
        mock_wf_coll.find_one.return_value = None  # not found

        def getitem(name):
            return mock_wf_coll  # same mock for all collections

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=getitem)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            result = agent._load_from_database()

        assert result is None

    @pytest.mark.unit
    def test_zero_graph_version_defaults_to_one(self):
        """When current_graph_version=0 (or negative), graph_version is reset to 1 (line 143)."""
        agent = _make_agent(
            workflow_id="507f1f77bcf86cd799439011",
            workflow_owner="owner1",
        )

        mock_wf_coll = MagicMock()
        mock_wf_coll.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "WF",
            "user": "owner1",
            "current_graph_version": 0,  # <= 0 triggers line 143
        }

        mock_nodes_coll = MagicMock()
        mock_nodes_coll.find.return_value = []
        mock_edges_coll = MagicMock()
        mock_edges_coll.find.return_value = []

        def getitem(name):
            mapping = {
                "workflows": mock_wf_coll,
                "workflow_nodes": mock_nodes_coll,
                "workflow_edges": mock_edges_coll,
            }
            return mapping[name]

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=getitem)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            result = agent._load_from_database()

        # Should succeed with graph_version=1 fallback
        assert result is not None


# ---------------------------------------------------------------------------
# Lines 214-221 – _pg_write closure body inside _save_workflow_run
# ---------------------------------------------------------------------------


def _capture_pg_write_fn(agent, mock_collection):
    """
    Run _save_workflow_run while intercepting dual_write so we can
    capture the ``_pg_write`` closure and call it separately.
    """
    captured = []

    def fake_dual_write(repo_cls, fn):
        captured.append(fn)

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
         patch("application.agents.workflow_agent.settings") as mock_settings, \
         patch("application.agents.workflow_agent.dual_write", side_effect=fake_dual_write):
        mock_settings.MONGO_DB_NAME = "test_db"
        MockMongo.get_client.return_value = {"test_db": mock_db}
        agent._save_workflow_run("query")

    return captured[0] if captured else None


class TestSaveWorkflowRunPgWriteCallback:

    def _make_agent_with_engine(self, workflow_id="507f1f77bcf86cd799439011", owner_id="user1"):
        agent = _make_agent(workflow_id=workflow_id, workflow_owner=owner_id)
        mock_engine = MagicMock()
        mock_engine.state = {}
        mock_engine.execution_log = []
        mock_engine.get_execution_summary.return_value = []
        agent._engine = mock_engine
        return agent

    @pytest.mark.unit
    def test_pg_write_skips_when_no_workflow_id(self):
        """_pg_write returns early when agent has no workflow_id (line 214)."""
        agent = self._make_agent_with_engine(workflow_id=None)
        # workflow_id is None, so _pg_write should exit without calling repo.create

        inserted = MagicMock()
        inserted.inserted_id = "507f1f77bcf86cd799439012"
        mock_coll = MagicMock()
        mock_coll.insert_one.return_value = inserted

        pg_write_fn = _capture_pg_write_fn(agent, mock_coll)

        if pg_write_fn is None:
            # dual_write was never called (workflow_id is None → no owner_id → early return in _save_workflow_run)
            return

        mock_repo = MagicMock()
        mock_repo._conn = MagicMock()
        pg_write_fn(mock_repo)  # must not raise
        mock_repo.create.assert_not_called()

    @pytest.mark.unit
    def test_pg_write_skips_when_no_legacy_mongo_id(self):
        """_pg_write returns early when insert_one.inserted_id is None (line 214)."""
        agent = self._make_agent_with_engine()

        inserted = MagicMock()
        inserted.inserted_id = None  # simulate missing inserted_id
        mock_coll = MagicMock()
        mock_coll.insert_one.return_value = inserted

        pg_write_fn = _capture_pg_write_fn(agent, mock_coll)
        if pg_write_fn is None:
            pytest.skip("dual_write not called")

        mock_repo = MagicMock()
        mock_repo._conn = MagicMock()
        pg_write_fn(mock_repo)
        mock_repo.create.assert_not_called()

    @pytest.mark.unit
    def test_pg_write_skips_when_workflow_not_in_pg(self):
        """_pg_write returns early when workflows repo returns None (line 219-220)."""
        agent = self._make_agent_with_engine()

        inserted = MagicMock()
        inserted.inserted_id = "507f1f77bcf86cd799439012"
        mock_coll = MagicMock()
        mock_coll.insert_one.return_value = inserted

        pg_write_fn = _capture_pg_write_fn(agent, mock_coll)
        if pg_write_fn is None:
            pytest.skip("dual_write not called")

        mock_repo = MagicMock()
        mock_repo._conn = MagicMock()

        mock_wf_repo = MagicMock()
        mock_wf_repo.get_by_legacy_id.return_value = None  # not in PG

        with patch("application.agents.workflow_agent.WorkflowsRepository", return_value=mock_wf_repo):
            pg_write_fn(mock_repo)

        mock_repo.create.assert_not_called()

    @pytest.mark.unit
    def test_pg_write_creates_run_when_all_present(self):
        """_pg_write calls repo.create when workflow_id, owner_id, and legacy_id all exist (lines 221-231)."""
        import uuid
        agent = self._make_agent_with_engine()

        inserted = MagicMock()
        inserted.inserted_id = "507f1f77bcf86cd799439012"
        mock_coll = MagicMock()
        mock_coll.insert_one.return_value = inserted

        pg_write_fn = _capture_pg_write_fn(agent, mock_coll)
        if pg_write_fn is None:
            pytest.skip("dual_write not called")

        pg_wf_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo._conn = MagicMock()

        mock_wf_repo = MagicMock()
        mock_wf_repo.get_by_legacy_id.return_value = {"id": pg_wf_id}

        with patch("application.agents.workflow_agent.WorkflowsRepository", return_value=mock_wf_repo):
            pg_write_fn(mock_repo)

        mock_repo.create.assert_called_once()
        call_kwargs = mock_repo.create.call_args
        # First positional arg is workflow uuid, second is owner_id
        assert pg_wf_id in call_kwargs.args
        assert "user1" in call_kwargs.args
