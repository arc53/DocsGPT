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
        lambda _model_id, **_kwargs: {"supports_structured_output": True},
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


def _state_workflow(operations, nested=True):
    """Start → state → end, with state config in either accepted shape."""
    data = {"config": {"operations": operations}} if nested else {
        "operations": operations
    }
    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {"id": "state", "type": "state", "title": "Build reply", "data": data},
        {"id": "end", "type": "end", "title": "End", "data": {}},
    ]
    edges = [
        {"id": "edge_1", "source": "start", "target": "state"},
        {"id": "edge_2", "source": "state", "target": "end"},
    ]
    return nodes, edges


@pytest.mark.parametrize("nested", [True, False])
def test_validate_workflow_structure_rejects_template_syntax_in_state_node(nested):
    """``{{query}}`` compiles nowhere but used to save and publish clean.

    It then aborted the run on the first message with a bare caret dump that
    ``sanitize_api_error`` collapsed into "try again later" — the 2026-08-01
    report, where a new user retried eight times over seven hours.
    """
    nodes, edges = _state_workflow(
        [{"expression": "{{query}}", "target_variable": "reply"}], nested=nested
    )

    errors = validate_workflow_structure(nodes, edges)

    assert any(
        "Set State node 'Build reply'" in err and "invalid expression" in err
        for err in errors
    ), errors
    # The message must teach the correction, not just report a failure.
    assert any("CEL" in err for err in errors), errors


def test_validate_workflow_structure_accepts_valid_state_expression():
    nodes, edges = _state_workflow(
        [{"expression": 'query + "!"', "target_variable": "reply"}]
    )
    assert validate_workflow_structure(nodes, edges) == []


def test_validate_workflow_structure_accepts_runtime_only_state_reference():
    """Names resolve from run state, so they cannot be checked at save time."""
    nodes, edges = _state_workflow(
        [{"expression": "node_agent_1_output", "target_variable": "reply"}]
    )
    assert validate_workflow_structure(nodes, edges) == []


def test_validate_workflow_structure_rejects_half_configured_state_operation():
    """The engine skips these silently, so downstream reads an unset var."""
    nodes, edges = _state_workflow(
        [{"expression": "query", "target_variable": ""}]
    )
    errors = validate_workflow_structure(nodes, edges)
    assert any("no target variable" in err for err in errors), errors


def test_validate_workflow_structure_rejects_invalid_condition_expression():
    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {
            "id": "cond",
            "type": "condition",
            "title": "Route",
            "data": {
                "cases": [
                    {"expression": "{{query}}", "sourceHandle": "case_0"},
                    {"expression": "true", "sourceHandle": "else"},
                ]
            },
        },
        {"id": "end", "type": "end", "title": "End", "data": {}},
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "cond"},
        {"id": "e2", "source": "cond", "target": "end", "sourceHandle": "case_0"},
        {"id": "e3", "source": "cond", "target": "end", "sourceHandle": "else"},
    ]

    errors = validate_workflow_structure(nodes, edges)

    assert any("invalid expression" in err for err in errors), errors


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
        lambda _model_id, **_kwargs: {"supports_structured_output": False},
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
        lambda _model_id, **_kwargs: {"supports_structured_output": True},
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
        lambda _model_id, **_kwargs: {"supports_structured_output": True},
    )

    with pytest.raises(
        ValueError,
        match="Structured output was expected but response was not valid JSON",
    ):
        list(engine._execute_agent_node(node))


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines: 204, 213-215, 223, 283-284, 289,
# 355, 375
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowEngineAdditionalCoverage:

    def test_agent_node_prompt_template_empty_uses_query(self, monkeypatch):
        """Cover line 204: prompt_template is empty, uses state query."""
        engine = create_engine()
        engine.state["query"] = "What is the answer?"
        node = create_agent_node(node_id="n1")
        node.config["prompt_template"] = ""

        node_events = [{"answer": "42"}]
        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _: None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda _, **_kwargs: None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_model_capabilities",
            lambda _, **_kwargs: None,
        )

        list(engine._execute_agent_node(node))
        assert engine.state["node_n1_output"] == "42"

    def test_agent_node_model_config_override(self, monkeypatch):
        """Cover lines 213-215: node_config with model_id and llm_name."""
        engine = create_engine()
        engine.state["query"] = "test"
        node = create_agent_node(node_id="n2")
        node.config["model_id"] = "gpt-4o"
        node.config["llm_name"] = "openai"

        node_events = [{"answer": "result"}]
        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _: "key",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda _, **_kwargs: "openai",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_model_capabilities",
            lambda _, **_kwargs: None,
        )

        list(engine._execute_agent_node(node))
        assert engine.state["node_n2_output"] == "result"

    def test_agent_node_unsupported_structured_output_raises(self, monkeypatch):
        """Cover line 223: model does not support structured output raises."""
        engine = create_engine()
        engine.state["query"] = "test"
        node = create_agent_node(
            node_id="n3",
            json_schema={"type": "object", "properties": {"a": {"type": "string"}}},
        )
        node.config["model_id"] = "model-no-struct"

        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _: "key",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda _, **_kwargs: "openai",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_model_capabilities",
            lambda _, **_kwargs: {"supports_structured_output": False},
        )

        with pytest.raises(ValueError, match="does not support structured output"):
            list(engine._execute_agent_node(node))

    def test_structured_output_with_structured_response(self, monkeypatch):
        """Cover lines 283-284: structured response parsed and validated."""
        engine = create_engine()
        engine.state["query"] = "test"
        node = create_agent_node(
            node_id="n4",
            output_variable="result",
            json_schema={"type": "object", "properties": {"key": {"type": "string"}}},
        )

        node_events = [
            {"answer": '{"key": "val"}', "structured": True},
        ]
        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _: None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda _, **_kwargs: None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_model_capabilities",
            lambda _, **_kwargs: {"supports_structured_output": True},
        )

        list(engine._execute_agent_node(node))
        assert engine.state["result"] == {"key": "val"}

    def test_json_schema_no_structured_flag_parses_response(self, monkeypatch):
        """Cover line 289: json_schema set but no structured flag; non-JSON response raises."""
        engine = create_engine()
        engine.state["query"] = "test"
        node = create_agent_node(
            node_id="n5",
            json_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )

        node_events = [{"answer": "not valid json"}]
        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _: None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda _, **_kwargs: None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_model_capabilities",
            lambda _, **_kwargs: {"supports_structured_output": True},
        )

        with pytest.raises(
            ValueError,
            match="Structured output was expected but response was not valid JSON",
        ):
            list(engine._execute_agent_node(node))

    def test_parse_structured_output_empty_string(self):
        """Cover line 355: _parse_structured_output with empty string."""
        engine = create_engine()
        success, result = engine._parse_structured_output("")
        assert success is False
        assert result is None

    def test_normalize_node_json_schema_invalid(self):
        """Cover line 375: _normalize_node_json_schema with invalid schema raises."""
        engine = create_engine()
        # A non-dict schema triggers JsonSchemaValidationError
        with pytest.raises(ValueError, match="Invalid JSON schema"):
            engine._normalize_node_json_schema("not_a_dict", "TestNode")


