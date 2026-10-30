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


def _seed_docs():
    return [
        _SeedDoc("The capital of France is Paris.", {"source": "geo.txt"}),
        _SeedDoc("Postgres is a relational database.", {"source": "db.txt"}),
        _SeedDoc("Celery runs background tasks.", {"source": "queue.txt"}),
    ]


@pytest.fixture
def make_store(storage):
    """Opens (or with ``docs_init`` builds) a store on ``on``, the ``storage`` fixture by default."""

    def _make(on=None, source_id="src", docs_init=None):
        with patch(
            "docsgpt.vectorstore.base.BaseVectorStore._get_embeddings", return_value=_FakeEmbeddings(),
        ), patch(
            "docsgpt.vectorstore.faiss.StorageCreator.get_storage", return_value=on or storage,
        ), patch("docsgpt.vectorstore.faiss.settings") as mock_settings:
            mock_settings.EMBEDDINGS_NAME = "test_model"
            return FaissStore(source_id, "key", docs_init=docs_init)

    return _make


@pytest.fixture
def populated(make_store):
    store = make_store(docs_init=_seed_docs())
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

    def test_add_chunk_keeps_its_own_source_id(self, populated):
        # metadata comes from the chunk API: it must not claim another source, as the other stores ensure
        chunk_id = populated.add_chunk("Redis caches things.", {"source": "cache.txt", "source_id": "other"})
        assert populated.documents[chunk_id]["metadata"] == {"source": "cache.txt", "source_id": "src"}

    def test_delete_chunk_with_unknown_id_is_false(self, populated):
        with patch.object(populated, "_save_to_storage") as save:
            assert populated.delete_chunk("nope") is False
        save.assert_not_called()
        assert len(populated.get_chunks()) == 3

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
        assert chunks[1]["metadata"] == {"source": "cache.txt", "source_id": "src"}
        assert populated.documents[target] == {
            "page_content": "Redis caches things.",
            "metadata": {"source": "cache.txt", "source_id": "src"},
        }

    def test_keeps_its_own_source_id(self, make_store):
        store = make_store(source_id="docsgpt/indexes/src/", docs_init=[_SeedDoc("Paris.", {"source": "geo.txt"})])
        target = store.get_chunks()[0]["doc_id"]

        store.update_chunk(target, "Redis caches things.", {"source": "cache.txt", "source_id": "other"})

        assert store.documents[target]["metadata"] == {"source": "cache.txt", "source_id": "src"}

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
        assert chunks[1]["metadata"] == {"source": "cache.txt", "source_id": "src"}
        _assert_rows_match_documents(reloaded)
        assert "Redis" in str(reloaded.search("something neutral", k=1)[0])


@pytest.mark.unit
class TestFaissDeleteChunks:
    def test_deletes_several_chunks_with_one_save(self, populated):
        ids = {c["metadata"]["source"]: c["doc_id"] for c in populated.get_chunks()}
        with patch.object(populated, "_save_to_storage") as save:
            deleted = populated.delete_chunks([ids["geo.txt"], ids["db.txt"], "missing"])

        assert deleted == 2
        save.assert_called_once()
        assert [c["metadata"]["source"] for c in populated.get_chunks()] == ["queue.txt"]
        _assert_rows_match_documents(populated)

    def test_nothing_to_delete_saves_nothing(self, populated):
        with patch.object(populated, "_save_to_storage") as save:
            assert populated.delete_chunks(["missing"]) == 0
        save.assert_not_called()

    def test_delete_by_source_path_saves_once(self, populated):
        populated.add_chunk("More geography.", {"source": "geo.txt"})
        with patch.object(populated, "_save_to_storage") as save:
            assert populated.delete_chunks_by_source_path("geo.txt") == 2
        save.assert_called_once()


