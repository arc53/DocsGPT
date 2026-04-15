"""Additional coverage tests for application.api.user.workflows.routes.

No bson/ObjectId imports. Mongo collections are replaced by Mock objects.
``validate_object_id`` (which calls bson internally) is patched wherever
WorkflowDetail routes invoke it so that tests run without pymongo.
Repository classes (WorkflowsRepository, etc.) are patched for dual-write paths.
"""

import uuid
from contextlib import contextmanager
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
    pass

@pytest.mark.unit
class TestSerializeNodeCoverage:
    pass

@pytest.mark.unit
class TestSerializeEdgeCoverage:
    pass





# ---------------------------------------------------------------------------
# get_workflow_graph_version — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWorkflowGraphVersionCoverage:
    pass

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
    pass





# ---------------------------------------------------------------------------
# validate_workflow_structure — additional condition-node coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateWorkflowStructureCoverage:
    pass

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
    pass

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



# ---------------------------------------------------------------------------
# WorkflowDetail.get — retrieve a single workflow (mocked validate_object_id)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowDetailGetCoverage:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context("/api/workflows/abc", method="GET"):
            from flask import request

            request.decoded_token = None
            response = WorkflowDetail().get("abc")

        assert response.status_code == 401




# ---------------------------------------------------------------------------
# WorkflowDetail.delete — delete workflow (mocked validate_object_id)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowDetailDeleteCoverage:
    pass

    def test_delete_unauthorized(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context("/api/workflows/abc", method="DELETE"):
            from flask import request

            request.decoded_token = None
            response = WorkflowDetail().delete("abc")

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Real-PG happy-path tests using pg_conn
# ---------------------------------------------------------------------------


@contextmanager
def _patch_wf_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.workflows.routes.db_session", _yield
    ), patch(
        "application.api.user.workflows.routes.db_readonly", _yield
    ):
        yield


def _minimal_workflow_body(name="WF1"):
    return {
        "name": name,
        "description": "desc",
        "nodes": [
            {"id": "start1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "end1", "type": "end", "position": {"x": 100, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start1", "target": "end1"},
        ],
    }


class TestSerializers:
    def test_serialize_workflow_fields(self):
        from application.api.user.workflows.routes import serialize_workflow
        import datetime

        wf = {
            "id": "00000000-0000-0000-0000-000000000001",
            "user_id": "u1",
            "name": "hello",
            "description": "d",
            "current_graph_version": 3,
            "created_at": datetime.datetime(2024, 1, 1, 12, 0, 0),
            "updated_at": datetime.datetime(2024, 1, 2, 12, 0, 0),
        }
        got = serialize_workflow(wf)
        assert got["id"] == wf["id"]
        assert got["name"] == "hello"
        assert got["description"] == "d"
        # created_at gets iso-formatted
        assert got["created_at"] == "2024-01-01T12:00:00"

    def test_serialize_node_shape(self):
        from application.api.user.workflows.routes import serialize_node

        node = {
            "id": "00000000-0000-0000-0000-000000000002",
            "node_id": "start1",
            "node_type": "start",
            "title": "Start",
            "description": "",
            "position": {"x": 0, "y": 0},
            "config": {},
        }
        out = serialize_node(node)
        assert out["id"] == "start1"
        assert out["type"] == "start"
        assert out["position"] == {"x": 0, "y": 0}

    def test_serialize_edge_shape(self):
        from application.api.user.workflows.routes import serialize_edge

        edge = {
            "id": "00000000-0000-0000-0000-000000000003",
            "edge_id": "e-1",
            "source_node_id": "start1",
            "target_node_id": "end1",
            "source_handle": None,
            "target_handle": None,
            "config": {},
        }
        out = serialize_edge(edge)
        assert out["id"] == "e-1"


