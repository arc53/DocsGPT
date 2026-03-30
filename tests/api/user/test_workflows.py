from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from bson import ObjectId


@pytest.mark.unit
class TestSerializeWorkflow:

    def test_serializes_full_workflow(self):
        from application.api.user.workflows.routes import serialize_workflow

        now = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        doc = {
            "_id": ObjectId(),
            "name": "My Workflow",
            "description": "A test workflow",
            "created_at": now,
            "updated_at": now,
        }
        result = serialize_workflow(doc)
        assert result["id"] == str(doc["_id"])
        assert result["name"] == "My Workflow"
        assert result["description"] == "A test workflow"
        assert result["created_at"] == now.isoformat()

    def test_handles_missing_optional_fields(self):
        from application.api.user.workflows.routes import serialize_workflow

        doc = {"_id": ObjectId()}
        result = serialize_workflow(doc)
        assert result["name"] is None
        assert result["created_at"] is None


@pytest.mark.unit
class TestSerializeNode:

    def test_serializes_node(self):
        from application.api.user.workflows.routes import serialize_node

        node = {
            "id": "node-1",
            "type": "agent",
            "title": "Agent Node",
            "description": "Does things",
            "position": {"x": 100, "y": 200},
            "config": {"model": "gpt-4"},
        }
        result = serialize_node(node)
        assert result["id"] == "node-1"
        assert result["type"] == "agent"
        assert result["title"] == "Agent Node"
        assert result["data"] == {"model": "gpt-4"}
        assert result["position"] == {"x": 100, "y": 200}

    def test_defaults_for_missing_fields(self):
        from application.api.user.workflows.routes import serialize_node

        node = {"id": "n1", "type": "start"}
        result = serialize_node(node)
        assert result["data"] == {}
        assert result["title"] is None


@pytest.mark.unit
class TestSerializeEdge:

    def test_serializes_edge(self):
        from application.api.user.workflows.routes import serialize_edge

        edge = {
            "id": "edge-1",
            "source_id": "node-1",
            "target_id": "node-2",
            "source_handle": "output",
            "target_handle": "input",
        }
        result = serialize_edge(edge)
        assert result["id"] == "edge-1"
        assert result["source"] == "node-1"
        assert result["target"] == "node-2"
        assert result["sourceHandle"] == "output"
        assert result["targetHandle"] == "input"


