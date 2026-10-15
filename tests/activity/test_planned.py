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
        events = [e for e in _week(pg_conn)["events"] if e["state"] != "missed"]
        times = [e["at"] for e in events]
        # Tue 15:00 (after now) through Fri; Monday's past slot is "missed".
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
        planned_slots = [e for e in _week(pg_conn)["events"] if e["state"] == "planned"]
        assert len(planned_slots) == 2  # Tue and Wed only

    def test_a_run_exactly_at_end_at_is_planned(self, pg_conn):
        # The dispatcher still runs a slot at end_at itself.
        _schedule(pg_conn, end_at=MONDAY + timedelta(days=3, hours=15))
        planned_slots = [e for e in _week(pg_conn)["events"] if e["state"] == "planned"]
        assert [e["at"][:10] for e in planned_slots] == ["2030-03-05", "2030-03-06", "2030-03-07"]


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
        # Tuesday 07:00 is before "now" with no run: missed. Wed to Fri are ahead.
        assert [e["state"] for e in events[1:]] == ["missed", "planned", "planned", "planned"]


class TestMissedRuns:
    def test_a_past_slot_with_no_run_is_missed(self, pg_conn):
        _schedule(pg_conn, name="Daily digest")  # weekdays 15:00, created a month ago
        events = _week(pg_conn)["events"]
        monday = [e for e in events if e["at"].startswith("2030-03-04")]
        assert [e["state"] for e in monday] == ["missed"]
        assert all(e["state"] == "planned" for e in events if e["at"] >= "2030-03-05T15")

    def test_a_slot_that_ran_is_not_missed(self, pg_conn):
        schedule = _schedule(pg_conn, name="Daily digest")
        runs = ScheduleRunsRepository(pg_conn)
        run = runs.record_pending(str(schedule["id"]), "u1", None, MONDAY + timedelta(hours=15))
        runs.update(str(run["id"]), {"status": "success"})
        monday = [e for e in _week(pg_conn)["events"] if e["at"].startswith("2030-03-04")]
        assert [e["state"] for e in monday] == ["success"]

    def test_slots_before_the_schedule_existed_are_not_missed(self, pg_conn):
        schedule = _schedule(pg_conn, name="Daily digest")
        pg_conn.execute(
            text("UPDATE schedules SET created_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": MONDAY + timedelta(days=1), "id": str(schedule["id"])},
        )
        assert not [e for e in _week(pg_conn)["events"] if e["state"] == "missed"]

    def test_slots_before_the_last_plan_change_are_not_missed(self, pg_conn):
        schedule = _schedule(pg_conn, name="Daily digest")
        # An edit of the timing (or a resume) on Tuesday: Monday's slot was
        # planned under the old timing.
        pg_conn.execute(
            text("UPDATE schedules SET plan_changed_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": MONDAY + timedelta(days=1), "id": str(schedule["id"])},
        )
        assert not [e for e in _week(pg_conn)["events"] if e["state"] == "missed"]

    def test_a_dispatcher_write_does_not_hide_missed_slots(self, pg_conn):
        schedule = _schedule(pg_conn, name="Daily digest")
        # The dispatcher recovers Tuesday 13:00 and moves next_run_at past the
        # slots it skipped; the trigger stamps updated_at then. Pinned by hand
        # here, as the test clock is in 2030.
        pg_conn.execute(text("ALTER TABLE schedules DISABLE TRIGGER USER"))
        pg_conn.execute(
            text("UPDATE schedules SET updated_at = :t, last_run_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": MONDAY + timedelta(days=1, hours=13), "id": str(schedule["id"])},
        )
        monday = [e for e in _week(pg_conn)["events"] if e["at"].startswith("2030-03-04")]
        assert [e["state"] for e in monday] == ["missed"]

    def test_a_paused_schedule_has_no_missed_slots(self, pg_conn):
        _schedule(pg_conn, name="Scan", status="paused")
        assert not [e for e in _week(pg_conn)["events"] if e["state"] == "missed"]

    def test_slots_older_than_run_retention_are_not_missed(self, pg_conn):
        # Runs are trimmed after SCHEDULE_RUN_OUTPUT_RETENTION_DAYS, so an
        # older slot with no run may well have run.
        from docsgpt.core.settings import settings

        schedule = _schedule(pg_conn, cron="0 15 * * *")
        pg_conn.execute(
            text("UPDATE schedules SET created_at = :t, plan_changed_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": NOW - timedelta(days=400), "id": str(schedule["id"])},
        )
        horizon = NOW - timedelta(days=settings.SCHEDULE_RUN_OUTPUT_RETENTION_DAYS)
        start = horizon - timedelta(days=20)
        events = planned.build_planned(pg_conn, "u1", start, start + timedelta(days=40), now=NOW)["events"]
        missed = [e["at"] for e in events if e["state"] == "missed"]
        assert len(missed) == 20
        assert min(missed) >= horizon.isoformat()

    def test_a_slot_inside_the_grace_period_is_not_missed_yet(self, pg_conn):
        _schedule(pg_conn, cron="55 13 * * 2")  # Tue 13:55, five minutes before NOW
        # Still planned, not dropped: the calendar keeps the slot until it
        # turns missed (or its run appears).
        assert [(e["at"], e["state"]) for e in _week(pg_conn)["events"] if e["kind"] == "schedule"] == [
            ("2030-03-05T13:55:00+00:00", "planned")
        ]


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

    def test_syncs_are_events_at_their_times(self, pg_conn, monkeypatch):
        SourcesRepository(pg_conn).create("Carrier contracts", user_id="u1", sync_frequency="daily")
        SourcesRepository(pg_conn).create("Static PDF", user_id="u1", sync_frequency="never")
        wednesday = MONDAY + timedelta(days=2, hours=3, minutes=12)
        monkeypatch.setattr(planned, "sync_schedule", lambda: {"daily": (wednesday, timedelta(days=1))})
        week = _week(pg_conn)
        syncs = [e for e in week["events"] if e["kind"] == "sync"]
        # Wed to Sun at 03:12; next Monday is outside the window.
        assert [e["at"] for e in syncs] == [(wednesday + timedelta(days=n)).isoformat() for n in range(5)]
        assert syncs[0]["frequency"] == "daily"
        assert [source["name"] for source in syncs[0]["sources"]] == ["Carrier contracts"]
        assert "syncs" not in week

    def test_schedule_slots_are_marked_as_schedules(self, pg_conn):
        _schedule(pg_conn)
        assert {e["kind"] for e in _week(pg_conn)["events"]} == {"schedule"}


