"""Tests for ScheduleRunsRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from docsgpt.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from docsgpt.storage.db.repositories.schedules import SchedulesRepository


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


def _add_run(
    conn,
    schedule_id: str,
    user_id: str,
    agent_id: str,
    *,
    ago: timedelta,
    status: str,
    prompt_tokens: int = 0,
    generated_tokens: int = 0,
    error_type: str | None = None,
) -> dict:
    repo = ScheduleRunsRepository(conn)
    run = repo.record_pending(schedule_id, user_id, agent_id, _now() - ago)
    return repo.update(
        str(run["id"]),
        {
            "status": status,
            "prompt_tokens": prompt_tokens,
            "generated_tokens": generated_tokens,
            "error_type": error_type,
        },
    )


class TestStatsForAgent:
    def test_empty_window_returns_zeros(self, pg_conn):
        _, agent_id = _make_schedule(pg_conn)
        stats = ScheduleRunsRepository(pg_conn).stats_for_agent(
            agent_id, "u1", days=30,
        )
        assert stats == {
            "runs": 0, "failed": 0, "tokens": 0, "latest_failure": None,
        }

    def test_aggregates_window_and_scopes_owner(self, pg_conn):
        schedule_id, agent_id = _make_schedule(pg_conn)
        _add_run(
            pg_conn, schedule_id, "u1", agent_id, ago=timedelta(hours=12),
            status="success", prompt_tokens=100, generated_tokens=50,
        )
        _add_run(
            pg_conn, schedule_id, "u1", agent_id, ago=timedelta(days=3),
            status="failed", prompt_tokens=10, generated_tokens=5,
            error_type="agent_error",
        )
        _add_run(
            pg_conn, schedule_id, "u1", agent_id, ago=timedelta(days=2),
            status="timeout", prompt_tokens=1, generated_tokens=2,
            error_type="timeout",
        )
        # Outside the window: must not count.
        _add_run(
            pg_conn, schedule_id, "u1", agent_id, ago=timedelta(days=40),
            status="failed", prompt_tokens=1000, generated_tokens=1000,
        )
        # Another user's schedule on the same agent: must not count.
        other = SchedulesRepository(pg_conn).create(
            user_id="u2", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(minutes=5),
        )
        _add_run(
            pg_conn, str(other["id"]), "u2", agent_id, ago=timedelta(hours=1),
            status="failed", prompt_tokens=7, generated_tokens=7,
        )

        stats = ScheduleRunsRepository(pg_conn).stats_for_agent(
            agent_id, "u1", days=30,
        )
        assert stats["runs"] == 3
        assert stats["failed"] == 2
        assert stats["tokens"] == 168
        latest = stats["latest_failure"]
        assert latest["status"] == "timeout"
        assert latest["error_type"] == "timeout"
        assert isinstance(latest["scheduled_for"], str)

        # A tighter window drops the older runs.
        narrow = ScheduleRunsRepository(pg_conn).stats_for_agent(
            agent_id, "u1", days=1,
        )
        assert narrow["runs"] == 1
        assert narrow["failed"] == 0
        assert narrow["latest_failure"] is None
