"""Tests for knowledge syncs in Activity: when each frequency syncs next, and
which of a user's sources sync then."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from docsgpt.activity import now as activity_now
from docsgpt.activity import syncs
from docsgpt.storage.db.repositories.sources import SourcesRepository

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _entry(last_run_at, every=timedelta(days=1)):
    return SimpleNamespace(last_run_at=last_run_at, schedule=SimpleNamespace(run_every=every))


class TestNextSyncTimes:
    def test_last_run_plus_its_interval(self):
        entries = {
            "schedule-syncs-daily": _entry(NOW - timedelta(hours=20)),
            "schedule-syncs-weekly": _entry(NOW - timedelta(days=2), timedelta(weeks=1)),
        }
        times = syncs.next_sync_times(load=lambda name: entries[name] if name in entries else None)
        assert times == {"daily": NOW + timedelta(hours=4), "weekly": NOW + timedelta(days=5)}

    def test_a_stopped_scheduler_reads_as_overdue_not_now(self):
        times = syncs.next_sync_times(load=lambda name: _entry(NOW - timedelta(days=3)))
        assert times["daily"] == NOW - timedelta(days=2)

    def test_a_naive_time_is_utc(self):
        times = syncs.next_sync_times(load=lambda name: _entry(datetime(2026, 10, 14, 1, 0)))
        assert times["daily"] == datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)

    def test_never_run_missing_or_unreadable_entries_have_no_time(self):
        def load(name):
            if name == "schedule-syncs-daily":
                return _entry(None)
            if name == "schedule-syncs-weekly":
                raise RuntimeError("redis down")
            return None

        assert syncs.next_sync_times(load=load) == {}


def _source(conn, name: str, frequency: str = "daily", user_id: str = "u1", **extra) -> str:
    source = SourcesRepository(conn).create(name, user_id=user_id, sync_frequency=frequency, **extra)
    return str(source["id"])


def _connect(conn, source_id: str, *, paused: bool = False) -> None:
    connection = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, status, account_label) "
            "VALUES ('u1', 'google_drive', 'active', :label) RETURNING id"
        ),
        {"label": source_id},
    ).scalar()
    conn.execute(
        text(
            "UPDATE sources SET connection_id = :c, metadata = CAST(:m AS jsonb) "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"c": connection, "id": source_id, "m": '{"sync_state": "paused_reconnect"}' if paused else "{}"},
    )


class TestDueBatches:
    def test_one_batch_per_frequency_due_in_the_window(self, pg_conn):
        _source(pg_conn, "Carrier portal")
        _source(pg_conn, "Rate cards")
        _source(pg_conn, "Customs handbook", "weekly")
        _source(pg_conn, "Never synced", "never")
        _source(pg_conn, "Someone else's", user_id="u2")
        times = {"daily": NOW + timedelta(hours=3), "weekly": NOW + timedelta(days=3)}
        batches = syncs.due_batches(pg_conn, "u1", NOW, NOW + timedelta(hours=24), times)
        assert len(batches) == 1
        batch = batches[0]
        assert batch["kind"] == "sync"
        assert batch["id"] == "sync:daily"
        assert batch["frequency"] == "daily"
        assert batch["next_run_at"] == (NOW + timedelta(hours=3)).isoformat()
        assert batch["sources"] == ["Carrier portal", "Rate cards"]
        assert batch["blocked"] == []

    def test_sources_that_would_be_skipped_are_blocked(self, pg_conn):
        _source(pg_conn, "Carrier portal")
        paused = _source(pg_conn, "Shared drive", type="s3")
        _connect(pg_conn, paused, paused=True)
        _source(pg_conn, "Old drive folder", type="connector:google_drive")
        _source(pg_conn, "Roadmap", type="linear")
        connected = _source(pg_conn, "Team drive", type="connector:google_drive")
        _connect(pg_conn, connected)
        batch = syncs.due_batches(pg_conn, "u1", NOW, NOW + timedelta(hours=24), {"daily": NOW})[0]
        assert batch["sources"] == ["Carrier portal", "Team drive"]
        assert batch["blocked"] == ["Old drive folder", "Roadmap", "Shared drive"]

    def test_an_overdue_batch_is_listed(self, pg_conn):
        _source(pg_conn, "Carrier portal")
        batches = syncs.due_batches(pg_conn, "u1", NOW, NOW + timedelta(hours=24), {"daily": NOW - timedelta(days=2)})
        assert [batch["frequency"] for batch in batches] == ["daily"]

    def test_no_time_no_batch(self, pg_conn):
        _source(pg_conn, "Carrier portal")
        assert syncs.due_batches(pg_conn, "u1", NOW, NOW + timedelta(hours=24), {}) == []

    def test_mirrors_the_workers_connection_only_loaders(self):
        from docsgpt.worker import _CONNECTION_ONLY_LOADERS

        assert syncs.CONNECTION_ONLY_LOADERS == _CONNECTION_ONLY_LOADERS


class TestUpNext:
    @pytest.fixture(autouse=True)
    def _quiet(self, monkeypatch):
        monkeypatch.setattr(activity_now, "list_runs", lambda user_id: [])

    def test_syncs_and_schedules_share_up_next(self, pg_conn, monkeypatch):
        _source(pg_conn, "Carrier portal")
        current = datetime.now(timezone.utc)
        monkeypatch.setattr(activity_now, "next_sync_times", lambda: {"daily": current + timedelta(hours=2)})
        snap = activity_now.build_now(pg_conn, "u1", now=current)
        assert [item["kind"] for item in snap["up_next"]] == ["sync"]
        assert snap["up_next"][0]["sources"] == ["Carrier portal"]
        assert snap["stats"]["next_24h"] == 1


class TestCalendarSyncs:
    def test_each_sync_carries_its_next_time(self, pg_conn, monkeypatch):
        from docsgpt.activity import planned

        _source(pg_conn, "Carrier portal")
        _source(pg_conn, "Customs handbook", "weekly")
        monkeypatch.setattr(planned, "next_sync_times", lambda: {"daily": NOW + timedelta(hours=3)})
        result = planned.build_planned(pg_conn, "u1", NOW, NOW + timedelta(days=7), now=NOW)
        by_name = {sync["name"]: sync for sync in result["syncs"]}
        assert by_name["Carrier portal"]["next_sync_at"] == (NOW + timedelta(hours=3)).isoformat()
        assert by_name["Customs handbook"]["next_sync_at"] is None
