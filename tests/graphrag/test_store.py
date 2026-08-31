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
from unittest.mock import MagicMock, patch

import pytest

import application.graphrag.store as store_module
from application.vectorstore import pgconn
from application.vectorstore import pgvector as pgvector_module

GraphStore = store_module.GraphStore

TEST_EMBEDDING_DIM = 8

POOL_DSN = "postgresql://u:p@localhost/graphpool"

_REAL_EMBEDDING_DIM = GraphStore._embedding_dim


@pytest.fixture(autouse=True)
def _mock_embedding_dim(monkeypatch):
    monkeypatch.setattr(
        GraphStore, "_embedding_dim", lambda self: TEST_EMBEDDING_DIM
    )


@pytest.fixture(autouse=True)
def _close_pools():
    """Never leak a pool into another test; an ephemeral DSN dies with its DB."""
    yield
    for dsn, pool in list(pgconn._POOLS.items()):
        try:
            pool.close()
        except Exception:
            pass
        pgconn._POOLS.pop(dsn, None)


def _ephemeral_dsn(info) -> str:
    """libpq DSN for the ephemeral pytest-postgresql database.

    Deliberately not the operator's ``POSTGRES_URI``: these tests create and
    drop graph tables, and the dev database is not theirs to rewrite.
    """
    password = f":{info.password}" if info.password else ""
    return (
        f"postgresql://{info.user}{password}@{info.host}:{info.port}/{info.dbname}"
    )


def _embedding(seed: float) -> list:
    vec = [0.0] * TEST_EMBEDDING_DIM
    vec[0] = seed
    return vec