class TestCap:
    def test_schedules_with_the_same_timing_share_one_expansion(self, pg_conn, monkeypatch):
        expanded = []
        real = planned.cron_runs
        monkeypatch.setattr(planned, "cron_runs", lambda *a, **kw: expanded.append(a) or real(*a, **kw))
        for name in ("Digest A", "Digest B", "Digest C"):
            _schedule(pg_conn, name=name)
        events = _week(pg_conn)["events"]
        assert len([e for e in events if e["state"] == "planned"]) == 3 * 4
        # One expansion for the future slots, one for the missed ones.
        assert len(expanded) == 2

    def test_a_minute_cron_is_truncated(self, pg_conn, monkeypatch):
        # Even summed up per day, a frequent schedule lists at most
        # MAX_FREQUENT_SLOTS slots.
        monkeypatch.setattr(planned, "MAX_SLOTS_PER_SCHEDULE", 50)
        monkeypatch.setattr(planned, "MAX_FREQUENT_SLOTS", 100)
        schedule = _schedule(pg_conn, cron="* * * * *")
        week = _week(pg_conn)
        assert sum(e.get("count", 1) for e in week["events"] if e["state"] == "planned") == 100
        assert str(schedule["id"]) in week["truncated"]

    def test_past_runs_are_capped_per_schedule_and_reported(self, pg_conn, monkeypatch):
        # A busy schedule's runs must not crowd out another's, nor leave the
        # days after the cut looking empty with no word of it.
        monkeypatch.setattr(planned, "MAX_SLOTS_PER_SCHEDULE", 5)
        busy = _schedule(pg_conn, cron="0 */2 * * *", name="Inbox triage")  # not frequent
        daily = _schedule(pg_conn, cron="0 15 * * 1-5", name="Daily digest")
        runs = ScheduleRunsRepository(pg_conn)
        for hour in range(0, 20, 2):
            run = runs.record_pending(str(busy["id"]), "u1", None, MONDAY + timedelta(hours=hour))
            runs.update(str(run["id"]), {"status": "success"})
        run = runs.record_pending(str(daily["id"]), "u1", None, MONDAY + timedelta(hours=15))
        runs.update(str(run["id"]), {"status": "success"})
        week = _week(pg_conn)
        busy_runs = [e for e in week["events"] if e["schedule_id"] == str(busy["id"]) and e.get("run_id")]
        assert [e["at"][11:16] for e in busy_runs] == ["00:00", "02:00", "04:00", "06:00", "08:00"]
        assert str(busy["id"]) in week["truncated"]
        assert [e["state"] for e in week["events"] if e["schedule_id"] == str(daily["id"])][0] == "success"

    def test_slots_past_the_cut_runs_are_not_missed(self, pg_conn, monkeypatch):
        # The runs after the cut exist; their slots must not read as missed.
        monkeypatch.setattr(planned, "MAX_SLOTS_PER_SCHEDULE", 5)
        busy = _schedule(pg_conn, cron="0 */2 * * *", name="Inbox triage")
        pg_conn.execute(
            text("UPDATE schedules SET created_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": MONDAY + timedelta(hours=6), "id": str(busy["id"])},
        )
        runs = ScheduleRunsRepository(pg_conn)
        for hour in range(0, 20, 2):
            run = runs.record_pending(str(busy["id"]), "u1", None, MONDAY + timedelta(hours=hour))
            runs.update(str(run["id"]), {"status": "success"})
        assert not [e for e in _week(pg_conn)["events"] if e["state"] == "missed"]


