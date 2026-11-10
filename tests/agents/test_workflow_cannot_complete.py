"""A workflow agent node of a scheduled run that reports it cannot do its step is noted on the run's agent."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

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


class _StubNodeAgent:
    def __init__(self, answer: str):
        self._answer = answer
        self.tool_executor = None
        self.attachments = []
        self.llm = SimpleNamespace(get_supported_attachment_types=lambda: [])

    def gen(self, _prompt):
        yield {"answer": self._answer}


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _p: "k")


def _answers(monkeypatch, answers: List[str]) -> None:
    pending = list(answers)
    monkeypatch.setattr(
        WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: _StubNodeAgent(pending.pop(0)))
    )


def _node(node_id: str, node_type: NodeType, title: str, **config: Any) -> WorkflowNode:
    return WorkflowNode(id=node_id, workflow_id="wf", type=node_type, title=title, config=config)


def _run(endpoint: str, *middle: WorkflowNode) -> SimpleNamespace:
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
    engine = WorkflowEngine(graph, agent, workflow_run_id="33333333-3333-3333-3333-333333333333")
    list(engine._run_graph({}, "go"))
    return agent


def _agent(node_id: str, title: str, **config: Any) -> WorkflowNode:
    config.setdefault("stream_to_user", False)
    return _node(node_id, NodeType.AGENT, title, **config)


@pytest.mark.unit
class TestScheduledWorkflowCannotComplete:
    def test_a_quiet_node_that_cannot_do_its_step_is_noted(self, monkeypatch):
        _answers(monkeypatch, ["CANNOT_COMPLETE: no browser tool to open the site", "Summary sent."])

        agent = _run("schedule", _agent("check", "Check site"), _agent("report", "Report", stream_to_user=True))

        assert agent.cannot_complete == "Check site: no browser tool to open the site"

    def test_the_first_node_to_report_is_kept(self, monkeypatch):
        _answers(monkeypatch, ["**CANNOT_COMPLETE:** no browser tool", "CANNOT_COMPLETE: no email tool"])

        agent = _run("schedule", _agent("check", "Check site"), _agent("mail", "Mail"))

        assert agent.cannot_complete == "Check site: no browser tool"

    def test_nodes_that_did_their_steps_note_nothing(self, monkeypatch):
        _answers(monkeypatch, ["The site is up; I cannot complete a login check without an account.", "Sent."])

        agent = _run("schedule", _agent("check", "Check site"), _agent("mail", "Mail"))

        assert agent.cannot_complete is None

    def test_a_run_that_is_not_scheduled_notes_nothing(self, monkeypatch):
        _answers(monkeypatch, ["CANNOT_COMPLETE: no browser tool"])

        agent = _run("stream", _agent("check", "Check site"))

        assert agent.cannot_complete is None
