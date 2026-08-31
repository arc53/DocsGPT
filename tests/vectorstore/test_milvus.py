"""MilvusStore tests, run against a real Milvus Lite database.

pymilvus is a first-party dependency now that the store no longer goes through
langchain, so these drive a real local Milvus (a file under ``tmp_path``)
rather than asserting against mocks.
"""

import os
from unittest.mock import patch

import pytest

pytest.importorskip("milvus_lite", reason="Milvus Lite is not available on this platform")


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


@pytest.fixture
def store(tmp_path):
    from application.vectorstore.milvus import MilvusStore

    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings",
        return_value=_FakeEmbeddings(),
    ), patch("application.vectorstore.milvus.settings") as mock_settings:
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.MILVUS_COLLECTION_NAME = "test_collection"
        mock_settings.MILVUS_URI = str(tmp_path / "milvus.db")
        mock_settings.MILVUS_TOKEN = ""
        yield MilvusStore(source_id="src-A", embeddings_key="k")


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
class TestMilvusStore:
    def test_source_id_stored(self, store):
        assert store._source_id == "src-A"

    def test_filter_expression_scopes_to_source(self, store):
        assert store._filter == 'source_id == "src-A"'

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

    def test_search_honours_score_threshold(self, populated):
        assert populated.search_with_scores("Paris", k=3, score_threshold=0.99)
        assert not populated.search_with_scores("Paris", k=3, score_threshold=1.01)

    def test_get_chunks_returns_all(self, populated):
        chunks = populated.get_chunks()
        assert len(chunks) == 3
        assert {c["metadata"]["source"] for c in chunks} == {
            "geo.txt", "db.txt", "queue.txt"
        }

    def test_add_texts_stamps_source_id(self, populated):
        assert all(c["metadata"]["source_id"] == "src-A" for c in populated.get_chunks())

    def test_add_and_delete_chunk(self, populated):
        chunk_id = populated.add_chunk("Redis caches things.", {"source": "cache.txt"})
        assert len(populated.get_chunks()) == 4
        assert populated.delete_chunk(chunk_id) is True
        assert len(populated.get_chunks()) == 3

    def test_delete_chunks_by_source_path(self, populated):
        assert populated.delete_chunks_by_source_path("db.txt") == 1
        assert len(populated.get_chunks()) == 2

    def test_delete_index_removes_only_this_source(self, populated):
        from application.vectorstore.milvus import MilvusStore

        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=_FakeEmbeddings(),
        ), patch("application.vectorstore.milvus.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = "test_model"
            mock_settings.MILVUS_COLLECTION_NAME = "test_collection"
            mock_settings.MILVUS_URI = ":memory:"
            mock_settings.MILVUS_TOKEN = ""
            other = MilvusStore.__new__(MilvusStore)
        # Share the open Milvus Lite handle: one file, two logical sources.
        other._client = populated._client
        other._collection = populated._collection
        other._source_id = "src-B"
        other._embeddings = _FakeEmbeddings()
        other.add_texts(["Another source entirely."], [{"source": "other.txt"}])

        populated.delete_index()

        assert populated.get_chunks() == []
        assert len(other.get_chunks()) == 1

    def test_get_chunks_returns_empty_when_client_raises(self, populated):
        with patch.object(
            populated._client, "query", side_effect=RuntimeError("milvus down")
        ):
            assert populated.get_chunks() == []

    def test_save_local_is_noop(self, store):
        assert store.save_local() is None


@pytest.mark.unit
class TestMilvusUriEnvGuard:
    """pymilvus reads MILVUS_URI at import and rejects non-http values.

    DocsGPT's setting of the same name defaults to a Milvus Lite file path, so
    the import must be shielded from it and the value restored afterwards.
    """

    def test_env_var_hidden_during_import_and_restored(self):
        from application.vectorstore.milvus import _without_milvus_uri_env

        with patch.dict(os.environ, {"MILVUS_URI": "./milvus_local.db"}):
            with _without_milvus_uri_env():
                assert "MILVUS_URI" not in os.environ
            assert os.environ["MILVUS_URI"] == "./milvus_local.db"

    def test_absent_env_var_stays_absent(self):
        from application.vectorstore.milvus import _without_milvus_uri_env

        env = {k: v for k, v in os.environ.items() if k != "MILVUS_URI"}
        with patch.dict(os.environ, env, clear=True):
            with _without_milvus_uri_env():
                assert "MILVUS_URI" not in os.environ
            assert "MILVUS_URI" not in os.environ
