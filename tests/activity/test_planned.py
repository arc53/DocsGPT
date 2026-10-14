"""Tests for the Activity › Calendar window against an ephemeral Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.activity import planned
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository

# A Monday, so a week window is Mon 00:00 to the next Mon 00:00.
MONDAY = datetime(2030, 3, 4, tzinfo=timezone.utc)
NOW = MONDAY + timedelta(days=1, hours=14)  # Tue 14:00


def _agent(conn, name="Desk") -> str:
    return str(
        conn.execute(
            text("INSERT INTO agents (user_id, name, status) VALUES ('u1', :n, 'published') RETURNING id"),
            {"n": name},
        ).scalar()
    )


def _week(conn):
    return planned.build_planned(conn, "u1", MONDAY, MONDAY + timedelta(days=7), now=NOW)


def _schedule(conn, **kw):
    kw.setdefault("cron", "0 15 * * 1-5")
    created = SchedulesRepository(conn).create(
        "u1", kw.pop("agent_id", None), kw.pop("trigger_type", "recurring"), kw.pop("instruction", "x"), **kw
    )
    # Created long before the window, as a real schedule would be.
    conn.execute(
        text("UPDATE schedules SET created_at = :t WHERE id = CAST(:id AS uuid)"),
        {"t": MONDAY - timedelta(days=30), "id": str(created["id"])},
    )
    return created


class TestWindow:
    def test_parses_and_checks(self):
        start, end = planned.parse_window("2030-03-04T00:00:00Z", "2030-03-11T00:00:00Z")
        assert end - start == timedelta(days=7)

    @pytest.mark.parametrize(
        "raw_from, raw_to",
        [(None, "2030-03-11"), ("nope", "2030-03-11"), ("2030-03-11", "2030-03-04"), ("2030-01-01", "2030-06-01")],
    )
    def test_rejects_bad_windows(self, raw_from, raw_to):
        with pytest.raises(planned.WindowError):
            planned.parse_window(raw_from, raw_to)


class TestPlannedSlots:
    def test_expands_future_weekday_runs_only(self, pg_conn):
        _schedule(pg_conn, agent_id=_agent(pg_conn, "Support"), name="Daily support digest")
        events = _week(pg_conn)["events"]
        times = [e["at"] for e in events]
        # Tue 15:00 (after now) through Fri; Mon's slot is past and had no run.
        assert len(times) == 4
        assert times[0].startswith("2030-03-05T15:00")
        assert {e["state"] for e in events} == {"planned"}
        assert events[0]["agent_name"] == "Support"
        assert events[0]["cron"] == "0 15 * * 1-5"

    def test_a_paused_schedule_shows_paused_slots(self, pg_conn):
        _schedule(pg_conn, name="Prospect news scan", cron="0 7 * * 1-5", status="paused")
        events = _week(pg_conn)["events"]
        assert len(events) == 3  # Wed, Thu, Fri 07:00
        assert {e["state"] for e in events} == {"paused"}

    def test_a_one_time_task_is_one_slot(self, pg_conn):
        conv = str(ConversationsRepository(pg_conn).create("u1", "Halvorsen QBR")["id"])
        at = MONDAY + timedelta(days=1, hours=17)
        _schedule(
            pg_conn, trigger_type="once", cron=None, run_at=at, next_run_at=at,
            origin_conversation_id=conv, name="Remind me",
        )
        events = _week(pg_conn)["events"]
        assert len(events) == 1
        assert events[0]["trigger_type"] == "once"
        assert events[0]["origin_conversation_name"] == "Halvorsen QBR"

    def test_marks_hourly_schedules_frequent(self, pg_conn):
        _schedule(pg_conn, name="Inbox triage", cron="0 8-18 * * 1-5")
        events = _week(pg_conn)["events"]
        assert events and all(e["frequent"] for e in events)

    def test_end_at_stops_the_slots(self, pg_conn):
        _schedule(pg_conn, end_at=MONDAY + timedelta(days=3))
        assert len(_week(pg_conn)["events"]) == 2  # Tue and Wed only


class TestPastRuns:
    def test_a_run_replaces_its_slot_and_keeps_its_status(self, pg_conn):
        schedule = _schedule(pg_conn, cron="0 7 * * 1-5", name="Prospect news scan")
        runs = ScheduleRunsRepository(pg_conn)
        monday_run = runs.record_pending(str(schedule["id"]), "u1", None, MONDAY + timedelta(hours=7))
        runs.update(str(monday_run["id"]), {"status": "failed", "error_type": "auth_expired"})
        events = _week(pg_conn)["events"]
        first = events[0]
        assert first["state"] == "failed"
        assert first["run_id"] == str(monday_run["id"])
        assert first["error_type"] == "auth_expired"
        assert [e["state"] for e in events[1:]] == ["planned"] * 3


class TestMonitorsAndSyncs:
    def test_monitors_are_ranges(self, pg_conn):
        conv = str(ConversationsRepository(pg_conn).create("u1", "Rotterdam")["id"])
        MonitorsRepository(pg_conn).create(
            user_id="u1", conversation_id=conv, agent_id=None, description="Rotterdam congestion",
            source_type="webpage", spec={"source": {"type": "webpage", "url": "https://example.com"}},
            on_match="tell me", end_at=MONDAY + timedelta(days=4), next_run_at=NOW,
            max_wakes=1, interval_seconds=1800,
        )
        week = _week(pg_conn)
        assert week["events"] == []
        assert [m["description"] for m in week["monitors"]] == ["Rotterdam congestion"]
        assert week["monitors"][0]["interval_seconds"] == 1800

    def test_syncs_are_listed_by_frequency(self, pg_conn):
        SourcesRepository(pg_conn).create("Carrier contracts", user_id="u1", sync_frequency="daily")
        SourcesRepository(pg_conn).create("Static PDF", user_id="u1", sync_frequency="never")
        assert [(s["name"], s["frequency"]) for s in _week(pg_conn)["syncs"]] == [("Carrier contracts", "daily")]


class TestCap:
    def test_a_minute_cron_is_truncated(self, pg_conn, monkeypatch):
        monkeypatch.setattr(planned, "MAX_SLOTS_PER_SCHEDULE", 50)
        schedule = _schedule(pg_conn, cron="* * * * *")
        week = _week(pg_conn)
        assert len(week["events"]) == 50
        assert week["truncated"] == [str(schedule["id"])]
