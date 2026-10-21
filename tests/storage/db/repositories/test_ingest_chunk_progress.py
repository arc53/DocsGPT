"""Tests for IngestChunkProgressRepository against ephemeral Postgres."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.storage.db.repositories.ingest_chunk_progress import (
    IngestChunkProgressRepository,
)


def _status(conn, source_id: str) -> str:
    return conn.execute(
        text(
            "SELECT status FROM ingest_chunk_progress "
            "WHERE source_id = CAST(:sid AS uuid)"
        ),
        {"sid": source_id},
    ).scalar()


def _mark_stalled(conn, source_id: str) -> None:
    conn.execute(
        text(
            "UPDATE ingest_chunk_progress SET status = 'stalled' "
            "WHERE source_id = CAST(:sid AS uuid)"
        ),
        {"sid": source_id},
    )


class TestInitProgressStatus:
    def test_new_row_starts_active(self, pg_conn):
        sid = "3c000000-0000-0000-0000-0000000000c1"
        IngestChunkProgressRepository(pg_conn).init_progress(sid, 10, "att-1")
        assert _status(pg_conn, sid) == "active"

    def test_reingest_resets_stalled_to_active(self, pg_conn):
        """A reconciler-escalated 'stalled' row flips back to 'active'
        when the source is reingested under a fresh attempt id.
        """
        sid = "3c000000-0000-0000-0000-0000000000c2"
        repo = IngestChunkProgressRepository(pg_conn)
        repo.init_progress(sid, 10, "att-1")
        _mark_stalled(pg_conn, sid)

        repo.init_progress(sid, 10, "att-2")
        assert _status(pg_conn, sid) == "active"

    def test_same_attempt_retry_also_clears_stalled(self, pg_conn):
        """A same-attempt resume (Celery autoretry) also clears a stale
        'stalled' flag — the task is running again.
        """
        sid = "3c000000-0000-0000-0000-0000000000c3"
        repo = IngestChunkProgressRepository(pg_conn)
        repo.init_progress(sid, 10, "att-1")
        _mark_stalled(pg_conn, sid)

        repo.init_progress(sid, 10, "att-1")
        assert _status(pg_conn, sid) == "active"


class TestDelete:
    def test_delete_removes_row(self, pg_conn):
        sid = "3c000000-0000-0000-0000-0000000000d1"
        repo = IngestChunkProgressRepository(pg_conn)
        repo.init_progress(sid, 10, "att-1")

        assert repo.delete(sid) is True
        assert repo.get_progress(sid) is None

    def test_delete_missing_row_returns_false(self, pg_conn):
        repo = IngestChunkProgressRepository(pg_conn)
        assert repo.delete("3c000000-0000-0000-0000-0000000000df") is False


class TestMarkFailed:
    """A failed ingest closes its checkpoint at once, as ``'stalled'``."""

    def _row(self, conn, sid: str, *, done: int, total: int = 10) -> None:
        IngestChunkProgressRepository(conn).init_progress(sid, total, "att-1")
        conn.execute(
            text(
                "UPDATE ingest_chunk_progress SET embedded_chunks = :done "
                "WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": sid, "done": done},
        )

    def test_closes_an_unfinished_row(self, pg_conn):
        sid = "3c000000-0000-0000-0000-0000000000d1"
        self._row(pg_conn, sid, done=4)
        assert IngestChunkProgressRepository(pg_conn).mark_failed(sid) is True
        assert _status(pg_conn, sid) == "stalled"

    def test_leaves_a_finished_row_alone(self, pg_conn):
        # A failure after embedding (say, the index upload) leaves the
        # chunks done; the row is not what failed.
        sid = "3c000000-0000-0000-0000-0000000000d2"
        self._row(pg_conn, sid, done=10)
        assert IngestChunkProgressRepository(pg_conn).mark_failed(sid) is False
        assert _status(pg_conn, sid) == "active"

    def test_no_row_is_a_no_op(self, pg_conn):
        # A failure while the files are still read: no checkpoint yet.
        sid = "3c000000-0000-0000-0000-0000000000d3"
        assert IngestChunkProgressRepository(pg_conn).mark_failed(sid) is False

    def test_a_retry_reopens_it(self, pg_conn):
        sid = "3c000000-0000-0000-0000-0000000000d4"
        self._row(pg_conn, sid, done=4)
        repo = IngestChunkProgressRepository(pg_conn)
        repo.mark_failed(sid)
        row = repo.init_progress(sid, 10, "att-1")
        assert row["status"] == "active"
        # Same attempt: the checkpoint survives the failure.
        assert row["embedded_chunks"] == 4

    def test_a_chunk_from_a_live_ingest_reopens_it(self, pg_conn):
        # Another ingest of the same source failed and closed the row while
        # this one was still embedding; its next chunk says it is alive.
        sid = "3c000000-0000-0000-0000-0000000000d5"
        self._row(pg_conn, sid, done=4)
        repo = IngestChunkProgressRepository(pg_conn)
        repo.mark_failed(sid)
        repo.record_chunk(sid, last_index=4, embedded_chunks=5)
        assert _status(pg_conn, sid) == "active"
