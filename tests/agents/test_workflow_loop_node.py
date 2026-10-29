import threading
import time
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
from docsgpt.api.user.workflows.routes import validate_workflow_structure


class PromptAgent:
    """A node agent whose answer is ``reply(prompt)``; raising fails the node."""

    def __init__(self, reply):
        self.reply = reply

    def gen(self, prompt):
        yield {"answer": self.reply(prompt)}


@pytest.fixture
def node_agent(monkeypatch):
    """Route every agent node to ``holder['reply']``; record what each node was created with."""
    holder: Dict[str, Any] = {"reply": lambda prompt: prompt.upper(), "created": []}

    def create(**kwargs):
        holder["created"].append(kwargs)
        return PromptAgent(holder["reply"])

    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(create))
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _provider: None)
    return holder


def _node(node_id: str, node_type: NodeType, parent: Optional[str] = None, **config) -> WorkflowNode:
    if parent:
        config["parent_id"] = parent
    return WorkflowNode(
        id=node_id, workflow_id="wf", type=node_type, title=node_id, position={"x": 0, "y": 0}, config=config
    )


def _agent(node_id: str, parent: Optional[str] = None, **config) -> WorkflowNode:
    defaults = {"agent_type": "classic", "prompt_template": "{{ item.name }}", "stream_to_user": False}
    return _node(node_id, NodeType.AGENT, parent, **{**defaults, **config})


def _edge(source: str, target: str) -> WorkflowEdge:
    return WorkflowEdge(id=f"{source}-{target}", workflow_id="wf", source=source, target=target)


def _engine(loop_config: Dict[str, Any], body: List[WorkflowNode], body_edges=(), state=None) -> WorkflowEngine:
    nodes = [
        _node("start", NodeType.START),
        _node("each", NodeType.LOOP, **loop_config),
        _node("end", NodeType.END),
        *body,
    ]
    edges = [_edge("start", "each"), _edge("each", "end"), *body_edges]
    graph = WorkflowGraph(workflow=Workflow(name="Loop"), nodes=nodes, edges=edges)
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="key",
        chat_history=[],
        decoded_token={"sub": "user-1"},
    )
    engine = WorkflowEngine(graph, agent)
    engine._initial = state or {}
    return engine


def _run(engine: WorkflowEngine) -> List[Dict[str, Any]]:
    return list(engine.execute(engine._initial, "q"))


ITEMS = [{"name": "a"}, {"name": "b"}, {"name": "c"}]


def test_three_items_give_three_results_in_input_order(node_agent):
    # Earlier items finish last, so completion order is the reverse of input order.
    delays = {"a": 0.15, "b": 0.08, "c": 0.0}

    def reply(prompt):
        time.sleep(delays[prompt])
        return prompt.upper()

    node_agent["reply"] = reply
    engine = _engine(
        {"items": "extracted.items", "concurrency": 3, "output_variable": "results"},
        [_agent("summarize", parent="each")],
        state={"extracted": {"items": ITEMS}},
    )

    events = _run(engine)

    assert engine.state["results"] == ["A", "B", "C"]
    assert engine.state["node_each_output"] == ["A", "B", "C"]
    assert "item" not in engine.state
    assert "node_summarize_output" not in engine.state
    assert not [e for e in events if e.get("type") == "error"]


def test_item_variable_and_body_writes_stay_out_of_parent_state(node_agent):
    engine = _engine(
        {"items": "names", "item_variable": "person", "output_variable": "results"},
        [_agent("greet", parent="each", prompt_template="{{ person }}", output_variable="greeting")],
        state={"names": ["ann", "bo"]},
    )

    _run(engine)

    assert engine.state["results"] == ["ANN", "BO"]
    assert "person" not in engine.state
    assert "greeting" not in engine.state


def test_collect_puts_the_error_in_the_failed_items_slot(node_agent):
    def reply(prompt):
        if prompt == "b":
            raise ValueError("bad item")
        return prompt.upper()

    node_agent["reply"] = reply
    engine = _engine(
        {"items": "items", "on_item_error": "collect", "output_variable": "results"},
        [_agent("summarize", parent="each")],
        state={"items": ITEMS},
    )

    events = _run(engine)

    assert engine.state["results"] == ["A", {"error": "bad item"}, "C"]
    assert not [e for e in events if e.get("type") == "error"]