@pytest.mark.integration
class TestGraphStoreLive:
    @pytest.fixture
    def store(self, postgresql):
        """Graph store on a fresh ephemeral database.

        Construction no longer creates tables, so the fixture calls
        ``_ensure_tables`` explicitly — exactly what ``ensure_vector_schema``
        does at boot in production — and read-before-write tests still pass.
        """
        store = GraphStore(connection_string=_ephemeral_dsn(postgresql.info))
        try:
            store._ensure_tables()
        except Exception as exc:
            pytest.skip(f"pgvector extension unavailable: {exc}")
        yield store
        store.close()

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

    def test_apply_chunk_writes_nodes_links_and_edges(self, store, source_id):
        """One transactional write: entities linked to the chunk, edges added,
        and a bare relationship endpoint upserted but not chunk-linked."""
        try:
            entities = [
                {"name": "Ada", "normalized_name": "ada", "type": "person",
                 "description": "mathematician"},
                {"name": "Engine", "normalized_name": "engine", "type": "machine",
                 "description": None},
            ]
            relationships = [
                {"source": "Ada", "target": "Engine", "type": "designed",
                 "description": "Ada designed the Engine", "weight": 2.0},
                # 'Babbage' is only an endpoint — upserted edge-only.
                {"source": "Babbage", "target": "Engine", "type": "built",
                 "description": None, "weight": 1.0},
            ]
            name_embeddings = {
                "ada": [0.1] * store._embedding_dim(),
                "engine": [0.2] * store._embedding_dim(),
                "babbage": [0.3] * store._embedding_dim(),
            }

            nodes, edges = store.apply_chunk(
                source_id, "c1", entities, relationships, name_embeddings
            )
            assert nodes == 2  # only entities are counted
            assert edges == 2

            ada = store.get_node_by_normalized(source_id, "ada")
            engine = store.get_node_by_normalized(source_id, "engine")
            babbage = store.get_node_by_normalized(source_id, "babbage")
            assert ada is not None and engine is not None
            assert babbage is not None  # endpoint upserted

            mapping = store.get_chunk_ids_for_nodes(
                source_id, [ada["id"], engine["id"], babbage["id"]]
            )
            assert mapping[ada["id"]] == ["c1"]
            assert mapping[engine["id"]] == ["c1"]
            # Bare endpoint is not linked to the chunk.
            assert babbage["id"] not in mapping
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
            assert recomputed == 1
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

    def test_count_nodes_many_batches_and_zero_fills(self, store):
        """One query for N sources; a source with no graph still gets an entry."""
        a, b, c = (str(uuid.uuid4()) for _ in range(3))
        try:
            store.upsert_node(a, "A1", "a1")
            store.upsert_node(a, "A2", "a2")
            store.upsert_node(b, "B1", "b1")

            counts = store.count_nodes_many([a, b, c])

            assert counts == {a: 2, b: 1, c: 0}
            # Agrees with the per-source query it replaces.
            assert [store.count_nodes(s) for s in (a, b, c)] == [2, 1, 0]
            assert store.count_nodes_many([]) == {}
        finally:
            store.delete_by_source(a)
            store.delete_by_source(b)

    def test_pooled_connection_is_returned_to_the_shared_pool(self, store):
        """The live store borrows from the shared pool and gives the socket back."""
        source_id = str(uuid.uuid4())
        assert store.count_nodes_many([source_id]) == {source_id: 0}
        assert store._pooled is True
        assert list(pgconn._POOLS) == [store._connection_string]

        pool = pgconn._POOLS[store._connection_string]
        store.close()

        assert store._connection is None
        stats = pool.get_stats()
        assert stats["pool_available"] == stats["pool_size"]

    def test_the_vector_store_reuses_the_graph_store_pool(self, store, postgresql):
        """Same DSN, one pool: the graph store does not double the connections."""
        from application.vectorstore.pgvector import PGVectorStore

        stub = MagicMock()
        stub.dimension = TEST_EMBEDDING_DIM
        stub.embed_query.return_value = [0.0] * TEST_EMBEDDING_DIM
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=stub,
        ):
            vector_store = PGVectorStore(
                source_id="live-source", connection_string=store._connection_string
            )
        try:
            store.count_nodes_many([str(uuid.uuid4())])
            vector_store._get_connection()

            assert list(pgconn._POOLS) == [store._connection_string]
            assert vector_store._pooled is True
        finally:
            vector_store.close()

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
        # Boot owns the schema; the write-path safety net has its own tests.
        store._tables_ensured = True
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

        monkeypatch.setattr(base_module.settings, "EMBEDDINGS_BASE_URL", None)
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

    def test_none_dimension_falls_back_to_default(self, monkeypatch):
        """A remote model outside the registry reports ``None``, not nothing.

        ``getattr`` with a default cannot catch that -- the attribute exists --
        so the width reached the DDL as ``vector(None)``.
        """
        from application.vectorstore import base as base_module

        monkeypatch.setattr(base_module.settings, "EMBEDDINGS_BASE_URL", None)
        fake_embedding = MagicMock()
        fake_embedding.dimension = None
        monkeypatch.setattr(
            base_module.EmbeddingsSingleton,
            "get_instance",
            staticmethod(lambda *a, **k: fake_embedding),
        )
        monkeypatch.setattr(GraphStore, "_embedding_dim", _REAL_EMBEDDING_DIM)

        store = GraphStore.__new__(GraphStore)
        assert store._embedding_dim() == store_module.DEFAULT_NAME_EMBEDDING_DIM

    def test_falls_back_to_default_dimension(self, monkeypatch):
        from application.vectorstore import base as base_module

        monkeypatch.setattr(base_module.settings, "EMBEDDINGS_BASE_URL", None)
        fake_embedding = object()
        monkeypatch.setattr(
            base_module.EmbeddingsSingleton,
            "get_instance",
            staticmethod(lambda *a, **k: fake_embedding),
        )
        monkeypatch.setattr(GraphStore, "_embedding_dim", _REAL_EMBEDDING_DIM)

        store = GraphStore.__new__(GraphStore)
        assert store._embedding_dim() == store_module.DEFAULT_NAME_EMBEDDING_DIM


