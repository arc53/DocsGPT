"""Tests for the scheduler reconciliation sweep + cleanup task."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from application.api.user.reconciliation import run_reconciliation
from application.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from application.storage.db.repositories.schedules import SchedulesRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_pending_run(conn, *, user_id="u1"):
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
        user_id=user_id, agent_id=agent_id, trigger_type="recurring",
        instruction="i", cron="*/5 * * * *",
        next_run_at=_now() + timedelta(minutes=5),
    )
    run = ScheduleRunsRepository(conn).record_pending(
        str(schedule["id"]), user_id, agent_id, _now(),
    )
    return schedule, run, agent_id


def _make_once_pending_run(conn, *, user_id="u1"):
    """Once-schedule + pending run variant of _make_pending_run."""
    agent_id = str(
        conn.execute(
            text(
                "INSERT INTO agents (user_id, name, status) "
                "VALUES (:u, 'a', 'draft') RETURNING id"
            ),
            {"u": user_id},
        ).fetchone()[0]
    )
    fire = _now() + timedelta(minutes=5)
    schedule = SchedulesRepository(conn).create(
        user_id=user_id, agent_id=agent_id, trigger_type="once",
        instruction="do once", run_at=fire,
        next_run_at=fire,
    )
    run = ScheduleRunsRepository(conn).record_pending(
        str(schedule["id"]), user_id, agent_id, fire,
    )
    return schedule, run, agent_id


@pytest.fixture
def patched_engine(pg_engine, monkeypatch):
    monkeypatch.setattr(
        "application.api.user.reconciliation.get_engine",
        lambda: pg_engine,
    )
    monkeypatch.setattr(
        "application.api.user.reconciliation.settings",
        type("S", (), {
            "POSTGRES_URI": str(pg_engine.url),
            "SCHEDULE_RUN_TIMEOUT": 60,
        })(),
    )
    yield pg_engine


class TestReconciler:
    def test_stuck_running_flipped_to_timeout(self, pg_engine, patched_engine):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
            ScheduleRunsRepository(conn).mark_running(run["id"], "t1")
            conn.execute(
                text(
                    "UPDATE schedule_runs "
                    "SET started_at = now() - interval '120 minutes' "
                    "WHERE id = CAST(:i AS uuid)"
                ),
                {"i": run["id"]},
            )

        summary = run_reconciliation()
        assert summary["schedule_runs_failed"] >= 1
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(run["id"])
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "timeout"
        assert row["error_type"] == "timeout"
        assert sched["consecutive_failure_count"] == 1

    def test_stuck_pending_flipped_to_failed(self, pg_engine, patched_engine):
        """A pending run whose worker never started reconciles to 'failed'."""
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
            conn.execute(
                text(
                    "UPDATE schedule_runs "
                    "SET created_at = now() - interval '120 minutes' "
                    "WHERE id = CAST(:i AS uuid)"
                ),
                {"i": run["id"]},
            )

        summary = run_reconciliation()
        assert summary["schedule_runs_failed"] >= 1
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(run["id"])
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "failed"
        assert row["error_type"] == "internal"
        assert "worker_never_started" in (row["error"] or "")
        assert sched["consecutive_failure_count"] == 1

    def test_once_schedule_with_stuck_running_run_marked_completed(
        self, pg_engine, patched_engine,
    ):
        """Once + stuck 'running' run -> parent flipped to 'completed'."""
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_once_pending_run(conn)
            ScheduleRunsRepository(conn).mark_running(run["id"], "t-once")
            conn.execute(
                text(
                    "UPDATE schedule_runs "
                    "SET started_at = now() - interval '120 minutes' "
                    "WHERE id = CAST(:i AS uuid)"
                ),
                {"i": run["id"]},
            )

        run_reconciliation()
        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
            row = ScheduleRunsRepository(conn).get_internal(run["id"])
        assert row["status"] == "timeout"
        assert sched["status"] == "completed", (
            "stuck once-run must terminal-flip the parent schedule"
        )
        assert sched["next_run_at"] is None

    def test_once_schedule_with_stuck_pending_run_marked_completed(
        self, pg_engine, patched_engine,
    ):
        """Once + stuck 'pending' run -> parent flipped to 'completed'."""
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_once_pending_run(conn)
            conn.execute(
                text(
                    "UPDATE schedule_runs "
                    "SET created_at = now() - interval '120 minutes' "
                    "WHERE id = CAST(:i AS uuid)"
                ),
                {"i": run["id"]},
            )

        run_reconciliation()
        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
            row = ScheduleRunsRepository(conn).get_internal(run["id"])
        assert row["status"] == "failed"
        assert sched["status"] == "completed", (
            "stuck pending once-run must terminal-flip the parent schedule"
        )
        assert sched["next_run_at"] is None

    def test_agentless_once_stuck_running_marked_completed(
        self, pg_engine, patched_engine,
    ):
        """Stuck-run terminal flip works for agentless once-schedules."""
        with pg_engine.begin() as conn:
            fire = _now() + timedelta(minutes=5)
            schedule = SchedulesRepository(conn).create(
                user_id="u-agentless", agent_id=None, trigger_type="once",
                instruction="agentless go", run_at=fire,
                next_run_at=fire,
                created_via="chat",
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u-agentless", None, fire,
            )
            ScheduleRunsRepository(conn).mark_running(run["id"], "t-stuck")
            conn.execute(
                text(
                    "UPDATE schedule_runs "
                    "SET started_at = now() - interval '120 minutes' "
                    "WHERE id = CAST(:i AS uuid)"
                ),
                {"i": run["id"]},
            )

        run_reconciliation()
        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
            row = ScheduleRunsRepository(conn).get_internal(run["id"])
        assert row["status"] == "timeout"
        assert sched["status"] == "completed"
        assert sched["next_run_at"] is None

    def test_recurring_schedule_with_stuck_run_stays_active(
        self, pg_engine, patched_engine,
    ):
        """Recurring keeps firing; only the run flips, not the parent."""
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
            ScheduleRunsRepository(conn).mark_running(run["id"], "t-rec")
            conn.execute(
                text(
                    "UPDATE schedule_runs "
                    "SET started_at = now() - interval '120 minutes' "
                    "WHERE id = CAST(:i AS uuid)"
                ),
                {"i": run["id"]},
            )

        run_reconciliation()
        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert sched["status"] == "active"
        assert sched["consecutive_failure_count"] == 1


class TestCleanup:
    def test_cleanup_schedule_runs_trims_old_rows(self, pg_engine, monkeypatch):
        from application.api.user.tasks import cleanup_schedule_runs as _task

        monkeypatch.setattr(
            "application.storage.db.engine.get_engine",
            lambda: pg_engine,
        )

        class S:
            POSTGRES_URI = str(pg_engine.url)
            SCHEDULE_RUN_OUTPUT_RETENTION_DAYS = 30
        monkeypatch.setattr("application.api.user.tasks.settings", S, raising=False)
        monkeypatch.setattr(
            "application.core.settings.settings.POSTGRES_URI",
            str(pg_engine.url),
            raising=False,
        )
        monkeypatch.setattr(
            "application.core.settings.settings.SCHEDULE_RUN_OUTPUT_RETENTION_DAYS",
            30,
            raising=False,
        )

        with pg_engine.begin() as conn:
            schedule, _, _ = _make_pending_run(conn)
            for i in range(60):
                conn.execute(
                    text(
                        """
                        INSERT INTO schedule_runs (
                            schedule_id, user_id, agent_id, status,
                            scheduled_for, created_at
                        ) VALUES (
                            CAST(:s AS uuid), 'u1',
                            CAST(:a AS uuid), 'success',
                            now() - interval '100 days' - (:i * interval '1 second'),
                            now() - interval '100 days'
                        )
                        """
                    ),
                    {"s": str(schedule["id"]),
                     "a": str(schedule["agent_id"]),
                     "i": i},
                )

        result = _task.run()
        assert isinstance(result.get("deleted"), int)
        assert result["deleted"] >= 1
