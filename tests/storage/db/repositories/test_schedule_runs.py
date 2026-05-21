"""Tests for ScheduleRunsRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from application.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from application.storage.db.repositories.schedules import SchedulesRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_schedule(conn, *, user_id: str = "u1") -> tuple[str, str]:
    agent_id = str(
        conn.execute(
            text(
                "INSERT INTO agents (user_id, name, status) "
                "VALUES (:u, 'a', 'draft') RETURNING id"
            ),
            {"u": user_id},
        ).fetchone()[0]
    )
    schedule = SchedulesRepository(conn).create(
        user_id=user_id,
        agent_id=agent_id,
        trigger_type="recurring",
        instruction="i",
        cron="* * * * *",
        next_run_at=_now() + timedelta(minutes=5),
    )
    return str(schedule["id"]), agent_id


class TestRecordPending:
    def test_first_insert_wins(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        scheduled_for = _now().replace(microsecond=0)
        first = repo.record_pending(
            schedule_id, "u1", agent_id, scheduled_for,
        )
        assert first is not None
        assert first["status"] == "pending"

    def test_conflict_returns_none(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        scheduled_for = _now().replace(microsecond=0)
        first = repo.record_pending(
            schedule_id, "u1", agent_id, scheduled_for,
        )
        second = repo.record_pending(
            schedule_id, "u1", agent_id, scheduled_for,
        )
        assert first is not None
        assert second is None

    def test_different_scheduled_for_both_succeed(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        first = repo.record_pending(
            schedule_id, "u1", agent_id, _now(),
        )
        second = repo.record_pending(
            schedule_id, "u1", agent_id, _now() + timedelta(seconds=1),
        )
        assert first is not None
        assert second is not None
        assert first["id"] != second["id"]


class TestAgentlessRuns:
    """Agentless schedules (NULL agent_id) write runs with NULL agent_id."""

    def test_record_pending_with_null_agent_id(self, pg_conn):
        schedule = SchedulesRepository(pg_conn).create(
            user_id="u-agentless",
            agent_id=None,
            trigger_type="once",
            instruction="ping",
            run_at=_now() + timedelta(minutes=5),
            next_run_at=_now() + timedelta(minutes=5),
        )
        repo = ScheduleRunsRepository(pg_conn)
        run = repo.record_pending(
            str(schedule["id"]), "u-agentless", None,
            _now().replace(microsecond=0),
        )
        assert run is not None
        assert run["agent_id"] is None
        assert run["user_id"] == "u-agentless"

    def test_record_skipped_with_null_agent_id(self, pg_conn):
        schedule = SchedulesRepository(pg_conn).create(
            user_id="u-agentless",
            agent_id=None,
            trigger_type="once",
            instruction="ping",
            run_at=_now() + timedelta(minutes=5),
            next_run_at=_now() + timedelta(minutes=5),
        )
        repo = ScheduleRunsRepository(pg_conn)
        row = repo.record_skipped(
            str(schedule["id"]), "u-agentless", None, _now(),
            error_type="missed", error="agentless miss",
        )
        assert row is not None
        assert row["agent_id"] is None
        assert row["status"] == "skipped"


class TestSkippedAndActive:
    def test_record_skipped(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        row = repo.record_skipped(
            schedule_id, "u1", agent_id, _now(),
            error_type="missed", error="worker down",
        )
        assert row["status"] == "skipped"
        assert row["error_type"] == "missed"

    def test_has_active_run(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        assert repo.has_active_run(schedule_id) is False
        run = repo.record_pending(schedule_id, "u1", agent_id, _now())
        assert repo.has_active_run(schedule_id) is True
        repo.update(run["id"], {"status": "success", "finished_at": _now()})
        assert repo.has_active_run(schedule_id) is False


class TestUpdateAndList:
    def test_mark_running_only_from_pending(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        run = repo.record_pending(schedule_id, "u1", agent_id, _now())
        assert repo.mark_running(run["id"], "task-1") is True
        assert repo.mark_running(run["id"], "task-2") is False

    def test_list_runs_owner_scoped(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        for i in range(3):
            repo.record_pending(
                schedule_id, "u1", agent_id,
                _now() + timedelta(seconds=i),
            )
        rows = repo.list_runs(schedule_id, "u1")
        assert len(rows) == 3
        assert repo.list_runs(schedule_id, "u2") == []

    def test_list_stuck_running(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        run = repo.record_pending(schedule_id, "u1", agent_id, _now())
        pg_conn.execute(
            text(
                "UPDATE schedule_runs "
                "SET status = 'running', started_at = now() - interval '30 minutes' "
                "WHERE id = CAST(:i AS uuid)"
            ),
            {"i": run["id"]},
        )
        stuck = repo.list_stuck_running(age_minutes=15)
        assert any(r["id"] == run["id"] for r in stuck)


class TestCleanup:
    def test_cleanup_older_than_keeps_recent(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        repo = ScheduleRunsRepository(pg_conn)
        ids = []
        for i in range(5):
            row = repo.record_pending(
                schedule_id, "u1", agent_id,
                _now() + timedelta(seconds=i),
            )
            ids.append(row["id"])
        pg_conn.execute(
            text(
                """
                UPDATE schedule_runs
                SET created_at = now() - interval '120 days',
                    scheduled_for = scheduled_for - interval '120 days'
                WHERE id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"ids": "{" + ",".join(ids[:3]) + "}"},
        )
        deleted = repo.cleanup_older_than(90, keep_recent_per_schedule=2)
        assert deleted >= 1