def test_skip_leaves_failed_items_out(node_agent):
    def reply(prompt):
        if prompt == "a":
            raise ValueError("bad item")
        return prompt.upper()

    node_agent["reply"] = reply
    engine = _engine(
        {"items": "items", "on_item_error": "skip", "output_variable": "results"},
        [_agent("summarize", parent="each")],
        state={"items": ITEMS},
    )

    _run(engine)

    assert engine.state["results"] == ["B", "C"]


def test_fail_is_the_default_and_writes_nothing(node_agent):
    def reply(prompt):
        if prompt == "b":
            raise ValueError("bad item")
        return prompt.upper()

    node_agent["reply"] = reply
    engine = _engine(
        {"items": "items", "concurrency": 1, "output_variable": "results"},
        [_agent("summarize", parent="each")],
        state={"items": ITEMS},
    )

    events = _run(engine)

    assert "results" not in engine.state
    assert "node_each_output" not in engine.state
    errors = [e for e in events if e.get("type") == "error"]
    assert len(errors) == 1
    assert "item 2 of 3 failed: bad item" in errors[0]["error"]
    assert errors[0]["user_facing"] is True
    loop_log = next(log for log in engine.execution_log if log["node_id"] == "each")
    assert loop_log["status"] == "failed"
    # Sequential: the item after the failure never started.
    assert [item["status"] for item in loop_log["items"]] == ["completed", "failed", "pending"]
    assert all(e.get("node_id") != "end" for e in events if e.get("type") == "workflow_step")


def test_more_than_max_items_fails_before_running_any(node_agent):
    engine = _engine(
        {"items": "items", "max_items": 2, "output_variable": "results"},
        [_agent("summarize", parent="each")],
        state={"items": ITEMS},
    )

    events = _run(engine)

    assert node_agent["created"] == []
    assert "results" not in engine.state
    error = next(e for e in events if e.get("type") == "error")
    assert "got 3 items; it accepts at most 2" in error["error"]


def test_instance_cap_on_items_overrides_the_node(node_agent, monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "WORKFLOW_LOOP_MAX_ITEMS", 2)
    engine = _engine({"items": "items", "max_items": 50}, [_agent("summarize", parent="each")], state={"items": ITEMS})

    events = _run(engine)

    assert node_agent["created"] == []
    assert any("accepts at most 2" in e.get("error", "") for e in events if e.get("type") == "error")


def test_items_that_are_not_a_list_fail_the_node(node_agent):
    engine = _engine({"items": "items"}, [_agent("summarize", parent="each")], state={"items": {"a": 1}})

    events = _run(engine)

    error = next(e for e in events if e.get("type") == "error")
    assert '"items" is dict, not a list' in error["error"]


def test_items_read_a_json_array_string_and_the_agent_prefix(node_agent):
    engine = _engine(
        {"items": "agent.raw", "item_variable": "word", "output_variable": "results"},
        [_agent("summarize", parent="each", prompt_template="{{ word }}")],
        state={"raw": '["x", "y"]'},
    )

    _run(engine)

    assert engine.state["results"] == ["X", "Y"]


def test_body_steps_carry_the_loop_and_item_and_never_stream(node_agent):
    engine = _engine(
        {"items": "items", "concurrency": 2},
        [_agent("summarize", parent="each", stream_to_user=True)],
        state={"items": ITEMS},
    )

    events = _run(engine)

    assert not [e for e in events if "answer" in e]
    body_steps = [e for e in events if e.get("type") == "workflow_step" and e["node_id"] == "summarize"]
    assert len(body_steps) == 6
    assert {e["parent_node_id"] for e in body_steps} == {"each"}
    assert sorted({e["item_index"] for e in body_steps}) == [0, 1, 2]
    assert {e["item_count"] for e in body_steps} == {3}
    top_steps = [e for e in events if e.get("type") == "workflow_step" and e["node_id"] != "summarize"]
    assert all("parent_node_id" not in e for e in top_steps)
    item_events = [e for e in events if e.get("type") == "workflow_loop_item"]
    assert sorted((e["item_index"], e["status"]) for e in item_events) == [
        (0, "completed"), (0, "running"), (1, "completed"), (1, "running"), (2, "completed"), (2, "running"),
    ]


