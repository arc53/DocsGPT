"""A workflow run's token total is the sum of its agent nodes' LLM usage.

Each agent node runs its own node agent with its own LLM, so the run's
agent's LLM never sees the tokens; the engine tallies them per run.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from docsgpt.agents.workflow_agent import WorkflowAgent
from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory
from docsgpt.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from docsgpt.agents.workflows.workflow_engine import WorkflowEngine, add_token_usage


class _MeteredLLM:
    """An LLM stand-in whose tally grows when a call ends, as the usage decorators do."""

    def __init__(self, prompt_tokens: int, generated_tokens: int):
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        self._call = (prompt_tokens, generated_tokens)

    def record_call(self) -> None:
        self.token_usage["prompt_tokens"] += self._call[0]
        self.token_usage["generated_tokens"] += self._call[1]

    @staticmethod
    def get_supported_attachment_types() -> List[str]:
        return []


class _MeteredNodeAgent:
    """A node agent that answers once; its call is billed when its stream ends or is closed."""

    def __init__(self, prompt_tokens: int, generated_tokens: int, answer: str = "done", fails: bool = False):
        self.llm = _MeteredLLM(prompt_tokens, generated_tokens)
        self.tool_executor = SimpleNamespace(cannot_complete=None)
        self.attachments: List[Any] = []
        self._answer = answer
        self._fails = fails

    def gen(self, _prompt):
        try:
            yield {"answer": self._answer}
            if self._fails:
                raise RuntimeError("the provider dropped the stream")
        finally:
            self.llm.record_call()


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _p: "k")


def _nodes_answer(monkeypatch, *agents: _MeteredNodeAgent) -> None:
    """Hand out the node agents to the agent nodes in the order they run."""
    pending = list(agents)
    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: pending.pop(0)))


def _node(node_id: str, node_type: NodeType, **config: Any) -> WorkflowNode:
    return WorkflowNode(id=node_id, workflow_id="wf", type=node_type, title=node_id, config=config)


def _agent_node(node_id: str, **config: Any) -> WorkflowNode:
    config.setdefault("stream_to_user", False)
    return _node(node_id, NodeType.AGENT, **config)


def _run_agent() -> SimpleNamespace:
    return SimpleNamespace(
        endpoint="schedule",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="k",
        chat_history=[],
        decoded_token={"sub": "user-1"},
        cannot_complete=None,
        llm=_MeteredLLM(0, 0),
    )


def _engine(nodes: List[WorkflowNode], edges: List[WorkflowEdge]) -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Nightly"), nodes=nodes, edges=edges)
    return WorkflowEngine(graph, _run_agent(), workflow_run_id="44444444-4444-4444-4444-444444444444")


def _chain(*middle: WorkflowNode) -> WorkflowEngine:
    """An engine over Start, ``middle`` and End."""
    nodes = [_node("start", NodeType.START), *middle, _node("end", NodeType.END)]
    edges = [
        WorkflowEdge(id=f"e{i}", workflow_id="wf", source=a.id, target=b.id)
        for i, (a, b) in enumerate(zip(nodes, nodes[1:]))
    ]
    return _engine(nodes, edges)


@pytest.mark.unit
class TestWorkflowNodeTokenUsage:
    def test_two_agent_nodes_are_summed(self, monkeypatch):
        _nodes_answer(monkeypatch, _MeteredNodeAgent(120, 30), _MeteredNodeAgent(80, 20))
        engine = _chain(_agent_node("fetch"), _agent_node("summarize"))

        list(engine.execute({}, "go"))

        assert engine.node_token_usage == {"prompt_tokens": 200, "generated_tokens": 50}

    def test_a_node_that_fails_mid_stream_still_counts(self, monkeypatch):
        _nodes_answer(monkeypatch, _MeteredNodeAgent(50, 5), _MeteredNodeAgent(40, 4, fails=True))
        engine = _chain(_agent_node("fetch"), _agent_node("summarize"))

        events = list(engine.execute({}, "go"))

        assert any(e.get("type") == "error" for e in events)
        assert engine.node_token_usage == {"prompt_tokens": 90, "generated_tokens": 9}

    def test_a_retried_attempt_counts_too(self, monkeypatch):
        monkeypatch.setattr(WorkflowEngine, "_wait_before_retry", lambda self, delay: None)
        _nodes_answer(monkeypatch, _MeteredNodeAgent(60, 0, answer=""), _MeteredNodeAgent(60, 6))
        engine = _chain(_agent_node("ask", retry={"max_attempts": 2, "backoff_seconds": [1]}))

        list(engine.execute({}, "go"))

        assert engine.state["node_ask_output"] == "done"
        assert engine.node_token_usage == {"prompt_tokens": 120, "generated_tokens": 6}

    def test_a_run_closed_mid_node_counts_the_open_call(self, monkeypatch):
        # A stopped run closes the engine while a node streams; that node's call ended too.
        _nodes_answer(monkeypatch, _MeteredNodeAgent(70, 7))
        engine = _chain(_agent_node("fetch", stream_to_user=True))

        events = engine.execute({}, "go")
        for event in events:
            if "answer" in event:
                break
        events.close()

        assert engine.node_token_usage == {"prompt_tokens": 70, "generated_tokens": 7}

    def test_loop_items_add_to_the_runs_total(self, monkeypatch):
        _nodes_answer(monkeypatch, *(_MeteredNodeAgent(10, 2) for _ in range(3)))
        nodes = [
            _node("start", NodeType.START),
            _node("each", NodeType.LOOP, items="items", concurrency=3, output_variable="results"),
            _node("end", NodeType.END),
            _agent_node("summarize", parent_id="each", agent_type="classic", prompt_template="{{ item }}"),
        ]
        edges = [
            WorkflowEdge(id="e0", workflow_id="wf", source="start", target="each"),
            WorkflowEdge(id="e1", workflow_id="wf", source="each", target="end"),
        ]
        engine = _engine(nodes, edges)

        list(engine.execute({"items": ["a", "b", "c"]}, "go"))

        assert engine.state["results"] == ["done", "done", "done"]
        assert engine.node_token_usage == {"prompt_tokens": 30, "generated_tokens": 6}

    def test_a_fallback_models_tokens_count(self, monkeypatch):
        node_agent = _MeteredNodeAgent(50, 5)
        node_agent.llm._fallback_llm = SimpleNamespace(token_usage={"prompt_tokens": 40, "generated_tokens": 4})
        _nodes_answer(monkeypatch, node_agent)
        engine = _chain(_agent_node("ask"))

        list(engine.execute({}, "go"))

        assert engine.node_token_usage == {"prompt_tokens": 90, "generated_tokens": 9}

    def test_cache_bins_are_carried_when_reported(self):
        total = {"prompt_tokens": 1, "generated_tokens": 1}

        add_token_usage(total, {"prompt_tokens": 9, "generated_tokens": 2, "cached_tokens": 4})
        add_token_usage(total, None)

        assert total == {"prompt_tokens": 10, "generated_tokens": 3, "cached_tokens": 4}


@pytest.mark.unit
class TestWorkflowAgentTokenUsage:
    def _agent(self, own: Dict[str, int], nodes: Dict[str, int] | None) -> WorkflowAgent:
        agent = WorkflowAgent.__new__(WorkflowAgent)
        agent.llm = SimpleNamespace(token_usage=own)
        agent._engine = SimpleNamespace(node_token_usage=nodes) if nodes is not None else None
        return agent

    def test_adds_its_own_llm_to_its_nodes(self):
        agent = self._agent({"prompt_tokens": 3, "generated_tokens": 1}, {"prompt_tokens": 200, "generated_tokens": 50})

        assert agent.token_usage == {"prompt_tokens": 203, "generated_tokens": 51}

    def test_a_run_that_never_started_reports_its_own_llm(self):
        agent = self._agent({"prompt_tokens": 0, "generated_tokens": 0}, None)

        assert agent.token_usage == {"prompt_tokens": 0, "generated_tokens": 0}
