"""Ingest paths enqueue graph extraction after embed for graphrag sources.

Exercises ``remote_worker`` as the representative ingest path: the remote
loader, embedding pipeline, and ``upload_index`` are mocked, so the only thing
under test is the post-embed ``extract_graph.delay`` hook. ``graphrag_available``
is forced on so the gate doesn't depend on the test env's vector store. The
``sources`` row is real (seeded via ``pg_conn``) so the hook can read the
source's ``updated_at`` for the idempotency key.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document
from application.storage.db.repositories.sources import SourcesRepository


@pytest.fixture
def _mock_remote_pipeline(monkeypatch):
    from application import worker

    fake_loader = MagicMock(name="remote_loader")
    fake_loader.load_data.return_value = [
        Document(
            text="page body",
            extra_info={"file_path": "guides/setup.md", "title": "setup"},
            doc_id="d1",
        )
    ]
    monkeypatch.setattr(
        worker.RemoteCreator, "create_loader", lambda loader: fake_loader
    )
    monkeypatch.setattr(
        worker,
        "embed_and_store_documents",
        lambda docs, full_path, source_id, task, **kw: None,
    )
    monkeypatch.setattr(
        worker, "assert_index_complete", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        worker, "upload_index", lambda full_path, file_data: None
    )
    # Reset constructs a real GraphStore (pgvector); not under test here.
    monkeypatch.setattr(
        worker, "_reset_graph_for_source", lambda *a, **kw: None
    )


def _patch_delay(monkeypatch):
    delay = MagicMock(name="extract_graph_delay")
    monkeypatch.setattr(
        "application.api.user.tasks.extract_graph.delay", delay
    )
    return delay


def _seed_source(pg_conn, user, config):
    src = SourcesRepository(pg_conn).create(
        "graph-remote", user_id=user, type="crawler", config=config,
    )
    return str(src["id"])


@pytest.mark.unit
class TestGraphExtractionKey:
    def test_shape_and_state_sensitivity(self):
        from application.worker import _source_updated_at, graph_extraction_key

        sid = "11111111-1111-1111-1111-111111111111"
        key_a = graph_extraction_key(
            sid, _source_updated_at({"updated_at": "2026-06-23T00:00:00+00:00"})
        )
        key_b = graph_extraction_key(
            sid, _source_updated_at({"updated_at": "2026-06-23T00:00:01+00:00"})
        )
        key_a_again = graph_extraction_key(
            sid, _source_updated_at({"updated_at": "2026-06-23T00:00:00+00:00"})
        )

        assert key_a.startswith(f"extract-graph:{sid}:")
        # A changed ``updated_at`` (re-ingest/re-enable) yields a fresh key.
        assert key_a != key_b
        # The same state collapses to one key (concurrent dups dedupe).
        assert key_a == key_a_again

    def test_falls_back_to_date(self):
        from application.worker import _source_updated_at

        assert _source_updated_at({"date": "2026-06-23T00:00:00+00:00"}) == (
            "2026-06-23T00:00:00+00:00"
        )
        assert _source_updated_at({"updated_at": None, "date": "x"}) == "x"
        assert _source_updated_at(None) == ""


@pytest.mark.unit
class TestRemoteWorkerEnqueuesGraphExtraction:
    def test_graphrag_source_enqueues_after_embed(
        self, task_self, pg_conn, patch_worker_db, monkeypatch,
        _mock_remote_pipeline,
    ):
        from application import worker

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        delay = _patch_delay(monkeypatch)

        config = {"kind": "graphrag", "retrieval": {"retriever": "graphrag"}}
        sid = _seed_source(pg_conn, "bob", config)

        worker.remote_worker(
            task_self,
            {"urls": ["http://example.com"]},
            "graph-remote",
            "bob",
            "crawler",
            directory="temp",
            retriever="classic",
            operation_mode="upload",
            config=config,
            source_id=sid,
        )

        delay.assert_called_once()
        assert delay.call_args.args[0] == sid
        assert delay.call_args.args[1] == "bob"
        key = delay.call_args.kwargs["idempotency_key"]
        assert key.startswith(f"extract-graph:{sid}:")

    def test_same_state_dedupes_to_one_key(
        self, task_self, pg_conn, patch_worker_db, monkeypatch,
        _mock_remote_pipeline,
    ):
        """Two enqueues for the same source state share a key (concurrent dups)."""
        from application import worker

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        delay = _patch_delay(monkeypatch)

        config = {"kind": "graphrag", "retrieval": {"retriever": "graphrag"}}
        sid = _seed_source(pg_conn, "bob", config)

        def _run():
            worker.remote_worker(
                task_self,
                {"urls": ["http://example.com"]},
                "graph-remote",
                "bob",
                "crawler",
                directory="temp",
                retriever="classic",
                operation_mode="upload",
                config=config,
                source_id=sid,
            )
            return delay.call_args.kwargs["idempotency_key"]

        assert _run() == _run()

    def test_resets_graph_before_enqueue(
        self, task_self, pg_conn, patch_worker_db, monkeypatch,
        _mock_remote_pipeline,
    ):
        """A re-ingest clears the prior graph before re-enqueuing extraction."""
        from application import worker

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        reset = MagicMock(name="reset_graph")
        monkeypatch.setattr(worker, "_reset_graph_for_source", reset)
        delay = _patch_delay(monkeypatch)

        config = {"kind": "graphrag", "retrieval": {"retriever": "graphrag"}}
        sid = _seed_source(pg_conn, "bob", config)

        worker.remote_worker(
            task_self,
            {"urls": ["http://example.com"]},
            "graph-remote",
            "bob",
            "crawler",
            directory="temp",
            retriever="classic",
            operation_mode="upload",
            config=config,
            source_id=sid,
        )

        reset.assert_called_once_with(sid)
        delay.assert_called_once()

    def test_classic_source_does_not_enqueue(
        self, task_self, pg_conn, patch_worker_db, monkeypatch,
        _mock_remote_pipeline,
    ):
        from application import worker

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        delay = _patch_delay(monkeypatch)

        sid = _seed_source(pg_conn, "bob", {"kind": "classic"})

        worker.remote_worker(
            task_self,
            {"urls": ["http://example.com"]},
            "classic-remote",
            "bob",
            "crawler",
            directory="temp",
            retriever="classic",
            operation_mode="upload",
            config={"kind": "classic"},
            source_id=sid,
        )

        delay.assert_not_called()

    def test_graphrag_unavailable_does_not_enqueue(
        self, task_self, pg_conn, patch_worker_db, monkeypatch,
        _mock_remote_pipeline,
    ):
        from application import worker

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: False
        )
        delay = _patch_delay(monkeypatch)

        config = {"kind": "graphrag", "retrieval": {"retriever": "graphrag"}}
        sid = _seed_source(pg_conn, "bob", config)

        worker.remote_worker(
            task_self,
            {"urls": ["http://example.com"]},
            "graph-remote",
            "bob",
            "crawler",
            directory="temp",
            retriever="classic",
            operation_mode="upload",
            config=config,
            source_id=sid,
        )

        delay.assert_not_called()


@pytest.mark.unit
class TestEnqueueIsolatesBrokerFailures:
    def test_delay_exception_does_not_propagate(
        self, pg_conn, patch_worker_db, monkeypatch
    ):
        """A broker hiccup in ``.delay`` must not fail an otherwise-good ingest."""
        from application import worker
        from application.storage.db.source_config import SourceConfig

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        monkeypatch.setattr(
            worker, "_reset_graph_for_source", lambda *a, **kw: None
        )

        def _boom(*a, **kw):
            raise RuntimeError("broker down")

        monkeypatch.setattr(
            "application.api.user.tasks.extract_graph.delay", _boom
        )

        config = {"kind": "graphrag", "retrieval": {"retriever": "graphrag"}}
        sid = _seed_source(pg_conn, "bob", config)

        worker._maybe_enqueue_graph_extraction(
            SourceConfig.parse(config), sid, "bob"
        )

    def test_updated_at_read_exception_does_not_propagate(
        self, pg_conn, patch_worker_db, monkeypatch
    ):
        """A DB hiccup reading ``updated_at`` must also be swallowed."""
        from application import worker
        from application.storage.db.source_config import SourceConfig

        monkeypatch.setattr(
            "application.graphrag.graphrag_available", lambda: True
        )
        monkeypatch.setattr(
            worker, "_reset_graph_for_source", lambda *a, **kw: None
        )
        delay = _patch_delay(monkeypatch)

        def _boom(self, source_id, user_id):
            raise RuntimeError("pg down")

        monkeypatch.setattr(SourcesRepository, "get_any", _boom)

        config = {"kind": "graphrag", "retrieval": {"retriever": "graphrag"}}
        sid = _seed_source(pg_conn, "bob", config)

        worker._maybe_enqueue_graph_extraction(
            SourceConfig.parse(config), sid, "bob"
        )

        delay.assert_not_called()
