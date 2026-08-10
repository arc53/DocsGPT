"""QdrantStore tests, run against a real in-process Qdrant.

qdrant-client is a first-party dependency now that the store no longer goes
through langchain, so these exercise the real client in ``:memory:`` mode
rather than asserting against mocks.
"""

from unittest.mock import patch

import pytest


class _FakeEmbeddings:
    """Deterministic 3-dim embeddings: distinct texts get distinct directions."""

    dimension = 3

    _VECTORS = {
        "paris": [1.0, 0.0, 0.0],
        "database": [0.0, 1.0, 0.0],
        "celery": [0.0, 0.0, 1.0],
    }

    def _vector(self, text):
        lowered = (text or "").lower()
        for keyword, vector in self._VECTORS.items():
            if keyword in lowered:
                return vector
        return [0.577, 0.577, 0.577]

    def embed_query(self, query):
        return self._vector(query)

    def embed_documents(self, documents):
        return [self._vector(d) for d in documents]


def _settings(mock_settings, collection="test_collection"):
    mock_settings.EMBEDDINGS_NAME = "test_model"
    mock_settings.QDRANT_COLLECTION_NAME = collection
    mock_settings.QDRANT_LOCATION = ":memory:"
    mock_settings.QDRANT_DISTANCE_FUNC = "Cosine"
    mock_settings.QDRANT_PREFER_GRPC = False
    mock_settings.QDRANT_GRPC_PORT = 6334
    for unset in (
        "QDRANT_URL", "QDRANT_HOST", "QDRANT_PORT", "QDRANT_HTTPS",
        "QDRANT_API_KEY", "QDRANT_PREFIX", "QDRANT_TIMEOUT", "QDRANT_PATH",
    ):
        setattr(mock_settings, unset, None)


@pytest.fixture
def store():
    from application.vectorstore.qdrant import QdrantStore

    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings",
        return_value=_FakeEmbeddings(),
    ), patch("application.vectorstore.qdrant.settings") as mock_settings:
        _settings(mock_settings)
        yield QdrantStore(source_id="src-A", embeddings_key="k")


@pytest.fixture
def populated(store):
    store.add_texts(
        ["The capital of France is Paris.",
         "Postgres is a relational database.",
         "Celery runs background tasks."],
        [{"source": "geo.txt"}, {"source": "db.txt"}, {"source": "queue.txt"}],
    )
    return store


@pytest.mark.unit
class TestQdrantStore:
    def test_source_id_strips_index_prefix(self, store):
        assert store._source_id == "src-A"

    def test_add_texts_returns_one_id_per_text(self, store):
        ids = store.add_texts(["a", "b"], [{}, {}])
        assert len(ids) == 2 and len(set(ids)) == 2

    def test_add_texts_empty_is_noop(self, store):
        assert store.add_texts([], []) == []

    def test_search_ranks_by_similarity(self, populated):
        hits = populated.search("Tell me about Paris", k=2)
        assert "Paris" in str(hits[0])
        assert hits[0].metadata["source"] == "geo.txt"

    def test_search_with_scores_reports_cosine(self, populated):
        scored = populated.search_with_scores("Tell me about Paris", k=3)
        assert populated.score_kind == "cosine_similarity"
        assert scored[0][1] == pytest.approx(1.0, abs=1e-3)
        # Scores must come back in descending rank order.
        assert [s for _, s in scored] == sorted(
            (s for _, s in scored), reverse=True
        )

    def test_search_honours_score_threshold(self, populated):
        assert populated.search_with_scores("Paris", k=3, score_threshold=0.99)
        assert not populated.search_with_scores("Paris", k=3, score_threshold=1.01)

    def test_add_texts_stamps_source_id(self, populated):
        assert all(c["metadata"]["source_id"] == "src-A" for c in populated.get_chunks())

    def test_get_chunks_returns_all(self, populated):
        chunks = populated.get_chunks()
        assert len(chunks) == 3
        assert {c["metadata"]["source"] for c in chunks} == {
            "geo.txt", "db.txt", "queue.txt"
        }

    def test_add_and_delete_chunk(self, populated):
        chunk_id = populated.add_chunk("Redis caches things.", {"source": "cache.txt"})
        assert len(populated.get_chunks()) == 4
        assert populated.delete_chunk(chunk_id) is True
        assert len(populated.get_chunks()) == 3

    def test_delete_chunk_returns_false_when_client_raises(self, populated):
        with patch.object(
            populated._client, "delete", side_effect=RuntimeError("qdrant down")
        ):
            assert populated.delete_chunk("some-id") is False

    def test_get_chunks_returns_empty_when_client_raises(self, populated):
        with patch.object(
            populated._client, "scroll", side_effect=RuntimeError("qdrant down")
        ):
            assert populated.get_chunks() == []

    def test_delete_chunks_by_source_path(self, populated):
        assert populated.delete_chunks_by_source_path("db.txt") == 1
        assert len(populated.get_chunks()) == 2

    def test_delete_index_removes_only_this_source(self, populated):
        from application.vectorstore.qdrant import QdrantStore

        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=_FakeEmbeddings(),
        ), patch("application.vectorstore.qdrant.settings") as mock_settings:
            _settings(mock_settings)
            other = QdrantStore(source_id="src-B", embeddings_key="k")
        # Share the in-memory backend so both sources live in one collection.
        other._client = populated._client
        other.add_texts(["Another source entirely."], [{"source": "other.txt"}])

        populated.delete_index()

        assert populated.get_chunks() == []
        assert len(other.get_chunks()) == 1

    def test_save_local_is_noop(self, store):
        assert store.save_local() is None


@pytest.mark.unit
class TestQdrantClientKwargs:
    def test_unset_settings_are_omitted(self):
        from application.vectorstore.qdrant import QdrantStore

        with patch("application.vectorstore.qdrant.settings") as mock_settings:
            _settings(mock_settings)
            kwargs = QdrantStore._client_kwargs()
        # location/url/path are mutually exclusive in qdrant-client, so only
        # the configured one may be forwarded.
        assert kwargs["location"] == ":memory:"
        assert "url" not in kwargs and "path" not in kwargs and "host" not in kwargs

    def test_configured_settings_are_forwarded(self):
        from application.vectorstore.qdrant import QdrantStore

        with patch("application.vectorstore.qdrant.settings") as mock_settings:
            _settings(mock_settings)
            mock_settings.QDRANT_LOCATION = None
            mock_settings.QDRANT_URL = "http://qdrant:6333"
            mock_settings.QDRANT_API_KEY = "secret"
            kwargs = QdrantStore._client_kwargs()
        assert kwargs["url"] == "http://qdrant:6333"
        assert kwargs["api_key"] == "secret"
        assert "location" not in kwargs