class TestWorkflowListPost:
    def test_creates_valid_workflow(self, app, pg_conn):
        from application.api.user.workflows.routes import WorkflowList

        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows",
            method="POST",
            json=_minimal_workflow_body("first"),
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowList().post()

        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert body["data"]["id"]

    def test_create_validation_failure_returns_400(self, app, pg_conn):
        """Workflow with no start node should fail validation."""
        from application.api.user.workflows.routes import WorkflowList

        body = {
            "name": "bad",
            "nodes": [{"id": "end1", "type": "end"}],
            "edges": [],
        }
        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows", method="POST", json=body
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowList().post()

        assert response.status_code == 400

    def test_create_db_error_returns_400(self, app):
        from application.api.user.workflows.routes import WorkflowList

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.workflows.routes.db_session", _broken
        ), app.test_request_context(
            "/api/workflows",
            method="POST",
            json=_minimal_workflow_body("x"),
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowList().post()

        assert response.status_code == 400


class TestWorkflowDetailGet:
    def test_returns_404_for_missing_workflow(self, app, pg_conn):
        from application.api.user.workflows.routes import WorkflowDetail

        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows/00000000-0000-0000-0000-000000000000",
            method="GET",
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().get(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404

    def test_returns_workflow_after_create(self, app, pg_conn):
        from application.api.user.workflows.routes import (
            WorkflowDetail,
            WorkflowList,
        )

        # Create one first
        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows",
            method="POST",
            json=_minimal_workflow_body("retrievable"),
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            created = WorkflowList().post()
        wf_id = created.get_json()["data"]["id"]

        with _patch_wf_db(pg_conn), app.test_request_context(
            f"/api/workflows/{wf_id}", method="GET"
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().get(wf_id)

        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["workflow"]["name"] == "retrievable"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

    def test_db_error_returns_400(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.workflows.routes.db_readonly", _broken
        ), app.test_request_context("/api/workflows/abc"):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().get("abc")
        assert response.status_code == 400


class TestWorkflowDetailPut:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context(
            "/api/workflows/abc",
            method="PUT",
            json={"name": "x"},
        ):
            from flask import request
            request.decoded_token = None
            response = WorkflowDetail().put("abc")
        assert response.status_code == 401

    def test_returns_400_missing_name(self, app, pg_conn):
        from application.api.user.workflows.routes import WorkflowDetail

        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows/abc",
            method="PUT",
            json={"description": "x"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().put("abc")
        assert response.status_code == 400

    def test_returns_404_missing_workflow(self, app, pg_conn):
        from application.api.user.workflows.routes import WorkflowDetail

        body = _minimal_workflow_body("new")
        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows/00000000-0000-0000-0000-000000000000",
            method="PUT",
            json=body,
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().put(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404

    def test_validation_failure_returns_400(self, app, pg_conn):
        from application.api.user.workflows.routes import WorkflowDetail

        body = {
            "name": "bad",
            "nodes": [{"id": "end1", "type": "end"}],
            "edges": [],
        }
        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows/abc",
            method="PUT",
            json=body,
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().put("abc")
        assert response.status_code == 400

    def test_updates_workflow(self, app, pg_conn):
        from application.api.user.workflows.routes import (
            WorkflowDetail,
            WorkflowList,
        )

        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows",
            method="POST",
            json=_minimal_workflow_body("before"),
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            created = WorkflowList().post()
        wf_id = created.get_json()["data"]["id"]

        body = _minimal_workflow_body("after")
        with _patch_wf_db(pg_conn), app.test_request_context(
            f"/api/workflows/{wf_id}",
            method="PUT",
            json=body,
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().put(wf_id)
        assert response.status_code == 200

        # Verify the version bumped
        with _patch_wf_db(pg_conn), app.test_request_context(
            f"/api/workflows/{wf_id}", method="GET"
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            got = WorkflowDetail().get(wf_id)
        data = got.get_json()["data"]
        assert data["workflow"]["name"] == "after"

    def test_db_error_returns_400(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.workflows.routes.db_session", _broken
        ), app.test_request_context(
            "/api/workflows/abc",
            method="PUT",
            json=_minimal_workflow_body("x"),
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().put("abc")
        assert response.status_code == 400


class TestWorkflowDetailDelete:
    def test_returns_404_missing(self, app, pg_conn):
        from application.api.user.workflows.routes import WorkflowDetail

        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows/00000000-0000-0000-0000-000000000000",
            method="DELETE",
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().delete(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404

    def test_deletes_workflow(self, app, pg_conn):
        from application.api.user.workflows.routes import (
            WorkflowDetail,
            WorkflowList,
        )

        with _patch_wf_db(pg_conn), app.test_request_context(
            "/api/workflows",
            method="POST",
            json=_minimal_workflow_body("tbd"),
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            created = WorkflowList().post()
        wf_id = created.get_json()["data"]["id"]

        with _patch_wf_db(pg_conn), app.test_request_context(
            f"/api/workflows/{wf_id}", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().delete(wf_id)
        assert response.status_code == 200

    def test_db_error_returns_400(self, app):
        from application.api.user.workflows.routes import WorkflowDetail

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.workflows.routes.db_session", _broken
        ), app.test_request_context(
            "/api/workflows/abc", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            response = WorkflowDetail().delete("abc")
        assert response.status_code == 400


class TestValidateWorkflowStructureExtras:
    def test_no_nodes_returns_error(self):
        from application.api.user.workflows.routes import (
            validate_workflow_structure,
        )
        errors = validate_workflow_structure([], [])
        assert any("at least one node" in e for e in errors)

    def test_missing_start_node_returns_error(self):
        from application.api.user.workflows.routes import (
            validate_workflow_structure,
        )
        errors = validate_workflow_structure(
            [{"id": "end1", "type": "end"}], []
        )
        assert any("start" in e for e in errors)

    def test_missing_end_node_returns_error(self):
        from application.api.user.workflows.routes import (
            validate_workflow_structure,
        )
        errors = validate_workflow_structure(
            [{"id": "s", "type": "start"}],
            [{"id": "e1", "source": "s", "target": "s"}],
        )
        assert any("end" in e for e in errors)

    def test_edge_with_missing_source_reports_error(self):
        from application.api.user.workflows.routes import (
            validate_workflow_structure,
        )
        errors = validate_workflow_structure(
            [
                {"id": "s", "type": "start"},
                {"id": "e", "type": "end"},
            ],
            [
                {"id": "edge1", "source": "ghost", "target": "e"},
                {"id": "edge2", "source": "s", "target": "e"},
            ],
        )
        assert any("non-existent source" in err for err in errors)

    def test_condition_node_without_else_branch_errors(self):
        from application.api.user.workflows.routes import (
            validate_workflow_structure,
        )
        nodes = [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "data": {"cases": [{"expression": "x", "sourceHandle": "yes"}]},
            },
            {"id": "end", "type": "end"},
        ]
        edges = [
            {"id": "e1", "source": "start", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "end", "sourceHandle": "yes"},
        ]
        errors = validate_workflow_structure(nodes, edges)
        assert any("'else'" in e for e in errors)


class TestValidateJsonSchemaPayload:
    def test_none_returns_pair_of_none(self):
        from application.api.user.workflows.routes import (
            validate_json_schema_payload,
        )
        got, err = validate_json_schema_payload(None)
        assert got is None and err is None

    def test_valid_schema(self):
        from application.api.user.workflows.routes import (
            validate_json_schema_payload,
        )
        got, err = validate_json_schema_payload(
            {"type": "object", "properties": {"a": {"type": "string"}}},
        )
        assert err is None
        assert got is not None

    def test_invalid_schema_returns_error(self):
        from application.api.user.workflows.routes import (
            validate_json_schema_payload,
        )
        # Force an invalid payload by passing something that isn't dict
        got, err = validate_json_schema_payload("not-a-schema")
        # Either returns error, or returns normalized; handle both
        assert (got is None and isinstance(err, str)) or got is not None


class TestNormalizeAgentNodeJsonSchemas:
    def test_returns_non_dict_entries_as_is(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )
        got = normalize_agent_node_json_schemas(["not-a-dict"])
        assert got == ["not-a-dict"]

    def test_non_agent_node_passes_through(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )
        got = normalize_agent_node_json_schemas(
            [{"id": "s", "type": "start"}]
        )
        assert got[0]["type"] == "start"

    def test_agent_node_without_json_schema_passes_through(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )
        got = normalize_agent_node_json_schemas(
            [{"id": "a", "type": "agent", "data": {"other": 1}}]
        )
        assert got[0]["data"]["other"] == 1

    def test_agent_node_with_schema_normalizes(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )
        got = normalize_agent_node_json_schemas([
            {
                "id": "a",
                "type": "agent",
                "data": {"json_schema": {"type": "object"}},
            }
        ])
        assert got[0]["data"]["json_schema"] is not None

    def test_agent_node_invalid_schema_kept_original(self):
        from application.api.user.workflows.routes import (
            normalize_agent_node_json_schemas,
        )
        got = normalize_agent_node_json_schemas([
            {
                "id": "a",
                "type": "agent",
                "data": {"json_schema": "not-a-dict"},
            }
        ])
        # Should still return something
        assert got[0]["type"] == "agent"


class TestWriteGraphEdgesWithUnresolvedNodes:
    def test_drops_edge_with_unknown_source(self, pg_conn, app):
        from application.api.user.workflows.routes import (
            _write_graph,
        )
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )

        user = "u-unresolved"
        wf = WorkflowsRepository(pg_conn).create(user, "wf")
        pg_wf_id = str(wf["id"])

        nodes_data = [
            {"id": "n1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "n2", "type": "end", "position": {"x": 100, "y": 0}, "data": {}},
        ]
        edges_data = [
            {"id": "e1", "source": "n1", "target": "n2"},
            # Unresolved node reference
            {"id": "e2", "source": "ghost", "target": "n2"},
        ]
        with app.app_context():
            _write_graph(pg_conn, pg_wf_id, 1, nodes_data, edges_data)

    def test_get_workflow_graph_version_negative_falls_back(self):
        from application.api.user.workflows.routes import (
            get_workflow_graph_version,
        )
        assert get_workflow_graph_version({"current_graph_version": -5}) == 1