@pytest.mark.unit
class TestGetWorkflowGraphVersion:

    def test_returns_version(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        assert get_workflow_graph_version({"current_graph_version": 3}) == 3

    def test_defaults_to_1(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        assert get_workflow_graph_version({}) == 1

    def test_handles_invalid_version(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        assert get_workflow_graph_version({"current_graph_version": "bad"}) == 1

    def test_handles_zero_version(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        assert get_workflow_graph_version({"current_graph_version": 0}) == 1

    def test_handles_negative_version(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        assert get_workflow_graph_version({"current_graph_version": -1}) == 1


@pytest.mark.unit
class TestFetchGraphDocuments:

    def test_returns_versioned_docs(self):
        from application.api.user.workflows.routes import fetch_graph_documents

        collection = Mock()
        docs = [{"id": "n1", "graph_version": 2}]
        collection.find.return_value = docs

        result = fetch_graph_documents(collection, "wf1", 2)
        assert result == docs
        collection.find.assert_called_once_with(
            {"workflow_id": "wf1", "graph_version": 2}
        )

    def test_falls_back_to_unversioned_for_v1(self):
        from application.api.user.workflows.routes import fetch_graph_documents

        collection = Mock()
        unversioned_docs = [{"id": "n1"}]
        collection.find.side_effect = [[], unversioned_docs]

        result = fetch_graph_documents(collection, "wf1", 1)
        assert result == unversioned_docs
        assert collection.find.call_count == 2

    def test_no_fallback_for_higher_versions(self):
        from application.api.user.workflows.routes import fetch_graph_documents

        collection = Mock()
        collection.find.return_value = []

        result = fetch_graph_documents(collection, "wf1", 3)
        assert result == []
        assert collection.find.call_count == 1


@pytest.mark.unit
class TestValidateWorkflowStructure:

    def _make_minimal_workflow(self):
        nodes = [
            {"id": "start", "type": "start"},
            {"id": "end", "type": "end"},
        ]
        edges = [{"id": "e1", "source": "start", "target": "end"}]
        return nodes, edges

    def test_valid_minimal_workflow(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes, edges = self._make_minimal_workflow()
        errors = validate_workflow_structure(nodes, edges)
        assert errors == []

    def test_empty_nodes(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        errors = validate_workflow_structure([], [])
        assert any("at least one node" in e for e in errors)

    def test_missing_start_node(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [{"id": "end", "type": "end"}]
        edges = []
        errors = validate_workflow_structure(nodes, edges)
        assert any("start node" in e for e in errors)

    def test_missing_end_node(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [{"id": "start", "type": "start"}]
        edges = [{"id": "e1", "source": "start", "target": "somewhere"}]
        errors = validate_workflow_structure(nodes, edges)
        assert any("end node" in e for e in errors)

    def test_start_node_without_outgoing_edge(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {"id": "end", "type": "end"},
        ]
        edges = []
        errors = validate_workflow_structure(nodes, edges)
        assert any("outgoing edge" in e for e in errors)

    def test_edge_references_nonexistent_node(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {"id": "end", "type": "end"},
        ]
        edges = [{"id": "e1", "source": "start", "target": "ghost"}]
        errors = validate_workflow_structure(nodes, edges)
        assert any("non-existent target" in e for e in errors)

    def test_node_without_id(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {"type": "end"},
        ]
        edges = [{"id": "e1", "source": "start", "target": None}]
        errors = validate_workflow_structure(nodes, edges)
        assert any("must have an id" in e for e in errors)

    def test_node_without_type(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {"id": "end"},
        ]
        edges = [{"id": "e1", "source": "start", "target": "end"}]
        errors = validate_workflow_structure(nodes, edges)
        assert any("must have a type" in e for e in errors)

    def test_condition_node_needs_two_outgoing_edges(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("at least 2 outgoing edges" in e for e in errors)

    def test_condition_node_needs_else_branch(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "case1"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("else" in e for e in errors)


@pytest.mark.unit
class TestCanReachEnd:

    def test_direct_end_node(self):
        from application.api.user.workflows.routes import _can_reach_end

        node_map = {"end": {"id": "end", "type": "end"}}
        assert _can_reach_end("end", [], node_map, {"end"}) is True

    def test_reachable_through_chain(self):
        from application.api.user.workflows.routes import _can_reach_end

        node_map = {
            "a": {"id": "a"},
            "b": {"id": "b"},
            "end": {"id": "end", "type": "end"},
        }
        edges = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "end"},
        ]
        assert _can_reach_end("a", edges, node_map, {"end"}) is True

    def test_unreachable(self):
        from application.api.user.workflows.routes import _can_reach_end

        node_map = {
            "a": {"id": "a"},
            "b": {"id": "b"},
        }
        edges = [{"source": "a", "target": "b"}]
        assert _can_reach_end("a", edges, node_map, {"end"}) is False

    def test_handles_cycles(self):
        from application.api.user.workflows.routes import _can_reach_end

        node_map = {"a": {"id": "a"}, "b": {"id": "b"}}
        edges = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ]
        assert _can_reach_end("a", edges, node_map, {"end"}) is False


@pytest.mark.unit
class TestValidateJsonSchemaPayload:

    def test_none_input(self):
        from application.api.user.workflows.routes import validate_json_schema_payload

        result, error = validate_json_schema_payload(None)
        assert result is None
        assert error is None

    @patch("application.api.user.workflows.routes.normalize_json_schema_payload")
    def test_valid_schema(self, mock_normalize):
        from application.api.user.workflows.routes import validate_json_schema_payload

        mock_normalize.return_value = {"type": "object"}
        result, error = validate_json_schema_payload({"type": "object"})
        assert result == {"type": "object"}
        assert error is None

    @patch("application.api.user.workflows.routes.normalize_json_schema_payload")
    def test_invalid_schema(self, mock_normalize):
        from application.api.user.workflows.routes import validate_json_schema_payload
        from application.core.json_schema_utils import JsonSchemaValidationError

        mock_normalize.side_effect = JsonSchemaValidationError("bad schema")
        result, error = validate_json_schema_payload({"bad": True})
        assert result is None
        assert "bad schema" in error


@pytest.mark.unit
class TestNormalizeAgentNodeJsonSchemas:

    def test_non_agent_nodes_pass_through(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )

        nodes = [
            {"id": "n1", "type": "start"},
            {"id": "n2", "type": "end"},
        ]
        result = normalize_agent_node_json_schemas(nodes)
        assert result == nodes

    @patch("application.api.user.workflows.routes.normalize_json_schema_payload")
    def test_normalizes_agent_node_schema(self, mock_normalize):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )

        mock_normalize.return_value = {"type": "object", "properties": {}}
        nodes = [
            {
                "id": "a1",
                "type": "agent",
                "data": {"json_schema": {"type": "object"}},
            }
        ]
        result = normalize_agent_node_json_schemas(nodes)
        assert result[0]["data"]["json_schema"] == {
            "type": "object",
            "properties": {},
        }

    def test_agent_node_without_schema(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )

        nodes = [{"id": "a1", "type": "agent", "data": {"model": "gpt-4"}}]
        result = normalize_agent_node_json_schemas(nodes)
        assert result[0]["data"] == {"model": "gpt-4"}

    def test_non_dict_node_passes_through(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )

        nodes = ["not_a_dict", 42]
        result = normalize_agent_node_json_schemas(nodes)
        assert result == ["not_a_dict", 42]

    def test_agent_node_with_non_dict_data(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )

        nodes = [{"id": "a1", "type": "agent", "data": "not_a_dict"}]
        result = normalize_agent_node_json_schemas(nodes)
        assert result[0]["data"] == "not_a_dict"

    def test_agent_node_with_no_data_key(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )

        nodes = [{"id": "a1", "type": "agent"}]
        result = normalize_agent_node_json_schemas(nodes)
        assert result[0] == {"id": "a1", "type": "agent"}

    @patch("application.api.user.workflows.routes.normalize_json_schema_payload")
    def test_agent_node_schema_validation_error_keeps_original(self, mock_normalize):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )
        from application.core.json_schema_utils import JsonSchemaValidationError

        mock_normalize.side_effect = JsonSchemaValidationError("bad")
        nodes = [
            {
                "id": "a1",
                "type": "agent",
                "data": {"json_schema": {"invalid": True}},
            }
        ]
        result = normalize_agent_node_json_schemas(nodes)
        # Original schema is preserved on validation error
        assert result[0]["data"]["json_schema"] == {"invalid": True}


# ---- Additional coverage: validate_workflow_structure condition node edge cases ----


@pytest.mark.unit
class TestValidateWorkflowStructureConditionEdgeCases:

    def test_condition_case_without_branch_handle(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": ""},
                        {"expression": "x > 2", "sourceHandle": "case2"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case2"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("without a branch handle" in e for e in errors)

    def test_duplicate_case_handles(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                        {"expression": "x > 2", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("duplicate case handle" in e for e in errors)

    def test_outgoing_edge_without_source_handle(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
            {"id": "e4", "source": "cond", "target": "end1", "sourceHandle": ""},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("without sourceHandle" in e for e in errors)

    def test_unknown_branch_handle(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
            {"id": "end3", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
            {
                "id": "e4",
                "source": "cond",
                "target": "end3",
                "sourceHandle": "unknown_branch",
            },
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("unknown branch 'unknown_branch'" in e for e in errors)

    def test_multiple_outgoing_edges_from_same_branch(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
            {"id": "end3", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "case1"},
            {"id": "e4", "source": "cond", "target": "end3", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("multiple outgoing edges from branch 'case1'" in e for e in errors)

    def test_case_with_expression_but_no_outgoing_edge(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                        {"expression": "x > 2", "sourceHandle": "case2"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any(
            "case 'case2' has an expression but no outgoing edge" in e
            for e in errors
        )

    def test_case_with_outgoing_edge_but_no_expression(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                        {"expression": "", "sourceHandle": "case2"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
            {"id": "end3", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
            {"id": "e4", "source": "cond", "target": "end3", "sourceHandle": "case2"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any(
            "case 'case2' has an outgoing edge but no expression" in e
            for e in errors
        )

    def test_condition_with_cases_not_a_list(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {"cases": "not_a_list"},
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("at least one case with an expression" in e for e in errors)

    def test_condition_node_with_none_data(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": None,
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("at least one case with an expression" in e for e in errors)

    def test_branch_unreachable_end(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        {"expression": "x > 1", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "dead", "type": "agent"},  # dead end, no connection to end
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "dead", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("must eventually reach an end node" in e for e in errors)

    def test_non_dict_case_in_cases_list(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "title": "Check",
                "data": {
                    "cases": [
                        "not_a_dict",
                        {"expression": "x > 1", "sourceHandle": "case1"},
                    ]
                },
            },
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end1", "sourceHandle": "case1"},
            {"id": "e3", "source": "cond", "target": "end2", "sourceHandle": "else"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        # Should not crash; non-dict cases are skipped
        assert isinstance(errors, list)


# ---- Additional coverage: agent node validation in validate_workflow_structure ----


@pytest.mark.unit
class TestValidateWorkflowStructureAgentNodes:

    def test_agent_node_with_invalid_config_type(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {"id": "agent1", "type": "agent", "title": "A1", "data": "not_dict"},
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "agent1"},
            {"id": "e2", "source": "agent1", "target": "end"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("invalid configuration" in e for e in errors)

    @patch("application.api.user.workflows.routes.get_model_capabilities")
    @patch("application.api.user.workflows.routes.normalize_json_schema_payload")
    def test_agent_node_model_no_structured_output(
        self, mock_normalize, mock_capabilities
    ):
        from application.api.user.workflows.routes import validate_workflow_structure

        mock_normalize.return_value = {"type": "object"}
        mock_capabilities.return_value = {"supports_structured_output": False}

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "agent1",
                "type": "agent",
                "title": "A1",
                "data": {
                    "json_schema": {"type": "object"},
                    "model_id": "model-no-so",
                },
            },
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "agent1"},
            {"id": "e2", "source": "agent1", "target": "end"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("does not support structured output" in e for e in errors)

    @patch("application.api.user.workflows.routes.normalize_json_schema_payload")
    def test_agent_node_schema_validation_error(self, mock_normalize):
        from application.api.user.workflows.routes import validate_workflow_structure
        from application.core.json_schema_utils import JsonSchemaValidationError

        mock_normalize.side_effect = JsonSchemaValidationError("schema invalid")

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "agent1",
                "type": "agent",
                "title": "A1",
                "data": {"json_schema": {"bad": True}},
            },
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "agent1"},
            {"id": "e2", "source": "agent1", "target": "end"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("JSON schema" in e for e in errors)

    def test_edge_references_nonexistent_source(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "ghost", "target": "end"},
            {"id": "e2", "source": "start", "target": "end"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("non-existent source: ghost" in e for e in errors)

    def test_multiple_start_nodes(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start1", "type": "start"},
            {"id": "start2", "type": "start"},
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start1", "target": "end"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("exactly one start node" in e for e in errors)


# ---- Additional coverage: WorkflowList.post ----


@pytest.fixture
def app():
    from flask import Flask

    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestWorkflowListPost:

    def test_create_workflow_success(self, app):
        from application.api.user.workflows.routes import WorkflowList

        inserted_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_nodes_collection = Mock()
        mock_edges_collection = Mock()

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(
                "/api/workflows",
                method="POST",
                json={
                    "name": "My Workflow",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"id": "e1", "source": "start", "target": "end"},
                    ],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowList().post()

        assert response.status_code == 201
        assert response.json["id"] == str(inserted_id)

    def test_create_workflow_validation_failure(self, app):
        from application.api.user.workflows.routes import WorkflowList

        with app.test_request_context(
            "/api/workflows",
            method="POST",
            json={
                "name": "Bad Workflow",
                "nodes": [],
                "edges": [],
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = WorkflowList().post()

        assert response.status_code == 400
        assert response.json["success"] is False

    def test_create_workflow_unauthorized(self, app):
        from application.api.user.workflows.routes import WorkflowList

        with app.test_request_context(
            "/api/workflows",
            method="POST",
            json={"name": "WF"},
        ):
            from flask import request

            request.decoded_token = None
            response = WorkflowList().post()

        assert response.status_code == 401

    def test_create_workflow_missing_name(self, app):
        from application.api.user.workflows.routes import WorkflowList

        with app.test_request_context(
            "/api/workflows",
            method="POST",
            json={"description": "No name"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = WorkflowList().post()

        assert response.status_code == 400

    def test_create_workflow_db_error(self, app):
        from application.api.user.workflows.routes import WorkflowList

        mock_wf_collection = Mock()
        mock_wf_collection.insert_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ):
            with app.test_request_context(
                "/api/workflows",
                method="POST",
                json={
                    "name": "WF",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"id": "e1", "source": "start", "target": "end"},
                    ],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowList().post()

        assert response.status_code == 400

    def test_create_workflow_node_insert_error_cleans_up(self, app):
        from application.api.user.workflows.routes import WorkflowList

        inserted_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_nodes_collection = Mock()
        mock_nodes_collection.insert_many.side_effect = Exception("Node insert fail")
        mock_edges_collection = Mock()

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(
                "/api/workflows",
                method="POST",
                json={
                    "name": "WF",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"id": "e1", "source": "start", "target": "end"},
                    ],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowList().post()

        assert response.status_code == 400
        # Cleanup should have been called
        mock_nodes_collection.delete_many.assert_called()
        mock_edges_collection.delete_many.assert_called()
        mock_wf_collection.delete_one.assert_called_once()


# ---- Additional coverage: WorkflowDetail.get ----


@pytest.mark.unit
class TestWorkflowDetailGet:

    def test_get_workflow_success(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = {
            "_id": wf_id,
            "name": "WF",
            "user": "user1",
            "current_graph_version": 1,
        }
        mock_nodes_collection = Mock()
        mock_nodes_collection.find.return_value = [
            {"id": "start", "type": "start", "config": {}}
        ]
        mock_edges_collection = Mock()
        mock_edges_collection.find.return_value = []

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(f"/api/workflows/{wf_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().get(str(wf_id))

        assert response.status_code == 200
        assert response.json["workflow"]["id"] == str(wf_id)

    def test_get_workflow_invalid_id(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context("/api/workflows/bad-id"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = WorkflowDetail().get("bad-id")

        assert response.status_code == 400

    def test_get_workflow_not_found(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = None

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ):
            with app.test_request_context(f"/api/workflows/{wf_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().get(str(wf_id))

        assert response.status_code == 404

    def test_get_workflow_unauthorized(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        with app.test_request_context(f"/api/workflows/{wf_id}"):
            from flask import request

            request.decoded_token = None
            response = WorkflowDetail().get(str(wf_id))

        assert response.status_code == 401


# ---- Additional coverage: WorkflowDetail.put ----


@pytest.mark.unit
class TestWorkflowDetailPut:

    def test_put_workflow_success(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = {
            "_id": wf_id,
            "name": "Old",
            "user": "user1",
            "current_graph_version": 1,
        }
        mock_wf_collection.update_one.return_value = Mock()
        mock_nodes_collection = Mock()
        mock_edges_collection = Mock()

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="PUT",
                json={
                    "name": "Updated WF",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"id": "e1", "source": "start", "target": "end"},
                    ],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().put(str(wf_id))

        assert response.status_code == 200

    def test_put_workflow_validation_failure(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = {
            "_id": wf_id,
            "name": "WF",
            "user": "user1",
            "current_graph_version": 1,
        }

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="PUT",
                json={
                    "name": "Updated",
                    "nodes": [],
                    "edges": [],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().put(str(wf_id))

        assert response.status_code == 400

    def test_put_workflow_not_found(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = None

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="PUT",
                json={"name": "X", "nodes": [], "edges": []},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().put(str(wf_id))

        assert response.status_code == 404

    def test_put_workflow_node_insert_error_cleans_up(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = {
            "_id": wf_id,
            "name": "WF",
            "user": "user1",
            "current_graph_version": 1,
        }
        mock_nodes_collection = Mock()
        mock_nodes_collection.insert_many.side_effect = Exception("insert fail")
        mock_edges_collection = Mock()

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="PUT",
                json={
                    "name": "X",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"id": "e1", "source": "start", "target": "end"},
                    ],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().put(str(wf_id))

        assert response.status_code == 400
        # Cleanup for the new version
        mock_nodes_collection.delete_many.assert_called()
        mock_edges_collection.delete_many.assert_called()

    def test_put_workflow_update_db_error_cleans_up(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = {
            "_id": wf_id,
            "name": "WF",
            "user": "user1",
            "current_graph_version": 1,
        }
        mock_wf_collection.update_one.side_effect = Exception("update fail")
        mock_nodes_collection = Mock()
        mock_edges_collection = Mock()

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="PUT",
                json={
                    "name": "X",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"id": "e1", "source": "start", "target": "end"},
                    ],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().put(str(wf_id))

        assert response.status_code == 400


# ---- Additional coverage: WorkflowDetail.delete ----


@pytest.mark.unit
class TestWorkflowDetailDelete:

    def test_delete_workflow_success(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = {
            "_id": wf_id,
            "name": "WF",
            "user": "user1",
        }
        mock_nodes_collection = Mock()
        mock_edges_collection = Mock()

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="DELETE",
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().delete(str(wf_id))

        assert response.status_code == 200
        mock_nodes_collection.delete_many.assert_called_once()
        mock_edges_collection.delete_many.assert_called_once()
        mock_wf_collection.delete_one.assert_called_once()

    def test_delete_workflow_not_found(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = None

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="DELETE",
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().delete(str(wf_id))

        assert response.status_code == 404

    def test_delete_workflow_invalid_id(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context(
            "/api/workflows/bad-id",
            method="DELETE",
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = WorkflowDetail().delete("bad-id")

        assert response.status_code == 400

    def test_delete_workflow_unauthorized(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        with app.test_request_context(
            f"/api/workflows/{wf_id}",
            method="DELETE",
        ):
            from flask import request

            request.decoded_token = None
            response = WorkflowDetail().delete(str(wf_id))

        assert response.status_code == 401

    def test_delete_workflow_db_error(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf_collection = Mock()
        mock_wf_collection.find_one.return_value = {
            "_id": wf_id,
            "name": "WF",
            "user": "user1",
        }
        mock_nodes_collection = Mock()
        mock_nodes_collection.delete_many.side_effect = Exception("DB error")
        mock_edges_collection = Mock()

        with patch(
            "application.api.user.workflows.routes.workflows_collection",
            mock_wf_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_collection,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_collection,
        ):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="DELETE",
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().delete(str(wf_id))

        assert response.status_code == 400
