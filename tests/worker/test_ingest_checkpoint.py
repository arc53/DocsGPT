"""Tests for the ingest chunk checkpoint and heartbeat.

* ``embed_and_store_documents`` writes/reads ``ingest_chunk_progress``;
  fresh runs end with ``embedded_chunks=N`` and resumes seeded at
  ``last_index=k`` embed only chunks ``k+1..N-1``.
* ``_ingest_heartbeat_loop`` is the daemon body that bumps ``last_updated``.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Connection, text


@dataclass
class _LCDoc:
    """Tiny stand-in for a LangChain document — only the fields the loop reads."""
    page_content: str
    metadata: dict = field(default_factory=dict)


@pytest.fixture
def patch_pipeline_db(pg_conn, monkeypatch):
    """Make ``db_session`` inside the embedding pipeline yield ``pg_conn``."""

    @contextmanager
    def _use_pg_conn() -> Iterator[Connection]:
        yield pg_conn

    monkeypatch.setattr(
        "application.parser.embedding_pipeline.db_session", _use_pg_conn
    )


@pytest.fixture
def faiss_settings(monkeypatch):
    """Force the embed pipeline down the faiss branch with a stub vector store."""
    from application.parser import embedding_pipeline as ep

    monkeypatch.setattr(ep.settings, "VECTOR_STORE", "faiss", raising=False)

    fake_store = MagicMock(name="vector_store")
    monkeypatch.setattr(
        ep.VectorCreator, "create_vectorstore", lambda *a, **kw: fake_store
    )
    return fake_store


def _seed_progress_row(
    pg_conn, source_id: str, total: int, last_index: int,
    attempt_id: str | None = None,
) -> None:
    pg_conn.execute(
        text(
            """
            INSERT INTO ingest_chunk_progress
                (source_id, total_chunks, embedded_chunks, last_index,
                 attempt_id, last_updated)
            VALUES (CAST(:sid AS uuid), :total, :emb, :idx, :att, now())
            """
        ),
        {
            "sid": source_id,
            "total": total,
            "emb": last_index + 1,
            "idx": last_index,
            "att": attempt_id,
        },
    )


def _make_docs(n: int) -> list:
    return [_LCDoc(page_content=f"chunk-{i}", metadata={"i": i}) for i in range(n)]


@pytest.mark.unit
class TestEmbedCheckpoint:
    def test_fresh_run_records_progress_to_completion(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        source_id = str(uuid.uuid4())
        docs = _make_docs(5)
        captured_chunks: list[str] = []

        def _fake_add(store, doc, sid):
            captured_chunks.append(doc.page_content)

        # The retry decorator wraps the real fn. Patch the module-level name
        # so our loop calls the spy directly.
        import application.parser.embedding_pipeline as ep_mod

        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = _fake_add
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock()
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        # Faiss seeds the store with docs[0]; the loop picks up at idx=1.
        assert captured_chunks == ["chunk-1", "chunk-2", "chunk-3", "chunk-4"]

        row = pg_conn.execute(
            text(
                "SELECT total_chunks, embedded_chunks, last_index "
                "FROM ingest_chunk_progress WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": source_id},
        ).fetchone()
        assert row is not None
        m = dict(row._mapping)
        # Loop wrote the last record at idx=4 over the full 5-doc list.
        assert m["total_chunks"] == 5
        assert m["embedded_chunks"] == 5
        assert m["last_index"] == 4

    def test_resume_skips_already_embedded_chunks(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        """Pre-seed progress at ``last_index=2`` and assert chunks 0..2 are not re-embedded."""
        import application.parser.embedding_pipeline as ep_mod

        source_id = str(uuid.uuid4())
        docs = _make_docs(6)
        # Seed: last_index=2 means chunks at original indices 0..2 are done;
        # resume should pick up at idx=3 (chunks 3, 4, 5).
        _seed_progress_row(pg_conn, source_id, total=6, last_index=2)

        captured_chunks: list[str] = []

        def _fake_add(store, doc, sid):
            captured_chunks.append(doc.page_content)

        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = _fake_add
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock()
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        # On resume the FAISS store is loaded from storage (no docs_init);
        # the loop iterates the un-popped docs list starting at resume_index.
        assert captured_chunks == ["chunk-3", "chunk-4", "chunk-5"]

        row = pg_conn.execute(
            text(
                "SELECT embedded_chunks, last_index "
                "FROM ingest_chunk_progress WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": source_id},
        ).fetchone()
        m = dict(row._mapping)
        assert m["last_index"] == 5
        assert m["embedded_chunks"] == 6

    def test_faiss_resume_loads_existing_index_without_docs_init(
        self, pg_conn, patch_pipeline_db, monkeypatch, tmp_path
    ):
        """Resuming a FAISS run must NOT pass ``docs_init`` (which would
        overwrite the previously-saved index with a partial reset).
        """
        import application.parser.embedding_pipeline as ep_mod

        monkeypatch.setattr(ep_mod.settings, "VECTOR_STORE", "faiss", raising=False)

        captured_kwargs: list[dict] = []

        def _capture_create(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return MagicMock(name="vector_store")

        monkeypatch.setattr(
            ep_mod.VectorCreator, "create_vectorstore", _capture_create,
        )

        source_id = str(uuid.uuid4())
        docs = _make_docs(6)
        _seed_progress_row(pg_conn, source_id, total=6, last_index=2)

        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = lambda store, doc, sid: None
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock()
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        assert len(captured_kwargs) == 1
        # No ``docs_init`` on resume — this is what triggers FaissStore to
        # load the existing index from storage rather than minting a new
        # single-doc store.
        assert "docs_init" not in captured_kwargs[0]

    def test_resume_keeps_existing_index_for_non_faiss(
        self, pg_conn, patch_pipeline_db, monkeypatch, tmp_path
    ):
        """Non-faiss stores must NOT have ``delete_index`` called on resume."""
        import application.parser.embedding_pipeline as ep_mod

        monkeypatch.setattr(ep_mod.settings, "VECTOR_STORE", "qdrant", raising=False)

        fake_store = MagicMock(name="vector_store")
        monkeypatch.setattr(
            ep_mod.VectorCreator, "create_vectorstore", lambda *a, **kw: fake_store
        )

        source_id = str(uuid.uuid4())
        docs = _make_docs(4)
        _seed_progress_row(pg_conn, source_id, total=4, last_index=1)

        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = lambda store, doc, sid: None
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock()
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        fake_store.delete_index.assert_not_called()

    def test_same_attempt_id_resumes_from_checkpoint(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        """A Celery autoretry passes the same ``self.request.id`` and
        must resume from the persisted ``last_index``.
        """
        import application.parser.embedding_pipeline as ep_mod

        source_id = str(uuid.uuid4())
        docs = _make_docs(6)
        _seed_progress_row(
            pg_conn, source_id, total=6, last_index=2, attempt_id="att-A",
        )

        captured: list[str] = []
        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = (
            lambda store, doc, sid: captured.append(doc.page_content)
        )
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock(),
                attempt_id="att-A",
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        # Same attempt → resume past the last persisted index.
        assert captured == ["chunk-3", "chunk-4", "chunk-5"]

    def test_different_attempt_id_resets_checkpoint(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        """A fresh sync/reingest passes a new ``attempt_id`` and must
        reset the checkpoint so the index is rebuilt from chunk 0.
        """
        import application.parser.embedding_pipeline as ep_mod

        source_id = str(uuid.uuid4())
        # Prior run completed: last_index=4 (chunks 0..4 embedded over a
        # 5-doc list). New run brings 5 fresh docs under a different
        # attempt_id.
        _seed_progress_row(
            pg_conn, source_id, total=5, last_index=4, attempt_id="att-old",
        )
        docs = _make_docs(5)

        captured: list[str] = []
        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = (
            lambda store, doc, sid: captured.append(doc.page_content)
        )
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock(),
                attempt_id="att-new",
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        # Fresh attempt → reset to chunk 0; FAISS branch seeds with
        # docs[0] and the loop picks up at idx=1.
        assert captured == ["chunk-1", "chunk-2", "chunk-3", "chunk-4"]

        # Post-run state belongs to the new attempt.
        row = pg_conn.execute(
            text(
                "SELECT total_chunks, embedded_chunks, last_index, attempt_id "
                "FROM ingest_chunk_progress WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": source_id},
        ).fetchone()
        m = dict(row._mapping)
        assert m["embedded_chunks"] == 5
        assert m["last_index"] == 4
        assert m["attempt_id"] == "att-new"

    def test_completed_checkpoint_does_not_block_fresh_attempt(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        """Regression: a completed-and-cached checkpoint from an earlier
        upload must not silently no-op a later sync. Pre-fix the embed
        loop saw ``loop_start >= total_docs`` and embedded zero chunks,
        leaving stale vectors in place.
        """
        import application.parser.embedding_pipeline as ep_mod

        source_id = str(uuid.uuid4())
        # Upload finished cleanly with 5 chunks; checkpoint reflects done.
        _seed_progress_row(
            pg_conn, source_id, total=5, last_index=4, attempt_id="upload-1",
        )
        # Sync brings the same number of docs (the dangerous case where
        # the old code's ``loop_start >= total_docs`` branch fired).
        docs = _make_docs(5)

        captured: list[str] = []
        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = (
            lambda store, doc, sid: captured.append(doc.page_content)
        )
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock(),
                attempt_id="sync-2",
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        # All non-seed chunks re-embedded under the new attempt.
        assert captured == ["chunk-1", "chunk-2", "chunk-3", "chunk-4"]

    def test_legacy_null_attempt_id_resumes_against_null_caller(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        """Pre-migration rows have ``attempt_id=NULL``; legacy callers
        (or tests) that pass no ``attempt_id`` must still resume against
        them — IS NOT DISTINCT FROM treats NULL/NULL as equal.
        """
        import application.parser.embedding_pipeline as ep_mod

        source_id = str(uuid.uuid4())
        _seed_progress_row(
            pg_conn, source_id, total=4, last_index=1, attempt_id=None,
        )
        docs = _make_docs(4)

        captured: list[str] = []
        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = (
            lambda store, doc, sid: captured.append(doc.page_content)
        )
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock(),
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        # Resumed past last_index=1.
        assert captured == ["chunk-2", "chunk-3"]

    def test_single_chunk_faiss_records_seeded_doc(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        """Regression: a 1-doc FAISS ingest seeds with ``docs[0]`` and
        the loop runs zero iterations. Pre-fix, no ``_record_progress``
        call ever ran, ``embedded_chunks`` stayed at 0, and
        ``assert_index_complete`` raised on every retry until the
        poison-loop guard finalised the row. Post-fix, the seed is
        recorded immediately so ``embedded == total == 1``.
        """
        import application.parser.embedding_pipeline as ep_mod

        source_id = str(uuid.uuid4())
        docs = _make_docs(1)

        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = lambda store, doc, sid: None
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock(),
                attempt_id="att-single",
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        row = pg_conn.execute(
            text(
                "SELECT total_chunks, embedded_chunks, last_index, attempt_id "
                "FROM ingest_chunk_progress WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": source_id},
        ).fetchone()
        assert row is not None
        m = dict(row._mapping)
        assert m["total_chunks"] == 1
        assert m["embedded_chunks"] == 1
        assert m["last_index"] == 0
        assert m["attempt_id"] == "att-single"

        # Tripwire passes — assert_index_complete reads the same row.
        ep_mod.assert_index_complete(source_id)

    def test_multi_chunk_faiss_seed_record_is_overwritten_correctly(
        self, pg_conn, patch_pipeline_db, faiss_settings, tmp_path
    ):
        """The new seed-record call must not break multi-chunk runs:
        the loop's per-iteration record overshoots correctly (counts
        seed + iterations) and the final state is ``embedded=total``.
        """
        import application.parser.embedding_pipeline as ep_mod

        source_id = str(uuid.uuid4())
        docs = _make_docs(4)

        original = ep_mod.add_text_to_store_with_retry
        ep_mod.add_text_to_store_with_retry = lambda store, doc, sid: None
        try:
            ep_mod.embed_and_store_documents(
                docs, str(tmp_path), source_id, MagicMock(),
                attempt_id="att-multi",
            )
        finally:
            ep_mod.add_text_to_store_with_retry = original

        row = pg_conn.execute(
            text(
                "SELECT total_chunks, embedded_chunks, last_index "
                "FROM ingest_chunk_progress WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": source_id},
        ).fetchone()
        m = dict(row._mapping)
        assert m["total_chunks"] == 4
        assert m["embedded_chunks"] == 4
        assert m["last_index"] == 3


@pytest.mark.unit
class TestIngestHeartbeat:
    def test_loop_bumps_last_updated_then_exits(
        self, pg_conn, patch_worker_db, monkeypatch
    ):
        """One tick of the heartbeat must move ``last_updated`` forward."""
        from application import worker

        source_id = str(uuid.uuid4())
        # Seed a row with ``last_updated`` deliberately in the past so we
        # can assert the heartbeat tick moves it forward.
        pg_conn.execute(
            text(
                """
                INSERT INTO ingest_chunk_progress
                    (source_id, total_chunks, embedded_chunks, last_index, last_updated)
                VALUES (CAST(:sid AS uuid), 1, 0, -1, now() - interval '1 hour')
                """
            ),
            {"sid": source_id},
        )
        before = pg_conn.execute(
            text(
                "SELECT last_updated FROM ingest_chunk_progress "
                "WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": source_id},
        ).fetchone()._mapping["last_updated"]

        stop_event = threading.Event()
        # First call returns False -> loop body runs once. Second returns
        # True -> loop exits cleanly.
        wait_returns = iter([False, True])
        monkeypatch.setattr(stop_event, "wait", lambda interval: next(wait_returns))

        worker._ingest_heartbeat_loop(source_id, stop_event, interval=0)

        after = pg_conn.execute(
            text(
                "SELECT last_updated FROM ingest_chunk_progress "
                "WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": source_id},
        ).fetchone()._mapping["last_updated"]
        assert after > before

    def test_loop_swallows_db_errors(self, monkeypatch):
        """A failing DB call must not crash the daemon — it should keep ticking."""
        from application import worker

        @contextmanager
        def _broken_session():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        monkeypatch.setattr(worker, "db_session", _broken_session)

        stop_event = threading.Event()
        wait_returns = iter([False, False, True])
        monkeypatch.setattr(stop_event, "wait", lambda interval: next(wait_returns))

        # Should not raise — failures are logged, loop continues.
        worker._ingest_heartbeat_loop("00000000-0000-0000-0000-000000000000", stop_event, interval=0)

    def test_start_and_stop_helpers_join_quickly(self, monkeypatch):
        """``_start_ingest_heartbeat`` + ``_stop_ingest_heartbeat`` must not hang."""
        from application import worker

        @contextmanager
        def _noop_session():
            yield MagicMock()

        monkeypatch.setattr(worker, "db_session", _noop_session)

        thread, stop_event = worker._start_ingest_heartbeat(
            "00000000-0000-0000-0000-000000000000"
        )
        assert thread.is_alive()
        worker._stop_ingest_heartbeat(thread, stop_event)
        assert not thread.is_alive()