def test_concurrency_is_bounded_by_the_instance_cap(node_agent, monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "WORKFLOW_LOOP_MAX_CONCURRENCY", 2)
    lock = threading.Lock()
    running = {"now": 0, "peak": 0}

    def reply(prompt):
        with lock:
            running["now"] += 1
            running["peak"] = max(running["peak"], running["now"])
        time.sleep(0.05)
        with lock:
            running["now"] -= 1
        return prompt

    node_agent["reply"] = reply
    engine = _engine(
        {"items": "items", "concurrency": 10},
        [_agent("summarize", parent="each")],
        state={"items": [{"name": str(i)} for i in range(6)]},
    )

    _run(engine)

    assert running["peak"] == 2


def test_execution_log_nests_item_steps_under_the_loop(node_agent):
    engine = _engine({"items": "items"}, [_agent("summarize", parent="each")], state={"items": ITEMS[:2]})

    _run(engine)

    assert [log["node_id"] for log in engine.execution_log] == ["start", "each", "end"]
    summary = {log.node_id: log for log in engine.get_execution_summary()}
    items = summary["each"].items
    assert [item.item_index for item in items] == [0, 1]
    assert all(item.status.value == "completed" for item in items)
    assert [step.node_id for step in items[0].steps] == ["summarize"]
    assert items[0].steps[0].state_delta["node_summarize_output"] == "A"
    # The run record serializes the nested logs.
    dumped = summary["each"].model_dump(mode="json")
    assert dumped["items"][1]["steps"][0]["node_id"] == "summarize"


def test_sub_graph_body_runs_its_nodes_in_order(node_agent):
    body = [
        _node(
            "label",
            NodeType.STATE,
            parent="each",
            operations=[{"expression": "item.name + '!'", "target_variable": "label"}],
        ),
        _agent("shout", parent="each", prompt_template="{{ label }}"),
        _node("note", NodeType.NOTE, parent="each"),
    ]
    engine = _engine(
        {"items": "items", "output_variable": "results"},
        body,
        body_edges=[_edge("label", "shout")],
        state={"items": ITEMS[:2]},
    )

    _run(engine)

    assert engine.state["results"] == ["A!", "B!"]
    assert "label" not in engine.state


def test_result_variable_picks_the_item_result(node_agent):
    body = [
        _agent("shout", parent="each"),
        _node(
            "score",
            NodeType.STATE,
            parent="each",
            operations=[{"expression": "size(item.name)", "target_variable": "score"}],
        ),
    ]
    engine = _engine(
        {"items": "items", "output_variable": "results", "result_variable": "score"},
        body,
        body_edges=[_edge("shout", "score")],
        state={"items": [{"name": "ab"}, {"name": "c"}]},
    )

    _run(engine)

    assert engine.state["results"] == [2, 1]


def test_condition_in_the_body_ends_the_item_on_a_branch(node_agent):
    body = [
        _node(
            "check",
            NodeType.CONDITION,
            parent="each",
            cases=[{"expression": "item.name == 'b'", "sourceHandle": "is_b"}],
        ),
        _agent("shout", parent="each"),
        _agent("whisper", parent="each", prompt_template="quiet {{ item.name }}"),
    ]
    edges = [
        WorkflowEdge(id="e1", workflow_id="wf", source="check", target="shout", sourceHandle="is_b"),
        WorkflowEdge(id="e2", workflow_id="wf", source="check", target="whisper", sourceHandle="else"),
    ]
    node_agent["reply"] = lambda prompt: prompt
    engine = _engine(
        {"items": "items", "output_variable": "results"},
        body,
        body_edges=edges,
        state={"items": ITEMS},
    )

    _run(engine)

    assert engine.state["results"] == ["quiet a", "b", "quiet c"]


def test_empty_list_gives_empty_results(node_agent):
    engine = _engine(
        {"items": "items", "output_variable": "results"}, [_agent("summarize", parent="each")], state={"items": []}
    )

    _run(engine)

    assert engine.state["results"] == []


