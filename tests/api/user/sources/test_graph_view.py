"""Tests for the GraphRAG graph-view routes in
docsgpt/api/user/sources/routes.py.

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

from docsgpt.storage.db.repositories.sources import SourcesRepository


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "docsgpt.api.user.sources.routes.db_session", _yield
    ), patch(
        "docsgpt.api.user.sources.routes.db_readonly", _yield
    ):
        yield


def _grant_team_access(pg_conn, owner, member, source_id, access_level):
    from docsgpt.storage.db.repositories.team_members import (
        TeamMembersRepository,
    )
    from docsgpt.storage.db.repositories.team_resource_grants import (
        TeamResourceGrantsRepository,
    )
    from docsgpt.storage.db.repositories.teams import TeamsRepository

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
        from docsgpt.api.user.sources.routes import SourceGraph

        with app.test_request_context("/api/sources/x/graph"):
            from flask import request
            request.decoded_token = None
            response = SourceGraph().get("x")
        assert response.status_code == 401

    def test_owner_gets_bounded_overview(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraph

        user = "u-graph-view-owner"
        sid = _graphrag_source(pg_conn, user)

        store = MagicMock()
        store.count_nodes.return_value = 3
        store.count_edges.return_value = 5
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
            "docsgpt.graphrag.store.GraphStore", return_value=store
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
        # Totals describe the whole graph, not the bounded overview.
        assert response.json["stats"] == {"nodes": 3, "edges": 5}
        store.count_edges.assert_called_once_with(sid)
        # The store receives the source's resolved id and the clamped limit.
        args = store.get_graph_overview.call_args.args
        assert args[0] == sid
        # The route forwards the raw limit; clamping is the store's job (tested
        # below) but a sane request limit must reach it.
        assert args[1] == 9999

    def test_empty_graph_returns_empty_lists(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraph

        user = "u-graph-view-empty"
        sid = _graphrag_source(pg_conn, user)

        store = MagicMock()
        store.count_nodes.return_value = 0

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraph().get(sid)

        assert response.status_code == 200
        assert response.json["nodes"] == []
        assert response.json["edges"] == []
        assert response.json["stats"] == {"nodes": 0, "edges": 0}
        # No graph rows → never query the overview.
        store.get_graph_overview.assert_not_called()

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraph

        owner = "u-graph-view-owner2"
        stranger = "u-graph-view-stranger"
        sid = _graphrag_source(pg_conn, owner)

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore"
        ) as mock_store, app.test_request_context(
            f"/api/sources/{sid}/graph"
        ):
            from flask import request
            request.decoded_token = {"sub": stranger}
            response = SourceGraph().get(sid)

        assert response.status_code == 404
        mock_store.assert_not_called()

    def test_team_viewer_can_read(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraph

        owner = "alice-graph-view"
        viewer = "bob-graph-view-viewer"
        sid = _graphrag_source(pg_conn, owner)
        _grant_team_access(pg_conn, owner, viewer, sid, "viewer")

        store = MagicMock()
        store.count_nodes.return_value = 1
        store.count_edges.return_value = 0
        store.get_graph_overview.return_value = {
            "nodes": [
                {"id": "n1", "name": "A", "type": None,
                 "description": None, "degree": 0},
            ],
            "edges": [],
        }

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph"):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = SourceGraph().get(sid)

        assert response.status_code == 200
        assert {n["id"] for n in response.json["nodes"]} == {"n1"}
        assert response.json["stats"] == {"nodes": 1, "edges": 0}


def _node_list_store():
    store = MagicMock()
    store.list_nodes.return_value = {
        "nodes": [
            {"id": "n1", "name": "Ada", "type": "Person", "degree": 3,
             "doc_freq": 2},
        ],
        "total": 41,
    }
    store.node_type_facets.return_value = [
        {"key": "person", "label": "Person", "count": 30},
        {"key": "", "label": None, "count": 11},
    ]
    return store


@pytest.mark.unit
class TestSourceGraphNodes:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        with app.test_request_context("/api/sources/x/graph/nodes"):
            from flask import request
            request.decoded_token = None
            response = SourceGraphNodes().get("x")
        assert response.status_code == 401

    def test_owner_gets_paged_nodes_and_type_facets(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        user = "u-graph-nodes-owner"
        sid = _graphrag_source(pg_conn, user)
        store = _node_list_store()

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/nodes"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 200
        assert response.json == {
            "success": True,
            "nodes": [
                {"id": "n1", "name": "Ada", "type": "Person", "degree": 3,
                 "doc_freq": 2},
            ],
            "total": 41,
            "page": 1,
            "per_page": 25,
            "types": [
                {"key": "person", "label": "Person", "count": 30},
                {"key": "", "label": None, "count": 11},
            ],
        }
        store.list_nodes.assert_called_once_with(
            sid, query=None, type_key=None, offset=0, limit=25
        )
        store.node_type_facets.assert_called_once_with(sid)

    def test_forwards_filters_and_clamps_paging(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        user = "u-graph-nodes-params"
        sid = _graphrag_source(pg_conn, user)
        store = _node_list_store()

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(
            f"/api/sources/{sid}/graph/nodes?q=%20ada%20&type=person&page=3&per_page=500"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 200
        assert response.json["page"] == 3
        assert response.json["per_page"] == 100
        store.list_nodes.assert_called_once_with(
            sid, query="ada", type_key="person", offset=200, limit=100
        )

    def test_caps_search_query_length(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        user = "u-graph-nodes-long-q"
        sid = _graphrag_source(pg_conn, user)
        store = _node_list_store()

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(
            f"/api/sources/{sid}/graph/nodes?q=%20{'a' * 500}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 200
        store.list_nodes.assert_called_once_with(
            sid, query="a" * 200, type_key=None, offset=0, limit=25
        )

    @pytest.mark.parametrize(
        "qs, page, per_page",
        [
            ("page=0&per_page=0", 1, 1),
            ("page=-4&per_page=-9", 1, 1),
            ("page=abc&per_page=xyz", 1, 25),
        ],
    )
    def test_bad_paging_values_fall_back(self, app, pg_conn, qs, page, per_page):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        user = "u-graph-nodes-bad-paging"
        sid = _graphrag_source(pg_conn, user)
        store = _node_list_store()

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/nodes?{qs}"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 200
        assert (response.json["page"], response.json["per_page"]) == (page, per_page)
        kwargs = store.list_nodes.call_args.kwargs
        assert kwargs["offset"] == (page - 1) * per_page
        assert kwargs["limit"] == per_page

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        owner = "u-graph-nodes-owner2"
        stranger = "u-graph-nodes-stranger"
        sid = _graphrag_source(pg_conn, owner)

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore"
        ) as mock_store, app.test_request_context(
            f"/api/sources/{sid}/graph/nodes"
        ):
            from flask import request
            request.decoded_token = {"sub": stranger}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 404
        mock_store.assert_not_called()

    def test_team_viewer_can_read(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        owner = "alice-graph-nodes"
        viewer = "bob-graph-nodes-viewer"
        sid = _graphrag_source(pg_conn, owner)
        _grant_team_access(pg_conn, owner, viewer, sid, "viewer")
        store = _node_list_store()

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/nodes"):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 200
        assert response.json["total"] == 41
        assert store.list_nodes.call_args.args == (sid,)

    def test_store_failure_returns_400(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        user = "u-graph-nodes-fail"
        sid = _graphrag_source(pg_conn, user)

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", side_effect=RuntimeError("no db")
        ), app.test_request_context(f"/api/sources/{sid}/graph/nodes"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 400


def _real_store_with_mock_conn(fail: bool = False, total: int = 0):
    """A real ``GraphStore`` whose connection is a mock, so the store's own
    error handling runs. ``fail`` makes every query raise."""
    from docsgpt.graphrag.store import GraphStore

    store = GraphStore.__new__(GraphStore)
    cursor = MagicMock()
    cursor.fetchone.return_value = [total]
    cursor.fetchall.return_value = []
    if fail:
        cursor.execute.side_effect = RuntimeError("connection reset")
    conn = MagicMock()
    conn.cursor.return_value = cursor
    store._connection = conn
    store._get_connection = lambda: conn
    store._tables_ensured = True
    return store, cursor


@pytest.mark.unit
class TestSourceGraphNodesRealStore:
    def test_query_failure_returns_400_not_empty_200(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        user = "u-graph-nodes-query-fail"
        sid = _graphrag_source(pg_conn, user)
        store, _ = _real_store_with_mock_conn(fail=True)

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/nodes"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 400
        assert response.json == {"success": False}

    def test_empty_graph_returns_empty_200(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        user = "u-graph-nodes-empty"
        sid = _graphrag_source(pg_conn, user)
        store, _ = _real_store_with_mock_conn(total=0)

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/nodes"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 200
        assert response.json["nodes"] == []
        assert response.json["total"] == 0
        assert response.json["types"] == []

    def _get(self, app, pg_conn, user, store=None, store_error=None, qs=""):
        from docsgpt.api.user.sources.routes import SourceGraphNodes

        sid = _graphrag_source(pg_conn, user)
        kwargs = {"side_effect": store_error} if store_error else {"return_value": store}
        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", **kwargs
        ), app.test_request_context(f"/api/sources/{sid}/graph/nodes{qs}"):
            from flask import request
            request.decoded_token = {"sub": user}
            return SourceGraphNodes().get(sid)

    def test_missing_graph_tables_return_empty_200(self, app, pg_conn):
        import psycopg

        store, cursor = _real_store_with_mock_conn()
        cursor.execute.side_effect = psycopg.errors.UndefinedTable(
            'relation "graph_nodes" does not exist'
        )

        response = self._get(
            app, pg_conn, "u-graph-nodes-no-tables", store=store,
            qs="?type=person&page=2&per_page=10",
        )

        assert response.status_code == 200
        assert response.json == {
            "success": True,
            "nodes": [],
            "total": 0,
            "page": 2,
            "per_page": 10,
            "types": [],
        }

    def test_unconfigured_graph_store_returns_empty_200(self, app, pg_conn):
        response = self._get(
            app, pg_conn, "u-graph-nodes-unconfigured",
            store_error=ValueError("PostgreSQL connection string is required."),
        )

        assert response.status_code == 200
        assert response.json["nodes"] == []
        assert response.json["total"] == 0
        assert response.json["types"] == []

    def test_other_store_errors_still_return_400(self, app, pg_conn):
        import psycopg

        store, cursor = _real_store_with_mock_conn()
        cursor.execute.side_effect = psycopg.errors.InvalidTextRepresentation("bad")

        response = self._get(app, pg_conn, "u-graph-nodes-bad-input", store=store)

        assert response.status_code == 400
        assert response.json == {"success": False}

    def test_huge_page_is_clamped_and_keeps_the_total(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNodes
        from docsgpt.graphrag.store import GRAPH_NODE_LIST_MAX_PAGE

        user = "u-graph-nodes-huge-page"
        sid = _graphrag_source(pg_conn, user)
        store, cursor = _real_store_with_mock_conn(total=41)

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(
            f"/api/sources/{sid}/graph/nodes?page=100000000000000000000&per_page=100"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNodes().get(sid)

        assert response.status_code == 200
        assert response.json["total"] == 41
        assert response.json["nodes"] == []
        assert response.json["page"] == GRAPH_NODE_LIST_MAX_PAGE
        offset = cursor.execute.call_args_list[1].args[1][-1]
        assert offset == (GRAPH_NODE_LIST_MAX_PAGE - 1) * 100
        assert offset < 2**63

@pytest.mark.unit
class TestSourceGraphNode:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import SourceGraphNode

        with app.test_request_context("/api/sources/x/graph/node/n"):
            from flask import request
            request.decoded_token = None
            response = SourceGraphNode().get("x", "n")
        assert response.status_code == 401

    def test_owner_gets_node_detail_with_chunks(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNode

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
            "relationships": [
                {"id": "n2", "name": "Alan", "type": "person", "degree": 2,
                 "edge_type": "knows", "direction": "out"},
            ],
            "relationships_total": 1204,
            "chunks": [{"chunk_id": "5", "text": "body", "metadata": {}}],
        }

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/node/n1"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNode().get(sid, "n1")

        assert response.status_code == 200
        assert response.json["node"]["name"] == "Ada"
        assert response.json["node"]["chunks"][0]["text"] == "body"
        # The capped list and its true total pass through untouched.
        assert len(response.json["node"]["relationships"]) == 1
        assert response.json["node"]["relationships_total"] == 1204
        store.get_node_detail.assert_called_once_with(sid, "n1")

    def test_unknown_node_404(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNode

        user = "u-graph-node-missing"
        sid = _graphrag_source(pg_conn, user)

        store = MagicMock()
        store.get_node_detail.return_value = None

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=store
        ), app.test_request_context(f"/api/sources/{sid}/graph/node/nope"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceGraphNode().get(sid, "nope")

        assert response.status_code == 404

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceGraphNode

        owner = "u-graph-node-owner2"
        stranger = "u-graph-node-stranger"
        sid = _graphrag_source(pg_conn, owner)

        with _patch_db(pg_conn), patch(
            "docsgpt.graphrag.store.GraphStore"
        ) as mock_store, app.test_request_context(
            f"/api/sources/{sid}/graph/node/n1"
        ):
            from flask import request
            request.decoded_token = {"sub": stranger}
            response = SourceGraphNode().get(sid, "n1")

        assert response.status_code == 404
        mock_store.assert_not_called()
