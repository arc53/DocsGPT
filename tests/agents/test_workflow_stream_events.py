"""Size of the ``workflow_step`` events a run streams.

A completed or failed step carries its output and state delta while they fit
``WORKFLOW_STREAM_MAX_EVENT_BYTES``; past that it carries a summary, and the
full values stay in the run's saved steps. A node can opt into ``full`` or
``none`` with ``stream_output``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List

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
from docsgpt.core.settings import settings

LIMIT = 4096


def _size(event: Dict[str, Any]) -> int:
    return len(json.dumps(event, ensure_ascii=False, default=str).encode("utf-8"))


class _StubNodeAgent:
    def __init__(self, answer: str, **kwargs):
        self._answer = answer
        self.tool_executor = None
        self.attachments = []
        self.llm = SimpleNamespace(get_supported_attachment_types=lambda: [])

    def gen(self, _prompt):
        yield {"answer": self._answer}


@pytest.fixture(autouse=True)
def _limit(monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_STREAM_MAX_EVENT_BYTES", LIMIT)
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _p: "k")


def _stub_answer(monkeypatch, answer: str) -> None:
    monkeypatch.setattr(
        WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: _StubNodeAgent(answer, **kwargs))
    )


def _node(node_id: str, node_type: NodeType, title: str, **config: Any) -> WorkflowNode:
    return WorkflowNode(id=node_id, workflow_id="wf", type=node_type, title=title, config=config)


def _engine(*middle: WorkflowNode, end_config: Dict[str, Any] = None) -> WorkflowEngine:
    nodes = [_node("start", NodeType.START, "Start"), *middle, _node("end", NodeType.END, "End", **(end_config or {}))]
    edges = [
        WorkflowEdge(id=f"e{i}", workflow_id="wf", source=a.id, target=b.id)
        for i, (a, b) in enumerate(zip(nodes, nodes[1:]))
    ]
    graph = WorkflowGraph(workflow=Workflow(name="Stream"), nodes=nodes, edges=edges)
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="k",
        chat_history=[],
        user="user-1",
        decoded_token={"sub": "user-1"},
    )
    return WorkflowEngine(graph, agent, workflow_run_id="33333333-3333-3333-3333-333333333333")


def _agent(node_id: str = "extract", **config: Any) -> WorkflowNode:
    config.setdefault("output_variable", "terms")
    return _node(node_id, NodeType.AGENT, "Extract", stream_to_user=False, **config)


def _run(engine: WorkflowEngine, inputs: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    return list(engine._run_graph(inputs or {}, "go"))


def _step(events: List[Dict[str, Any]], node_id: str, status: str = "completed") -> Dict[str, Any]:
    return next(e for e in events if e.get("type") == "workflow_step" and e["node_id"] == node_id and e["status"] == status)


@pytest.mark.unit
class TestSmallSteps:
    def test_a_small_step_carries_its_output_once(self, monkeypatch):
        _stub_answer(monkeypatch, "30 days")

        event = _step(_run(_engine(_agent())), "extract")

        assert event["output"] == "30 days"
        assert "node_extract_output" not in event["state_delta"]
        assert event["state_delta"]["terms"] == "30 days"
        assert "summarized" not in event

    def test_every_finished_step_names_its_place_in_the_run(self, monkeypatch):
        _stub_answer(monkeypatch, "ok")
        events = _run(_engine(_agent("a"), _agent("b")))

        assert [_step(events, n)["step_index"] for n in ("start", "a", "b", "end")] == [0, 1, 2, 3]
        assert "step_index" not in next(e for e in events if e.get("status") == "running")


@pytest.mark.unit
class TestLargeSteps:
    def test_a_large_output_is_summarized_under_the_limit(self, monkeypatch):
        _stub_answer(monkeypatch, "word " * 5000)

        event = _step(_run(_engine(_agent())), "extract")

        assert _size(event) <= LIMIT
        assert event["summarized"] is True
        assert event["output_truncated"] is True
        assert event["output_preview"].startswith("word word")
        assert event["output_bytes"] == len(json.dumps(("word " * 5000).strip()).encode())
        assert event["state_keys_changed"] == ["terms"]
        assert "output" not in event and "state_delta" not in event

    def test_a_small_output_stays_whole_when_the_state_is_what_is_large(self, monkeypatch):
        _stub_answer(monkeypatch, "short")
        state_node = _node(
            "copy", NodeType.STATE, "Copy", operations=[{"expression": "big", "target_variable": "copied"}]
        )
        events = _run(_engine(state_node, _agent()), {"big": "x" * 10000})

        copy_event = _step(events, "copy")
        assert _size(copy_event) <= LIMIT
        assert copy_event["summarized"] is True
        assert "copied" in copy_event["state_keys_changed"]
        assert _step(events, "extract")["output"] == "short"

    def test_the_budget_counts_utf8_bytes_not_ascii_escapes(self, monkeypatch):
        # 1,500 Cyrillic characters: 3,000 bytes as UTF-8, 9,000 as \\u escapes.
        _stub_answer(monkeypatch, "д" * 1500)

        event = _step(_run(_engine(_agent(output_variable=None))), "extract")

        assert event["output"] == "д" * 1500
        assert "summarized" not in event

    def test_a_failed_step_with_a_large_delta_is_summarized(self, monkeypatch):
        state_node = _node(
            "copy",
            NodeType.STATE,
            "Copy",
            operations=[
                {"expression": "big", "target_variable": "copied"},
                {"expression": "missing_var + 1", "target_variable": "boom"},
            ],
        )
        events = _run(_engine(state_node), {"big": "x" * 10000})

        failed = _step(events, "copy", "failed")
        assert _size(failed) <= LIMIT
        assert failed["error"]
        assert failed["summarized"] is True

    def test_a_long_list_of_changed_keys_is_cut_to_fit(self, monkeypatch):
        operations = [{"expression": f'"{"v" * 40}"', "target_variable": f"key_{i:04d}_{'k' * 60}"} for i in range(400)]
        events = _run(_engine(_node("many", NodeType.STATE, "Many", operations=operations)))

        event = _step(events, "many")
        assert _size(event) <= LIMIT
        assert event["state_keys_truncated"] is True
        assert 0 < len(event["state_keys_changed"]) < 400


@pytest.mark.unit
class TestStreamOutputSetting:
    def test_full_sends_everything(self, monkeypatch):
        _stub_answer(monkeypatch, "word " * 5000)

        event = _step(_run(_engine(_agent(stream_output="full"))), "extract")

        assert event["output"] == ("word " * 5000).strip()
        assert event["state_delta"]["terms"] == event["output"]
        assert "summarized" not in event

    def test_none_sends_the_status_only(self, monkeypatch):
        _stub_answer(monkeypatch, "secret terms")

        event = _step(_run(_engine(_agent(stream_output="none"))), "extract")

        assert event["output_omitted"] is True
        for key in ("output", "state_delta", "output_preview", "state_keys_changed"):
            assert key not in event
        assert "secret" not in json.dumps(event)

    def test_none_works_on_any_node_type(self):
        state_node = _node(
            "copy", NodeType.STATE, "Copy", stream_output="none",
            operations=[{"expression": '"hidden"', "target_variable": "v"}],
        )
        event = _step(_run(_engine(state_node)), "copy")
        assert event["output_omitted"] is True and "hidden" not in json.dumps(event)

    def test_an_unknown_value_falls_back_to_summary(self, monkeypatch):
        state_node = _node(
            "copy", NodeType.STATE, "Copy", stream_output="everything",
            operations=[{"expression": "big", "target_variable": "copied"}],
        )
        event = _step(_run(_engine(state_node), {"big": "x" * 10000}), "copy")
        assert event["summarized"] is True


@pytest.mark.unit
class TestAnswerChunks:
    def test_a_long_end_node_answer_streams_in_chunks_under_the_limit(self):
        text = "Ответ " * 3000
        events = _run(_engine(end_config={"output_template": "{{ long }}"}), {"long": text})

        answers = [e for e in events if "answer" in e]
        assert len(answers) > 1
        assert all(_size(e) <= LIMIT for e in answers)
        assert "".join(e["answer"] for e in answers) == text


@pytest.mark.unit
class TestValidation:
    def _graph(self, stream_output):
        from docsgpt.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start", "title": "Start", "data": {}},
            {
                "id": "copy",
                "type": "state",
                "title": "Copy",
                "data": {
                    "operations": [{"expression": '"x"', "target_variable": "v"}],
                    "stream_output": stream_output,
                },
            },
            {"id": "end", "type": "end", "title": "End", "data": {}},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "copy"},
            {"id": "e2", "source": "copy", "target": "end"},
        ]
        return validate_workflow_structure(nodes, edges)

    @pytest.mark.parametrize("value", ["full", "summary", "none"])
    def test_known_values_save(self, value):
        assert self._graph(value) == []

    def test_an_unknown_value_is_rejected_on_save(self):
        errors = self._graph("everything")
        assert any("Copy" in e and "stream_output" in e for e in errors), errors

    def test_the_schemas_accept_it(self):
        from docsgpt.agents.workflows.schemas import AgentNodeConfig, CodeNodeConfig

        assert AgentNodeConfig().stream_output == "summary"
        assert CodeNodeConfig(stream_output="none").stream_output == "none"