@pytest.mark.unit
class TestEmbeddingDimResolution:
    def test_uses_shared_resolver(self, monkeypatch):
        """The dimension probe must not build its own embeddings instance."""
        from unittest.mock import patch

        fake_embedding = MagicMock()
        fake_embedding.dimension = 1536
        monkeypatch.setattr(GraphStore, "_embedding_dim", _REAL_EMBEDDING_DIM)

        with patch(
            "application.vectorstore.base.get_embeddings",
            return_value=fake_embedding,
        ) as mock_resolver:
            store = GraphStore.__new__(GraphStore)
            assert store._embedding_dim() == 1536

        mock_resolver.assert_called_once_with()


@pytest.mark.unit
class TestGraphSchemaIsBootOwned:
    """Construction must not run DDL: reads happen once per query, per source."""

    def _mock_store(self):
        store = GraphStore.__new__(GraphStore)
        cursor = MagicMock()
        cursor.fetchone.return_value = [str(uuid.uuid4())]
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = cursor
        store._connection = conn
        store._get_connection = lambda: conn
        store._tables_ensured = False
        store._ensure_tables = MagicMock()
        return store, cursor

    def test_init_opens_no_connection_and_creates_no_tables(self):
        from unittest.mock import patch

        with patch.dict(
            "sys.modules",
            {
                "psycopg": MagicMock(),
                "pgvector": MagicMock(),
                "pgvector.psycopg": MagicMock(),
            },
        ), patch.object(GraphStore, "_ensure_tables") as ensure, patch.object(
            GraphStore, "_get_connection"
        ) as get_conn:
            store = GraphStore(connection_string="postgresql://u:p@localhost/db")

        ensure.assert_not_called()
        get_conn.assert_not_called()
        assert store._tables_ensured is False

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.upsert_node("sid", "N", "n"),
            lambda s: s.add_edge("sid", "a", "b"),
            lambda s: s.link_node_chunk("sid", "n", "c1"),
            lambda s: s.apply_chunk("sid", "c1", [], [], {}),
            lambda s: s.set_node_degrees("sid"),
            lambda s: s.mark_chunk("sid", "c1", "done"),
            lambda s: s.delete_by_source("sid"),
        ],
        ids=[
            "upsert_node",
            "add_edge",
            "link_node_chunk",
            "apply_chunk",
            "set_node_degrees",
            "mark_chunk",
            "delete_by_source",
        ],
    )
    def test_writes_ensure_tables_once(self, call):
        store, _ = self._mock_store()

        call(store)
        store._tables_ensured = True  # what the real _ensure_tables_once sets
        call(store)

        assert store._ensure_tables.call_count == 1

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.count_nodes("sid"),
            lambda s: s.count_nodes_many(["sid"]),
            lambda s: s.get_node_by_normalized("sid", "n"),
            lambda s: s.search_nodes_by_embedding("sid", _embedding(1.0)),
            lambda s: s.get_subgraph("sid", ["n"]),
            lambda s: s.get_graph_overview("sid"),
            lambda s: s.get_chunk_ids_for_nodes("sid", ["n"]),
            lambda s: s.pending_chunks("sid", ["c1"]),
            lambda s: s.get_progress("sid"),
        ],
        ids=[
            "count_nodes",
            "count_nodes_many",
            "get_node_by_normalized",
            "search_nodes_by_embedding",
            "get_subgraph",
            "get_graph_overview",
            "get_chunk_ids_for_nodes",
            "pending_chunks",
            "get_progress",
        ],
    )
    def test_reads_never_create_tables(self, call):
        store, _ = self._mock_store()

        call(store)

        store._ensure_tables.assert_not_called()

    def test_create_schema_emits_the_ddl_without_committing(self):
        conn, cursor = MagicMock(), MagicMock()
        conn.cursor.return_value = cursor

        GraphStore.create_schema(conn, dimension=8)

        statements = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "CREATE EXTENSION IF NOT EXISTS vector" in statements
        for table in (
            "graph_nodes",
            "graph_edges",
            "graph_node_chunks",
            "graph_ingest_progress",
        ):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in statements
        assert "name_embedding vector(8)" in statements
        assert statements.count("CREATE INDEX IF NOT EXISTS") == 5
        conn.commit.assert_not_called()

    def test_ensure_tables_locks_then_commits(self):
        store, cursor = self._mock_store()
        del store._ensure_tables  # exercise the real method

        store._ensure_tables()

        statements = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "pg_advisory_xact_lock" in statements
        assert "CREATE TABLE IF NOT EXISTS graph_nodes" in statements
        store._connection.commit.assert_called_once()


