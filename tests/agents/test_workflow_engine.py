from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from application.api.user.workflows import routes as workflow_routes
from application.agents.workflows.node_agent import WorkflowNodeAgentFactory
from application.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowGraph,
    WorkflowNode,
)
from application.agents.workflows.workflow_engine import WorkflowEngine
from application.api.user.workflows.routes import validate_workflow_structure


class StubNodeAgent:
    def __init__(self, events):
        self.events = events

    def gen(self, _prompt):
        yield from self.events


def create_engine() -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Engine Test"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="test-key",
        chat_history=[],
        decoded_token={"sub": "user-1"},
    )
    return WorkflowEngine(graph, agent)


def create_agent_node(
    node_id: str,
    output_variable: str = "",
    json_schema: Optional[Dict[str, Any]] = None,
) -> WorkflowNode:
    config = {
        "agent_type": "classic",
        "system_prompt": "You are a helpful assistant.",
        "prompt_template": "",
        "stream_to_user": False,
        "tools": [],
    }
    if output_variable:
        config["output_variable"] = output_variable
    if json_schema is not None:
        config["json_schema"] = json_schema

    return WorkflowNode(
        id=node_id,
        workflow_id="workflow-1",
        type=NodeType.AGENT,
        title="Agent",
        position={"x": 0, "y": 0},
        config=config,
    )


def test_execute_agent_node_saves_structured_output_as_json(monkeypatch):
    engine = create_engine()
    node = create_agent_node(
        node_id="agent_1",
        output_variable="result",
        json_schema={"type": "object"},
    )
    node_events = [
        {"answer": '{"summary":"ok",', "structured": True},
        {"answer": '"score":2}', "structured": True},
    ]

    monkeypatch.setattr(
        WorkflowNodeAgentFactory,
        "create",
        staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider",
        lambda _provider: None,
    )

    list(engine._execute_agent_node(node))

    expected_output = {"summary": "ok", "score": 2}
    assert engine.state["node_agent_1_output"] == expected_output
    assert engine.state["result"] == expected_output


def test_execute_agent_node_normalizes_wrapped_schema_before_agent_create(monkeypatch):
    engine = create_engine()
    node = create_agent_node(
        node_id="agent_wrapped",
        json_schema={"schema": {"type": "object"}},
    )
    node_events = [{"answer": '{"summary":"ok"}', "structured": True}]
    captured: Dict[str, Any] = {}

    def create_node_agent(**kwargs):
        captured["json_schema"] = kwargs.get("json_schema")
        return StubNodeAgent(node_events)

    monkeypatch.setattr(
        WorkflowNodeAgentFactory,
        "create",
        staticmethod(create_node_agent),
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider",
        lambda _provider: None,
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_model_capabilities",
        lambda _model_id: {"supports_structured_output": True},
    )

    list(engine._execute_agent_node(node))

    assert captured["json_schema"] == {"type": "object"}
    assert engine.state["node_agent_wrapped_output"] == {"summary": "ok"}


def test_execute_agent_node_falls_back_to_text_when_schema_not_configured(monkeypatch):
    engine = create_engine()
    node = create_agent_node(node_id="agent_2", output_variable="result")
    node_events = [{"answer": "plain text answer"}]

    monkeypatch.setattr(
        WorkflowNodeAgentFactory,
        "create",
        staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider",
        lambda _provider: None,
    )

    list(engine._execute_agent_node(node))

    assert engine.state["node_agent_2_output"] == "plain text answer"
    assert engine.state["result"] == "plain text answer"


def test_validate_workflow_structure_rejects_invalid_agent_json_schema():
    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {
            "id": "agent",
            "type": "agent",
            "title": "Agent",
            "data": {"json_schema": "invalid"},
        },
        {"id": "end", "type": "end", "title": "End", "data": {}},
    ]
    edges = [
        {"id": "edge_1", "source": "start", "target": "agent"},
        {"id": "edge_2", "source": "agent", "target": "end"},
    ]

    errors = validate_workflow_structure(nodes, edges)

    assert any(
        "Agent node 'Agent' JSON schema must be a valid JSON object" in err
        for err in errors
    )


