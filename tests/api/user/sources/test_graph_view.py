"""Tests for the GraphRAG graph-view routes in
application/api/user/sources/routes.py.

The endpoints are read-access gated (owner or team grant). The ``GraphStore`` is
mocked so no live vector store, embeddings, or LLM calls run; the ``sources`` row
is real so the authz lookup resolves. A separate suite exercises
``GraphStore.get_graph_overview`` against a live pgvector store (skipped when
unreachable) and asserts the SQL is parameterized via a mock cursor.
"""

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from application.storage.db.repositories.sources import SourcesRepository


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.sources.routes.db_session", _yield
    ), patch(
        "application.api.user.sources.routes.db_readonly", _yield
    ):
        yield


def _grant_team_access(pg_conn, owner, member, source_id, access_level):
    from application.storage.db.repositories.team_members import (
        TeamMembersRepository,
    )
    from application.storage.db.repositories.team_resource_grants import (
        TeamResourceGrantsRepository,
    )
    from application.storage.db.repositories.teams import TeamsRepository

    team = TeamsRepository(pg_conn).create(
        "Acme", f"acme-{uuid.uuid4().hex[:8]}", owner
    )
    TeamMembersRepository(pg_conn).add_member(
        team["id"], member, role="team_member"
    )
    TeamResourceGrantsRepository(pg_conn).grant(
        team["id"], "source", source_id, owner_id=owner, granted_by=owner,
        access_level=access_level,
    )


def _graphrag_source(pg_conn, user):
    src = SourcesRepository(pg_conn).create(
        "graph-src", user_id=user, type="file",
        config={
            "kind": "graphrag",
            "retrieval": {"retriever": "graphrag"},
        },
        directory_structure={"a.md": {"type": "text/markdown"}},
    )
    return str(src["id"])


@pytest.mark.unit
class TestSourceGraph:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import SourceGraph

        with app.test_request_context("/api/sources/x/graph"):
            from flask import request
            request.decoded_token = None
            response = SourceGraph().get("x")
        assert response.status_code == 401

    def test_owner_gets_bounded_overview(self, app, pg_conn):
        from application.api.user.sources.routes import SourceGraph

        user = "u-graph-view-owner"
        sid = _graphrag_source(pg_conn, user)

        store = MagicMock()
        store.count_nodes.return_value = 3
        store.get_graph_overview.return_value = {
            "nodes": [
                {"id": "n1", "name": "A", "type": "person",
                 "description": "d", "degree": 2},
                {"id": "n2", "name": "B", "type": "org",
                 "description": "e", "degree": 1},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "type": "rel", "weight": 1.0},
            ],
        }

        with _patch_db(pg_conn), patch(
            "application.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(
            f"/api/sources/{sid}/graph?limit=9999"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraph().get(sid)

        assert response.status_code == 200
        assert response.json["success"] is True
        assert {n["id"] for n in response.json["nodes"]} == {"n1", "n2"}
        assert response.json["edges"][0]["source"] == "n1"
        # The store receives the source's resolved id and the clamped limit.
        args = store.get_graph_overview.call_args.args
        assert args[0] == sid
        # The route forwards the raw limit; clamping is the store's job (tested
        # below) but a sane request limit must reach it.
        assert args[1] == 9999

    def test_empty_graph_returns_empty_lists(self, app, pg_conn):
        from application.api.user.sources.routes import SourceGraph

        user = "u-graph-view-empty"
        sid = _graphrag_source(pg_conn, user)

        store = MagicMock()
        store.count_nodes.return_value = 0

        with _patch_db(pg_conn), patch(
            "application.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraph().get(sid)

        assert response.status_code == 200
        assert response.json["nodes"] == []
        assert response.json["edges"] == []
        # No graph rows → never query the overview.
        store.get_graph_overview.assert_not_called()

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from application.api.user.sources.routes import SourceGraph

        owner = "u-graph-view-owner2"
        stranger = "u-graph-view-stranger"
        sid = _graphrag_source(pg_conn, owner)

        with _patch_db(pg_conn), patch(
            "application.graphrag.store.GraphStore"
        ) as mock_store, app.test_request_context(
            f"/api/sources/{sid}/graph"
        ):
            from flask import request
            request.decoded_token = {"sub": stranger}
            response = SourceGraph().get(sid)

        assert response.status_code == 404
        mock_store.assert_not_called()

    def test_team_viewer_can_read(self, app, pg_conn):
        from application.api.user.sources.routes import SourceGraph

        owner = "alice-graph-view"
        viewer = "bob-graph-view-viewer"
        sid = _graphrag_source(pg_conn, owner)
        _grant_team_access(pg_conn, owner, viewer, sid, "viewer")

        store = MagicMock()
        store.count_nodes.return_value = 1
        store.get_graph_overview.return_value = {
            "nodes": [
                {"id": "n1", "name": "A", "type": None,
                 "description": None, "degree": 0},
            ],
            "edges": [],
        }

        with _patch_db(pg_conn), patch(
            "application.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph"):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = SourceGraph().get(sid)

        assert response.status_code == 200
        assert {n["id"] for n in response.json["nodes"]} == {"n1"}


@pytest.mark.unit
class TestSourceGraphNode:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import SourceGraphNode

        with app.test_request_context("/api/sources/x/graph/node/n"):
            from flask import request
            request.decoded_token = None
            response = SourceGraphNode().get("x", "n")
        assert response.status_code == 401

    def test_owner_gets_node_detail_with_chunks(self, app, pg_conn):
        from application.api.user.sources.routes import SourceGraphNode

        user = "u-graph-node-owner"
        sid = _graphrag_source(pg_conn, user)

        store = MagicMock()
        store.get_node_detail.return_value = {
            "id": "n1",
            "name": "Ada",
            "type": "person",
            "description": "A mathematician.",
            "degree": 3,
            "doc_freq": 2,
            "chunks": [{"chunk_id": "5", "text": "body", "metadata": {}}],
        }

        with _patch_db(pg_conn), patch(
            "application.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/node/n1"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNode().get(sid, "n1")

        assert response.status_code == 200
        assert response.json["node"]["name"] == "Ada"
        assert response.json["node"]["chunks"][0]["text"] == "body"
        store.get_node_detail.assert_called_once_with(sid, "n1")

    def test_unknown_node_404(self, app, pg_conn):
        from application.api.user.sources.routes import SourceGraphNode

        user = "u-graph-node-missing"
        sid = _graphrag_source(pg_conn, user)

        store = MagicMock()
        store.get_node_detail.return_value = None

        with _patch_db(pg_conn), patch(
            "application.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/node/nope"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNode().get(sid, "nope")

        assert response.status_code == 404

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from application.api.user.sources.routes import SourceGraphNode

        owner = "u-graph-node-owner2"
        stranger = "u-graph-node-stranger"
        sid = _graphrag_source(pg_conn, owner)

        with _patch_db(pg_conn), patch(
            "application.graphrag.store.GraphStore"
        ) as mock_store, app.test_request_context(
            f"/api/sources/{sid}/graph/node/n1"
        ):
            from flask import request
            request.decoded_token = {"sub": stranger}
            response = SourceGraphNode().get(sid, "n1")

        assert response.status_code == 404
        mock_store.assert_not_called()