@pytest.mark.unit
class TestGraphStorePooling:
    """The graph store borrows from the same per-DSN pool as ``PGVectorStore``."""

    def _store(self, dsn=POOL_DSN, pool_max_size=4):
        store = GraphStore.__new__(GraphStore)
        store._connection_string = dsn
        store._connection = None
        store._pooled = False
        store._pool_max_size = pool_max_size
        store._psycopg = MagicMock()
        store._register_vector = MagicMock()
        store._tables_ensured = True
        return store

    def _fake_pool(self):
        pooled_conn = MagicMock()
        pooled_conn.closed = False
        pool = MagicMock()
        pool.getconn.return_value = pooled_conn
        return pool, pooled_conn

    def test_get_connection_checks_out_of_the_pool(self, monkeypatch):
        pool, pooled_conn = self._fake_pool()
        monkeypatch.setattr(store_module.pgconn, "pool_for", lambda dsn, n: pool)
        store = self._store()

        conn = store._get_connection()

        assert conn is pooled_conn
        assert store._pooled is True
        pool.getconn.assert_called_once()
        store._psycopg.connect.assert_not_called()
        # The pool's ``configure`` hook already registered the adapters.
        store._register_vector.assert_not_called()

    def test_close_rolls_back_and_returns_the_connection(self, monkeypatch):
        pool, pooled_conn = self._fake_pool()
        monkeypatch.setattr(store_module.pgconn, "pool_for", lambda dsn, n: pool)
        monkeypatch.setitem(pgconn._POOLS, POOL_DSN, pool)
        store = self._store()
        store._get_connection()
        pooled_conn.info.transaction_status.name = "INTRANS"

        store.close()

        pooled_conn.rollback.assert_called_once()
        pool.putconn.assert_called_once_with(pooled_conn)
        pooled_conn.close.assert_not_called()
        assert store._connection is None

    def test_close_does_not_roll_back_an_idle_connection(self, monkeypatch):
        pool, pooled_conn = self._fake_pool()
        monkeypatch.setattr(store_module.pgconn, "pool_for", lambda dsn, n: pool)
        monkeypatch.setitem(pgconn._POOLS, POOL_DSN, pool)
        store = self._store()
        store._get_connection()
        pooled_conn.info.transaction_status.name = "IDLE"

        store.close()

        pooled_conn.rollback.assert_not_called()
        pool.putconn.assert_called_once_with(pooled_conn)

    def test_a_dead_pooled_connection_is_returned_before_being_replaced(
        self, monkeypatch
    ):
        # Same contract as ``PGVectorStore``: a connection that dies while this
        # store holds it must go back to the pool, or the slot is lost for the
        # life of the process. Extraction holds one store across the whole
        # per-chunk LLM loop, which is exactly when a backend gets reaped.
        pool, pooled_conn = self._fake_pool()
        monkeypatch.setattr(store_module.pgconn, "pool_for", lambda dsn, n: pool)
        monkeypatch.setitem(pgconn._POOLS, POOL_DSN, pool)
        store = self._store()
        store._get_connection()
        replacement = MagicMock()
        replacement.closed = False
        pool.getconn.return_value = replacement

        pooled_conn.closed = True
        conn = store._get_connection()

        assert conn is replacement
        pool.putconn.assert_called_once_with(pooled_conn)
        assert pool.getconn.call_count == 2

    def test_legacy_path_connects_directly_and_closes(self, monkeypatch):
        def _never(dsn, n):
            raise AssertionError("pooling is off; no pool must be built")

        monkeypatch.setattr(store_module.pgconn, "pool_for", _never)
        store = self._store(pool_max_size=0)
        direct = MagicMock()
        direct.closed = False
        store._psycopg.connect.return_value = direct

        conn = store._get_connection()

        assert conn is direct
        assert store._pooled is False
        store._register_vector.assert_called_once_with(direct)

        store.close()
        direct.close.assert_called_once()

    def test_del_never_raises(self):
        store = self._store()
        broken = MagicMock()
        broken.closed = False
        broken.close.side_effect = RuntimeError("already gone")
        store._connection = broken

        store.__del__()  # must not propagate

    def test_the_graph_store_and_the_vector_store_share_one_pool(self):
        """One DSN, one pool object — reached from either module."""
        pool, _ = self._fake_pool()
        store = self._store()

        with patch("psycopg_pool.ConnectionPool", return_value=pool) as pool_cls:
            store._get_connection()
            # ``PGVectorStore``'s own entry point resolves to the same object.
            assert pgvector_module._pool_for(POOL_DSN, 4) is pool

        assert pool_cls.call_count == 1
        assert pgconn._POOLS[POOL_DSN] is pool
        assert pgvector_module._POOLS is pgconn._POOLS

    @pytest.mark.parametrize(
        "value,expected",
        [(0, 0), (2, 2), (None, 8), ("4", 8), (True, 8), (-1, 8)],
    )
    def test_pool_size_is_resolved_defensively(self, monkeypatch, value, expected):
        monkeypatch.setattr(
            store_module.settings, "PGVECTOR_POOL_MAX_SIZE", value, raising=False
        )
        assert store_module._resolve_pool_max_size() == expected


