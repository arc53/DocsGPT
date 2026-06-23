"""Tests for ``application.worker.extract_graph_worker``.

The worker loads the source row, fetches its chunks from the vector store, and
delegates to ``extract_graph_for_source``. ``graphrag_available``,
``VectorCreator.create_vectorstore``, and the extraction pipeline are mocked so
no live store access or LLM/model calls run; the ``sources`` row is real so
``SourcesRepository.get_any`` resolves.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.storage.db.repositories.sources import SourcesRepository


def _seed_source(pg_conn, config=None):
    src = SourcesRepository(pg_conn).create(
        "graph-set",
        user_id="alice",
        type="file",
        retriever="classic",
        config=config or {"kind": "graphrag", "retrieval": {"retriever": "graphrag"}},
    )
    return str(src["id"])


def _patch_store(monkeypatch, chunks):
    store = MagicMock(name="vectorstore")
    store.get_chunks.return_value = chunks
    monkeypatch.setattr(
        "application.vectorstore.vector_creator.VectorCreator.create_vectorstore",
        lambda *a, **kw: store,
    )
    return store


@pytest.mark.unit
class TestExtractGraphWorker:
    def test_fetches_chunks_and_calls_extraction(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        chunks = [
            {"doc_id": "c1", "text": "alpha"},
            {"doc_id": "c2", "text": "beta"},
        ]
        store = _patch_store(monkeypatch, chunks)

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        extract = MagicMock(
            name="extract_graph_for_source",
            return_value={"nodes": 3, "edges": 2, "chunks_processed": 2},
        )
        monkeypatch.setattr(
            "application.graphrag.extraction.extract_graph_for_source", extract
        )

        result = worker.extract_graph_worker(task_self, source_id, "alice")

        store.get_chunks.assert_called_once()
        extract.assert_called_once()
        assert extract.call_args.args[0] == source_id
        assert extract.call_args.args[1] == "alice"
        assert extract.call_args.args[2] == chunks
        assert extract.call_args.kwargs["config"].kind == "graphrag"
        assert result == {"nodes": 3, "edges": 2, "chunks_processed": 2}

    def test_unavailable_returns_status_no_extraction(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        store = _patch_store(monkeypatch, [])
        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: False
        )
        extract = MagicMock(name="extract_graph_for_source")
        monkeypatch.setattr(
            "application.graphrag.extraction.extract_graph_for_source", extract
        )

        result = worker.extract_graph_worker(task_self, "src-x", "alice")

        assert result == {"status": "unavailable"}
        store.get_chunks.assert_not_called()
        extract.assert_not_called()

    def test_empty_chunks_still_calls_extraction(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [])
        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        extract = MagicMock(
            name="extract_graph_for_source",
            return_value={"nodes": 0, "edges": 0, "chunks_processed": 0},
        )
        monkeypatch.setattr(
            "application.graphrag.extraction.extract_graph_for_source", extract
        )

        result = worker.extract_graph_worker(task_self, source_id, "alice")

        extract.assert_called_once()
        assert extract.call_args.args[2] == []
        assert result["chunks_processed"] == 0