class TestAgentNodeProviderResolution:
    """``llm_name`` stored on a node is a *display* label, not a dispatch name.

    ``/api/models`` reports ``display_provider`` (e.g. ``foundry``,
    ``azure_foundry``, ``cloudflare``) and the builder stores that string on
    the node. Handing it to ``LLMCreator`` raises ``No LLM class found for
    type <label>``, which fails the node before any LLM call and returns a
    blank answer to the user. The engine must resolve the real dispatch
    provider from the model registry instead.
    """

    @staticmethod
    def _run(monkeypatch, node, *, registry_provider="openai_compatible"):
        """Execute one agent node, returning the kwargs the factory saw."""
        engine = create_engine()
        engine.state["query"] = "test"
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return StubNodeAgent([{"answer": "ok"}])

        monkeypatch.setattr(
            WorkflowNodeAgentFactory, "create", staticmethod(_capture)
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda name: f"key-for-{name}",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda _, **_kwargs: registry_provider,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_model_capabilities",
            lambda _, **_kwargs: None,
        )
        list(engine._execute_agent_node(node))
        return captured

    @pytest.mark.parametrize(
        "display_label", ["azure_foundry", "cloudflare", "foundry"]
    )
    def test_display_provider_label_resolves_to_dispatch_provider(
        self, monkeypatch, display_label
    ):
        """A display label must not reach LLMCreator (err#33)."""
        node = create_agent_node(node_id="n1")
        node.config["model_id"] = "Kimi-K2.6"
        node.config["llm_name"] = display_label

        captured = self._run(monkeypatch, node)

        assert captured["llm_name"] == "openai_compatible"
        # The api_key must follow the *normalized* name: resolving against the
        # display label silently falls through to settings.API_KEY.
        assert captured["api_key"] == "key-for-openai_compatible"

    def test_real_provider_name_is_preserved(self, monkeypatch):
        """A node storing a genuine dispatch name keeps it."""
        node = create_agent_node(node_id="n2")
        node.config["model_id"] = "gpt-4o"
        node.config["llm_name"] = "openai"

        captured = self._run(monkeypatch, node, registry_provider="openai")

        assert captured["llm_name"] == "openai"

    def test_unresolvable_label_falls_back_to_parent_agent(self, monkeypatch):
        """No registry hit: inherit the parent agent rather than dispatching junk."""
        node = create_agent_node(node_id="n3")
        node.config["model_id"] = "mystery-model"
        node.config["llm_name"] = "some_unknown_label"

        captured = self._run(monkeypatch, node, registry_provider=None)

        # create_engine()'s parent agent is llm_name="openai"
        assert captured["llm_name"] == "openai"

    def test_retriever_config_uses_normalized_provider(self, monkeypatch):
        """The agentic retriever path builds its own kwargs — normalize there too."""
        node = create_agent_node(node_id="n4")
        node.config["model_id"] = "Kimi-K2.6"
        node.config["llm_name"] = "azure_foundry"
        node.config["agent_type"] = "agentic"
        node.config["sources"] = ["src-1"]

        captured = self._run(monkeypatch, node)

        assert captured["retriever_config"]["llm_name"] == "openai_compatible"
        assert captured["retriever_config"]["api_key"] == "key-for-openai_compatible"
