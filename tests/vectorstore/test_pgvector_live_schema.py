"""Live pgvector end-to-end: boot-owned schema, pure-read queries, pooling.

Runs against the ephemeral pytest-postgresql cluster (never the operator's dev
database) with an 8-dimension stub embeddings model, so a real ``CREATE
EXTENSION vector`` / ``vector(8)`` round trip is exercised in a few seconds.
Skips when the cluster's Postgres has no pgvector build installed.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from application.storage.db.bootstrap import ensure_vector_schema
from application.vectorstore import pgvector as pgvector_module
from application.vectorstore.pgvector import PGVectorStore

pytestmark = pytest.mark.integration

STUB_DIM = 8


class _StubEmbeddings:
    """Deterministic tiny embeddings; no model download, no network."""

    dimension = STUB_DIM

    def embed_documents(self, texts):
        return [self._vector(float(i + 1)) for i, _ in enumerate(texts)]

    def embed_query(self, query):
        return self._vector(1.0)

    @staticmethod
    def _vector(seed: float):
        vector = [0.0] * STUB_DIM
        vector[0] = seed
        return vector


class _WideStubEmbeddings(_StubEmbeddings):
    dimension = 16


def _dsn(info) -> str:
    password = f":{info.password}" if info.password else ""
    return (
        f"postgresql://{info.user}{password}@{info.host}:{info.port}/{info.dbname}"
    )


def _regclass(conn, name: str):
    """Look a relation up on ``conn``, in a transaction that starts fresh.

    ``to_regclass`` takes no lock, so a negative catalog-cache entry from an
    earlier lookup in the same transaction survives another backend's DDL. A
    new transaction accepts the invalidation.
    """
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s);", (name,))
        return cursor.fetchone()[0]


@pytest.fixture(autouse=True)
def _close_pools():
    """Never leak a pool into another test; the DSN dies with the test DB."""
    yield
    for dsn, pool in list(pgvector_module._POOLS.items()):
        try:
            pool.close()
        except Exception:
            pass
        pgvector_module._POOLS.pop(dsn, None)


@pytest.fixture
def live_dsn(postgresql, monkeypatch):
    """DSN of an empty ephemeral DB, with pgvector proven installable."""
    try:
        with postgresql.cursor() as cursor:
            cursor.execute("CREATE EXTENSION vector;")
        postgresql.rollback()  # leave the database pristine for the hook
    except Exception as exc:
        postgresql.rollback()
        pytest.skip(f"pgvector extension unavailable: {exc}")

    dsn = _dsn(postgresql.info)
    from application.core import settings as settings_module

    settings = settings_module.settings
    monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector", raising=False)
    monkeypatch.setattr(
        settings, "PGVECTOR_CONNECTION_STRING", dsn, raising=False
    )
    monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_IVFFLAT_PROBES", None, raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_POOL_MAX_SIZE", 4, raising=False)
    return dsn


@pytest.fixture
def stub_embeddings():
    """Stand in for the configured model everywhere its width is read.

    ``ensure_vector_schema`` takes the width from the registry rather than by
    constructing the model, so patching only the constructors would leave the
    boot hook sizing the table from whatever EMBEDDINGS_NAME happens to be.
    """
    stub = _StubEmbeddings()
    with patch(
        "application.vectorstore.base.get_embeddings", return_value=stub
    ), patch(
        "application.vectorstore.base.build_local_embeddings", return_value=stub
    ), patch(
        "application.vectorstore.model_registry.dimension_for",
        return_value=STUB_DIM,
    ), patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings",
        return_value=stub,
    ):
        yield stub


def _store(dsn, source_id="live-source"):
    return PGVectorStore(source_id=source_id, connection_string=dsn)


class TestBootHookCreatesTheSchema:
    def test_creates_the_table_and_indexes_and_is_idempotent(
        self, live_dsn, postgresql, stub_embeddings
    ):
        ensure_vector_schema()
        ensure_vector_schema()  # second boot must be a no-op

        assert _regclass(postgresql, "documents") is not None
        with postgresql.cursor() as cursor:
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'documents';"
            )
            indexes = {row[0] for row in cursor.fetchall()}
        assert "documents_source_id_idx" in indexes
        assert "documents_text_fts_idx" in indexes
        assert PGVectorStore.table_dimension(postgresql) == STUB_DIM

    def test_mismatched_model_width_fails_loudly(self, live_dsn, stub_embeddings):
        ensure_vector_schema()

        wide = _WideStubEmbeddings()
        with patch(
            "application.vectorstore.base.get_embeddings", return_value=wide
        ), patch(
            "application.vectorstore.model_registry.dimension_for",
            return_value=wide.dimension,
        ):
            with pytest.raises(RuntimeError) as excinfo:
                ensure_vector_schema()

        message = str(excinfo.value)
        assert f"vector({STUB_DIM})" in message
        assert "16-dim" in message

    def test_creates_graph_tables_when_graphrag_is_enabled(
        self, live_dsn, postgresql, stub_embeddings, monkeypatch
    ):
        from application.core import settings as settings_module

        monkeypatch.setattr(
            settings_module.settings, "GRAPHRAG_ENABLED", True, raising=False
        )

        ensure_vector_schema()

        for table in (
            "graph_nodes",
            "graph_edges",
            "graph_node_chunks",
            "graph_ingest_progress",
        ):
            assert _regclass(postgresql, table) is not None


class TestStoreRoundTrip:
    def test_construction_is_free_and_writes_then_reads_survive(
        self, live_dsn, stub_embeddings
    ):
        ensure_vector_schema()

        store = _store(live_dsn)
        # Construction must not open a connection or build a pool: the
        # retriever makes one of these per source, per request.
        assert store._connection is None
        assert pgvector_module._POOLS == {}

        ids = store.add_texts(
            ["alpha chunk", "beta chunk"],
            [{"source": "a.txt"}, {"source": "b.txt"}],
        )
        assert len(ids) == 2

        results = store.search_with_scores("alpha", k=2)
        assert [doc.page_content for doc, _ in results] == [
            "alpha chunk",
            "beta chunk",
        ]
        assert results[0][1] == pytest.approx(1.0)

        keyword_hits = store.keyword_search("alpha", k=5)
        assert [doc.page_content for doc in keyword_hits] == ["alpha chunk"]

        # The read paths must not leave the pooled connection in a transaction.
        assert store._connection.info.transaction_status.name == "IDLE"
        store.close()
        assert store._connection is None


class TestWritePathSafetyNet:
    """A process that never ran the boot hook must still be able to ingest.

    ``register_vector`` raises when the ``vector`` type is absent, which is the
    state of a brand-new database — so the store has to tolerate that, create
    the extension, and re-register before it inserts a vector.
    """

    def test_first_write_bootstraps_a_brand_new_database(
        self, live_dsn, postgresql, stub_embeddings
    ):
        assert _regclass(postgresql, "documents") is None

        store = _store(live_dsn)
        store.add_texts(["alpha chunk"], [{"source": "a.txt"}])


        assert _regclass(postgresql, "documents") is not None
        assert [doc.page_content for doc in store.search("alpha", k=2)] == [
            "alpha chunk"
        ]
        store.close()


class TestPooling:
    def test_concurrent_stores_share_one_pool_and_return_connections(
        self, live_dsn, stub_embeddings
    ):
        ensure_vector_schema()
        seed = _store(live_dsn)
        seed.add_texts(["alpha chunk"], [{"source": "a.txt"}])
        seed.close()

        errors: list[Exception] = []
        hits: list[int] = []

        def _search():
            store = _store(live_dsn)
            try:
                hits.append(len(store.search("alpha", k=2)))
            except Exception as exc:  # surfaced below
                errors.append(exc)
            finally:
                store.close()

        threads = [threading.Thread(target=_search) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert errors == []
        assert hits == [1, 1]
        assert list(pgvector_module._POOLS) == [live_dsn]
        stats = pgvector_module._POOLS[live_dsn].get_stats()
        assert stats["pool_size"] <= 4
        assert stats["pool_available"] == stats["pool_size"]
