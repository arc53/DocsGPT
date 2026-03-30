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
