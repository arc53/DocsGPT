"""FaissStore tests, run against a real FAISS index and real local storage.

The store no longer wraps langchain, so these drive the actual index rather
than asserting that calls were forwarded to a mock.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.storage.local import LocalStorage
from docsgpt.vectorstore.faiss import FaissStore


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
        return [0.5, 0.5, 0.5]

    def embed_query(self, query):
        return self._vector(query)

    def embed_documents(self, documents):
        return [self._vector(d) for d in documents]


class _SeedDoc:
    def __init__(self, page_content, metadata):
        self.page_content = page_content
        self.metadata = metadata


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


@pytest.fixture
def make_store(storage):
    from docsgpt.vectorstore.faiss import FaissStore

    def _make(source_id="src", docs_init=None):
        with patch(
            "docsgpt.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=_FakeEmbeddings(),
        ), patch(
            "docsgpt.vectorstore.faiss.StorageCreator.get_storage",
            return_value=storage,
        ), patch("docsgpt.vectorstore.faiss.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = "test_model"
            return FaissStore(source_id, "key", docs_init=docs_init)

    return _make


@pytest.fixture
def populated(make_store):
    store = make_store(
        docs_init=[
            _SeedDoc("The capital of France is Paris.", {"source": "geo.txt"}),
            _SeedDoc("Postgres is a relational database.", {"source": "db.txt"}),
            _SeedDoc("Celery runs background tasks.", {"source": "queue.txt"}),
        ]
    )
    store.save_local()
    return store


@pytest.mark.unit
class TestFaissStore:
    def test_build_from_documents(self, populated):
        assert populated.index.ntotal == 3
        assert len(populated.get_chunks()) == 3

    def test_search_ranks_by_similarity(self, populated):
        hits = populated.search("Tell me about Paris", k=2)
        assert "Paris" in str(hits[0])
        assert hits[0].metadata["source"] == "geo.txt"

    def test_search_with_scores_reports_l2(self, populated):
        scored = populated.search_with_scores("Tell me about Paris", k=3)
        assert populated.score_kind == "l2_distance"
        # L2 is lower-is-better, so the ranking must be ascending.
        assert [s for _, s in scored] == sorted(s for _, s in scored)
        assert scored[0][1] == pytest.approx(0.0, abs=1e-4)

    def test_search_drops_score_threshold(self, populated):
        """FAISS has no threshold knob; the kwarg must be ignored, not raise."""
        assert populated.search("Paris", k=1, score_threshold=0.9)

    def test_search_on_empty_index_returns_empty(self, make_store):
        store = make_store(docs_init=[_SeedDoc("only doc", {})])
        store.delete_index()
        assert store.search("anything") == []

    def test_add_texts_appends(self, populated):
        ids = populated.add_texts(["Redis caches things."], [{"source": "cache.txt"}])
        assert len(ids) == 1
        assert populated.index.ntotal == 4
        assert len(populated.get_chunks()) == 4

    def test_add_texts_empty_is_noop(self, populated):
        assert populated.add_texts([], []) == []
        assert populated.index.ntotal == 3

    def test_add_and_delete_chunk_roundtrip(self, populated):
        chunk_id = populated.add_chunk("Redis caches things.", {"source": "cache.txt"})
        assert len(populated.get_chunks()) == 4
        populated.delete_chunk(chunk_id)
        assert len(populated.get_chunks()) == 3
        assert populated.index.ntotal == 3
        # The index must stay searchable after a removal renumbers the mapping.
        assert populated.search("Paris", k=1)

    def test_delete_index_with_unknown_id_raises(self, populated):
        with pytest.raises(ValueError, match="not found in index"):
            populated.delete_index(["nope"])

    def test_delete_index_without_ids_clears(self, populated):
        populated.delete_index()
        assert populated.get_chunks() == []
        assert populated.index.ntotal == 0

    def test_get_chunks_shape(self, populated):
        chunk = populated.get_chunks()[0]
        assert set(chunk) == {"doc_id", "text", "metadata"}


@pytest.mark.unit
class TestFaissPersistence:
    def test_save_writes_both_sidecars(self, populated, storage, tmp_path):
        for name in ("index.faiss", "index.json", "index.pkl"):
            assert storage.file_exists(f"indexes/src/{name}"), name

    def test_reload_prefers_json_sidecar(self, populated, make_store, storage):
        reloaded = make_store()
        assert len(reloaded.get_chunks()) == 3
        assert reloaded.index.ntotal == 3
        assert "Paris" in str(reloaded.search("Paris", k=1)[0])

    def test_reload_falls_back_to_legacy_pickle(self, populated, make_store, storage, tmp_path):
        (tmp_path / "indexes" / "src" / "index.json").unlink()
        reloaded = make_store()
        assert len(reloaded.get_chunks()) == 3
        assert "Paris" in str(reloaded.search("Paris", k=1)[0])

    def test_missing_index_raises(self, make_store):
        with pytest.raises(Exception, match="Error loading FAISS index"):
            make_store(source_id="never-written")

    def test_save_local_writes_to_path(self, populated, tmp_path):
        target = tmp_path / "exported"
        populated.save_local(str(target))
        assert {p.name for p in target.iterdir()} == {
            "index.faiss", "index.json", "index.pkl"
        }

    def test_json_sidecar_is_readable_json(self, populated, tmp_path):
        payload = json.loads((tmp_path / "indexes" / "src" / "index.json").read_text())
        assert payload["version"] == 1
        assert len(payload["documents"]) == 3
        assert len(payload["index_to_docstore_id"]) == 3


@pytest.mark.unit
class TestFaissStoreAssertEmbeddingDimensions:
    def test_dimension_mismatch_raises(self, populated):
        with patch("docsgpt.vectorstore.faiss.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = (
                "huggingface_sentence-transformers/all-mpnet-base-v2"
            )
            with pytest.raises(ValueError, match="Embedding dimension mismatch"):
                populated.assert_embedding_dimensions(Mock(dimension=768))

    def test_unknown_dimension_defers_rather_than_raising(self, populated):
        """A remote model reports no width until its first call.

        Refusing to open the index in that window would break startup for a
        perfectly valid remote configuration, so an unknown width is deferred,
        not treated as a mismatch.
        """
        with patch("docsgpt.vectorstore.faiss.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = (
                "huggingface_sentence-transformers/all-mpnet-base-v2"
            )
            embeddings = Mock()
            embeddings.dimension = None
            assert populated.assert_embedding_dimensions(embeddings) is None

    def test_dimension_match_passes(self, populated):
        with patch("docsgpt.vectorstore.faiss.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = (
                "huggingface_sentence-transformers/all-mpnet-base-v2"
            )
            assert populated.assert_embedding_dimensions(Mock(dimension=3)) is None

    def test_mismatch_is_caught_for_every_model_not_just_mpnet(self, populated):
        """The check used to run only when EMBEDDINGS_NAME was mpnet.

        That skipped exactly the case it exists for: an index built with one
        model being opened under a different one.
        """
        with patch("docsgpt.vectorstore.faiss.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = "openai_text-embedding-ada-002"
            with pytest.raises(ValueError, match="Embedding dimension mismatch"):
                populated.assert_embedding_dimensions(Mock(dimension=1536))

    def test_mismatch_message_points_at_the_reembed_script(self, populated):
        with patch("docsgpt.vectorstore.faiss.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = "granite-311m"
            with pytest.raises(ValueError, match="docsgpt.scripts.reembed"):
                populated.assert_embedding_dimensions(Mock(dimension=768))


@pytest.mark.unit
class TestGetVectorstore:
    def test_empty_path_returns_base(self):
        from docsgpt.vectorstore.faiss import get_vectorstore

        assert get_vectorstore("") == "indexes"

    def test_normal_path(self):
        from docsgpt.vectorstore.faiss import get_vectorstore

        assert get_vectorstore("abc") == "indexes/abc"

    @pytest.mark.parametrize("bad", ["../etc", "..\\etc", "a/../../b"])
    def test_traversal_rejected(self, bad):
        from docsgpt.vectorstore.faiss import get_vectorstore

        with pytest.raises(ValueError, match="Invalid source_id path"):
            get_vectorstore(bad)


class TestBuildFromDocumentsBatching:
    """The full rebuild path: honour caller ids and embed in batches."""

    def _docs(self, n):
        return [
            SimpleNamespace(page_content=f"chunk {i}", metadata={"i": i})
            for i in range(n)
        ]

    def _store(self, embed):
        store = FaissStore.__new__(FaissStore)
        store.embeddings = MagicMock()
        store.embeddings.embed_documents.side_effect = embed
        store.documents = {}
        store.index_to_docstore_id = {}
        store.index = None
        return store

    def test_supplied_ids_are_used(self):
        store = self._store(lambda texts: [[float(len(texts))] * 2 for _ in texts])
        store._build_from_documents(self._docs(3), ids=["a", "b", "c"])
        assert list(store.documents) == ["a", "b", "c"]

    def test_embedding_is_split_into_batches(self):
        sizes = []

        def embed(texts):
            sizes.append(len(texts))
            return [[1.0, 2.0] for _ in texts]

        store = self._store(embed)
        store._build_from_documents(self._docs(5), batch_size=2)
        assert sizes == [2, 2, 1]
        assert len(store.index_to_docstore_id) == 5

    def test_embedding_override_preserves_full_stored_text(self):
        embedded = []

        def embed(texts):
            embedded.extend(texts)
            return [[1.0, 2.0] for _ in texts]

        store = self._store(embed)
        docs = [_SeedDoc("full legacy chunk text", {"source": "legacy"})]
        store._build_from_documents(docs, embedding_texts=["bounded prefix"])

        assert embedded == ["bounded prefix"]
        assert store.get_chunks()[0]["text"] == "full legacy chunk text"

    def test_embedding_override_must_match_document_count(self):
        store = self._store(lambda texts: [[1.0, 2.0] for _ in texts])
        with pytest.raises(ValueError, match="must match docs_init length"):
            store._build_from_documents(self._docs(2), embedding_texts=["one"])

    def test_defaults_are_unchanged(self):
        store = self._store(lambda texts: [[1.0, 2.0] for _ in texts])
        store._build_from_documents(self._docs(3))
        assert len(store.documents) == 3
        assert all(len(k) == 36 for k in store.documents), "uuid4 ids by default"


def _assert_rows_match_documents(store):
    """Every FAISS row must hold the embedding of the chunk it maps to."""
    import numpy as np

    embeddings = _FakeEmbeddings()
    assert store.index.ntotal == len(store.documents) == len(store.index_to_docstore_id)
    assert sorted(store.index_to_docstore_id) == list(range(store.index.ntotal))
    for row, doc_id in store.index_to_docstore_id.items():
        expected = embeddings.embed_documents([store.documents[doc_id]["page_content"]])[0]
        assert np.allclose(store.index.reconstruct(row), expected), (row, doc_id)


@pytest.mark.unit
class TestFaissUpdateChunk:
    def test_keeps_id_and_position(self, populated):
        before = [c["doc_id"] for c in populated.get_chunks()]
        target = before[1]

        returned = populated.update_chunk(target, "Redis caches things.", {"source": "cache.txt"})

        assert returned == target
        chunks = populated.get_chunks()
        assert [c["doc_id"] for c in chunks] == before
        assert chunks[1]["text"] == "Redis caches things."
        assert chunks[1]["metadata"] == {"source": "cache.txt"}
        assert populated.documents[target] == {
            "page_content": "Redis caches things.",
            "metadata": {"source": "cache.txt"},
        }

    def test_replaces_the_vector_and_keeps_rows_consistent(self, populated):
        target = populated.get_chunks()[0]["doc_id"]

        populated.update_chunk(target, "Redis caches things.", {})

        _assert_rows_match_documents(populated)
        # The old "Paris" vector is gone and the neutral query finds the edit.
        assert "Paris" not in str(populated.search("Paris", k=1)[0])
        assert "Redis" in str(populated.search("something neutral", k=1)[0])

    def test_saves_once(self, populated):
        target = populated.get_chunks()[0]["doc_id"]
        with patch.object(populated, "_save_to_storage") as save:
            populated.update_chunk(target, "Redis caches things.", {})
        save.assert_called_once()

    def test_embedding_failure_leaves_the_chunk_untouched(self, populated):
        chunks_before = populated.get_chunks()
        mapping_before = dict(populated.index_to_docstore_id)
        target = chunks_before[1]["doc_id"]

        with patch.object(
            populated.embeddings, "embed_documents", side_effect=RuntimeError("embed down")
        ), patch.object(populated, "_save_to_storage") as save:
            with pytest.raises(RuntimeError):
                populated.update_chunk(target, "Redis caches things.", {})

        assert populated.get_chunks() == chunks_before
        assert populated.index_to_docstore_id == mapping_before
        assert populated.index.ntotal == 3
        save.assert_not_called()

    def test_unknown_id_raises(self, populated):
        with pytest.raises(KeyError):
            populated.update_chunk("nope", "text", {})
        assert populated.index.ntotal == 3

    @pytest.mark.parametrize("sidecar", ["json", "pickle"])
    def test_survives_save_and_reload(self, populated, make_store, tmp_path, sidecar):
        before = [c["doc_id"] for c in populated.get_chunks()]
        target = before[1]
        populated.update_chunk(target, "Redis caches things.", {"source": "cache.txt"})

        if sidecar == "pickle":
            (tmp_path / "indexes" / "src" / "index.json").unlink()
        reloaded = make_store()

        chunks = reloaded.get_chunks()
        assert [c["doc_id"] for c in chunks] == before
        assert chunks[1]["text"] == "Redis caches things."
        assert chunks[1]["metadata"] == {"source": "cache.txt"}
        _assert_rows_match_documents(reloaded)
        assert "Redis" in str(reloaded.search("something neutral", k=1)[0])