def test_validate_workflow_structure_accepts_valid_agent_json_schema():
    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {
            "id": "agent",
            "type": "agent",
            "title": "Agent",
            "data": {"json_schema": {"type": "object"}},
        },
        {"id": "end", "type": "end", "title": "End", "data": {}},
    ]
    edges = [
        {"id": "edge_1", "source": "start", "target": "agent"},
        {"id": "edge_2", "source": "agent", "target": "end"},
    ]

    errors = validate_workflow_structure(nodes, edges)

    assert errors == []


def test_validate_workflow_structure_accepts_wrapped_agent_json_schema():
    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {
            "id": "agent",
            "type": "agent",
            "title": "Agent",
            "data": {"json_schema": {"schema": {"type": "object"}}},
        },
        {"id": "end", "type": "end", "title": "End", "data": {}},
    ]
    edges = [
        {"id": "edge_1", "source": "start", "target": "agent"},
        {"id": "edge_2", "source": "agent", "target": "end"},
    ]

    errors = validate_workflow_structure(nodes, edges)

    assert errors == []


def test_validate_workflow_structure_accepts_output_variable_and_schema_together():
    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {
            "id": "agent",
            "type": "agent",
            "title": "Agent",
            "data": {
                "output_variable": "answer",
                "json_schema": {"type": "object"},
            },
        },
        {"id": "end", "type": "end", "title": "End", "data": {}},
    ]
    edges = [
        {"id": "edge_1", "source": "start", "target": "agent"},
        {"id": "edge_2", "source": "agent", "target": "end"},
    ]

    errors = validate_workflow_structure(nodes, edges)

    assert errors == []


def test_validate_workflow_structure_rejects_unsupported_structured_output_model(
    monkeypatch,
):
    monkeypatch.setattr(
        workflow_routes,
        "get_model_capabilities",
        lambda _model_id: {"supports_structured_output": False},
    )

    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {
            "id": "agent",
            "type": "agent",
            "title": "Agent",
            "data": {
                "model_id": "some-model",
                "json_schema": {"type": "object"},
            },
        },
        {"id": "end", "type": "end", "title": "End", "data": {}},
    ]
    edges = [
        {"id": "edge_1", "source": "start", "target": "agent"},
        {"id": "edge_2", "source": "agent", "target": "end"},
    ]

    errors = validate_workflow_structure(nodes, edges)

    assert any(
        "Agent node 'Agent' selected model does not support structured output"
        in err
        for err in errors
    )


def test_execute_agent_node_raises_when_structured_output_violates_schema(monkeypatch):
    engine = create_engine()
    node = create_agent_node(
        node_id="agent_3",
        json_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    )
    node_events = [{"answer": '{"score":2}', "structured": True}]

    monkeypatch.setattr(
        WorkflowNodeAgentFactory,
        "create",
        staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider",
        lambda _provider: None,
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_model_capabilities",
        lambda _model_id: {"supports_structured_output": True},
    )

    with pytest.raises(ValueError, match="Structured output did not match schema"):
        list(engine._execute_agent_node(node))


def test_execute_agent_node_raises_when_schema_set_and_response_not_json(monkeypatch):
    engine = create_engine()
    node = create_agent_node(
        node_id="agent_4",
        json_schema={"type": "object"},
    )
    node_events = [{"answer": "not-json"}]

    monkeypatch.setattr(
        WorkflowNodeAgentFactory,
        "create",
        staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider",
        lambda _provider: None,
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_model_capabilities",
        lambda _model_id: {"supports_structured_output": True},
    )

    with pytest.raises(
        ValueError,
        match="Structured output was expected but response was not valid JSON",
    ):
        list(engine._execute_agent_node(node))
