#!/usr/bin/env python3
"""
Integration tests for DocsGPT workflow management endpoints.

Uses Flask test client with real MongoDB (must be running).

Endpoints tested:
- /api/workflows (POST) - Create workflow
- /api/workflows/<id> (GET) - Get workflow
- /api/workflows/<id> (PUT) - Update workflow
- /api/workflows/<id> (DELETE) - Delete workflow

Run:
    pytest tests/integration/test_workflows.py -v
"""

import time

import pytest
from jose import jwt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Create the real Flask app (connects to real MongoDB)."""
    from application.app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture(scope="module")
def client(app):
    """Flask test client.

    When AUTH_TYPE is set to simple_jwt/session_jwt a Bearer token is
    injected; otherwise the backend already returns {"sub": "local"}
    for every request so no token is needed.
    """
    from application.core.settings import settings

    c = app.test_client()
    if settings.AUTH_TYPE in ("simple_jwt", "session_jwt"):
        secret = settings.JWT_SECRET_KEY
        if not secret:
            pytest.skip("JWT_SECRET_KEY not configured")
        payload = {"sub": f"test_workflow_integration_{int(time.time())}"}
        token = jwt.encode(payload, secret, algorithm="HS256")
        c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return c


@pytest.fixture(scope="module")
def created_ids():
    """Accumulator for workflow IDs to clean up after all tests."""
    return []


@pytest.fixture(autouse=True, scope="module")
def cleanup(client, created_ids):
    """Delete all test-created workflows after the module finishes."""
    yield
    for wf_id in created_ids:
        try:
            client.delete(f"/api/workflows/{wf_id}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def simple_workflow(suffix=""):
    """Start -> End."""
    return {
        "name": f"Simple WF {int(time.time())}{suffix}",
        "description": "integration test",
        "nodes": [
            {"id": "start_1", "type": "start", "title": "Start",
             "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "end_1", "type": "end", "title": "End",
             "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "edge_1", "source": "start_1", "target": "end_1"},
        ],
    }


def linear_workflow(suffix=""):
    """Start -> Agent -> End."""
    return {
        "name": f"Linear WF {int(time.time())}{suffix}",
        "description": "integration test",
        "nodes": [
            {"id": "start_1", "type": "start", "title": "Start",
             "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "agent_1", "type": "agent", "title": "Agent",
             "position": {"x": 200, "y": 0}, "data": {
                 "agent_type": "classic",
                 "system_prompt": "You are helpful.",
                 "prompt_template": "",
                 "stream_to_user": False,
             }},
            {"id": "end_1", "type": "end", "title": "End",
             "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "edge_1", "source": "start_1", "target": "agent_1"},
            {"id": "edge_2", "source": "agent_1", "target": "end_1"},
        ],
    }


def multi_input_end_workflow(suffix=""):
    """Condition branches into two agents, both converging on one end node.

    Graph:
        start -> condition --(case_1)--> agent_a --\
                           --(else)----> agent_b ---+--> end
    """
    return {
        "name": f"Multi-Input End {int(time.time())}{suffix}",
        "description": "end node with multiple inputs",
        "nodes": [
            {"id": "start_1", "type": "start", "title": "Start",
             "position": {"x": 0, "y": 100}, "data": {}},
            {"id": "cond_1", "type": "condition", "title": "Branch",
             "position": {"x": 200, "y": 100}, "data": {
                 "mode": "simple",
                 "cases": [
                     {"name": "Case 1", "expression": "true",
                      "sourceHandle": "case_1"},
                 ],
             }},
            {"id": "agent_a", "type": "agent", "title": "Agent A",
             "position": {"x": 400, "y": 0}, "data": {
                 "agent_type": "classic",
                 "system_prompt": "Branch A",
                 "prompt_template": "",
                 "stream_to_user": False,
             }},
            {"id": "agent_b", "type": "agent", "title": "Agent B",
             "position": {"x": 400, "y": 200}, "data": {
                 "agent_type": "classic",
                 "system_prompt": "Branch B",
                 "prompt_template": "",
                 "stream_to_user": False,
             }},
            {"id": "end_1", "type": "end", "title": "End",
             "position": {"x": 600, "y": 100}, "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "cond_1"},
            {"id": "e2", "source": "cond_1", "target": "agent_a",
             "sourceHandle": "case_1"},
            {"id": "e3", "source": "cond_1", "target": "agent_b",
             "sourceHandle": "else"},
            # Both agents feed into the SAME end node
            {"id": "e4", "source": "agent_a", "target": "end_1"},
            {"id": "e5", "source": "agent_b", "target": "end_1"},
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_id(resp):
    """Pull workflow id from create/update response."""
    body = resp.get_json()
    data = body.get("data") or body
    return data.get("id")


def _get_graph(client, wf_id):
    """Fetch workflow and return (nodes, edges)."""
    resp = client.get(f"/api/workflows/{wf_id}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    data = body.get("data") or body
    return data.get("nodes", []), data.get("edges", [])


# ===========================================================================
# CRUD tests
# ===========================================================================


class TestWorkflowCRUD:

    def test_create_simple_workflow(self, client, created_ids):
        resp = client.post("/api/workflows", json=simple_workflow())
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)
        wf_id = _extract_id(resp)
        assert wf_id
        created_ids.append(wf_id)

    def test_create_linear_workflow(self, client, created_ids):
        resp = client.post("/api/workflows", json=linear_workflow())
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)
        wf_id = _extract_id(resp)
        assert wf_id
        created_ids.append(wf_id)

    def test_get_workflow_returns_nodes_and_edges(self, client, created_ids):
        resp = client.post("/api/workflows", json=simple_workflow(" get"))
        wf_id = _extract_id(resp)
        created_ids.append(wf_id)

        nodes, edges = _get_graph(client, wf_id)
        assert len(nodes) == 2
        assert len(edges) == 1

    def test_update_workflow(self, client, created_ids):
        resp = client.post("/api/workflows", json=simple_workflow(" upd"))
        wf_id = _extract_id(resp)
        created_ids.append(wf_id)

        update_resp = client.put(
            f"/api/workflows/{wf_id}", json=linear_workflow(" updated")
        )
        assert update_resp.status_code == 200, update_resp.get_data(as_text=True)

        nodes, edges = _get_graph(client, wf_id)
        assert len(nodes) == 3  # start, agent, end
        assert len(edges) == 2

    def test_delete_workflow(self, client):
        resp = client.post("/api/workflows", json=simple_workflow(" del"))
        wf_id = _extract_id(resp)

        del_resp = client.delete(f"/api/workflows/{wf_id}")
        assert del_resp.status_code == 200

        get_resp = client.get(f"/api/workflows/{wf_id}")
        assert get_resp.status_code in (400, 404)

    def test_reject_workflow_without_end_node(self, client):
        payload = {
            "name": "No End",
            "nodes": [
                {"id": "s", "type": "start", "title": "Start",
                 "position": {"x": 0, "y": 0}, "data": {}},
            ],
            "edges": [],
        }
        resp = client.post("/api/workflows", json=payload)
        assert resp.status_code == 400, resp.get_data(as_text=True)


# ===========================================================================
# Multi-input end node tests
# ===========================================================================


class TestMultiInputEndNode:
    """Verify that an end node can receive edges from multiple source nodes."""

    def test_create_multi_input_end_workflow_accepted(self, client, created_ids):
        """Backend must accept a workflow where two edges target the same end node."""
        resp = client.post("/api/workflows", json=multi_input_end_workflow())
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)
        wf_id = _extract_id(resp)
        assert wf_id
        created_ids.append(wf_id)

    def test_multi_input_end_all_edges_persisted(self, client, created_ids):
        """After round-trip, both edges into the end node must still be present."""
        resp = client.post(
            "/api/workflows", json=multi_input_end_workflow(" persist")
        )
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)
        wf_id = _extract_id(resp)
        created_ids.append(wf_id)

        nodes, edges = _get_graph(client, wf_id)

        # Locate end node
        end_ids = {n["id"] for n in nodes if n["type"] == "end"}
        assert end_ids, "no end node in response"

        # Count edges targeting any end node
        edges_to_end = [e for e in edges if e["target"] in end_ids]
        assert len(edges_to_end) >= 2, (
            f"Expected >=2 edges to end, got {len(edges_to_end)}: {edges_to_end}"
        )

    def test_multi_input_end_total_edge_count(self, client, created_ids):
        """All 5 edges of the multi-input graph must survive persistence."""
        resp = client.post(
            "/api/workflows", json=multi_input_end_workflow(" count")
        )
        wf_id = _extract_id(resp)
        created_ids.append(wf_id)

        _, edges = _get_graph(client, wf_id)
        assert len(edges) == 5, f"Expected 5 edges, got {len(edges)}"

    def test_update_to_multi_input_end_preserves_edges(self, client, created_ids):
        """Updating a simple workflow to multi-input end keeps all edges."""
        # Create simple
        resp = client.post("/api/workflows", json=simple_workflow(" pre"))
        wf_id = _extract_id(resp)
        created_ids.append(wf_id)

        # Update to multi-input end
        update_resp = client.put(
            f"/api/workflows/{wf_id}",
            json=multi_input_end_workflow(" post"),
        )
        assert update_resp.status_code == 200, update_resp.get_data(as_text=True)

        nodes, edges = _get_graph(client, wf_id)
        end_ids = {n["id"] for n in nodes if n["type"] == "end"}
        edges_to_end = [e for e in edges if e["target"] in end_ids]
        assert len(edges_to_end) >= 2, (
            f"Expected >=2 edges to end after update, got {len(edges_to_end)}"
        )
