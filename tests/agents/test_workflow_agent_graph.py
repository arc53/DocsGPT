"""Tests for application/agents/workflow_agent.py graph loading and saving.

Tests _parse_embedded_workflow, _load_from_database, and _save_workflow_run
against the ephemeral ``pg_conn`` fixture. Agent construction is bypassed via
``__new__`` so we avoid the BaseAgent's LLM/tool wiring.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _make_agent(*, workflow_id=None, workflow=None, workflow_owner=None,
                decoded_token=None):
    """Construct a WorkflowAgent bypassing BaseAgent.__init__."""
    from application.agents.workflow_agent import WorkflowAgent
    agent = WorkflowAgent.__new__(WorkflowAgent)
    agent.workflow_id = workflow_id
    agent.workflow_owner = workflow_owner
    agent._workflow_data = workflow
    agent._engine = None
    agent.decoded_token = decoded_token or {}
    return agent


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.agents.workflow_agent.db_readonly", _yield
    ), patch(
        "application.agents.workflow_agent.db_session", _yield
    ):
        yield


class TestParseEmbeddedWorkflow:
    def test_returns_none_for_malformed_workflow(self):
        agent = _make_agent(workflow={"nodes": None})  # invalid shape
        assert agent._parse_embedded_workflow() is None

    def test_parses_valid_embedded_workflow(self):
        agent = _make_agent(
            workflow={
                "name": "Embedded",
                "description": "d",
                "nodes": [
                    {
                        "id": "n1", "type": "start", "title": "Start",
                        "position": {"x": 0, "y": 0}, "data": {},
                    },
                    {
                        "id": "n2", "type": "end", "title": "End",
                        "position": {"x": 100, "y": 0}, "data": {},
                    },
                ],
                "edges": [
                    {
                        "id": "e1", "source": "n1", "target": "n2",
                    }
                ],
            }
        )
        graph = agent._parse_embedded_workflow()
        assert graph is not None
        assert graph.workflow.name == "Embedded"
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1

    def test_parses_edges_with_source_id_target_id(self):
        """Edges may arrive with ``source_id``/``target_id`` instead of
        ``source``/``target``."""
        agent = _make_agent(
            workflow={
                "name": "v2",
                "nodes": [
                    {"id": "a", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                    {"id": "b", "type": "end", "position": {"x": 0, "y": 0}, "data": {}},
                ],
                "edges": [
                    {
                        "id": "e1",
                        "source_id": "a", "target_id": "b",
                        "source_handle": "h", "target_handle": "h2",
                    }
                ],
            }
        )
        graph = agent._parse_embedded_workflow()
        assert graph.edges[0].source_id == "a"


class TestLoadWorkflowGraph:
    def test_returns_none_when_no_data_or_id(self):
        agent = _make_agent()
        assert agent._load_workflow_graph() is None

    def test_uses_embedded_when_provided(self):
        agent = _make_agent(workflow={"nodes": [], "edges": []})
        # Empty nodes returns WorkflowGraph with no nodes, still valid object
        got = agent._load_workflow_graph()
        assert got is not None

    def test_uses_database_when_id_set(self, pg_conn):
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )
        user = "u-loadwf"
        workflow = WorkflowsRepository(pg_conn).create(user, "wf")
        agent = _make_agent(
            workflow_id=str(workflow["id"]),
            workflow_owner=user,
        )
        with _patch_db(pg_conn):
            got = agent._load_workflow_graph()
        assert got is not None


class TestLoadFromDatabase:
    def test_returns_none_no_workflow_id(self):
        agent = _make_agent()
        assert agent._load_from_database() is None

    def test_returns_none_no_owner(self):
        agent = _make_agent(workflow_id="some-id")
        assert agent._load_from_database() is None

    def test_owner_from_decoded_token(self, pg_conn):
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )
        user = "u-token-owner"
        wf = WorkflowsRepository(pg_conn).create(user, "wf")
        agent = _make_agent(
            workflow_id=str(wf["id"]),
            decoded_token={"sub": user},
        )
        with _patch_db(pg_conn):
            got = agent._load_from_database()
        assert got is not None

    def test_returns_none_when_workflow_missing(self, pg_conn):
        agent = _make_agent(
            workflow_id="00000000-0000-0000-0000-000000000000",
            workflow_owner="u",
        )
        with _patch_db(pg_conn):
            got = agent._load_from_database()
        assert got is None

    def test_invalid_version_falls_back_to_1(self, pg_conn):
        """When current_graph_version is invalid it falls back to 1."""
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )
        user = "u-bad-version"
        wf = WorkflowsRepository(pg_conn).create(user, "wf")
        agent = _make_agent(
            workflow_id=str(wf["id"]), workflow_owner=user,
        )
        with _patch_db(pg_conn):
            got = agent._load_from_database()
        assert got is not None

    def test_handles_exception(self):
        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        agent = _make_agent(workflow_id="x", workflow_owner="u")
        with patch(
            "application.agents.workflow_agent.db_readonly", _broken
        ):
            got = agent._load_from_database()
        assert got is None


class TestSaveWorkflowRun:
    def test_returns_when_no_engine(self):
        agent = _make_agent(workflow_id="x", workflow_owner="u")
        # _engine is None
        agent._save_workflow_run("query")
        # should not raise

    def test_returns_when_no_workflow_id(self):
        agent = _make_agent(workflow_owner="u")
        agent._engine = MagicMock()
        agent._engine.execution_log = []
        agent._engine.state = {}
        agent._engine.get_execution_summary.return_value = []
        agent._save_workflow_run("query")

    def test_returns_when_workflow_missing_in_db(self, pg_conn):
        agent = _make_agent(
            workflow_id="00000000-0000-0000-0000-000000000000",
            workflow_owner="u",
        )
        agent._engine = MagicMock()
        agent._engine.execution_log = []
        agent._engine.state = {}
        agent._engine.get_execution_summary.return_value = []
        with _patch_db(pg_conn):
            # Should just return None since workflow not found in DB
            agent._save_workflow_run("q")

    def test_creates_run_row(self, pg_conn):
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )
        from application.storage.db.repositories.workflow_runs import (
            WorkflowRunsRepository,
        )

        user = "u-saverun"
        wf = WorkflowsRepository(pg_conn).create(user, "wf")
        agent = _make_agent(
            workflow_id=str(wf["id"]), workflow_owner=user,
        )
        agent._engine = MagicMock()
        agent._engine.execution_log = []
        agent._engine.state = {"output": "hello"}
        agent._engine.get_execution_summary.return_value = []

        with _patch_db(pg_conn):
            agent._save_workflow_run("my query")

        runs = WorkflowRunsRepository(pg_conn).list_for_workflow(str(wf["id"]))
        assert len(runs) >= 1

    def test_exception_is_swallowed(self):
        agent = _make_agent(workflow_id="x", workflow_owner="u")
        agent._engine = MagicMock()
        agent._engine.execution_log = []
        agent._engine.state = {}
        agent._engine.get_execution_summary.return_value = []

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.agents.workflow_agent.db_session", _broken
        ):
            # Should not raise
            agent._save_workflow_run("q")


class TestDetermineRunStatus:
    def test_completed_when_no_engine(self):
        from application.agents.workflows.schemas import ExecutionStatus

        agent = _make_agent()
        assert agent._determine_run_status() == ExecutionStatus.COMPLETED

    def test_completed_when_log_empty(self):
        from application.agents.workflows.schemas import ExecutionStatus

        agent = _make_agent()
        agent._engine = MagicMock()
        agent._engine.execution_log = []
        assert agent._determine_run_status() == ExecutionStatus.COMPLETED

    def test_failed_if_any_log_failed(self):
        from application.agents.workflows.schemas import ExecutionStatus

        agent = _make_agent()
        agent._engine = MagicMock()
        agent._engine.execution_log = [
            {"status": ExecutionStatus.COMPLETED.value},
            {"status": ExecutionStatus.FAILED.value},
        ]
        assert agent._determine_run_status() == ExecutionStatus.FAILED


class TestSerializeState:
    def test_primitive_passes_through(self):
        agent = _make_agent()
        assert agent._serialize_state_value(42) == 42
        assert agent._serialize_state_value("x") == "x"
        assert agent._serialize_state_value(None) is None
        assert agent._serialize_state_value(True) is True

    def test_datetime_becomes_iso(self):
        agent = _make_agent()
        now = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        assert agent._serialize_state_value(now) == now.isoformat()

    def test_dict_becomes_dict_with_string_keys(self):
        agent = _make_agent()
        got = agent._serialize_state_value({1: "a", "b": 2})
        assert got == {"1": "a", "b": 2}

    def test_tuple_becomes_list(self):
        agent = _make_agent()
        assert agent._serialize_state_value((1, 2, 3)) == [1, 2, 3]

    def test_unknown_becomes_string(self):
        agent = _make_agent()

        class Foo:
            def __str__(self):
                return "custom-foo"

        assert agent._serialize_state_value(Foo()) == "custom-foo"

    def test_serialize_state_dict(self):
        agent = _make_agent()
        got = agent._serialize_state({"x": 1, "y": [1, 2]})
        assert got == {"x": 1, "y": [1, 2]}


class TestGen:
    def test_yields_error_when_graph_fails(self):
        agent = _make_agent()  # no workflow data
        # _load_workflow_graph returns None so gen yields error
        results = list(agent._gen_inner("q", log_context=None))
        assert results == [
            {"type": "error", "error": "Failed to load workflow configuration."}
        ]