def test_reserved_item_variable_fails_the_node(node_agent):
    engine = _engine(
        {"items": "items", "item_variable": "query"}, [_agent("summarize", parent="each")], state={"items": ITEMS}
    )

    events = _run(engine)

    assert any('cannot use "query"' in e.get("error", "") for e in events if e.get("type") == "error")


def test_a_body_node_reached_from_outside_its_loop_fails(node_agent):
    engine = _engine({"items": "items"}, [_agent("summarize", parent="each")], state={"items": ITEMS})
    engine.graph.edges = [_edge("start", "summarize")]

    events = _run(engine)

    assert node_agent["created"] == []
    assert any("across a loop's boundary" in e.get("error", "") for e in events if e.get("type") == "error")


def test_failed_items_stop_running_items_at_their_next_node(node_agent):
    first_started = threading.Event()

    def reply(prompt):
        if prompt == "a":
            first_started.set()
            return "A"
        if prompt == "b":
            first_started.wait(1)
            raise ValueError("bad item")
        if prompt == "second a":
            time.sleep(0.2)
        return prompt

    node_agent["reply"] = reply
    body = [_agent("one", parent="each"), _agent("two", parent="each", prompt_template="second {{ item.name }}")]
    engine = _engine(
        {"items": "items", "concurrency": 2},
        body,
        body_edges=[_edge("one", "two")],
        state={"items": ITEMS[:2]},
    )

    _run(engine)

    loop_log = next(log for log in engine.execution_log if log["node_id"] == "each")
    assert loop_log["status"] == "failed"
    assert loop_log["items"][1]["error"] == "bad item"


def test_a_template_mutating_nested_state_stays_inside_its_item(node_agent):
    engine = _engine(
        {"items": "items", "concurrency": 1, "output_variable": "results"},
        [
            _agent(
                "touch",
                parent="each",
                prompt_template=(
                    "{% set _ = seen.append(item.name) %}{% set _ = item.update({'name': 'x'}) %}{{ seen | length }}"
                ),
            )
        ],
        state={"items": ITEMS[:2], "seen": []},
    )

    _run(engine)

    assert engine.state["results"] == ["1", "1"]
    assert engine.state["seen"] == []
    assert engine.state["items"] == ITEMS[:2]


def test_fail_names_the_item_that_failed_not_one_it_stopped(node_agent):
    failed = threading.Event()

    def reply(prompt):
        if prompt == "c":
            failed.set()
            raise ValueError("bad item")
        if prompt in ("a", "b"):
            # Finish the first node only after the failure has stopped the loop.
            failed.wait(1)
            time.sleep(0.2)
        return prompt

    node_agent["reply"] = reply
    body = [_agent("one", parent="each"), _agent("two", parent="each", prompt_template="again")]
    engine = _engine(
        {"items": "items", "concurrency": 3},
        body,
        body_edges=[_edge("one", "two")],
        state={"items": ITEMS},
    )

    events = _run(engine)

    error = next(e for e in events if e.get("type") == "error")
    assert "item 3 of 3 failed: bad item" in error["error"]
    loop_log = next(log for log in engine.execution_log if log["node_id"] == "each")
    assert loop_log["items"][0]["error"] == "Stopped because another item failed."


def test_progress_skips_steps_inside_a_loop():
    from docsgpt.agents.workflow_agent import WorkflowAgent

    agent = WorkflowAgent.__new__(WorkflowAgent)
    agent._run_persisted = True
    agent.workflow_id = "wf"
    agent._engine = SimpleNamespace(graph=SimpleNamespace(linear_step_count=lambda: 3), workflow_run_id="run")
    recorded = []
    agent._record_progress = lambda user, progress: recorded.append(progress["current"]["node_id"])
    events = [
        {"type": "workflow_step", "node_id": "each", "node_type": "loop", "status": "running"},
        {
            "type": "workflow_step",
            "node_id": "summarize",
            "node_type": "agent",
            "status": "running",
            "parent_node_id": "each",
            "item_index": 0,
        },
    ]

    list(agent._with_progress(iter(events), "user-1"))

    assert recorded == ["each"]


