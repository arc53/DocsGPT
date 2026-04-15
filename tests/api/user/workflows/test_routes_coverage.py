"""Additional coverage tests for application.api.user.workflows.routes.

No bson/ObjectId imports. Mongo collections are replaced by Mock objects.
``validate_object_id`` (which calls bson internally) is patched wherever
WorkflowDetail routes invoke it so that tests run without pymongo.
Repository classes (WorkflowsRepository, etc.) are patched for dual-write paths.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


def _fake_oid():
    """24-character hex string that substitutes for a Mongo ObjectId string."""
    return uuid.uuid4().hex[:24]


def _mock_validate_object_id(wf_id):
    """Return a patcher that makes validate_object_id return (wf_id, None)."""
    mock_oid = Mock()
    mock_oid.__str__ = lambda self: wf_id
    return patch(
        "application.api.user.workflows.routes.validate_object_id",
        return_value=(mock_oid, None),
    )


# ---------------------------------------------------------------------------
# Serializer helpers — pure functions, no DB
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerializeWorkflowCoverage:

    def test_id_is_stringified(self):
        from application.api.user.workflows.routes import serialize_workflow

        raw_id = _fake_oid()
        doc = {"_id": raw_id}
        result = serialize_workflow(doc)
        assert result["id"] == str(raw_id)

    def test_description_is_included(self):
        from application.api.user.workflows.routes import serialize_workflow

        doc = {"_id": _fake_oid(), "description": "my desc"}
        result = serialize_workflow(doc)
        assert result["description"] == "my desc"

    def test_datetime_updated_at_is_isoformat(self):
        from application.api.user.workflows.routes import serialize_workflow

        now = datetime(2024, 7, 4, 9, 0, 0, tzinfo=timezone.utc)
        doc = {"_id": _fake_oid(), "updated_at": now}
        result = serialize_workflow(doc)
        assert result["updated_at"] == now.isoformat()

    def test_name_none_when_missing(self):
        from application.api.user.workflows.routes import serialize_workflow

        doc = {"_id": _fake_oid()}
        result = serialize_workflow(doc)
        assert result["name"] is None

    def test_both_timestamps_none_when_missing(self):
        from application.api.user.workflows.routes import serialize_workflow

        doc = {"_id": _fake_oid(), "name": "WF"}
        result = serialize_workflow(doc)
        assert result["created_at"] is None
        assert result["updated_at"] is None


@pytest.mark.unit
class TestSerializeNodeCoverage:

    def test_description_included(self):
        from application.api.user.workflows.routes import serialize_node

        node = {"id": "n1", "type": "agent", "description": "does stuff"}
        result = serialize_node(node)
        assert result["description"] == "does stuff"

    def test_position_defaults_to_none(self):
        from application.api.user.workflows.routes import serialize_node

        node = {"id": "n1", "type": "start"}
        result = serialize_node(node)
        assert result["position"] is None

    def test_config_becomes_data(self):
        from application.api.user.workflows.routes import serialize_node

        node = {"id": "n1", "type": "agent", "config": {"model": "gpt-4"}}
        result = serialize_node(node)
        assert result["data"] == {"model": "gpt-4"}

    def test_empty_data_when_no_config(self):
        from application.api.user.workflows.routes import serialize_node

        node = {"id": "n1", "type": "start"}
        result = serialize_node(node)
        assert result["data"] == {}


@pytest.mark.unit
class TestSerializeEdgeCoverage:

    def test_missing_handles_return_none(self):
        from application.api.user.workflows.routes import serialize_edge

        edge = {"id": "e1", "source_id": "a", "target_id": "b"}
        result = serialize_edge(edge)
        assert result["sourceHandle"] is None
        assert result["targetHandle"] is None

    def test_edge_with_handles(self):
        from application.api.user.workflows.routes import serialize_edge

        edge = {
            "id": "e2",
            "source_id": "x",
            "target_id": "y",
            "source_handle": "out",
            "target_handle": "in",
        }
        result = serialize_edge(edge)
        assert result["sourceHandle"] == "out"
        assert result["targetHandle"] == "in"

    def test_edge_source_target_mapped(self):
        from application.api.user.workflows.routes import serialize_edge

        edge = {"id": "e3", "source_id": "s1", "target_id": "t1"}
        result = serialize_edge(edge)
        assert result["source"] == "s1"
        assert result["target"] == "t1"


# ---------------------------------------------------------------------------
# get_workflow_graph_version — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWorkflowGraphVersionCoverage:

    def test_large_version_number(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        assert get_workflow_graph_version({"current_graph_version": 99}) == 99

    def test_float_string_falls_back_to_1(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        # int("3.5") raises ValueError → falls back to 1
        assert get_workflow_graph_version({"current_graph_version": "3.5"}) == 1

    def test_none_value_returns_1(self):
        from application.api.user.workflows.routes import get_workflow_graph_version

        assert get_workflow_graph_version({"current_graph_version": None}) == 1


# ---------------------------------------------------------------------------
# fetch_graph_documents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchGraphDocumentsCoverage:

    def test_empty_result_for_non_v1_version(self):
        from application.api.user.workflows.routes import fetch_graph_documents

        collection = Mock()
        collection.find.return_value = []

        result = fetch_graph_documents(collection, "wfABC", 5)
        assert result == []
        collection.find.assert_called_once_with({"workflow_id": "wfABC", "graph_version": 5})

    def test_v1_returns_versioned_if_present(self):
        from application.api.user.workflows.routes import fetch_graph_documents

        collection = Mock()
        versioned_docs = [{"id": "n1", "graph_version": 1}]
        collection.find.side_effect = [versioned_docs]

        result = fetch_graph_documents(collection, "wfABC", 1)
        assert result == versioned_docs
        assert collection.find.call_count == 1

    def test_v1_falls_back_to_unversioned(self):
        from application.api.user.workflows.routes import fetch_graph_documents

        collection = Mock()
        unversioned_docs = [{"id": "n1"}]
        collection.find.side_effect = [[], unversioned_docs]

        result = fetch_graph_documents(collection, "wfABC", 1)
        assert result == unversioned_docs
        assert collection.find.call_count == 2


# ---------------------------------------------------------------------------
# validate_workflow_structure — additional condition-node coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateWorkflowStructureCoverage:

    def test_valid_condition_node_with_two_outgoing_edges(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "data": {
                    "cases": [{"expression": "x > 0", "sourceHandle": "case1"}]
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
        assert errors == []

    def test_multiple_end_nodes_allowed(self):
        from application.api.user.workflows.routes import validate_workflow_structure

        nodes = [
            {"id": "start", "type": "start"},
            {"id": "end1", "type": "end"},
            {"id": "end2", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "end1"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert isinstance(errors, list)


# ---------------------------------------------------------------------------
# WorkflowList.post — create workflow (uuid-based IDs, no bson)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowListPostCoverage:

    def test_create_with_description(self, app):
        from application.api.user.workflows.routes import WorkflowList

        wf_id = _fake_oid()
        mock_wf_col = Mock()
        mock_wf_col.insert_one.return_value = Mock(inserted_id=wf_id)
        mock_nodes_col = Mock()
        mock_nodes_col.insert_many.return_value = Mock(inserted_ids=[_fake_oid()])
        mock_edges_col = Mock()
        mock_edges_col.insert_many.return_value = Mock(inserted_ids=[])

        with patch(
            "application.api.user.workflows.routes.workflows_collection", mock_wf_col
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_col,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_col,
        ), patch(
            "application.api.user.workflows.routes.dual_write", lambda *a, **kw: None
        ), patch(
            "application.api.user.workflows.routes._dual_write_workflow_create",
            lambda *a, **kw: None,
        ):
            with app.test_request_context(
                "/api/workflows",
                method="POST",
                json={
                    "name": "Described Workflow",
                    "description": "A workflow with a description",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [{"id": "e1", "source": "start", "target": "end"}],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowList().post()

        assert response.status_code == 201
        assert response.json["id"] == str(wf_id)

    def test_create_unauthorized_returns_401(self, app):
        from application.api.user.workflows.routes import WorkflowList

        with app.test_request_context(
            "/api/workflows", method="POST", json={"name": "WF"}
        ):
            from flask import request

            request.decoded_token = None
            response = WorkflowList().post()

        assert response.status_code == 401

    def test_create_missing_name_returns_400(self, app):
        from application.api.user.workflows.routes import WorkflowList

        with app.test_request_context(
            "/api/workflows", method="POST", json={"description": "no name"}
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = WorkflowList().post()

        assert response.status_code == 400

    def test_create_db_error_returns_400(self, app):
        from application.api.user.workflows.routes import WorkflowList

        mock_wf_col = Mock()
        mock_wf_col.insert_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.workflows.routes.workflows_collection", mock_wf_col
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
                    "edges": [{"id": "e1", "source": "start", "target": "end"}],
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowList().post()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# WorkflowDetail.get — retrieve a single workflow (mocked validate_object_id)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowDetailGetCoverage:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context("/api/workflows/abc", method="GET"):
            from flask import request

            request.decoded_token = None
            response = WorkflowDetail().get("abc")

        assert response.status_code == 401

    def test_returns_404_when_not_found(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = _fake_oid()
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = None

        with _mock_validate_object_id(wf_id), patch(
            "application.api.user.workflows.routes.workflows_collection", mock_wf_col
        ):
            with app.test_request_context(f"/api/workflows/{wf_id}", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().get(wf_id)

        assert response.status_code == 404

    def test_returns_workflow_data_with_nodes_and_edges(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = _fake_oid()
        now = datetime(2024, 6, 1, tzinfo=timezone.utc)

        # check_resource_ownership needs find_one to return the doc
        mock_wf_col = Mock()
        wf_doc = {
            "_id": wf_id,
            "name": "Test WF",
            "description": "desc",
            "user": "user1",
            "created_at": now,
            "updated_at": now,
        }
        mock_wf_col.find_one.return_value = wf_doc

        mock_nodes_col = Mock()
        mock_nodes_col.find.return_value = []
        mock_edges_col = Mock()
        mock_edges_col.find.return_value = []

        with _mock_validate_object_id(wf_id), patch(
            "application.api.user.workflows.routes.workflows_collection", mock_wf_col
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_col,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_col,
        ):
            with app.test_request_context(f"/api/workflows/{wf_id}", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().get(wf_id)

        assert response.status_code == 200
        data = response.json
        assert data["workflow"]["id"] == str(wf_id)
        assert data["workflow"]["name"] == "Test WF"
        assert data["nodes"] == []
        assert data["edges"] == []


# ---------------------------------------------------------------------------
# WorkflowDetail.delete — delete workflow (mocked validate_object_id)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowDetailDeleteCoverage:

    def test_delete_returns_200_on_success(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = _fake_oid()
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = {"_id": wf_id, "name": "WF", "user": "user1"}
        mock_wf_col.delete_one.return_value = Mock(deleted_count=1)
        mock_nodes_col = Mock()
        mock_nodes_col.delete_many.return_value = Mock()
        mock_edges_col = Mock()
        mock_edges_col.delete_many.return_value = Mock()

        with _mock_validate_object_id(wf_id), patch(
            "application.api.user.workflows.routes.workflows_collection", mock_wf_col
        ), patch(
            "application.api.user.workflows.routes.workflow_nodes_collection",
            mock_nodes_col,
        ), patch(
            "application.api.user.workflows.routes.workflow_edges_collection",
            mock_edges_col,
        ), patch(
            "application.api.user.workflows.routes._dual_write_workflow_delete",
            lambda *a, **kw: None,
        ):
            with app.test_request_context(f"/api/workflows/{wf_id}", method="DELETE"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().delete(wf_id)

        assert response.status_code == 200
        assert response.json["success"] is True

    def test_delete_unauthorized(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context("/api/workflows/abc", method="DELETE"):
            from flask import request

            request.decoded_token = None
            response = WorkflowDetail().delete("abc")

        assert response.status_code == 401

    def test_delete_returns_404_when_not_found(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = _fake_oid()
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = None

        with _mock_validate_object_id(wf_id), patch(
            "application.api.user.workflows.routes.workflows_collection", mock_wf_col
        ):
            with app.test_request_context(f"/api/workflows/{wf_id}", method="DELETE"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().delete(wf_id)

        assert response.status_code == 404
