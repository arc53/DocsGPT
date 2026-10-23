"""Tests for ``docsgpt.worker.extract_graph_worker``.

The worker loads the source row, fetches its chunks from the vector store, and
delegates to ``extract_graph_for_source``. ``graphrag_available``,
``VectorCreator.create_vectorstore``, and the extraction pipeline are mocked so
no live store access or LLM/model calls run; the ``sources`` row is real so
``SourcesRepository.get_any`` resolves.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docsgpt.storage.db.repositories.sources import SourcesRepository


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
        "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore",
        lambda *a, **kw: store,
    )
    return store


@pytest.mark.unit
class TestExtractGraphWorker:
    def test_fetches_chunks_and_calls_extraction(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        source_id = _seed_source(pg_conn)
        chunks = [
            {"doc_id": "c1", "text": "alpha"},
            {"doc_id": "c2", "text": "beta"},
        ]
        store = _patch_store(monkeypatch, chunks)

        monkeypatch.setattr(
            "docsgpt.graphrag.graphrag_available", lambda: True
        )
        extract = MagicMock(
            name="extract_graph_for_source",
            return_value={"nodes": 3, "edges": 2, "chunks_processed": 2},
        )
        monkeypatch.setattr(
            "docsgpt.graphrag.extraction.extract_graph_for_source", extract
        )

        result = worker.extract_graph_worker(task_self, source_id, "alice")

        store.get_chunks.assert_called_once()
        extract.assert_called_once()
        assert extract.call_args.args[0] == source_id
        assert extract.call_args.args[1] == "alice"
        assert extract.call_args.args[2] == chunks
        assert extract.call_args.kwargs["config"].kind == "graphrag"
        assert result == {"nodes": 3, "edges": 2, "chunks_processed": 2}

    def test_a_page_change_passes_its_chunk_ids(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        # A page change extracts only the chunks it stored, not the source's backlog.
        from docsgpt import worker

        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [{"doc_id": "c1", "text": "alpha"}, {"doc_id": "c2", "text": "beta"}])
        monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: True)
        extract = MagicMock(return_value={"nodes": 1, "edges": 0, "chunks_processed": 1})
        monkeypatch.setattr("docsgpt.graphrag.extraction.extract_graph_for_source", extract)

        worker.extract_graph_worker(task_self, source_id, "alice", chunk_ids=["c2"])

        assert extract.call_args.kwargs["chunk_ids"] == ["c2"]

    def test_unavailable_returns_status_no_extraction(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        store = _patch_store(monkeypatch, [])
        monkeypatch.setattr(
            "docsgpt.graphrag.graphrag_available", lambda: False
        )
        extract = MagicMock(name="extract_graph_for_source")
        monkeypatch.setattr(
            "docsgpt.graphrag.extraction.extract_graph_for_source", extract
        )

        result = worker.extract_graph_worker(task_self, "src-x", "alice")

        assert result == {"status": "unavailable"}
        store.get_chunks.assert_not_called()
        extract.assert_not_called()

    def test_empty_chunks_still_calls_extraction(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [])
        monkeypatch.setattr(
            "docsgpt.graphrag.graphrag_available", lambda: True
        )
        extract = MagicMock(
            name="extract_graph_for_source",
            return_value={"nodes": 0, "edges": 0, "chunks_processed": 0},
        )
        monkeypatch.setattr(
            "docsgpt.graphrag.extraction.extract_graph_for_source", extract
        )

        result = worker.extract_graph_worker(task_self, source_id, "alice")

        extract.assert_called_once()
        assert extract.call_args.args[2] == []
        assert result["chunks_processed"] == 0

    def test_publishes_completed_event(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [{"doc_id": "c1", "text": "alpha"}])
        monkeypatch.setattr(
            "docsgpt.graphrag.graphrag_available", lambda: True
        )
        monkeypatch.setattr(
            "docsgpt.graphrag.extraction.extract_graph_for_source",
            MagicMock(return_value={"nodes": 1, "edges": 0, "chunks_processed": 1}),
        )
        events = []
        monkeypatch.setattr(
            worker, "publish_user_event",
            lambda user, etype, payload, **kw: events.append((etype, payload)),
        )

        worker.extract_graph_worker(task_self, source_id, "alice")

        types = [e[0] for e in events]
        assert "graph.extract.progress" in types
        assert types[-1] == "graph.extract.completed"
        assert events[-1][1]["nodes"] == 1

    def test_publishes_failed_event_on_error(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [{"doc_id": "c1", "text": "alpha"}])
        monkeypatch.setattr(
            "docsgpt.graphrag.graphrag_available", lambda: True
        )

        def _boom(*a, **kw):
            raise RuntimeError("extraction blew up")

        monkeypatch.setattr(
            "docsgpt.graphrag.extraction.extract_graph_for_source", _boom
        )
        events = []
        monkeypatch.setattr(
            worker, "publish_user_event",
            lambda user, etype, payload, **kw: events.append((etype, payload)),
        )

        with pytest.raises(RuntimeError):
            worker.extract_graph_worker(task_self, source_id, "alice")

        assert "graph.extract.failed" in [e[0] for e in events]


@pytest.mark.unit
class TestExtractionsTakeTurns:
    """Each extraction spends what is left of the source's chunk cap: two at once would each spend all of it."""

    def _setup(self, pg_conn, monkeypatch, held):
        from docsgpt import worker

        source_id = _seed_source(pg_conn)
        store = _patch_store(monkeypatch, [{"doc_id": "c1", "text": "alpha"}])
        store.get_chunks.side_effect = lambda: held.append("reading") or [{"doc_id": "c1", "text": "alpha"}]
        monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: True)
        monkeypatch.setattr(
            "docsgpt.graphrag.extraction.extract_graph_for_source",
            lambda *a, **k: held.append("extracting") or {"nodes": 1, "edges": 0, "chunks_processed": 1},
        )
        events = []
        monkeypatch.setattr(worker, "publish_user_event", lambda user, etype, payload, **kw: events.append(etype))
        return worker, source_id, events

    @pytest.mark.parametrize("chunk_ids", [None, ["c1"]])
    def test_extracts_holding_the_graph_extraction_lock(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, chunk_ids,
    ):
        from contextlib import contextmanager

        held = []
        worker, source_id, _events = self._setup(pg_conn, monkeypatch, held)

        @contextmanager
        def fake_lock(locked_id, **kwargs):
            held.append(locked_id)
            yield
            held.append("released")

        monkeypatch.setattr(worker, "graph_extract_lock", fake_lock)
        index_lock = MagicMock(name="source_index_lock")
        monkeypatch.setattr(worker, "source_index_lock", index_lock)

        worker.extract_graph_worker(task_self, source_id, "alice", chunk_ids=chunk_ids)

        assert held == [source_id, "reading", "extracting", "released"]
        index_lock.assert_not_called()

    def test_a_busy_source_retries_the_extraction_later(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        from contextlib import contextmanager

        from celery.exceptions import Retry

        from docsgpt.vectorstore.index_lock import SourceBusy

        held = []
        worker, source_id, events = self._setup(pg_conn, monkeypatch, held)

        @contextmanager
        def busy(locked_id, **kwargs):
            raise SourceBusy("busy")
            yield  # pragma: no cover

        monkeypatch.setattr(worker, "graph_extract_lock", busy)
        task_self.retry.side_effect = lambda **kwargs: Retry()

        with pytest.raises(Retry):
            worker.extract_graph_worker(task_self, source_id, "alice", chunk_ids=["c1"])

        assert held == []
        assert task_self.retry.call_args.kwargs["countdown"] > 0
        assert "graph.extract.failed" not in events

    def test_busy_past_the_retries_fails_the_build(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        from contextlib import contextmanager

        from docsgpt.vectorstore.index_lock import SourceBusy

        worker, source_id, events = self._setup(pg_conn, monkeypatch, [])

        @contextmanager
        def busy(locked_id, **kwargs):
            raise SourceBusy("busy")
            yield  # pragma: no cover

        def exhausted(exc=None, **kwargs):
            raise exc

        monkeypatch.setattr(worker, "graph_extract_lock", busy)
        task_self.retry.side_effect = exhausted

        with pytest.raises(SourceBusy):
            worker.extract_graph_worker(task_self, source_id, "alice")

        assert events[-1] == "graph.extract.failed"


@pytest.mark.unit
class TestExtractGraphTrace:
    """A graph build is one execution trace holding every extraction call."""

    def _run(self, pg_conn, monkeypatch, task_self, extract):
        from docsgpt import tracing, worker
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "TRACES_ENABLED", True)
        monkeypatch.setattr(settings, "TRACES_OTEL_EXPORT", False)
        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [{"doc_id": "c1", "text": "alpha"}])
        monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: True)
        monkeypatch.setattr("docsgpt.graphrag.extraction.extract_graph_for_source", extract)
        flushed = []

        def _flush(trace, status=None, **_kwargs):
            trace.flushed = True
            trace.finish(status)
            flushed.append(trace)

        monkeypatch.setattr(tracing, "flush", _flush)
        return worker, source_id, flushed

    def test_successful_build_is_traced(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        from docsgpt import tracing

        def _extract(*_a, **_kw):
            with tracing.span(tracing.KIND_LLM, "chat m"):
                pass
            return {"nodes": 3, "edges": 2, "chunks_processed": 1}

        worker, source_id, flushed = self._run(pg_conn, monkeypatch, task_self, _extract)
        worker.extract_graph_worker(task_self, source_id, "alice")
        (trace,) = flushed
        assert trace.source == "graph_extraction"
        assert trace.user_id == "alice"
        step, llm = trace.spans
        assert step.attributes["docsgpt.graph.nodes"] == 3
        assert llm.parent_id == step.id

    def test_failed_build_is_an_error_trace(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        worker, source_id, flushed = self._run(
            pg_conn, monkeypatch, task_self, MagicMock(side_effect=RuntimeError("llm down"))
        )
        with pytest.raises(RuntimeError):
            worker.extract_graph_worker(task_self, source_id, "alice")
        assert flushed[0].status == "error"
