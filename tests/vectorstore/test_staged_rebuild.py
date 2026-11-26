"""Staged full rebuilds: embed under a staging id, then swap it in (docsgpt/vectorstore/staged_rebuild.py)."""

from unittest.mock import MagicMock

import pytest

from docsgpt.vectorstore import staged_rebuild
from docsgpt.vectorstore.vector_creator import VectorCreator


@pytest.fixture
def stores(monkeypatch):
    """Every store built, by the source id it was built for."""
    built = {}

    def _create(store_type, *args, source_id=None, **kwargs):
        store = MagicMock(name=f"store:{source_id}")
        store.promote_staged.return_value = 3
        store.purge_index.return_value = 2
        built[source_id] = store
        return store

    monkeypatch.setattr(VectorCreator, "create_vectorstore", staticmethod(_create))
    return built


@pytest.mark.unit
class TestWhichStoresStage:
    @pytest.mark.parametrize("store, staged", [
        ("pgvector", True), ("PGVector", True), ("faiss", False), ("mongodb", False), ("qdrant", False),
        ("milvus", False), ("elasticsearch", False), ("nope", False), ("", False), (None, False),
    ])
    def test_only_stores_that_can_swap_in_one_step_stage(self, store, staged):
        assert VectorCreator.supports_staged_rebuild(store) is staged

    def test_the_staging_id_is_derived_from_the_source(self):
        assert staged_rebuild.staging_id("abc") == "abc:staging"
        assert staged_rebuild.owner_of("abc:staging") == "abc"
        assert staged_rebuild.owner_of("abc") == "abc"

    def test_a_store_that_cannot_swap_gets_no_staging_id(self, monkeypatch):
        monkeypatch.setattr(staged_rebuild.settings, "VECTOR_STORE", "mongodb")
        assert staged_rebuild.staged_index_id("abc") is None
        monkeypatch.setattr(staged_rebuild.settings, "VECTOR_STORE", "pgvector")
        assert staged_rebuild.staged_index_id("abc") == "abc:staging"


@pytest.mark.unit
class TestPromote:
    def test_the_live_store_takes_the_staged_chunks_and_is_closed(self, stores):
        assert staged_rebuild.promote_staged_index("abc", "abc:staging", 3) == 3
        stores["abc"].promote_staged.assert_called_once_with("abc:staging", expected=3)
        stores["abc"].close.assert_called_once_with()

    def test_an_error_is_raised_and_the_store_still_closed(self, stores, monkeypatch):
        def _create(store_type, *args, source_id=None, **kwargs):
            store = MagicMock()
            store.promote_staged.side_effect = RuntimeError("deadlock")
            stores[source_id] = store
            return store

        monkeypatch.setattr(VectorCreator, "create_vectorstore", staticmethod(_create))
        with pytest.raises(RuntimeError, match="deadlock"):
            staged_rebuild.promote_staged_index("abc", "abc:staging", 3)
        stores["abc"].close.assert_called_once_with()


@pytest.mark.unit
class TestDiscard:
    def test_the_staged_chunks_are_purged(self, stores, monkeypatch):
        monkeypatch.setattr(staged_rebuild.settings, "VECTOR_STORE", "pgvector")
        staged_rebuild.discard_staged_index("abc")
        stores["abc:staging"].purge_index.assert_called_once_with()
        stores["abc:staging"].close.assert_called_once_with()

    def test_nothing_is_built_for_a_store_that_never_stages(self, stores, monkeypatch):
        monkeypatch.setattr(staged_rebuild.settings, "VECTOR_STORE", "faiss")
        staged_rebuild.discard_staged_index("abc")
        assert stores == {}

    def test_a_failure_is_logged_not_raised(self, monkeypatch, caplog):
        monkeypatch.setattr(staged_rebuild.settings, "VECTOR_STORE", "pgvector")
        monkeypatch.setattr(
            VectorCreator, "create_vectorstore", staticmethod(MagicMock(side_effect=RuntimeError("db down"))),
        )
        staged_rebuild.discard_staged_index("abc")
        assert "abc:staging" in caplog.text


@pytest.mark.unit
class TestEdges:
    def test_a_store_without_a_swap_refuses_one(self):
        from docsgpt.vectorstore.base import BaseVectorStore

        class Plain(BaseVectorStore):
            def search(self, *args, **kwargs):
                return []

            def add_texts(self, texts, metadatas=None, *args, **kwargs):
                return []

        with pytest.raises(NotImplementedError):
            Plain().promote_staged("abc:staging")

    def test_an_incomplete_staging_set_is_dropped_with_the_checkpoint(self, stores, monkeypatch):
        from docsgpt.vectorstore.base import StagedIndexIncomplete

        forgotten = []
        monkeypatch.setattr(staged_rebuild.settings, "VECTOR_STORE", "pgvector")
        monkeypatch.setattr(staged_rebuild, "_forget_checkpoint", forgotten.append)

        def _create(store_type, *args, source_id=None, **kwargs):
            store = MagicMock(name=f"store:{source_id}")
            store.promote_staged.side_effect = StagedIndexIncomplete("2 of 3")
            stores[source_id] = store
            return store

        monkeypatch.setattr(VectorCreator, "create_vectorstore", staticmethod(_create))
        with pytest.raises(StagedIndexIncomplete):
            staged_rebuild.promote_staged_index("abc", "abc:staging", 3)
        stores["abc:staging"].purge_index.assert_called_once_with()
        assert forgotten == ["abc"]

    def test_forgetting_a_checkpoint_never_raises(self, monkeypatch, caplog):
        from contextlib import contextmanager

        @contextmanager
        def _down():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr(staged_rebuild, "db_session", _down)
        staged_rebuild._forget_checkpoint("abc")
        assert "checkpoint of source abc" in caplog.text
