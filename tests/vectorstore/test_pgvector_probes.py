"""IVFFlat probes must be raised, or a filtered search silently returns nothing.

An IVFFlat index splits vectors into ``lists`` clusters and the default
``probes = 1`` scans one of them. Our search filters by ``source_id`` *after*
the index picks candidates, so with one probe the candidates routinely all
belong to other sources and the query returns zero rows — retrieval reports no
documents and the model answers with no source material, with nothing logged.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.vectorstore import pgvector as pgvector_module
from application.vectorstore.pgvector import PGVectorStore


@pytest.fixture(autouse=True)
def _clear_cache():
    pgvector_module._IVFFLAT_LISTS_CACHE.clear()
    yield
    pgvector_module._IVFFLAT_LISTS_CACHE.clear()


def _store() -> PGVectorStore:
    store = PGVectorStore.__new__(PGVectorStore)
    store._table_name = "documents"
    store._source_id = "s1"
    store._text_column = "text"
    store._metadata_column = "metadata"
    store._vector_column = "embedding"
    return store


def _conn(indexdef):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (indexdef,) if indexdef else None
    return conn, cursor


@pytest.mark.unit
class TestIvfflatProbes:
    def test_probes_derived_from_the_index_lists(self, monkeypatch):
        monkeypatch.setattr(
            pgvector_module.settings, "PGVECTOR_IVFFLAT_PROBES", None, raising=False
        )
        conn, cursor = _conn(
            "CREATE INDEX i ON documents USING ivfflat (embedding vector_cosine_ops)"
            " WITH (lists='100')"
        )
        _store()._apply_ivfflat_probes(conn)

        # sqrt(100) = 10; 1 would scan a single cluster of a 100-way split.
        assert any(
            "ivfflat.probes = 10" in str(c) for c in cursor.execute.call_args_list
        ), cursor.execute.call_args_list

    def test_explicit_setting_overrides_derivation(self, monkeypatch):
        monkeypatch.setattr(
            pgvector_module.settings, "PGVECTOR_IVFFLAT_PROBES", 42, raising=False
        )
        conn, cursor = _conn("... ivfflat ... WITH (lists='100')")
        _store()._apply_ivfflat_probes(conn)

        assert any(
            "ivfflat.probes = 42" in str(c) for c in cursor.execute.call_args_list
        )

    def test_no_ivfflat_index_sets_nothing(self, monkeypatch):
        monkeypatch.setattr(
            pgvector_module.settings, "PGVECTOR_IVFFLAT_PROBES", None, raising=False
        )
        conn, cursor = _conn(None)
        _store()._apply_ivfflat_probes(conn)

        assert not any(
            "ivfflat.probes" in str(c) for c in cursor.execute.call_args_list
        )

    def test_introspection_failure_never_breaks_search(self, monkeypatch):
        monkeypatch.setattr(
            pgvector_module.settings, "PGVECTOR_IVFFLAT_PROBES", None, raising=False
        )
        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("no pg_indexes")
        _store()._apply_ivfflat_probes(conn)  # must not raise

    def test_lists_lookup_is_cached_per_table(self, monkeypatch):
        monkeypatch.setattr(
            pgvector_module.settings, "PGVECTOR_IVFFLAT_PROBES", None, raising=False
        )
        conn, _ = _conn("... ivfflat ... WITH (lists='64')")
        store = _store()
        assert store._ivfflat_lists(conn) == 64
        conn.cursor.side_effect = AssertionError("should not re-query")
        assert store._ivfflat_lists(conn) == 64


@pytest.mark.unit
class TestNoVectorIndexOnEmptyTable:
    """The table must not get a vector index at creation time.

    IVFFlat computes centroids at build time, so an index built on an empty
    table gets random ones and never recovers — measured recall 0.06 once rows
    arrive. With our ``source_id`` post-filter that returned zero rows for
    sources with hundreds of chunks, silently.
    """

    def test_create_schema_creates_no_vector_index(self):
        import inspect

        source = inspect.getsource(PGVectorStore.create_schema)
        assert "USING ivfflat" not in source
        assert "USING hnsw" not in source
        # the non-vector indexes are still expected
        assert "source_id_idx" in source and "text_fts_idx" in source


@pytest.mark.unit
class TestExactSearchFallback:
    """A short indexed result must be re-run exactly, never surfaced as-is."""

    def _cursor(self, available, exact_rows):
        cursor = MagicMock()
        cursor.fetchone.return_value = (available,)
        cursor.fetchall.return_value = exact_rows
        return cursor

    def test_short_result_is_replaced_by_exact(self):
        ann = [("a", {}, 0.1)]
        exact = [("a", {}, 0.1), ("b", {}, 0.2), ("c", {}, 0.3)]
        store = _store()
        out = store._exact_search(self._cursor(50, exact), [0.0], k=3, ann_results=ann)
        assert out == exact

    def test_full_result_is_left_alone(self):
        ann = [("a", {}, 0.1), ("b", {}, 0.2)]
        store = _store()
        cursor = self._cursor(50, [("x", {}, 0.0)] * 9)
        assert store._exact_search(cursor, [0.0], k=2, ann_results=ann) == ann

    def test_source_smaller_than_k_is_not_a_short_result(self):
        """A 2-chunk source answering k=100 is complete, not under-returning."""
        ann = [("a", {}, 0.1), ("b", {}, 0.2)]
        store = _store()
        cursor = self._cursor(2, [("x", {}, 0.0)] * 2)
        assert store._exact_search(cursor, [0.0], k=100, ann_results=ann) == ann

    def test_failure_returns_the_original_result(self):
        ann = [("a", {}, 0.1)]
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("boom")
        store = _store()
        assert store._exact_search(cursor, [0.0], k=5, ann_results=ann) == ann


@pytest.mark.unit
class TestFallbackNeverPoisonsTheConnection:
    """A failure inside the safety net must not blind every later search.

    The fallback runs extra statements on the shared connection. Without a
    rollback, one error leaves the transaction INERROR and every subsequent
    search on that store returns ``[]`` — reproducing the exact silent
    zero-retrieval the fallback exists to prevent, and blinding
    ``keyword_search`` too since hybrid retrieval reuses the store.
    """

    def test_failure_rolls_back(self):
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("aborted")
        store = _store()

        out = store._exact_search(cursor, [0.0], k=5, ann_results=[("a", {}, 0.1)])

        assert out == [("a", {}, 0.1)]
        cursor.connection.rollback.assert_called_once()

    def test_planner_gucs_are_reset_not_forced_on(self):
        """RESET restores the deployment's setting; ``= on`` overrides it."""
        cursor = MagicMock()
        cursor.fetchone.return_value = (50,)
        cursor.fetchall.return_value = [("a", {}, 0.1)] * 5
        _store()._exact_search(cursor, [0.0], k=5, ann_results=[("a", {}, 0.1)])

        executed = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "RESET enable_indexscan" in executed
        assert "enable_indexscan = on" not in executed


@pytest.mark.unit
class TestListsCacheAllowsLaterIndexCreation:
    """Caching a miss would keep probes unset for the process's lifetime.

    The store now tells operators to add an index deliberately, later — so a
    process that booted before that must notice it.
    """

    def test_absent_index_is_not_cached(self):
        store = _store()
        conn, _ = _conn(None)
        assert store._ivfflat_lists(conn) is None
        assert "documents" not in pgvector_module._IVFFLAT_LISTS_CACHE

        conn2, _ = _conn("... ivfflat ... WITH (lists='64')")
        assert store._ivfflat_lists(conn2) == 64