class TestFrequentDays:
    """A frequent schedule over the cap is summed up per day, not cut."""

    def _hourly_with_runs(self, conn):
        schedule = _schedule(conn, cron="0 * * * *", name="Inbox triage")
        runs = ScheduleRunsRepository(conn)
        for hour in range(10):
            run = runs.record_pending(str(schedule["id"]), "u1", None, MONDAY + timedelta(hours=hour))
            runs.update(str(run["id"]), {"status": "success"})
        failed = runs.record_pending(str(schedule["id"]), "u1", None, MONDAY + timedelta(hours=10))
        runs.update(str(failed["id"]), {"status": "failed"})
        return str(schedule["id"]), str(failed["id"])

    def test_every_day_is_there_with_its_count(self, pg_conn, monkeypatch):
        monkeypatch.setattr(planned, "MAX_SLOTS_PER_SCHEDULE", 5)
        schedule_id, failed_id = self._hourly_with_runs(pg_conn)
        week = _week(pg_conn)
        assert week["truncated"] == []
        mine = [e for e in week["events"] if e["schedule_id"] == schedule_id]
        monday_ok = next(e for e in mine if e["state"] == "success")
        assert (monday_ok["count"], monday_ok["at"], monday_ok["until"]) == (
            10, (MONDAY).isoformat(), (MONDAY + timedelta(hours=9)).isoformat(),
        )
        assert "run_id" not in monday_ok
        # A failure stays its own event, so it can still be opened.
        failures = [e for e in mine if e["state"] == "failed"]
        assert [(e["run_id"], e.get("count")) for e in failures] == [(failed_id, None)]
        # Monday 11:00 to 23:00 never ran: one summed-up missed event.
        monday_missed = [e for e in mine if e["state"] == "missed" and e["at"].startswith("2030-03-04")]
        assert [e["count"] for e in monday_missed] == [13]
        # Every later day is there in full.
        planned_days = {e["at"][:10]: e["count"] for e in mine if e["state"] == "planned"}
        assert [planned_days[f"2030-03-{d:02d}"] for d in range(6, 11)] == [24] * 5

    def test_under_the_cap_every_run_is_its_own_event(self, pg_conn):
        schedule_id, _ = self._hourly_with_runs(pg_conn)
        mine = [e for e in _week(pg_conn)["events"] if e["schedule_id"] == schedule_id]
        assert all("count" not in e for e in mine)
        assert len([e for e in mine if e["state"] == "success"]) == 10

    def test_days_split_in_the_viewers_time_zone(self, pg_conn, monkeypatch):
        monkeypatch.setattr(planned, "MAX_SLOTS_PER_SCHEDULE", 5)
        schedule = _schedule(pg_conn, cron="0 * * * *", name="Inbox triage")
        week = planned.build_planned(
            pg_conn, "u1", MONDAY, MONDAY + timedelta(days=7), now=NOW, tz="America/New_York",
        )
        thursday = [
            e for e in week["events"]
            if e["schedule_id"] == str(schedule["id"]) and e["at"].startswith("2030-03-07T05")
        ]
        # Midnight in New York is 05:00 UTC (EST), and the local day has 24 runs.
        assert [(e["state"], e["count"]) for e in thursday] == [("planned", 24)]

    def test_rejects_an_unknown_time_zone(self, pg_conn):
        with pytest.raises(planned.WindowError):
            planned.build_planned(pg_conn, "u1", MONDAY, MONDAY + timedelta(days=7), now=NOW, tz="Mars/Olympus")


class TestManyFrequentSchedules:
    def test_a_month_of_frequent_schedules_stays_small(self, pg_conn):
        # 50 paused 15-minute schedules (the per-user cap, and paused costs
        # nothing to run) over the widest window: about 300,000 slots. Each
        # used to become an event dict before the days were summed up, a
        # peak of some 165 MiB for one request; one schedule at a time, 8.
        import tracemalloc

        for i in range(50):
            _schedule(pg_conn, cron=f"{i % 15}/15 * * * *", status="paused", name=f"Scan {i}")
        start = MONDAY
        tracemalloc.start()
        try:
            window = planned.build_planned(
                pg_conn, "u1", start, start + planned.MAX_WINDOW, now=start - timedelta(days=1)
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert len(window["events"]) == 50 * 62
        assert all(e["count"] == 96 for e in window["events"])
        assert peak < 32 * 1024 * 1024
