"""Tests for the sweep that deletes the vectors of ingests that ended without a source."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text


def _seed_progress(
    conn, *, source_id: str, status: str = "stalled", embedded: int = 4, total: int = 40, age_hours: int = 73,
) -> str:
    conn.execute(
        text(
            """
            INSERT INTO ingest_chunk_progress (
                source_id, total_chunks, embedded_chunks, last_index, last_updated, status
            ) VALUES (
                CAST(:sid AS uuid), :total, :embedded, :embedded - 1,
                clock_timestamp() - make_interval(hours => :age), :status
            )
            """
        ),
        {"sid": source_id, "total": total, "embedded": embedded, "age": age_hours, "status": status},
    )
    return source_id


def _seed_source(conn, source_id: str) -> None:
    conn.execute(
        text("INSERT INTO sources (id, user_id, name, type) VALUES (CAST(:id AS uuid), 'u-1', 'doc', 'file')"),
        {"id": source_id},
    )


def _has_progress(conn, source_id: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM ingest_chunk_progress WHERE source_id = CAST(:sid AS uuid)"), {"sid": source_id},
    ).fetchone() is not None


@contextmanager
def _sweep_on(pg_conn, *, purged: int = 7, error: Exception | None = None):
    """Route the sweep onto the test connection and spy on the vector purge."""

    @contextmanager
    def _begin():
        yield pg_conn

    engine = MagicMock()
    engine.begin = _begin
    calls: list[str] = []

    def _purge(source_id: str):
        calls.append(source_id)
        if error is not None:
            raise error
        return purged

    with patch("docsgpt.api.user.ingest_orphans.get_engine", return_value=engine), patch(
        "docsgpt.api.user.ingest_orphans._purge_vectors", side_effect=_purge,
    ):
        yield calls


@pytest.mark.unit
class TestSweepOrphanedIngests:
    def test_a_stalled_ingest_without_a_source_past_the_ttl_is_deleted(self, pg_conn):
        from docsgpt.api.user.ingest_orphans import sweep_orphaned_ingests

        sid = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000001")

        with _sweep_on(pg_conn) as calls:
            summary = sweep_orphaned_ingests()

        assert calls == [sid]
        assert not _has_progress(pg_conn, sid)
        assert summary["orphans_deleted"] == 1
        assert summary["vectors_deleted"] == 7

    def test_a_finished_embed_that_never_got_its_source_is_deleted(self, pg_conn):
        from docsgpt.api.user.ingest_orphans import sweep_orphaned_ingests

        sid = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000002", status="active", embedded=40)

        with _sweep_on(pg_conn) as calls:
            sweep_orphaned_ingests()

        assert calls == [sid]
        assert not _has_progress(pg_conn, sid)

    def test_a_stalled_ingest_with_a_source_is_left_alone(self, pg_conn):
        from docsgpt.api.user.ingest_orphans import sweep_orphaned_ingests

        sid = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000003")
        _seed_source(pg_conn, sid)

        with _sweep_on(pg_conn) as calls:
            summary = sweep_orphaned_ingests()

        assert calls == []
        assert _has_progress(pg_conn, sid)
        assert summary["orphans_deleted"] == 0

    def test_a_stalled_ingest_newer_than_the_ttl_is_left_alone(self, pg_conn):
        from docsgpt.api.user.ingest_orphans import sweep_orphaned_ingests

        sid = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000004", age_hours=71)

        with _sweep_on(pg_conn) as calls:
            sweep_orphaned_ingests()

        assert calls == []
        assert _has_progress(pg_conn, sid)

    def test_an_unfinished_ingest_still_active_is_left_to_the_reconciler(self, pg_conn):
        from docsgpt.api.user.ingest_orphans import sweep_orphaned_ingests

        sid = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000005", status="active")

        with _sweep_on(pg_conn) as calls:
            sweep_orphaned_ingests()

        assert calls == []
        assert _has_progress(pg_conn, sid)

    def test_a_failed_vector_delete_keeps_the_row_for_the_next_run(self, pg_conn):
        from docsgpt.api.user.ingest_orphans import sweep_orphaned_ingests

        sid = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000006")

        with _sweep_on(pg_conn, error=RuntimeError("store down")) as calls:
            summary = sweep_orphaned_ingests()

        assert calls == [sid]
        assert _has_progress(pg_conn, sid)
        assert summary["failed"] == 1

    def test_a_ttl_of_zero_turns_it_off(self, pg_conn, monkeypatch):
        from docsgpt.api.user.ingest_orphans import sweep_orphaned_ingests
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "INGEST_ORPHAN_TTL_HOURS", 0, raising=False)
        sid = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000007")

        with _sweep_on(pg_conn) as calls:
            summary = sweep_orphaned_ingests()

        assert calls == []
        assert _has_progress(pg_conn, sid)
        assert "skipped" in summary


@pytest.mark.unit
class TestPurgeVectors:
    def test_purges_through_the_store_in_batches(self, monkeypatch):
        from docsgpt.api.user import ingest_orphans
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector", raising=False)
        store = MagicMock()
        store.purge_index.return_value = 12
        with patch("docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", return_value=store) as made:
            assert ingest_orphans._purge_vectors("s-1") == 12

        assert made.call_args.kwargs["source_id"] == "s-1"
        store.purge_index.assert_called_once_with(batch_size=ingest_orphans.PURGE_BATCH_SIZE)

    def test_faiss_has_nothing_to_purge(self, monkeypatch):
        from docsgpt.api.user import ingest_orphans
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss", raising=False)
        with patch("docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore") as made:
            assert ingest_orphans._purge_vectors("s-1") == 0
        made.assert_not_called()


@pytest.mark.unit
class TestOrphanReport:
    def test_pgvector_counts_vectors_without_a_source(self, pg_conn, monkeypatch):
        from docsgpt.api.user import ingest_orphans
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector", raising=False)
        stalled = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000011")
        fresh = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000012", age_hours=1)
        kept = "7a000000-0000-0000-0000-000000000013"
        _seed_source(pg_conn, kept)
        counts = {stalled: 30, fresh: 5, kept: 50, "legacy-no-row": 2}

        with patch("docsgpt.vectorstore.pgvector.chunk_counts_by_source", return_value=counts):
            report = {row["source_id"]: row for row in ingest_orphans.orphan_report(pg_conn)}

        assert set(report) == {stalled, fresh, "legacy-no-row"}
        assert report[stalled]["vectors"] == 30
        assert report[stalled]["swept"] is True
        assert report[fresh]["swept"] is False
        assert report["legacy-no-row"]["status"] is None
        assert report["legacy-no-row"]["swept"] is False

    def test_other_stores_list_the_rows_without_counts(self, pg_conn, monkeypatch):
        from docsgpt.api.user import ingest_orphans
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "qdrant", raising=False)
        stalled = _seed_progress(pg_conn, source_id="7a000000-0000-0000-0000-000000000021")

        report = ingest_orphans.orphan_report(pg_conn)

        assert [(r["source_id"], r["vectors"], r["swept"]) for r in report] == [(stalled, None, True)]
