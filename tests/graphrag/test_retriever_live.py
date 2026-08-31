"""Live GraphRAG retrieval: real graph store, real pool, batched classic fallback.

Runs against the ephemeral pytest-postgresql cluster (never the operator's dev
database) with an 8-dimension stub embeddings model, so the whole
``GraphRAGRetriever._get_data`` path — count batching, PPR over a real graph,
one pooled connection, one ClassicRAG call for the graphless sources — is
exercised end to end in a few seconds. Skips when the cluster's Postgres has no
pgvector build installed.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, Mock, patch

import pytest

from application.retriever.graph_rag import GraphRAGRetriever
from application.vectorstore import pgconn

pytestmark = pytest.mark.integration

STUB_DIM = 8


class _StubEmbeddings:
    """Deterministic tiny embeddings; no model download, no network."""

    dimension = STUB_DIM

    def embed_documents(self, texts):
        return [self._vector(1.0) for _ in texts]

    def embed_query(self, query):
        return self._vector(1.0)

    @staticmethod
    def _vector(seed: float):
        vector = [0.0] * STUB_DIM
        vector[0] = seed
        return vector


def _dsn(info) -> str:
    password = f":{info.password}" if info.password else ""
    return (
        f"postgresql://{info.user}{password}@{info.host}:{info.port}/{info.dbname}"
    )


@pytest.fixture(autouse=True)
def _close_pools():
    """Never leak a pool into another test; the ephemeral DSN dies with its DB."""
    yield
    for dsn, pool in list(pgconn._POOLS.items()):
        try:
            pool.close()
        except Exception:
            pass
        pgconn._POOLS.pop(dsn, None)


@pytest.fixture
def stub_embeddings():
    stub = _StubEmbeddings()
    with patch(
        "application.vectorstore.base.get_embeddings", return_value=stub
    ), patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings",
        return_value=stub,
    ), patch(
        "application.retriever.graph_rag.get_embeddings", return_value=stub
    ):
        yield stub


@pytest.fixture
def live_dsn(postgresql, monkeypatch):
    """DSN of an empty ephemeral DB with GraphRAG enabled and pooling on."""
    try:
        with postgresql.cursor() as cursor:
            cursor.execute("CREATE EXTENSION vector;")
        postgresql.commit()
    except Exception as exc:
        postgresql.rollback()
        pytest.skip(f"pgvector extension unavailable: {exc}")

    dsn = _dsn(postgresql.info)
    from application.core import settings as settings_module

    settings = settings_module.settings
    monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector", raising=False)
    monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_CONNECTION_STRING", dsn, raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_IVFFLAT_PROBES", None, raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_POOL_MAX_SIZE", 4, raising=False)
    return dsn


def _seed(dsn, graph_source_id):
    """Ingest one chunk and one graph node for ``graph_source_id``."""
    from application.graphrag.store import GraphStore
    from application.vectorstore.pgvector import PGVectorStore

    vector_store = PGVectorStore(
        source_id=graph_source_id, connection_string=dsn
    )
    try:
        chunk_ids = vector_store.add_texts(
            ["Ada Lovelace wrote the first algorithm."],
            [{"title": "Ada", "source": "/docs/ada.txt"}],
        )
    finally:
        vector_store.close()

    store = GraphStore(connection_string=dsn)
    try:
        store._ensure_tables()
        node_id = store.upsert_node(
            graph_source_id,
            "Ada Lovelace",
            "ada lovelace",
            "person",
            "A mathematician.",
            _StubEmbeddings._vector(1.0),
        )
        store.link_node_chunk(graph_source_id, node_id, chunk_ids[0])
    finally:
        store.close()
    return chunk_ids[0]


def _retriever(sources):
    with patch(
        "application.retriever.classic_rag.LLMCreator.create_llm",
        Mock(return_value=MagicMock()),
    ):
        return GraphRAGRetriever(
            source={"question": "who wrote the first algorithm?",
                    "active_docs": list(sources)},
            chat_history=None,
            prompt="",
            chunks=2,
            doc_token_limit=50000,
            model_id="test-model",
            llm_name="openai",
            api_key="fake",
            decoded_token={"sub": "user1"},
        )


class TestGraphRAGRetrieverLive:
    def test_one_pool_one_classic_batch_and_the_connection_goes_back(
        self, live_dsn, stub_embeddings
    ):
        graph_source = str(uuid.uuid4())
        graphless_source = str(uuid.uuid4())
        _seed(live_dsn, graph_source)

        rag = _retriever([graphless_source, graph_source])
        seen = []

        def _classic():
            seen.append(list(rag._classic.vectorstores))
            return [
                {
                    "title": "classic",
                    "text": "classic chunk",
                    "source": graphless_source,
                    "filename": "classic",
                }
            ]

        rag._classic._get_data = Mock(side_effect=_classic)

        docs = rag._get_data()

        # The graphless source is retrieved by exactly one ClassicRAG run.
        assert rag._classic._get_data.call_count == 1
        assert seen == [[graphless_source]]

        # The graph source came back through PPR, not the fallback.
        texts = [doc["text"] for doc in docs]
        assert texts == ["classic chunk", "Ada Lovelace wrote the first algorithm."]
        assert docs[1]["source"] == "/docs/ada.txt"

        # One pool for the DSN, shared with the vector store that seeded it,
        # and the retriever handed its connection back when it finished.
        assert list(pgconn._POOLS) == [live_dsn]
        stats = pgconn._POOLS[live_dsn].get_stats()
        assert stats["pool_size"] <= 4
        assert stats["pool_available"] == stats["pool_size"]

    def test_all_graphless_sources_take_one_classic_call(
        self, live_dsn, stub_embeddings
    ):
        from application.graphrag.store import GraphStore

        store = GraphStore(connection_string=live_dsn)
        store._ensure_tables()  # tables exist, but no source has a graph
        store.close()

        sources = [str(uuid.uuid4()) for _ in range(3)]
        rag = _retriever(sources)
        seen = []
        rag._classic._get_data = Mock(
            side_effect=lambda: seen.append(list(rag._classic.vectorstores)) or []
        )

        assert rag._get_data() == []
        assert seen == [sources]
        stats = pgconn._POOLS[live_dsn].get_stats()
        assert stats["pool_available"] == stats["pool_size"]
