"""Tests for a running workflow's step progress: the step count of a graph and
the progress ``WorkflowAgent`` records on the run row as each step starts."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from docsgpt.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository


def _graph(nodes: list[tuple[str, NodeType, str]], edges: list[tuple[str, str]]) -> WorkflowGraph:
    return WorkflowGraph(
        workflow=Workflow(name="Renewal flow"),
        nodes=[WorkflowNode(id=i, workflow_id="w", type=t, title=title) for i, t, title in nodes],
        edges=[
            WorkflowEdge(id=f"{s}-{d}", workflow_id="w", source=s, target=d) for s, d in edges
        ],
    )


_LINEAR = _graph(
    [
        ("s", NodeType.START, "Start"),
        ("a", NodeType.AGENT, "Read the contract"),
        ("b", NodeType.AGENT, "Draft reply"),
        ("e", NodeType.END, "Output"),
        ("n", NodeType.NOTE, "Remember the tone"),
    ],
    [("s", "a"), ("a", "b"), ("b", "e")],
)


class TestLinearStepCount:
    def test_counts_the_steps_after_start(self):
        assert _LINEAR.linear_step_count() == 3

    def test_leaves_out_the_end_node_when_asked(self):
        assert _LINEAR.linear_step_count(count_end=False) == 2

    def test_a_condition_on_the_path_has_no_count(self):
        graph = _graph(
            [
                ("s", NodeType.START, "Start"),
                ("c", NodeType.CONDITION, "Is it urgent?"),
                ("e", NodeType.END, "Output"),
            ],
            [("s", "c"), ("c", "e")],
        )
        assert graph.linear_step_count() is None

    def test_a_cycle_has_no_count(self):
        graph = _graph(
            [("s", NodeType.START, "Start"), ("a", NodeType.AGENT, "A"), ("b", NodeType.AGENT, "B")],
            [("s", "a"), ("a", "b"), ("b", "a")],
        )
        assert graph.linear_step_count() is None

    def test_no_start_has_no_count(self):
        graph = _graph([("a", NodeType.AGENT, "A")], [])
        assert graph.linear_step_count() is None


def _step(node_id: str, node_type: NodeType, title: str, status: str) -> dict:
    return {
        "type": "workflow_step",
        "node_id": node_id,
        "node_type": node_type.value,
        "node_title": title,
        "status": status,
    }


def _events() -> list[dict]:
    return [
        {"type": "workflow_run", "workflow_run_id": "x"},
        _step("s", NodeType.START, "Start", "running"),
        _step("s", NodeType.START, "Start", "completed"),
        _step("a", NodeType.AGENT, "Read the contract", "running"),
        {"answer": "partial"},
        _step("a", NodeType.AGENT, "Read the contract", "completed"),
        _step("b", NodeType.AGENT, "Draft reply", "running"),
    ]


def _stream():
    yield from _events()


def _agent(graph: WorkflowGraph, run_id: str, *, persisted: bool = True):
    from docsgpt.agents.workflow_agent import WorkflowAgent

    agent = WorkflowAgent.__new__(WorkflowAgent)
    agent.workflow_id = "wf"
    agent._engine = MagicMock()
    agent._engine.graph = graph
    agent._engine.workflow_run_id = run_id
    agent._run_persisted = persisted
    return agent


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.agents.workflow_agent.db_session", _yield):
        yield


class TestRecordsProgress:
    def _run(self, conn) -> str:
        wf = WorkflowsRepository(conn).create("u1", "Renewal flow")
        run_id = str(uuid.uuid4())
        WorkflowRunsRepository(conn).create(str(wf["id"]), "u1", "running", run_id=run_id)
        return run_id

    def test_each_step_start_writes_progress_and_tells_the_runner(self, pg_conn):
        run_id = self._run(pg_conn)
        agent = _agent(_LINEAR, run_id)
        with _patch_db(pg_conn), patch("docsgpt.agents.workflow_agent.publish_user_event") as publish:
            passed = list(agent._with_progress(_stream(), "u1"))

        assert passed == _events()
        progress = WorkflowRunsRepository(pg_conn).get(run_id)["progress"]
        assert progress["done"] == 1
        assert progress["total"] == 3
        assert progress["current"]["node_id"] == "b"
        assert progress["current"]["title"] == "Draft reply"
        assert progress["current"]["type"] == "agent"
        # The start node is not a step: two writes, one per counted step.
        assert publish.call_count == 2
        user, event_type, payload = publish.call_args.args
        assert (user, event_type) == ("u1", "workflow.run.step")
        assert payload["workflow_run_id"] == run_id
        assert payload["progress"] == progress

    def test_a_run_without_a_row_writes_nothing(self, pg_conn):
        agent = _agent(_LINEAR, str(uuid.uuid4()), persisted=False)
        with _patch_db(pg_conn), patch("docsgpt.agents.workflow_agent.publish_user_event") as publish:
            passed = list(agent._with_progress(_stream(), "u1"))
        assert passed == _events()
        publish.assert_not_called()

    def test_a_failed_write_never_breaks_the_run(self):
        agent = _agent(_LINEAR, str(uuid.uuid4()))

        @contextmanager
        def _broken():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        with patch("docsgpt.agents.workflow_agent.db_session", _broken), patch(
            "docsgpt.agents.workflow_agent.publish_user_event"
        ):
            assert list(agent._with_progress(_stream(), "u1")) == _events()

    def test_closing_the_stream_closes_the_engine(self):
        agent = _agent(_LINEAR, str(uuid.uuid4()), persisted=False)
        closed = []

        def _engine_events():
            try:
                yield {"answer": "a"}
                yield {"answer": "b"}
            finally:
                closed.append(True)

        stream = agent._with_progress(_engine_events(), "u1")
        next(stream)
        stream.close()
        assert closed == [True]
