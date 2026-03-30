"""Tests covering gaps in WorkflowEngine: execute loop, state/condition/end nodes,
template context, source data, structured output parsing, get_execution_summary."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from application.agents.workflows.schemas import (
    ExecutionStatus,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    Workflow,
)
from application.agents.workflows.workflow_engine import WorkflowEngine


def _make_graph(nodes, edges):
    wf = Workflow(name="Test", description="test workflow")
    return WorkflowGraph(workflow=wf, nodes=nodes, edges=edges)


def _make_node(id, type, title="Node", config=None, position=None):
    return WorkflowNode(
        id=id,
        workflow_id="wf1",
        type=type,
        title=title,
        position=position or {"x": 0, "y": 0},
        config=config or {},
    )


def _make_edge(id, source, target, source_handle=None, target_handle=None):
    return WorkflowEdge(
        id=id,
        workflow_id="wf1",
        source=source,
        target=target,
        sourceHandle=source_handle,
        targetHandle=target_handle,
    )


def _make_agent():
    agent = MagicMock()
    agent.chat_history = []
    agent.endpoint = "https://api.example.com"
    agent.llm_name = "openai"
    agent.model_id = "gpt-4"
    agent.api_key = "key"
    agent.decoded_token = {"sub": "user1"}
    agent.retrieved_docs = None
    return agent


class TestExecuteLoop:

    @pytest.mark.unit
    def test_no_start_node_yields_error(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        events = list(engine.execute({}, "query"))
        assert any(e.get("type") == "error" and "start node" in e.get("error", "") for e in events)

    @pytest.mark.unit
    def test_start_to_end(self):
        nodes = [
            _make_node("n1", NodeType.START, "Start"),
            _make_node("n2", NodeType.END, "End", config={"config": {}}),
        ]
        edges = [_make_edge("e1", "n1", "n2")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        events = list(engine.execute({}, "hello"))
        step_events = [e for e in events if e.get("type") == "workflow_step"]
        assert len(step_events) >= 2  # At least start + end

    @pytest.mark.unit
    def test_node_not_found_yields_error(self):
        nodes = [_make_node("n1", NodeType.START)]
        edges = [_make_edge("e1", "n1", "nonexistent")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        events = list(engine.execute({}, "q"))
        assert any("not found" in e.get("error", "") for e in events)

    @pytest.mark.unit
    def test_node_execution_error_yields_error(self):
        nodes = [
            _make_node("n1", NodeType.START),
            _make_node("n2", NodeType.STATE, "State", config={"config": {"operations": [{"expression": "bad!!!", "target_variable": "x"}]}}),
        ]
        edges = [_make_edge("e1", "n1", "n2")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        events = list(engine.execute({}, "q"))
        failed_events = [e for e in events if e.get("status") == "failed"]
        assert len(failed_events) >= 1

    @pytest.mark.unit
    def test_max_steps_limit(self):
        # Create a cycle: start -> state -> state (loop)
        nodes = [
            _make_node("n1", NodeType.START),
            _make_node("n2", NodeType.NOTE, "Note"),
        ]
        edges = [_make_edge("e1", "n1", "n2"), _make_edge("e2", "n2", "n2")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        engine.MAX_EXECUTION_STEPS = 5
        events = list(engine.execute({}, "q"))
        # Should not run forever
        assert len(events) > 0

    @pytest.mark.unit
    def test_branch_ends_without_end_node(self):
        nodes = [
            _make_node("n1", NodeType.START),
            _make_node("n2", NodeType.NOTE, "Note"),
        ]
        edges = [_make_edge("e1", "n1", "n2")]  # n2 has no outgoing edges
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        events = list(engine.execute({}, "q"))
        assert len(events) > 0


class TestInitializeState:

    @pytest.mark.unit
    def test_sets_query_and_history(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.chat_history = [{"prompt": "hi", "response": "hey"}]
        engine = WorkflowEngine(graph, agent)
        engine._initialize_state({"custom": "value"}, "test query")
        assert engine.state["query"] == "test query"
        assert "custom" in engine.state
        assert engine.state["chat_history"] is not None


class TestGetNextNodeId:

    @pytest.mark.unit
    def test_no_edges_returns_none(self):
        nodes = [_make_node("n1", NodeType.START)]
        graph = _make_graph(nodes, [])
        engine = WorkflowEngine(graph, _make_agent())
        assert engine._get_next_node_id("n1") is None

    @pytest.mark.unit
    def test_returns_first_edge_target(self):
        nodes = [_make_node("n1", NodeType.START), _make_node("n2", NodeType.END)]
        edges = [_make_edge("e1", "n1", "n2")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        assert engine._get_next_node_id("n1") == "n2"

    @pytest.mark.unit
    def test_condition_uses_matched_handle(self):
        nodes = [
            _make_node("n1", NodeType.CONDITION),
            _make_node("n2", NodeType.END, "Yes End"),
            _make_node("n3", NodeType.END, "No End"),
        ]
        edges = [
            _make_edge("e1", "n1", "n2", source_handle="yes"),
            _make_edge("e2", "n1", "n3", source_handle="no"),
        ]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        engine._condition_result = "no"
        assert engine._get_next_node_id("n1") == "n3"
        assert engine._condition_result is None  # Cleared after use

    @pytest.mark.unit
    def test_condition_no_matching_handle_returns_none(self):
        nodes = [_make_node("n1", NodeType.CONDITION)]
        edges = [_make_edge("e1", "n1", "n2", source_handle="yes")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        engine._condition_result = "nonexistent"
        assert engine._get_next_node_id("n1") is None


class TestExecuteStateNode:

    @pytest.mark.unit
    def test_evaluates_operations(self):
        node = _make_node("n1", NodeType.STATE, config={
            "config": {
                "operations": [
                    {"expression": "x + 1", "target_variable": "result"},
                ]
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"x": 5}
        list(engine._execute_state_node(node))
        assert engine.state["result"] == 6

    @pytest.mark.unit
    def test_skips_empty_expression(self):
        node = _make_node("n1", NodeType.STATE, config={
            "config": {
                "operations": [
                    {"expression": "", "target_variable": "result"},
                ]
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {}
        list(engine._execute_state_node(node))
        assert "result" not in engine.state


class TestExecuteConditionNode:

    @pytest.mark.unit
    def test_matches_first_true_case(self):
        node = _make_node("n1", NodeType.CONDITION, config={
            "config": {
                "cases": [
                    {"expression": "x > 10", "source_handle": "high"},
                    {"expression": "x > 5", "source_handle": "medium"},
                ]
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"x": 7}
        list(engine._execute_condition_node(node))
        assert engine._condition_result == "medium"

    @pytest.mark.unit
    def test_falls_through_to_else(self):
        node = _make_node("n1", NodeType.CONDITION, config={
            "config": {
                "cases": [
                    {"expression": "x > 100", "source_handle": "high"},
                ]
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"x": 1}
        list(engine._execute_condition_node(node))
        assert engine._condition_result == "else"

    @pytest.mark.unit
    def test_skips_empty_expression(self):
        node = _make_node("n1", NodeType.CONDITION, config={
            "config": {
                "cases": [
                    {"expression": "  ", "source_handle": "a"},
                    {"expression": "true", "source_handle": "b"},
                ]
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {}
        list(engine._execute_condition_node(node))
        assert engine._condition_result == "b"

    @pytest.mark.unit
    def test_cel_error_continues(self):
        node = _make_node("n1", NodeType.CONDITION, config={
            "config": {
                "cases": [
                    {"expression": "bad!!!", "source_handle": "a"},
                    {"expression": "true", "source_handle": "b"},
                ]
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {}
        list(engine._execute_condition_node(node))
        assert engine._condition_result == "b"


class TestExecuteEndNode:

    @pytest.mark.unit
    def test_with_output_template(self):
        node = _make_node("n1", NodeType.END, config={
            "config": {"output_template": "Result: {{ query }}"}
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"query": "hello"}
        engine._format_template = MagicMock(return_value="Result: hello")
        events = list(engine._execute_end_node(node))
        assert len(events) == 1
        assert events[0]["answer"] == "Result: hello"

    @pytest.mark.unit
    def test_without_output_template(self):
        node = _make_node("n1", NodeType.END, config={"config": {}})
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        events = list(engine._execute_end_node(node))
        assert len(events) == 0


class TestParseStructuredOutput:

    @pytest.mark.unit
    def test_valid_json(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        success, data = engine._parse_structured_output('{"key": "value"}')
        assert success is True
        assert data == {"key": "value"}

    @pytest.mark.unit
    def test_invalid_json(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        success, data = engine._parse_structured_output("not json")
        assert success is False
        assert data is None

    @pytest.mark.unit
    def test_empty_string(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        success, data = engine._parse_structured_output("")
        assert success is False
        assert data is None

    @pytest.mark.unit
    def test_whitespace_only(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        success, data = engine._parse_structured_output("   ")
        assert success is False
        assert data is None


class TestNormalizeNodeJsonSchema:

    @pytest.mark.unit
    def test_none_returns_none(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        assert engine._normalize_node_json_schema(None, "Node") is None

    @pytest.mark.unit
    def test_valid_schema(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = engine._normalize_node_json_schema(schema, "Node")
        assert result is not None

    @pytest.mark.unit
    def test_invalid_schema_raises(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        with patch("application.agents.workflows.workflow_engine.normalize_json_schema_payload") as mock_norm:
            from application.core.json_schema_utils import JsonSchemaValidationError
            mock_norm.side_effect = JsonSchemaValidationError("bad schema")
            with pytest.raises(ValueError, match="Invalid JSON schema"):
                engine._normalize_node_json_schema({"bad": True}, "TestNode")


class TestValidateStructuredOutput:

    @pytest.mark.unit
    def test_valid_output_passes(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        engine._validate_structured_output(schema, {"name": "Alice"})  # Should not raise

    @pytest.mark.unit
    def test_invalid_output_raises(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        with pytest.raises(ValueError, match="did not match schema"):
            engine._validate_structured_output(schema, {})

    @pytest.mark.unit
    def test_no_jsonschema_module(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        with patch("application.agents.workflows.workflow_engine.jsonschema", None):
            engine._validate_structured_output({"type": "object"}, {})  # Should not raise


class TestFormatTemplate:

    @pytest.mark.unit
    def test_renders_template(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"query": "hello"}
        engine._build_template_context = MagicMock(return_value={"query": "hello"})
        engine._template_engine = MagicMock()
        engine._template_engine.render.return_value = "hello world"
        result = engine._format_template("{{ query }} world")
        assert result == "hello world"

    @pytest.mark.unit
    def test_render_error_returns_raw(self):
        from application.templates.template_engine import TemplateRenderError
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine._build_template_context = MagicMock(return_value={})
        engine._template_engine = MagicMock()
        engine._template_engine.render.side_effect = TemplateRenderError("fail")
        result = engine._format_template("{{ bad }}")
        assert result == "{{ bad }}"


class TestBuildTemplateContext:

    @pytest.mark.unit
    def test_includes_state_variables(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = None
        engine = WorkflowEngine(graph, agent)
        engine.state = {"query": "hello", "custom_var": "value"}
        context = engine._build_template_context()
        assert context["agent"]["query"] == "hello"
        assert "custom_var" in context

    @pytest.mark.unit
    def test_reserved_namespace_gets_prefixed(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = None
        engine = WorkflowEngine(graph, agent)
        engine.state = {"source": "my_source_val"}
        context = engine._build_template_context()
        assert context.get("agent_source") == "my_source_val"

    @pytest.mark.unit
    def test_passthrough_data(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = None
        engine = WorkflowEngine(graph, agent)
        engine.state = {"passthrough": {"key": "val"}}
        context = engine._build_template_context()
        assert "passthrough" in context or "agent_passthrough" in context

    @pytest.mark.unit
    def test_tools_data(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = None
        engine = WorkflowEngine(graph, agent)
        engine.state = {"tools": {"tool1": "result"}}
        context = engine._build_template_context()
        assert "agent" in context


class TestGetSourceTemplateData:

    @pytest.mark.unit
    def test_no_docs_returns_none(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = None
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert docs is None
        assert together is None

    @pytest.mark.unit
    def test_empty_docs_returns_none(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = []
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert docs is None

    @pytest.mark.unit
    def test_docs_with_filename(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = [{"text": "content", "filename": "doc.txt"}]
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert docs is not None
        assert "doc.txt" in together
        assert "content" in together

    @pytest.mark.unit
    def test_docs_without_filename(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = [{"text": "content only"}]
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert together == "content only"

    @pytest.mark.unit
    def test_skips_non_dict_docs(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = ["not a dict", {"text": "ok"}]
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert together == "ok"

    @pytest.mark.unit
    def test_skips_non_string_text(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = [{"text": 123}]
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert together is None

    @pytest.mark.unit
    def test_doc_with_title_fallback(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = [{"text": "content", "title": "doc_title"}]
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert "doc_title" in together

    @pytest.mark.unit
    def test_doc_with_source_fallback(self):
        graph = _make_graph([], [])
        agent = _make_agent()
        agent.retrieved_docs = [{"text": "content", "source": "src"}]
        engine = WorkflowEngine(graph, agent)
        docs, together = engine._get_source_template_data()
        assert "src" in together


class TestGetExecutionSummary:

    @pytest.mark.unit
    def test_returns_log_entries(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        now = datetime.now(timezone.utc)
        engine.execution_log = [
            {
                "node_id": "n1",
                "node_type": "start",
                "status": "completed",
                "started_at": now,
                "completed_at": now,
                "error": None,
                "state_snapshot": {},
            }
        ]
        summary = engine.get_execution_summary()
        assert len(summary) == 1
        assert summary[0].node_id == "n1"
        assert summary[0].status == ExecutionStatus.COMPLETED

    @pytest.mark.unit
    def test_empty_log(self):
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        assert engine.get_execution_summary() == []


class TestAgentNodeExecution:
    """Cover lines 204, 213-215, 223, 232-233, 283-284, 289, 355, 375."""

    @pytest.mark.unit
    def test_agent_node_without_prompt_template(self):
        """Cover line 204/206: agent node without prompt_template uses query."""
        node = _make_node("n1", NodeType.AGENT, "Agent", config={
            "config": {
                "agent_type": "classic",
                "stream_to_user": False,
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"query": "test question"}

        mock_agent = MagicMock()
        mock_agent.gen.return_value = [{"answer": "response"}]

        with patch(
            "application.agents.workflows.workflow_engine.WorkflowNodeAgentFactory"
        ) as mock_factory, \
             patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), \
             patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), \
             patch(
            "application.core.model_utils.get_model_capabilities",
            return_value=None,
        ):
            mock_factory.create.return_value = mock_agent
            list(engine._execute_agent_node(node))

        output_key = f"node_{node.id}_output"
        assert output_key in engine.state

    @pytest.mark.unit
    def test_agent_node_with_structured_output(self):
        """Cover lines 283-284, 289: structured output parsing."""
        node = _make_node("n1", NodeType.AGENT, "Agent", config={
            "config": {
                "agent_type": "classic",
                "stream_to_user": False,
                "json_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"query": "test"}

        mock_agent = MagicMock()
        mock_agent.gen.return_value = [
            {"answer": '{"name": "Alice"}', "structured": True}
        ]

        with patch(
            "application.agents.workflows.workflow_engine.WorkflowNodeAgentFactory"
        ) as mock_factory, \
             patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), \
             patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), \
             patch(
            "application.core.model_utils.get_model_capabilities",
            return_value={"supports_structured_output": True},
        ):
            mock_factory.create.return_value = mock_agent
            list(engine._execute_agent_node(node))

        output_key = f"node_{node.id}_output"
        assert engine.state[output_key] == {"name": "Alice"}

    @pytest.mark.unit
    def test_agent_node_model_no_structured_support_raises(self):
        """Cover lines 223: model without structured output raises ValueError."""
        node = _make_node("n1", NodeType.AGENT, "Agent", config={
            "config": {
                "agent_type": "classic",
                "json_schema": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                },
                "model_id": "test-model",
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"query": "test"}

        with patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), \
             patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), \
             patch(
            "application.core.model_utils.get_model_capabilities",
            return_value={"supports_structured_output": False},
        ):
            with pytest.raises(ValueError, match="does not support structured output"):
                list(engine._execute_agent_node(node))

    @pytest.mark.unit
    def test_agent_node_output_variable(self):
        """Cover line 300: output_variable stores result."""
        node = _make_node("n1", NodeType.AGENT, "Agent", config={
            "config": {
                "agent_type": "classic",
                "stream_to_user": False,
                "output_variable": "my_result",
            }
        })
        graph = _make_graph([node], [])
        engine = WorkflowEngine(graph, _make_agent())
        engine.state = {"query": "test"}

        mock_agent = MagicMock()
        mock_agent.gen.return_value = [{"answer": "output text"}]

        with patch(
            "application.agents.workflows.workflow_engine.WorkflowNodeAgentFactory"
        ) as mock_factory, \
             patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), \
             patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), \
             patch(
            "application.core.model_utils.get_model_capabilities",
            return_value=None,
        ):
            mock_factory.create.return_value = mock_agent
            list(engine._execute_agent_node(node))

        assert engine.state["my_result"] == "output text"

    @pytest.mark.unit
    def test_validate_structured_output_schema_error(self):
        """Cover line 375/382-383: invalid schema raises ValueError."""
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        import jsonschema as js

        with patch(
            "application.agents.workflows.workflow_engine.normalize_json_schema_payload",
            return_value={"type": "invalid_schema_type"},
        ), \
             patch(
            "application.agents.workflows.workflow_engine.jsonschema"
        ) as mock_js:
            mock_js.validate.side_effect = js.exceptions.SchemaError("bad schema")
            mock_js.exceptions = js.exceptions
            with pytest.raises(ValueError, match="Invalid JSON schema"):
                engine._validate_structured_output(
                    {"type": "object"}, {"name": "test"}
                )

    @pytest.mark.unit
    def test_parse_structured_output_invalid_json(self):
        """Cover lines 349-352: invalid JSON returns False."""
        graph = _make_graph([], [])
        engine = WorkflowEngine(graph, _make_agent())
        success, data = engine._parse_structured_output("not json {")
        assert success is False
        assert data is None


# ---------------------------------------------------------------------------
# Additional coverage for workflow_engine.py
# Lines: 96-114 (exception in node execution), 122-130 (branch/max steps)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowNodeExecutionException:
    """Cover lines 96-114: exception during _execute_node yields error events."""

    def test_node_raises_exception_yields_error(self):
        """Force _execute_node to raise, covering lines 96-114."""
        nodes = [
            _make_node("n1", NodeType.START),
            _make_node("n2", NodeType.AGENT, "Agent"),
        ]
        edges = [_make_edge("e1", "n1", "n2")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())

        # Patch _execute_node to raise on agent node
        original_execute = engine._execute_node

        def patched_execute(node):
            if node.type == NodeType.AGENT:
                raise RuntimeError("Agent exploded")
            yield from original_execute(node)

        engine._execute_node = patched_execute
        events = list(engine.execute({}, "test query"))

        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) >= 1
        failed_steps = [e for e in events if e.get("status") == "failed"]
        assert len(failed_steps) >= 1


@pytest.mark.unit
class TestWorkflowMaxStepsReached:
    """Cover lines 127-130: max steps limit warning."""

    def test_max_steps_exactly_reached(self):
        nodes = [
            _make_node("n1", NodeType.START),
            _make_node("n2", NodeType.NOTE, "Note"),
        ]
        edges = [_make_edge("e1", "n1", "n2"), _make_edge("e2", "n2", "n2")]
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        engine.MAX_EXECUTION_STEPS = 3
        events = list(engine.execute({}, "q"))
        # The while loop runs 3 times then exits, steps >= MAX
        assert len(events) >= 3


@pytest.mark.unit
class TestWorkflowBranchEndsNonEndNode:
    """Cover lines 122-125: branch ends at non-end node without outgoing edges."""

    def test_branch_ends_at_state_node(self):
        nodes = [
            _make_node("n1", NodeType.START),
            _make_node(
                "n2",
                NodeType.STATE,
                "State",
                config={"config": {"operations": []}},
            ),
        ]
        edges = [_make_edge("e1", "n1", "n2")]  # n2 has no outgoing
        graph = _make_graph(nodes, edges)
        engine = WorkflowEngine(graph, _make_agent())
        events = list(engine.execute({}, "q"))
        # Should complete without crash, branch ended warning logged
        assert len(events) > 0