@pytest.mark.unit
class TestFaissAddChunks:
    def test_adds_several_chunks_with_one_save(self, populated):
        with patch.object(populated, "_save_to_storage") as save:
            ids = populated.add_chunks(
                ["Redis caches things.", "Kafka streams things."],
                [{"source": "cache.txt"}, {"source": "stream.txt", "source_id": "other"}],
            )

        save.assert_called_once()
        assert len(ids) == 2
        stored = {c["doc_id"]: c["metadata"] for c in populated.get_chunks()}
        assert stored[ids[0]]["source"] == "cache.txt"
        # Each keeps this index's source, as add_chunk does.
        assert stored[ids[1]]["source_id"] != "other"
        _assert_rows_match_documents(populated)

    def test_nothing_to_add_saves_nothing(self, populated):
        with patch.object(populated, "_save_to_storage") as save:
            assert populated.add_chunks([], []) == []
        save.assert_not_called()

    def test_a_failed_save_takes_the_chunks_back_out(self, populated):
        before = [c["doc_id"] for c in populated.get_chunks()]
        with patch.object(populated, "_save_to_storage", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                populated.add_chunks(["Redis caches things."], [{"source": "cache.txt"}])

        assert [c["doc_id"] for c in populated.get_chunks()] == before
        _assert_rows_match_documents(populated)


class _FlakyStorage(LocalStorage):
    """Local storage that refuses writes of the files named in ``refuse``, and all writes after ``ok_writes`` more."""

    def __init__(self, base_dir):
        super().__init__(base_dir=base_dir)
        self.ok_writes = None
        self.refuse = set()
        self.written = []

    def save_file(self, file_data, path, **kwargs):
        name = path.rsplit("/", 1)[-1]
        if name in self.refuse:
            raise OSError(f"storage refused {name}")
        if self.ok_writes is not None:
            if self.ok_writes <= 0:
                raise OSError("storage write failed")
            self.ok_writes -= 1
        self.written.append(name)
        return super().save_file(file_data, path, **kwargs)


@pytest.fixture
def flaky(tmp_path):
    return _FlakyStorage(str(tmp_path))


@pytest.fixture
def flaky_store(flaky, make_store):
    store = make_store(flaky, docs_init=_seed_docs())
    store.save_local()
    flaky.written.clear()
    return store


def _ids_by_source(store):
    return {c["metadata"]["source"]: c["doc_id"] for c in store.get_chunks()}


@pytest.mark.unit
class TestFaissSaveIsNeverMisaligned:
    """index.faiss and its sidecar are separate files; a save that stops between them must not pair rows wrongly."""

    def test_the_json_sidecar_is_written_last_and_names_its_index(self, flaky_store, flaky, tmp_path):
        flaky_store.delete_chunks([_ids_by_source(flaky_store)["geo.txt"]])

        assert flaky.written == ["index.pkl", "index.faiss", "index.json"]
        payload = json.loads((tmp_path / "indexes" / "src" / "index.json").read_text())
        import hashlib

        index_bytes = (tmp_path / "indexes" / "src" / "index.faiss").read_bytes()
        assert payload["index_sha256"] == hashlib.sha256(index_bytes).hexdigest()

    @pytest.mark.parametrize("ok_writes", [0, 1, 2])
    def test_a_delete_whose_save_stops_part_way_reloads_consistently(
        self, flaky_store, flaky, make_store, ok_writes,
    ):
        geo = _ids_by_source(flaky_store)["geo.txt"]
        flaky.ok_writes = ok_writes

        with pytest.raises(OSError):
            flaky_store.delete_chunks([geo])

        # The loaded store is back as it was, so a caller relisting it learns nothing was deleted.
        assert geo in flaky_store.documents
        _assert_rows_match_documents(flaky_store)
        flaky.ok_writes = None
        reloaded = make_store(flaky)
        _assert_rows_match_documents(reloaded)
        hit = reloaded.search_with_scores("q", k=1, query_vector=[0.0, 0.0, 1.0])[0][0]
        assert "Celery" in hit.page_content

    @pytest.mark.parametrize("ok_writes", [0, 1, 2])
    def test_an_update_whose_save_stops_part_way_reloads_consistently(
        self, flaky_store, flaky, make_store, ok_writes,
    ):
        geo = _ids_by_source(flaky_store)["geo.txt"]
        flaky.ok_writes = ok_writes

        with pytest.raises(OSError):
            flaky_store.update_chunk(geo, "Celery workers in Paris? No: about celery.", {"source": "geo.txt"})

        assert flaky_store.documents[geo]["page_content"] == "The capital of France is Paris."
        _assert_rows_match_documents(flaky_store)
        flaky.ok_writes = None
        _assert_rows_match_documents(make_store(flaky))

    def test_a_failed_save_is_undone_in_storage_when_it_can_be(self, flaky_store, flaky, make_store):
        geo = _ids_by_source(flaky_store)["geo.txt"]
        flaky.ok_writes = 2  # pkl + index written, json refused; the undo's writes then go through

        def recover(*a, **k):
            flaky.ok_writes = None

        real_save = flaky.save_file

        def save_file(file_data, path, **kwargs):
            try:
                return real_save(file_data, path, **kwargs)
            except OSError:
                recover()
                raise

        flaky.save_file = save_file
        with pytest.raises(OSError):
            flaky_store.delete_chunks([geo])

        reloaded = make_store(flaky)
        assert geo in reloaded.documents
        _assert_rows_match_documents(reloaded)

    def test_a_stale_json_sidecar_falls_back_to_the_pickle_that_matches(self, flaky_store, flaky, make_store,
                                                                        tmp_path):
        # A sync's upload stores index.faiss + index.pkl and leaves the json an earlier edit wrote.
        folder = tmp_path / "indexes" / "src"
        stale_json = (folder / "index.json").read_bytes()
        flaky_store.delete_chunks([_ids_by_source(flaky_store)["geo.txt"]])
        (folder / "index.json").write_bytes(stale_json)

        reloaded = make_store(flaky)

        assert sorted(_ids_by_source(reloaded)) == ["db.txt", "queue.txt"]
        _assert_rows_match_documents(reloaded)

    def test_an_index_that_matches_no_sidecar_fails_loudly(self, flaky_store, flaky, make_store, tmp_path):
        folder = tmp_path / "indexes" / "src"
        old_pkl = (folder / "index.pkl").read_bytes()
        old_json = json.loads((folder / "index.json").read_text())
        flaky_store.delete_chunks([_ids_by_source(flaky_store)["geo.txt"]])
        (folder / "index.pkl").write_bytes(old_pkl)
        # A sidecar from before sidecars named their index: only the row count can be checked.
        old_json.pop("index_sha256", None)
        (folder / "index.json").write_text(json.dumps(old_json))

        with pytest.raises(Exception, match="out of step"):
            make_store(flaky)


class _CappedEmbeddings(_FakeEmbeddings):
    """Records each request's size and refuses one over ``cap`` inputs, as a remote provider does."""

    def __init__(self, cap):
        self.cap = cap
        self.calls = []

    def embed_documents(self, documents):
        self.calls.append(len(documents))
        if len(documents) > self.cap:
            raise RuntimeError(f"400: {len(documents)} inputs in one request")
        return super().embed_documents(documents)


@pytest.mark.unit
class TestFaissEmbedsInBatches:
    """A long page's chunks go to the embeddings provider in EMBEDDINGS_BATCH_SIZE slices, then one save."""

    @pytest.fixture
    def capped(self, populated, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "EMBEDDINGS_BATCH_SIZE", 2)
        populated.embeddings = _CappedEmbeddings(cap=2)
        return populated

    def test_add_chunks_embeds_in_slices_and_saves_once(self, capped):
        texts = [f"Paris fact {i}" for i in range(5)]
        with patch.object(capped, "_save_to_storage") as save:
            ids = capped.add_chunks(texts, [{"source": "big.html"}] * 5)

        assert capped.embeddings.calls == [2, 2, 1]
        save.assert_called_once()
        assert len(ids) == 5 and capped.index.ntotal == 8
        assert [capped.documents[i]["page_content"] for i in ids] == texts
        _assert_rows_match_documents(capped)

    def test_add_texts_embeds_in_slices(self, capped):
        ids = capped.add_texts([f"Celery fact {i}" for i in range(3)], [{}] * 3)

        assert capped.embeddings.calls == [2, 1]
        assert len(ids) == 3 and capped.index.ntotal == 6
        _assert_rows_match_documents(capped)

    def test_a_failed_slice_adds_nothing(self, capped):
        before = [c["doc_id"] for c in capped.get_chunks()]
        real = capped.embeddings.embed_documents

        def fail_second(documents):
            if len(capped.embeddings.calls) == 1:
                capped.embeddings.calls.append(len(documents))
                raise RuntimeError("provider unavailable")
            return real(documents)

        capped.embeddings.embed_documents = fail_second
        with patch.object(capped, "_save_to_storage") as save:
            with pytest.raises(RuntimeError, match="provider unavailable"):
                capped.add_chunks([f"t{i}" for i in range(4)], [{}] * 4)

        save.assert_not_called()
        assert [c["doc_id"] for c in capped.get_chunks()] == before
        assert capped.index.ntotal == 3


@pytest.fixture
def legacy(flaky, flaky_store, tmp_path):
    """Storage holding an index from before index.json: index.faiss and index.pkl only."""
    (tmp_path / "indexes" / "src" / "index.json").unlink()
    return flaky


def _edit_geo(store, text="About celery instead."):
    store.update_chunk(_ids_by_source(store)["geo.txt"], text, {"source": "geo.txt"})


@pytest.mark.unit
class TestFaissSaveOverAnUnnamedPair:
    """A pickle is checked on its row count alone, so a save must not replace it while no index.json names the
    stored index.faiss: an edit keeps the row count and moves rows, and the pair would read silently wrong."""

    def test_a_legacy_index_is_saved_json_first_then_json_last(self, legacy, make_store):
        store = make_store(legacy)
        _edit_geo(store)
        _edit_geo(store, "Celery again.")

        assert legacy.written == ["index.json", "index.faiss", "index.pkl", "index.pkl", "index.faiss", "index.json"]
        _assert_rows_match_documents(make_store(legacy))

    @pytest.mark.parametrize("refused", ["index.faiss", "index.pkl"])
    def test_a_save_of_a_legacy_index_that_stops_part_way_reloads_consistently(
        self, legacy, make_store, refused,
    ):
        store = make_store(legacy)
        legacy.refuse = {refused}  # the undo's save is refused too

        with pytest.raises(OSError):
            _edit_geo(store)

        legacy.refuse = set()
        _assert_rows_match_documents(make_store(legacy))

    def test_a_save_after_a_stale_json_that_stops_part_way_reloads_consistently(
        self, legacy, make_store, tmp_path,
    ):
        # index.faiss and index.pkl from one save, index.json from an older one: the pickle is what pairs.
        folder = tmp_path / "indexes" / "src"
        make_store(legacy).save_local()
        stale_json = (folder / "index.json").read_bytes()
        _edit_geo(make_store(legacy))
        (folder / "index.json").write_bytes(stale_json)
        store = make_store(legacy)
        legacy.refuse = {"index.faiss"}

        with pytest.raises(OSError):
            store.update_chunk(_ids_by_source(store)["db.txt"], "Celery, not a database.", {"source": "db.txt"})

        legacy.refuse = set()
        reloaded = make_store(legacy)
        _assert_rows_match_documents(reloaded)
        assert "celery" in reloaded.documents[_ids_by_source(reloaded)["geo.txt"]]["page_content"]

    def test_a_failed_save_is_retried_in_the_order_its_files_allow(self, flaky, flaky_store, make_store):
        # Stopped before index.json: index.faiss and index.pkl are the new pair, the json still names the old index.
        storage = flaky
        store = make_store(storage)
        storage.refuse = {"index.json"}
        with pytest.raises(OSError):
            _edit_geo(store)
        storage.refuse = {"index.faiss"}

        with pytest.raises(OSError):
            store.update_chunk(_ids_by_source(store)["db.txt"], "Celery, not a database.", {"source": "db.txt"})

        storage.refuse = set()
        _assert_rows_match_documents(make_store(storage))

    def test_a_fresh_build_over_a_legacy_index_that_stops_part_way_reloads_consistently(
        self, legacy, make_store,
    ):
        rebuilt = make_store(legacy, docs_init=list(reversed(_seed_docs())))
        legacy.refuse = {"index.faiss"}

        with pytest.raises(OSError):
            rebuilt.save_local()

        legacy.refuse = set()
        _assert_rows_match_documents(make_store(legacy))

    @pytest.mark.parametrize("upload", [False, True], ids=["fresh-build", "upload"])
    @pytest.mark.parametrize("fingerprint", [True, False], ids=["fingerprinted-json", "legacy-json"])
    def test_rebuild_preserves_the_pickle_when_the_existing_json_is_stale(
        self, tmp_path, flaky, flaky_store, make_store, upload, fingerprint,
    ):
        from docsgpt.vectorstore.faiss import store_uploaded_index

        storage = flaky
        folder = tmp_path / "indexes" / "src"
        stale_json = json.loads((folder / "index.json").read_text())
        current = make_store(storage)
        if fingerprint:
            _edit_geo(current)
        else:
            # Before fingerprints, only a different row count reveals the stale JSON.
            stale_json.pop("index_sha256")
            current.delete_chunk(_ids_by_source(current)["geo.txt"])
        # A preceding upload stopped after index.faiss, before its JSON sidecar.
        (folder / "index.json").write_text(json.dumps(stale_json))
        rebuilt = make_store(storage, docs_init=list(reversed(_seed_docs())))
        storage.refuse = {"index.faiss"}

        with pytest.raises(OSError):
            if upload:
                export = tmp_path / "export"
                rebuilt._write_index_files(str(export))
                store_uploaded_index(
                    storage, "indexes/src", (export / "index.faiss").read_bytes(), (export / "index.pkl").read_bytes(),
                )
            else:
                rebuilt.save_local()

        storage.refuse = set()
        _assert_rows_match_documents(make_store(storage))

    @pytest.mark.parametrize("upload", [False, True], ids=["fresh-build", "upload"])
    def test_an_unreadable_stored_index_does_not_stop_its_replacement(
        self, tmp_path, flaky, flaky_store, make_store, upload,
    ):
        from docsgpt.vectorstore.faiss import store_uploaded_index

        storage = flaky
        folder = tmp_path / "indexes" / "src"
        legacy_json = json.loads((folder / "index.json").read_text())
        legacy_json.pop("index_sha256")
        (folder / "index.json").write_text(json.dumps(legacy_json))
        (folder / "index.faiss").write_bytes(b"not an index")
        rebuilt = make_store(storage, docs_init=list(reversed(_seed_docs())))

        if upload:
            export = tmp_path / "export"
            rebuilt._write_index_files(str(export))
            store_uploaded_index(
                storage, "indexes/src", (export / "index.faiss").read_bytes(), (export / "index.pkl").read_bytes(),
            )
        else:
            rebuilt.save_local()

        _assert_rows_match_documents(make_store(storage))


class _ReadHookStorage(LocalStorage):
    """Local storage that runs ``hook`` once as the named file is first read: after it for
    index.faiss (the reader holds the old index), before it for anything else (the reader gets the new file)."""

    def __init__(self, base_dir):
        super().__init__(base_dir=base_dir)
        self.hook_on = None
        self.hook = None

    def get_file(self, path):
        import io

        name = path.rsplit("/", 1)[-1]
        if self.hook is None or name != self.hook_on:
            return super().get_file(path)
        hook, self.hook = self.hook, None
        if name != "index.faiss":
            hook()
            return super().get_file(path)
        data = super().get_file(path).read()
        hook()
        return io.BytesIO(data)


@pytest.mark.unit
class TestFaissLoadDuringASave:
    """A reader takes no lock: a save landing between its reads must not pair one save's index with another's rows."""

    def _editor(self, storage, make_store):
        return lambda: _edit_geo(make_store(storage))

    def test_an_index_read_just_before_a_save_is_read_again(self, tmp_path, make_store):
        storage = _ReadHookStorage(str(tmp_path))
        make_store(storage, docs_init=_seed_docs()).save_local()
        storage.hook_on, storage.hook = "index.faiss", self._editor(storage, make_store)

        reader = make_store(storage)

        _assert_rows_match_documents(reader)
        assert "celery" in reader.documents[_ids_by_source(reader)["geo.txt"]]["page_content"]

    def test_a_legacy_index_saved_while_its_pickle_is_read_is_read_again(self, tmp_path, make_store):
        storage = _ReadHookStorage(str(tmp_path))
        make_store(storage, docs_init=_seed_docs()).save_local()
        (tmp_path / "indexes" / "src" / "index.json").unlink()
        storage.hook_on, storage.hook = "index.pkl", self._editor(storage, make_store)

        reader = make_store(storage)

        _assert_rows_match_documents(reader)


@pytest.mark.unit
class TestStoreUploadedIndex:
    """What /api/upload_index stores: the worker's index.faiss and index.pkl, plus an index.json naming them."""

    def _upload(self, storage, tmp_path, make_store, docs):
        from docsgpt.vectorstore.faiss import store_uploaded_index

        built = make_store(storage, docs_init=docs)
        folder = tmp_path / "built"
        built._write_index_files(str(folder))
        store_uploaded_index(
            storage, "indexes/src", (folder / "index.faiss").read_bytes(), (folder / "index.pkl").read_bytes(),
        )

    def test_the_upload_loads_through_its_json(self, legacy, tmp_path, make_store):
        self._upload(legacy, tmp_path, make_store, list(reversed(_seed_docs())))

        reloaded = make_store(legacy)

        assert reloaded._paired_sidecar == "index.json"
        _assert_rows_match_documents(reloaded)

    @pytest.mark.parametrize("named", [False, True])
    @pytest.mark.parametrize("refused", ["index.json", "index.faiss", "index.pkl"])
    def test_an_upload_that_stops_part_way_reloads_consistently(
        self, legacy, tmp_path, make_store, named, refused,
    ):
        if named:
            make_store(legacy).save_local()
        legacy.refuse = {refused}

        with pytest.raises(OSError):
            self._upload(legacy, tmp_path, make_store, list(reversed(_seed_docs())))

        legacy.refuse = set()
        _assert_rows_match_documents(make_store(legacy))

    def test_an_unreadable_pickle_stores_nothing(self, legacy):
        from docsgpt.vectorstore.faiss import store_uploaded_index

        with pytest.raises(ValueError, match="not a FAISS sidecar"):
            store_uploaded_index(legacy, "indexes/src", b"faiss", b"not a pickle")

        assert legacy.written == []