@pytest.mark.unit
class TestCountNodesMany:
    """One ``ANY(%s)`` query replaces the retriever's per-source count fan-out."""

    def _store_with_mock_conn(self, rows):
        store = GraphStore.__new__(GraphStore)
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        conn = MagicMock()
        conn.cursor.return_value = cursor
        store._connection = conn
        store._get_connection = lambda: conn
        store._tables_ensured = True
        return store, cursor, conn

    def test_binds_the_ids_as_one_array_and_zero_fills(self):
        store, cursor, _ = self._store_with_mock_conn([("a", 2), ("b", 1)])

        counts = store.count_nodes_many(["a", "b", "c"])

        assert counts == {"a": 2, "b": 1, "c": 0}
        sql, params = (
            cursor.execute.call_args.args[0],
            cursor.execute.call_args.args[1],
        )
        assert "source_id = ANY(%s)" in sql
        assert "GROUP BY source_id" in sql
        assert cursor.execute.call_count == 1
        assert params == (["a", "b", "c"],)

    def test_empty_input_short_circuits(self):
        store, cursor, _ = self._store_with_mock_conn([])

        assert store.count_nodes_many([]) == {}
        assert store.count_nodes_many([None, ""]) == {}
        cursor.execute.assert_not_called()

    def test_a_failed_query_reports_every_source_as_graphless(self):
        store, cursor, conn = self._store_with_mock_conn([])
        cursor.execute.side_effect = RuntimeError("no such table")

        assert store.count_nodes_many(["a", "b"]) == {"a": 0, "b": 0}
        conn.rollback.assert_called_once()

    def test_the_callers_id_spelling_is_preserved(self):
        """Postgres returns canonical lowercase UUID text; keys must still match."""
        source_id = str(uuid.uuid4()).upper()
        store, _, _ = self._store_with_mock_conn([(source_id.lower(), 3)])

        assert store.count_nodes_many([source_id]) == {source_id: 3}
