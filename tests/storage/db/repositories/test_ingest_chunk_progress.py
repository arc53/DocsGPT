"""Tests for IngestChunkProgressRepository against ephemeral Postgres."""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.ingest_chunk_progress import (
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
