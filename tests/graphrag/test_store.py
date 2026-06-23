"""Tests for the GraphRAG GraphStore (on-demand tables in the pgvector DB).

Two layers:

* A live-pg integration test that exercises the real DDL + SQL against the
  pgvector store DB (same connection-string source as ``PGVectorStore``). It
  uses a unique temp ``source_id`` and tears down every row it creates.
* A mock-cursor test that asserts the parameterized SQL shapes — ``source_id``
  and embeddings are bound params, never interpolated.

The embedding dimension is mocked everywhere so the suite never loads the real
SentenceTransformer model: the live store creates ``TEST_EMBEDDING_DIM`` vectors
and the helpers build matching ones.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

import application.graphrag.store as store_module
from application.graphrag.store import GraphStore

TEST_EMBEDDING_DIM = 8

_REAL_EMBEDDING_DIM = GraphStore._embedding_dim


@pytest.fixture(autouse=True)
def _mock_embedding_dim(monkeypatch):
    monkeypatch.setattr(
        GraphStore, "_embedding_dim", lambda self: TEST_EMBEDDING_DIM
    )


def _resolve_connection_string():
    from application.core.settings import settings

    conn = getattr(settings, "PGVECTOR_CONNECTION_STRING", None)
    if not conn and getattr(settings, "POSTGRES_URI", None):
        from application.core.db_uri import normalize_pgvector_connection_string

        conn = normalize_pgvector_connection_string(settings.POSTGRES_URI)
    return conn


_GRAPH_TABLES = (
    "graph_node_chunks",
    "graph_edges",
    "graph_nodes",
    "graph_ingest_progress",
)


def _drop_graph_tables(conn_string):
    import psycopg

    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS {', '.join(_GRAPH_TABLES)} CASCADE;"
            )
        conn.commit()


def _live_store():
    conn = _resolve_connection_string()
    if not conn:
        pytest.skip("No pgvector connection string configured")
    try:
        _drop_graph_tables(conn)
        return GraphStore(connection_string=conn)
    except Exception as exc:
        pytest.skip(f"pgvector DB not reachable: {exc}")


def _embedding(seed: float) -> list:
    vec = [0.0] * TEST_EMBEDDING_DIM
    vec[0] = seed
    return vec


@pytest.mark.integration
class TestGraphStoreLive:
    @pytest.fixture
    def store(self):
        store = _live_store()
        yield store
        _drop_graph_tables(store._connection_string)

    @pytest.fixture
    def source_id(self):
        return str(uuid.uuid4())

    def test_ensure_tables_idempotent(self, store):
        store._ensure_tables()
        store._ensure_tables()

    def test_upsert_node_merges_by_normalized_name(self, store, source_id):
        try:
            first = store.upsert_node(
                source_id=source_id,
                name="Ada Lovelace",
                normalized_name="ada lovelace",
                type="person",
                description="A mathematician.",
                name_embedding=_embedding(1.0),
            )
            second = store.upsert_node(
                source_id=source_id,
                name="Ada Lovelace",
                normalized_name="ada lovelace",
                type="person",
                description="Wrote the first algorithm.",
            )
            assert first == second

            node = store.get_node_by_normalized(source_id, "ada lovelace")
            assert node is not None
            assert node["id"] == first
            assert node["doc_freq"] == 2
            assert "mathematician" in node["description"]
            assert "first algorithm" in node["description"]

            duplicate = store.upsert_node(
                source_id=source_id,
                name="Ada Lovelace",
                normalized_name="ada lovelace",
                description="Wrote the first algorithm.",
            )
            assert duplicate == first
            node = store.get_node_by_normalized(source_id, "ada lovelace")
            assert node["description"].count("first algorithm") == 1

            assert store.count_nodes(source_id) == 1
        finally:
            store.delete_by_source(source_id)

    def test_add_edge_and_link_chunk(self, store, source_id):
        try:
            a = store.upsert_node(source_id, "A", "a", "thing", "desc a")
            b = store.upsert_node(source_id, "B", "b", "thing", "desc b")
            store.add_edge(
                source_id, a, b, "related", "a relates to b", 2.0, ["chunk-1"]
            )
            store.link_node_chunk(source_id, a, "chunk-1")
            store.link_node_chunk(source_id, a, "chunk-1")
            store.link_node_chunk(source_id, b, "chunk-1")

            mapping = store.get_chunk_ids_for_nodes(source_id, [a, b])
            assert mapping[a] == ["chunk-1"]
            assert mapping[b] == ["chunk-1"]

            store.set_node_degrees(source_id)
            node_a = store.get_node_by_normalized(source_id, "a")
            assert node_a["degree"] == 1
        finally:
            store.delete_by_source(source_id)

    def test_self_loop_degree_agrees_across_paths(self, store, source_id):
        """``add_edge``'s incremental +1 and ``set_node_degrees`` recompute must
        agree on a self-loop (count it once)."""
        try:
            node = store.upsert_node(source_id, "Solo", "solo")
            store.add_edge(source_id, node, node, "self")

            incremental = store.get_node_by_normalized(source_id, "solo")["degree"]
            assert incremental == 1

            store.set_node_degrees(source_id)
            recomputed = store.get_node_by_normalized(source_id, "solo")["degree"]
            assert recomputed == incremental == 1
        finally:
            store.delete_by_source(source_id)

    def test_search_nodes_by_embedding(self, store, source_id):
        try:
            near = store.upsert_node(
                source_id, "Near", "near", "thing", "d", _embedding(1.0)
            )
            store.upsert_node(
                source_id, "Far", "far", "thing", "d", _embedding(-1.0)
            )
            results = store.search_nodes_by_embedding(source_id, _embedding(1.0), k=2)
            assert len(results) == 2
            assert results[0]["id"] == near
            assert results[0]["distance"] <= results[1]["distance"]
        finally:
            store.delete_by_source(source_id)

    def test_get_subgraph_bounded(self, store, source_id):
        try:
            a = store.upsert_node(source_id, "A", "a")
            b = store.upsert_node(source_id, "B", "b")
            c = store.upsert_node(source_id, "C", "c")
            store.add_edge(source_id, a, b, "rel")
            store.add_edge(source_id, b, c, "rel")

            one_hop = store.get_subgraph(source_id, [a], hops=1)
            node_ids = {n["id"] for n in one_hop["nodes"]}
            assert a in node_ids and b in node_ids
            assert c not in node_ids

            two_hop = store.get_subgraph(source_id, [a], hops=2)
            node_ids = {n["id"] for n in two_hop["nodes"]}
            assert {a, b, c} <= node_ids
            assert len(two_hop["edges"]) >= 2
        finally:
            store.delete_by_source(source_id)

    def test_get_subgraph_frontier_truncation_is_deterministic(
        self, store, source_id, monkeypatch
    ):
        """Bounded expansion must pick the same neighbors run-to-run so PPR (G5)
        is reproducible."""
        try:
            hub = store.upsert_node(source_id, "Hub", "hub")
            leaves = []
            for i in range(6):
                leaf = store.upsert_node(source_id, f"L{i}", f"l{i}")
                store.add_edge(source_id, hub, leaf, "rel")
                leaves.append(leaf)

            monkeypatch.setattr(store_module, "MAX_SUBGRAPH_NODES", 4)

            first = {n["id"] for n in store.get_subgraph(source_id, [hub])["nodes"]}
            second = {n["id"] for n in store.get_subgraph(source_id, [hub])["nodes"]}
            assert first == second
            assert len(first) == 4

            kept_leaves = sorted(leaves)[:3]
            assert first == {hub, *kept_leaves}
        finally:
            store.delete_by_source(source_id)

    def test_get_graph_overview_bounded_by_degree(self, store, source_id):
        try:
            hub = store.upsert_node(source_id, "Hub", "hub")
            leaves = [
                store.upsert_node(source_id, f"L{i}", f"l{i}") for i in range(4)
            ]
            for leaf in leaves:
                store.add_edge(source_id, hub, leaf, "rel")
            store.set_node_degrees(source_id)

            overview = store.get_graph_overview(source_id, limit=3)
            node_ids = [n["id"] for n in overview["nodes"]]
            assert len(node_ids) == 3
            # The hub has the highest degree, so it must lead the bounded set.
            assert node_ids[0] == hub
            # Edges only connect nodes that survived the limit.
            for edge in overview["edges"]:
                assert edge["source"] in node_ids
                assert edge["target"] in node_ids
        finally:
            store.delete_by_source(source_id)

    def test_get_graph_overview_empty_source(self, store, source_id):
        overview = store.get_graph_overview(source_id)
        assert overview == {"nodes": [], "edges": []}

    def test_get_node_detail_with_linked_chunks(self, store, source_id):
        try:
            node = store.upsert_node(
                source_id, "Ada", "ada", "person", "A mathematician."
            )
            store.link_node_chunk(source_id, node, "chunk-1")

            detail = store.get_node_detail(source_id, node)
            assert detail is not None
            assert detail["name"] == "Ada"
            assert detail["description"] == "A mathematician."
            chunk_ids = [c["chunk_id"] for c in detail["chunks"]]
            assert "chunk-1" in chunk_ids

            assert store.get_node_detail(source_id, str(uuid.uuid4())) is None
        finally:
            store.delete_by_source(source_id)

    def test_checkpoint_pending_and_mark(self, store, source_id):
        try:
            all_chunks = ["c1", "c2", "c3"]
            assert store.pending_chunks(source_id, all_chunks) == all_chunks

            store.mark_chunk(source_id, "c1", "done")
            store.mark_chunk(source_id, "c2", "pending")
            assert store.pending_chunks(source_id, all_chunks) == ["c2", "c3"]

            store.mark_chunk(source_id, "c2", "done")
            assert store.pending_chunks(source_id, all_chunks) == ["c3"]

            progress = store.get_progress(source_id)
            assert progress["c1"] == "done"
            assert progress["c2"] == "done"
        finally:
            store.delete_by_source(source_id)

    def test_delete_by_source_isolation(self, store):
        keep = str(uuid.uuid4())
        drop = str(uuid.uuid4())
        try:
            k = store.upsert_node(keep, "K", "k")
            d = store.upsert_node(drop, "D", "d")
            store.add_edge(keep, k, k, "self")
            store.add_edge(drop, d, d, "self")
            store.link_node_chunk(keep, k, "kc")
            store.link_node_chunk(drop, d, "dc")
            store.mark_chunk(keep, "kc", "done")
            store.mark_chunk(drop, "dc", "done")

            store.delete_by_source(drop)

            assert store.count_nodes(drop) == 0
            assert store.get_progress(drop) == {}
            assert store.count_nodes(keep) == 1
            assert store.get_progress(keep) == {"kc": "done"}
        finally:
            store.delete_by_source(keep)
            store.delete_by_source(drop)


@pytest.mark.unit
class TestGraphStoreParameterization:
    """Asserts SQL is parameterized without touching a real DB."""

    def _store_with_mock_conn(self):
        store = GraphStore.__new__(GraphStore)
        cursor = MagicMock()
        cursor.fetchone.return_value = [str(uuid.uuid4())]
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = cursor
        store._connection = conn
        store._get_connection = lambda: conn
        return store, cursor

    def test_delete_by_source_binds_source_id(self):
        store, cursor = self._store_with_mock_conn()
        sid = str(uuid.uuid4())
        store.delete_by_source(sid)

        for call in cursor.execute.call_args_list:
            sql = call.args[0]
            params = call.args[1] if len(call.args) > 1 else None
            assert "WHERE source_id = %s" in sql
            assert sid not in sql
            assert params == (sid,)

    def test_search_binds_embedding_and_source(self):
        store, cursor = self._store_with_mock_conn()
        sid = str(uuid.uuid4())
        embedding = _embedding(0.5)
        store.search_nodes_by_embedding(sid, embedding, k=5)

        sql, params = cursor.execute.call_args.args[0], cursor.execute.call_args.args[1]
        assert "%s::vector" in sql
        assert "source_id = %s" in sql
        assert sid not in sql
        assert str(embedding) not in sql
        assert params == (embedding, sid, embedding, 5)

    def test_graph_overview_binds_source_and_clamps_limit(self):
        from application.graphrag.store import GRAPH_OVERVIEW_MAX_LIMIT

        store, cursor = self._store_with_mock_conn()
        cursor.fetchall.return_value = []
        sid = str(uuid.uuid4())

        store.get_graph_overview(sid, limit=10_000)

        sql, params = (
            cursor.execute.call_args.args[0],
            cursor.execute.call_args.args[1],
        )
        assert "source_id = %s" in sql
        assert sid not in sql
        # An empty node fetch short-circuits; only the node query ran, and the
        # limit is clamped to the hard cap before binding.
        assert params == (sid, GRAPH_OVERVIEW_MAX_LIMIT)

    def test_upsert_node_binds_all_values(self):
        store, cursor = self._store_with_mock_conn()
        sid = str(uuid.uuid4())
        embedding = _embedding(0.1)
        store.upsert_node(sid, "Name", "name", "type", "desc", embedding)

        sql, params = cursor.execute.call_args.args[0], cursor.execute.call_args.args[1]
        assert "ON CONFLICT (source_id, normalized_name) DO UPDATE" in sql
        assert sid not in sql
        assert "name" not in [t for t in sql.split() if t == sid]
        assert params[1] == sid
        assert params[-1] == embedding


@pytest.mark.unit
class TestEmbeddingDim:
    """The graph table dimension is derived from the configured model (FIX 1)."""

    def test_uses_configured_model_dimension(self, monkeypatch):
        from application.vectorstore import base as base_module

        fake_embedding = MagicMock()
        fake_embedding.dimension = 1536
        monkeypatch.setattr(
            base_module.EmbeddingsSingleton,
            "get_instance",
            staticmethod(lambda *a, **k: fake_embedding),
        )
        monkeypatch.setattr(GraphStore, "_embedding_dim", _REAL_EMBEDDING_DIM)

        store = GraphStore.__new__(GraphStore)
        assert store._embedding_dim() == 1536

    def test_falls_back_to_default_dimension(self, monkeypatch):
        from application.vectorstore import base as base_module

        fake_embedding = object()
        monkeypatch.setattr(
            base_module.EmbeddingsSingleton,
            "get_instance",
            staticmethod(lambda *a, **k: fake_embedding),
        )
        monkeypatch.setattr(GraphStore, "_embedding_dim", _REAL_EMBEDDING_DIM)

        store = GraphStore.__new__(GraphStore)
        assert store._embedding_dim() == store_module.DEFAULT_NAME_EMBEDDING_DIM