# --- save-time validation ---------------------------------------------------


def _graph(loop_data=None, body=None, extra_edges=()):
    loop = {"id": "each", "type": "loop", "title": "Each", "data": {"items": "extracted.items", **(loop_data or {})}}
    nodes = [
        {"id": "start", "type": "start", "data": {}},
        {"id": "first", "type": "agent", "title": "First", "data": {}},
        loop,
        {"id": "end", "type": "end", "data": {}},
        *(
            body
            if body is not None
            else [{"id": "summarize", "type": "agent", "title": "Summarize", "data": {"parent_id": "each"}}]
        ),
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "first"},
        {"id": "e2", "source": "first", "target": "each"},
        {"id": "e3", "source": "each", "target": "end"},
        *extra_edges,
    ]
    return nodes, edges


def test_validation_accepts_a_loop_with_a_body():
    assert validate_workflow_structure(*_graph()) == []


def test_validation_accepts_a_condition_in_the_body_without_an_end():
    body = [
        {
            "id": "check",
            "type": "condition",
            "title": "Check",
            "data": {"parent_id": "each", "cases": [{"expression": "item.x > 1", "sourceHandle": "big"}]},
        },
        {"id": "a", "type": "agent", "title": "A", "data": {"parent_id": "each"}},
        {"id": "b", "type": "agent", "title": "B", "data": {"parent_id": "each"}},
    ]
    edges = [
        {"id": "b1", "source": "check", "target": "a", "sourceHandle": "big"},
        {"id": "b2", "source": "check", "target": "b", "sourceHandle": "else"},
    ]
    assert validate_workflow_structure(*_graph(body=body, extra_edges=edges)) == []


@pytest.mark.parametrize(
    "loop_data, expected",
    [
        ({"items": ""}, "must name the state list"),
        ({"items": "a b"}, "must be a state path"),
        ({"item_variable": "query"}, "cannot use 'query'"),
        ({"item_variable": "1x"}, "cannot use '1x'"),
        ({"concurrency": 0}, "concurrency must be a whole number"),
        ({"max_items": "10"}, "max_items must be a whole number"),
        ({"on_item_error": "retry"}, "on_item_error must be"),
    ],
)
def test_validation_rejects_bad_loop_config(loop_data, expected):
    errors = validate_workflow_structure(*_graph(loop_data=loop_data))
    assert any(expected in error for error in errors), errors


def test_validation_rejects_an_empty_body():
    errors = validate_workflow_structure(*_graph(body=[]))
    assert any("needs at least one node inside it" in error for error in errors)


def test_validation_rejects_a_body_with_two_first_nodes():
    body = [
        {"id": "a", "type": "agent", "title": "A", "data": {"parent_id": "each"}},
        {"id": "b", "type": "agent", "title": "B", "data": {"parent_id": "each"}},
    ]
    errors = validate_workflow_structure(*_graph(body=body))
    assert any("must start at exactly one node" in error for error in errors)


def test_validation_rejects_edges_across_the_boundary():
    errors = validate_workflow_structure(
        *_graph(extra_edges=[{"id": "x", "source": "first", "target": "summarize"}])
    )
    assert any("crosses a loop's boundary" in error for error in errors)


def test_validation_rejects_nested_loops_and_end_nodes_in_a_body():
    body = [
        {"id": "summarize", "type": "agent", "title": "Summarize", "data": {"parent_id": "each"}},
        {"id": "inner", "type": "loop", "title": "Inner", "data": {"parent_id": "each", "items": "x"}},
        {"id": "stop", "type": "end", "title": "Stop", "data": {"parent_id": "each"}},
    ]
    errors = validate_workflow_structure(*_graph(body=body))
    assert any("cannot contain loop nodes" in error for error in errors)
    assert any("cannot contain end nodes" in error for error in errors)


def test_validation_rejects_a_parent_that_is_not_a_loop():
    body = [{"id": "summarize", "type": "agent", "title": "Summarize", "data": {"parent_id": "first"}}]
    errors = validate_workflow_structure(*_graph(body=body))
    assert any("which is not a loop" in error for error in errors)
