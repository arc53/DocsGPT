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

    def test_a_long_overdue_sync_is_listed_but_not_counted(self, pg_conn, monkeypatch):
        # Beat stopped two days ago: Up next says so, but, as on the
        # calendar, nothing is planned for the next 24 hours.
        _source(pg_conn, "Carrier portal")
        current = datetime.now(timezone.utc)
        monkeypatch.setattr(activity_now, "next_sync_times", lambda: {"daily": current - timedelta(days=2)})
        snap = activity_now.build_now(pg_conn, "u1", now=current)
        assert [item["kind"] for item in snap["up_next"]] == ["sync"]
        assert snap["up_next"][0]["runs_in_window"] == 0
        assert snap["stats"]["next_24h"] == 0

    def test_a_sync_just_late_still_counts(self, pg_conn, monkeypatch):
        _source(pg_conn, "Carrier portal")
        current = datetime.now(timezone.utc)
        monkeypatch.setattr(activity_now, "next_sync_times", lambda: {"daily": current - timedelta(minutes=5)})
        snap = activity_now.build_now(pg_conn, "u1", now=current)
        assert snap["stats"]["next_24h"] == 1


class TestSyncSchedule:
    def test_each_frequency_has_its_next_time_and_interval(self):
        entries = {"schedule-syncs-weekly": _entry(NOW - timedelta(days=2), timedelta(weeks=1))}
        schedule = syncs.sync_schedule(load=lambda name: entries.get(name))
        assert schedule == {"weekly": (NOW + timedelta(days=5), timedelta(weeks=1))}

    def test_beat_is_read_once_a_minute(self, monkeypatch):
        # Every Now load and calendar window asks; the entries move once a day.
        reads = []
        clock = [1000.0]
        entry = _entry(NOW - timedelta(hours=20))
        monkeypatch.setattr(syncs, "_load_entry", lambda name: reads.append(name) or entry)
        monkeypatch.setattr(syncs.time, "monotonic", lambda: clock[0])
        monkeypatch.setattr(syncs, "_cached", None)
        first = syncs.sync_schedule()
        assert syncs.sync_schedule() == first
        assert len(reads) == len(syncs.FREQUENCIES)
        clock[0] += syncs.SCHEDULE_CACHE_SECONDS + 1
        syncs.sync_schedule()
        assert len(reads) == 2 * len(syncs.FREQUENCIES)


class TestCalendarSlots:
    WEEK = (NOW, NOW + timedelta(days=7))  # Wed 12:00 to the next Wed 12:00

    def test_one_event_per_firing_with_its_sources(self, pg_conn):
        _source(pg_conn, "Carrier portal")
        paused = _source(pg_conn, "Shared drive", type="s3")
        _connect(pg_conn, paused, paused=True)
        _source(pg_conn, "Customs handbook", "weekly")
        schedule = {
            "daily": (NOW + timedelta(hours=15), timedelta(days=1)),
            "weekly": (NOW + timedelta(days=1, hours=15), timedelta(weeks=1)),
        }
        events = syncs.calendar_slots(pg_conn, "u1", *self.WEEK, schedule, now=NOW)
        daily = [e for e in events if e["frequency"] == "daily"]
        weekly = [e for e in events if e["frequency"] == "weekly"]
        assert len(daily) == 7
        assert len(weekly) == 1
        event = daily[0]
        assert event["kind"] == "sync"
        assert event["schedule_id"] == "sync:daily"
        assert event["state"] == "planned"
        assert event["frequent"] is False
        assert event["at"] == (NOW + timedelta(hours=15)).isoformat()
        by_name = {source["name"]: source for source in event["sources"]}
        assert by_name["Shared drive"]["blocked"] is True
        assert by_name["Carrier portal"]["blocked"] is False
        assert by_name["Carrier portal"]["last_synced_at"]

    def test_only_future_slots(self, pg_conn):
        _source(pg_conn, "Carrier portal")
        # Beat is behind: its next time already passed, so nothing is planned.
        overdue = {"daily": (NOW - timedelta(hours=2), timedelta(days=1))}
        assert syncs.calendar_slots(pg_conn, "u1", *self.WEEK, overdue, now=NOW) == []

    def test_a_beat_tick_late_keeps_the_series(self, pg_conn):
        # Beat fires a little after the time and only then moves last_run_at;
        # a calendar loaded in between must still show the frequency.
        _source(pg_conn, "Carrier portal")
        late = NOW - timedelta(minutes=1)
        schedule = {"daily": (late, timedelta(days=1))}
        window = (NOW - timedelta(days=1), NOW + timedelta(days=6))
        events = syncs.calendar_slots(pg_conn, "u1", *window, schedule, now=NOW)
        assert [e["at"] for e in events] == [(late + timedelta(days=n)).isoformat() for n in range(7)]

    def test_a_frequency_with_no_sources_has_no_slots(self, pg_conn):
        _source(pg_conn, "Carrier portal")
        schedule = {"weekly": (NOW + timedelta(hours=1), timedelta(weeks=1))}
        assert syncs.calendar_slots(pg_conn, "u1", *self.WEEK, schedule, now=NOW) == []
