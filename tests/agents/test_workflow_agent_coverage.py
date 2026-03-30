"""Tests for WorkflowAgent - covering _parse_embedded_workflow, _load_from_database,
_save_workflow_run, _determine_run_status, _serialize_state, and gen flow."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from application.agents.workflows.schemas import (
    ExecutionStatus,
    WorkflowGraph,
)


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


class TestWorkflowAgentInit:

    @pytest.mark.unit
    def test_sets_attributes(self):
        agent = _make_agent(workflow_id="wf1", workflow_owner="owner1")
        assert agent.workflow_id == "wf1"
        assert agent.workflow_owner == "owner1"
        assert agent._engine is None

    @pytest.mark.unit
    def test_embedded_workflow(self):
        wf_data = {"nodes": [], "edges": [], "name": "Test"}
        agent = _make_agent(workflow=wf_data)
        assert agent._workflow_data == wf_data


class TestParseEmbeddedWorkflow:

    @pytest.mark.unit
    def test_parses_valid_workflow(self):
        wf_data = {
            "name": "Test Workflow",
            "description": "A test",
            "nodes": [
                {"id": "n1", "type": "start", "title": "Start", "data": {}, "position": {"x": 0, "y": 0}},
                {"id": "n2", "type": "end", "title": "End", "data": {}, "position": {"x": 100, "y": 0}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "out", "targetHandle": "in"},
            ],
        }
        agent = _make_agent(workflow=wf_data, workflow_id="wf1")
        graph = agent._parse_embedded_workflow()
        assert graph is not None
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.workflow.name == "Test Workflow"

    @pytest.mark.unit
    def test_edge_source_id_alias(self):
        wf_data = {
            "nodes": [{"id": "n1", "type": "start", "data": {}}],
            "edges": [{"id": "e1", "source_id": "n1", "target_id": "n2", "source_handle": "out", "target_handle": "in"}],
        }
        agent = _make_agent(workflow=wf_data)
        graph = agent._parse_embedded_workflow()
        assert graph is not None
        assert graph.edges[0].source_id == "n1"

    @pytest.mark.unit
    def test_invalid_data_returns_none(self):
        agent = _make_agent(workflow={"nodes": [{"bad": "data"}], "edges": []})
        graph = agent._parse_embedded_workflow()
        assert graph is None


class TestLoadWorkflowGraph:

    @pytest.mark.unit
    def test_uses_embedded_when_available(self):
        agent = _make_agent(workflow={"nodes": [], "edges": [], "name": "E"})
        agent._parse_embedded_workflow = MagicMock(return_value="parsed_graph")
        result = agent._load_workflow_graph()
        assert result == "parsed_graph"

    @pytest.mark.unit
    def test_uses_database_when_workflow_id(self):
        agent = _make_agent(workflow_id="wf1")
        agent._load_from_database = MagicMock(return_value="db_graph")
        result = agent._load_workflow_graph()
        assert result == "db_graph"

    @pytest.mark.unit
    def test_returns_none_when_nothing(self):
        agent = _make_agent()
        result = agent._load_workflow_graph()
        assert result is None


class TestLoadFromDatabase:

    @pytest.mark.unit
    def test_invalid_workflow_id_returns_none(self):
        agent = _make_agent(workflow_id="invalid!")
        result = agent._load_from_database()
        assert result is None

    @pytest.mark.unit
    def test_no_owner_returns_none(self):
        agent = _make_agent(workflow_id="507f1f77bcf86cd799439011", decoded_token={})
        agent.workflow_owner = None
        result = agent._load_from_database()
        assert result is None

    @pytest.mark.unit
    def test_uses_decoded_token_sub(self):
        agent = _make_agent(
            workflow_id="507f1f77bcf86cd799439011",
            decoded_token={"sub": "user1"},
        )
        agent.workflow_owner = None

        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            result = agent._load_from_database()
        assert result is None  # workflow_doc not found

    @pytest.mark.unit
    def test_successful_load(self):
        agent = _make_agent(
            workflow_id="507f1f77bcf86cd799439011",
            workflow_owner="owner1",
        )

        mock_wf_coll = MagicMock()
        mock_wf_coll.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "Test WF",
            "user": "owner1",
            "current_graph_version": 1,
        }

        mock_nodes_coll = MagicMock()
        mock_nodes_coll.find.return_value = [
            {"id": "n1", "workflow_id": "507f1f77bcf86cd799439011", "type": "start",
             "title": "Start", "position": {"x": 0, "y": 0}, "config": {}},
        ]

        mock_edges_coll = MagicMock()
        mock_edges_coll.find.return_value = []

        def getitem(name):
            return {"workflows": mock_wf_coll, "workflow_nodes": mock_nodes_coll, "workflow_edges": mock_edges_coll}[name]

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=getitem)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            result = agent._load_from_database()

        assert result is not None
        assert len(result.nodes) == 1

    @pytest.mark.unit
    def test_invalid_graph_version(self):
        agent = _make_agent(
            workflow_id="507f1f77bcf86cd799439011",
            workflow_owner="owner1",
        )

        mock_wf_coll = MagicMock()
        mock_wf_coll.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "WF",
            "user": "owner1",
            "current_graph_version": "bad",
        }

        mock_nodes_coll = MagicMock()
        mock_nodes_coll.find.return_value = []
        mock_edges_coll = MagicMock()
        mock_edges_coll.find.return_value = []

        def getitem(name):
            return {"workflows": mock_wf_coll, "workflow_nodes": mock_nodes_coll, "workflow_edges": mock_edges_coll}[name]

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=getitem)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            result = agent._load_from_database()
        assert result is not None  # Defaults to version 1

    @pytest.mark.unit
    def test_fallback_nodes_without_version(self):
        """When graph_version=1 finds no nodes, falls back to nodes without version field."""
        agent = _make_agent(
            workflow_id="507f1f77bcf86cd799439011",
            workflow_owner="owner1",
        )

        mock_wf_coll = MagicMock()
        mock_wf_coll.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "WF",
            "user": "owner1",
            "current_graph_version": 1,
        }

        call_count = [0]
        def nodes_find(query):
            call_count[0] += 1
            if call_count[0] == 1:
                return []  # No versioned nodes
            return [{"id": "n1", "workflow_id": "wf", "type": "start",
                     "title": "S", "position": {"x": 0, "y": 0}, "config": {}}]

        mock_nodes_coll = MagicMock()
        mock_nodes_coll.find.side_effect = nodes_find

        edge_call = [0]
        def edges_find(query):
            edge_call[0] += 1
            if edge_call[0] == 1:
                return []
            return []

        mock_edges_coll = MagicMock()
        mock_edges_coll.find.side_effect = edges_find

        def getitem(name):
            return {"workflows": mock_wf_coll, "workflow_nodes": mock_nodes_coll, "workflow_edges": mock_edges_coll}[name]

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=getitem)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            result = agent._load_from_database()
        assert result is not None
        assert len(result.nodes) == 1

    @pytest.mark.unit
    def test_exception_returns_none(self):
        agent = _make_agent(
            workflow_id="507f1f77bcf86cd799439011",
            workflow_owner="owner1",
        )
        with patch("application.agents.workflow_agent.MongoDB") as MockMongo:
            MockMongo.get_client.side_effect = Exception("db error")
            result = agent._load_from_database()
        assert result is None


class TestGenInner:

    @pytest.mark.unit
    def test_no_graph_yields_error(self):
        agent = _make_agent()
        agent._load_workflow_graph = MagicMock(return_value=None)
        events = list(agent._gen_inner("query", None))
        assert any(e.get("type") == "error" for e in events)

    @pytest.mark.unit
    def test_successful_execution(self):
        agent = _make_agent(workflow_id="wf1")
        mock_graph = MagicMock(spec=WorkflowGraph)
        agent._load_workflow_graph = MagicMock(return_value=mock_graph)
        agent._save_workflow_run = MagicMock()

        mock_engine = MagicMock()
        mock_engine.execute.return_value = iter([{"answer": "result"}])

        with patch("application.agents.workflow_agent.WorkflowEngine", return_value=mock_engine):
            events = list(agent._gen_inner("query", None))
        assert len(events) == 1
        agent._save_workflow_run.assert_called_once_with("query")


class TestSaveWorkflowRun:

    @pytest.mark.unit
    def test_no_engine_returns_early(self):
        agent = _make_agent()
        agent._engine = None
        agent._save_workflow_run("query")  # Should not raise

    @pytest.mark.unit
    def test_saves_to_mongo(self):
        agent = _make_agent(workflow_id="wf1")
        mock_engine = MagicMock()
        mock_engine.state = {"query": "test"}
        mock_engine.execution_log = []
        mock_engine.get_execution_summary.return_value = []
        agent._engine = mock_engine

        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo, \
             patch("application.agents.workflow_agent.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            agent._save_workflow_run("query")

        mock_collection.insert_one.assert_called_once()

    @pytest.mark.unit
    def test_exception_does_not_propagate(self):
        agent = _make_agent(workflow_id="wf1")
        mock_engine = MagicMock()
        mock_engine.state = {}
        mock_engine.execution_log = []
        mock_engine.get_execution_summary.return_value = []
        agent._engine = mock_engine

        with patch("application.agents.workflow_agent.MongoDB") as MockMongo:
            MockMongo.get_client.side_effect = Exception("db fail")
            agent._save_workflow_run("query")  # Should not raise


class TestDetermineRunStatus:

    @pytest.mark.unit
    def test_no_engine_returns_completed(self):
        agent = _make_agent()
        agent._engine = None
        assert agent._determine_run_status() == ExecutionStatus.COMPLETED

    @pytest.mark.unit
    def test_empty_log_returns_completed(self):
        agent = _make_agent()
        agent._engine = MagicMock()
        agent._engine.execution_log = []
        assert agent._determine_run_status() == ExecutionStatus.COMPLETED

    @pytest.mark.unit
    def test_failed_log_returns_failed(self):
        agent = _make_agent()
        agent._engine = MagicMock()
        agent._engine.execution_log = [
            {"status": "completed"},
            {"status": "failed"},
        ]
        assert agent._determine_run_status() == ExecutionStatus.FAILED

    @pytest.mark.unit
    def test_all_completed_returns_completed(self):
        agent = _make_agent()
        agent._engine = MagicMock()
        agent._engine.execution_log = [
            {"status": "completed"},
            {"status": "completed"},
        ]
        assert agent._determine_run_status() == ExecutionStatus.COMPLETED


class TestSerializeState:

    @pytest.mark.unit
    def test_serializes_primitives(self):
        agent = _make_agent()
        state = {"str": "hello", "int": 42, "float": 3.14, "bool": True, "none": None}
        result = agent._serialize_state(state)
        assert result == state

    @pytest.mark.unit
    def test_serializes_nested_dict(self):
        agent = _make_agent()
        state = {"nested": {"key": "value"}}
        result = agent._serialize_state(state)
        assert result["nested"]["key"] == "value"

    @pytest.mark.unit
    def test_serializes_list(self):
        agent = _make_agent()
        state = {"items": [1, 2, "three"]}
        result = agent._serialize_state(state)
        assert result["items"] == [1, 2, "three"]

    @pytest.mark.unit
    def test_serializes_tuple(self):
        agent = _make_agent()
        state = {"tup": (1, 2)}
        result = agent._serialize_state(state)
        assert result["tup"] == [1, 2]

    @pytest.mark.unit
    def test_serializes_datetime(self):
        agent = _make_agent()
        dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        state = {"time": dt}
        result = agent._serialize_state(state)
        assert "2025-01-01" in result["time"]

    @pytest.mark.unit
    def test_serializes_unknown_to_str(self):
        agent = _make_agent()
        state = {"obj": object()}
        result = agent._serialize_state(state)
        assert isinstance(result["obj"], str)
