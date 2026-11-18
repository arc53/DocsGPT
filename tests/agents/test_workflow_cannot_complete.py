"""Which agent node's report that it can't do its step fails a scheduled workflow run.

The last agent node to run outside a loop decides: a later agent node clears
an earlier report, and loop items never report for the run.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory
from docsgpt.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

TOOL_CALL = {"type": "tool_call", "data": {"tool_name": "brave_search", "status": "completed"}}


class _StubNodeAgent:
    """A node agent that streams canned events, and may have reported through the tool."""

    def __init__(self, events: List[Dict[str, Any]], reported: Optional[str] = None):
        self._events = events
        self.tool_executor = SimpleNamespace(cannot_complete=reported)
        self.attachments = []
        self.llm = SimpleNamespace(get_supported_attachment_types=lambda: [])

    def gen(self, _prompt):
        yield from self._events


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _p: "k")


def _nodes_answer(monkeypatch, *agents: _StubNodeAgent) -> None:
    """Hand out the stub agents to the agent nodes in the order they run."""
    pending = list(agents)
    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: pending.pop(0)))


def _says(text: str, reported: Optional[str] = None) -> _StubNodeAgent:
    """A node agent whose one round is ``text``."""
    return _StubNodeAgent([{"answer": text}], reported)


def _node(node_id: str, node_type: NodeType, title: str, **config: Any) -> WorkflowNode:
    """A node of the test workflow."""
    return WorkflowNode(id=node_id, workflow_id="wf", type=node_type, title=title, config=config)


def _agent_node(node_id: str, title: str, **config: Any) -> WorkflowNode:
    """An agent node that doesn't stream unless asked to."""
    config.setdefault("stream_to_user", False)
    return _node(node_id, NodeType.AGENT, title, **config)


def _engine(endpoint: str, *middle: WorkflowNode) -> WorkflowEngine:
    """An engine over Start, ``middle`` and End, run for ``endpoint``."""
    nodes = [_node("start", NodeType.START, "Start"), *middle, _node("end", NodeType.END, "End")]
    edges = [
        WorkflowEdge(id=f"e{i}", workflow_id="wf", source=a.id, target=b.id)
        for i, (a, b) in enumerate(zip(nodes, nodes[1:]))
    ]
    graph = WorkflowGraph(workflow=Workflow(name="Nightly"), nodes=nodes, edges=edges)
    agent = SimpleNamespace(
        endpoint=endpoint,
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="k",
        chat_history=[],
        user="user-1",
        decoded_token={"sub": "user-1"},
        cannot_complete=None,
    )
    return WorkflowEngine(graph, agent, workflow_run_id="33333333-3333-3333-3333-333333333333")


def _run(endpoint: str, *middle: WorkflowNode) -> SimpleNamespace:
    """Run the workflow; the run's agent, with what the engine noted on it."""
    engine = _engine(endpoint, *middle)
    list(engine._run_graph({}, "go"))
    return engine.agent


@pytest.mark.unit
class TestScheduledWorkflowCannotComplete:
    def test_the_last_agent_node_reporting_through_the_tool_is_noted(self, monkeypatch):
        _nodes_answer(monkeypatch, _says("Prices fetched."), _says("I couldn't send it.", reported="no email tool"))

        agent = _run("schedule", _agent_node("fetch", "Fetch prices"), _agent_node("mail", "Mail"))

        assert agent.cannot_complete == "Mail: no email tool"

    def test_a_quiet_last_node_opening_with_the_marker_is_noted(self, monkeypatch):
        _nodes_answer(monkeypatch, _says("CANNOT_COMPLETE: no browser tool to open the site"))

        agent = _run("schedule", _agent_node("check", "Check site"))

        assert agent.cannot_complete == "Check site: no browser tool to open the site"

    def test_a_marker_after_the_nodes_tool_call_is_read(self, monkeypatch):
        _nodes_answer(
            monkeypatch,
            _StubNodeAgent([{"answer": "Checking the site."}, TOOL_CALL, {"answer": "CANNOT_COMPLETE: login needed"}]),
        )

        agent = _run("schedule", _agent_node("check", "Check site"))

        assert agent.cannot_complete == "Check site: login needed"

    def test_a_later_agent_node_clears_an_earlier_report(self, monkeypatch):
        # A fallback or a branch that handles the failure ran after it.
        _nodes_answer(monkeypatch, _says("Couldn't open it.", reported="no browser tool"), _says("Used the cached copy."))

        agent = _run("schedule", _agent_node("check", "Check site"), _agent_node("fallback", "Fallback"))

        assert agent.cannot_complete is None

    def test_nodes_that_did_their_steps_note_nothing(self, monkeypatch):
        _nodes_answer(monkeypatch, _says("The site is up; I cannot complete a login check without an account."))

        agent = _run("schedule", _agent_node("check", "Check site"))

        assert agent.cannot_complete is None

    def test_a_run_that_is_not_scheduled_notes_nothing(self, monkeypatch):
        _nodes_answer(monkeypatch, _says("CANNOT_COMPLETE: no browser tool", reported="no browser tool"))

        agent = _run("stream", _agent_node("check", "Check site"))

        assert agent.cannot_complete is None

    def test_a_loop_item_never_reports_for_the_run(self, monkeypatch):
        # Items run side by side; one failing item does not make the task impossible.
        _nodes_answer(monkeypatch, _says("CANNOT_COMPLETE: no browser tool", reported="no browser tool"))
        node = _agent_node("check", "Check site")
        engine = _engine("schedule", node)
        engine._loop_item = {"parent_node_id": "loop", "item_index": 0, "item_count": 3}

        list(engine._execute_agent_node(node))

        assert engine.agent.cannot_complete is None
