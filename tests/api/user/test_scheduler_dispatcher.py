"""Tests for the scheduler dispatcher (engine-level, no Celery worker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from application.api.user.scheduler_dispatcher import dispatch_due_runs
from application.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from application.storage.db.repositories.schedules import SchedulesRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_agent(conn, user_id: str = "u1") -> str:
    row = conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status) "
            "VALUES (:u, 'a', 'draft') RETURNING id"
        ),
        {"u": user_id},
    ).fetchone()
    return str(row[0])


@pytest.fixture
def patched_engine(pg_engine, monkeypatch):
    monkeypatch.setattr(
        "application.api.user.scheduler_dispatcher.get_engine",
        lambda: pg_engine,
    )
    yield pg_engine


@pytest.fixture
def stub_enqueue(monkeypatch):
    """Capture every execute_scheduled_run.apply_async."""
    enqueued: list[str] = []

    class _Task:
        @staticmethod
        def apply_async(args=None, **kwargs):
            if args:
                enqueued.append(args[0])

    monkeypatch.setattr(
        "application.api.user.tasks.execute_scheduled_run", _Task
    )
    return enqueued


def _create_schedule(engine, **kwargs):
    with engine.begin() as conn:
        return SchedulesRepository(conn).create(**kwargs)


def _set_postgres_uri(monkeypatch, pg_engine):
    monkeypatch.setattr(
        "application.api.user.scheduler_dispatcher.settings",
        type("S", (), {
            "POSTGRES_URI": str(pg_engine.url),
            "SCHEDULE_MISFIRE_GRACE": 60,
        })(),
    )


class TestDispatcherBasic:
    def test_due_recurring_enqueues_once_and_advances(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        _set_postgres_uri(monkeypatch, pg_engine)
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
        schedule = _create_schedule(
            pg_engine,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() - timedelta(seconds=5),
        )
        counts = dispatch_due_runs()
        assert counts["enqueued"] == 1
        assert len(stub_enqueue) == 1
        with pg_engine.connect() as conn:
            row = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["next_run_at"] is not None

    def test_once_dispatch_nulls_next_run_at_keeps_active(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        """Once: dispatcher nulls next_run_at but leaves status='active' for the worker."""
        _set_postgres_uri(monkeypatch, pg_engine)
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
        schedule = _create_schedule(
            pg_engine,
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(seconds=1),
            next_run_at=_now() - timedelta(seconds=5),
        )
        counts = dispatch_due_runs()
        assert counts["enqueued"] == 1
        with pg_engine.connect() as conn:
            row = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "active"
        assert row["next_run_at"] is None


class TestDedupConstraint:
    def test_double_dispatch_only_one_run(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        _set_postgres_uri(monkeypatch, pg_engine)
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
        schedule = _create_schedule(
            pg_engine,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="*/5 * * * *",
            next_run_at=_now() - timedelta(seconds=2),
        )
        # Pre-claim simulates a racing dispatcher tick.
        with pg_engine.begin() as conn:
            row = SchedulesRepository(conn).get_internal(str(schedule["id"]))
            ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]),
                "u1",
                str(row["agent_id"]),
                row["next_run_at"],
            )
        counts = dispatch_due_runs()
        assert counts["enqueued"] == 0
        assert stub_enqueue == []


class TestMisfireGrace:
    def test_stale_tick_recorded_skipped(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        _set_postgres_uri(monkeypatch, pg_engine)
        monkeypatch.setattr(
            "application.api.user.scheduler_dispatcher.settings",
            type("S", (), {
                "POSTGRES_URI": str(pg_engine.url),
                "SCHEDULE_MISFIRE_GRACE": 30,
            })(),
        )
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
        schedule = _create_schedule(
            pg_engine,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="*/5 * * * *",
            next_run_at=_now() - timedelta(hours=2),
        )
        counts = dispatch_due_runs()
        assert counts["enqueued"] == 0
        assert counts["skipped"] >= 1
        with pg_engine.connect() as conn:
            runs = ScheduleRunsRepository(conn).list_runs(
                str(schedule["id"]), "u1",
            )
        assert any(r["error_type"] == "missed" for r in runs)


class TestOverlap:
    def test_active_run_blocks_dispatch(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        _set_postgres_uri(monkeypatch, pg_engine)
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
        schedule = _create_schedule(
            pg_engine,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="*/5 * * * *",
            next_run_at=_now() - timedelta(seconds=2),
        )
        # Pre-create a running run with a different scheduled_for so overlap fires.
        with pg_engine.begin() as conn:
            row = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]),
                "u1",
                str(agent_id),
                _now() - timedelta(minutes=10),
            )
            ScheduleRunsRepository(conn).mark_running(row["id"], "t1")
        counts = dispatch_due_runs()
        assert counts["enqueued"] == 0

    def test_once_overlap_clears_next_run_at(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        """Once + overlap nulls next_run_at so the dispatcher stops re-picking."""
        _set_postgres_uri(monkeypatch, pg_engine)
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
        schedule = _create_schedule(
            pg_engine,
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(seconds=30),
            next_run_at=_now() - timedelta(seconds=5),
        )
        with pg_engine.begin() as conn:
            existing = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]),
                "u1",
                str(agent_id),
                _now() - timedelta(minutes=10),
            )
            ScheduleRunsRepository(conn).mark_running(existing["id"], "t-prev")
        dispatch_due_runs()
        with pg_engine.connect() as conn:
            row = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "active"
        assert row["next_run_at"] is None


class TestAgentlessSchedules:
    def test_dispatcher_claims_and_enqueues_agentless_once(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        """``agent_id IS NULL`` rows are claimed like any other once-schedule."""
        _set_postgres_uri(monkeypatch, pg_engine)
        schedule = _create_schedule(
            pg_engine,
            user_id="u-agentless", agent_id=None, trigger_type="once",
            instruction="agentless ping",
            run_at=_now() + timedelta(seconds=30),
            next_run_at=_now() - timedelta(seconds=5),
            origin_conversation_id=None,
            created_via="chat",
        )
        counts = dispatch_due_runs()
        assert counts["enqueued"] == 1
        assert len(stub_enqueue) == 1
        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
            run_row = conn.execute(
                text(
                    "SELECT * FROM schedule_runs "
                    "WHERE schedule_id = CAST(:s AS uuid)"
                ),
                {"s": str(schedule["id"])},
            ).fetchone()
        # Once: dispatcher nulled next_run_at, schedule still active.
        assert sched["status"] == "active"
        assert sched["next_run_at"] is None
        # The pending run carries NULL agent_id (matches the parent).
        assert run_row._mapping["agent_id"] is None
        assert run_row._mapping["user_id"] == "u-agentless"


class TestAgentlessRoundTrip:
    """Agentless chat → tool → dispatcher → headless run → message appended."""

    def test_agentless_dispatch_executes_and_appends_message(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        from unittest.mock import patch

        from application.api.user.scheduler_worker import (
            execute_scheduled_run_body,
        )

        _set_postgres_uri(monkeypatch, pg_engine)
        monkeypatch.setattr(
            "application.api.user.scheduler_worker.get_engine",
            lambda: pg_engine,
        )
        monkeypatch.setattr(
            "application.api.user.scheduler_worker.settings",
            type("S", (), {
                "POSTGRES_URI": str(pg_engine.url),
                "SCHEDULE_AUTOPAUSE_FAILURES": 3,
            })(),
        )
        monkeypatch.setattr(
            "application.api.user.scheduler_worker.publish_user_event",
            lambda *a, **k: "1-0",
        )

        with pg_engine.begin() as conn:
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, name) "
                    "VALUES ('u-e2e', 'agentless-chat') RETURNING id"
                )
            ).fetchone()[0]
        schedule = _create_schedule(
            pg_engine,
            user_id="u-e2e", agent_id=None, trigger_type="once",
            instruction="ping later",
            run_at=_now() + timedelta(seconds=30),
            next_run_at=_now() - timedelta(seconds=5),
            origin_conversation_id=str(conv_id),
            created_via="chat",
        )

        counts = dispatch_due_runs()
        assert counts["enqueued"] == 1
        run_id = stub_enqueue[0]

        with patch(
            "application.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "agentless e2e done",
                "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 1, "generated_tokens": 1,
                "denied": [], "error_type": None, "model_id": "fake",
            },
        ):
            result = execute_scheduled_run_body(run_id, "celery-e2e")
        assert result["status"] == "success"

        with pg_engine.connect() as conn:
            run = ScheduleRunsRepository(conn).get_internal(run_id)
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
            messages = conn.execute(
                text(
                    "SELECT * FROM conversation_messages "
                    "WHERE conversation_id = CAST(:c AS uuid)"
                ),
                {"c": str(conv_id)},
            ).fetchall()
        assert run["status"] == "success"
        assert run["agent_id"] is None
        assert sched["status"] == "completed"
        assert sched["agent_id"] is None
        assert len(messages) == 1
        meta = messages[0]._mapping["message_metadata"]
        assert meta.get("scheduled") is True


class TestOnceRoundTrip:
    """End-to-end: chat-driven once-schedule executes and the schedule completes."""

    def test_once_dispatch_executes_and_completes_schedule(
        self, pg_engine, patched_engine, stub_enqueue, monkeypatch,
    ):
        from unittest.mock import patch

        from application.api.user.scheduler_worker import (
            execute_scheduled_run_body,
        )

        _set_postgres_uri(monkeypatch, pg_engine)
        monkeypatch.setattr(
            "application.api.user.scheduler_worker.get_engine",
            lambda: pg_engine,
        )
        monkeypatch.setattr(
            "application.api.user.scheduler_worker.settings",
            type("S", (), {
                "POSTGRES_URI": str(pg_engine.url),
                "SCHEDULE_AUTOPAUSE_FAILURES": 3,
            })(),
        )
        monkeypatch.setattr(
            "application.api.user.scheduler_worker.publish_user_event",
            lambda *a, **k: "1-0",
        )
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
        schedule = _create_schedule(
            pg_engine,
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="follow up", run_at=_now() + timedelta(seconds=1),
            next_run_at=_now() - timedelta(seconds=5),
        )
        counts = dispatch_due_runs()
        assert counts["enqueued"] == 1
        assert len(stub_enqueue) == 1
        run_id = stub_enqueue[0]
        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert sched["status"] == "active"
        assert sched["next_run_at"] is None
        with patch(
            "application.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "done",
                "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 1, "generated_tokens": 1,
                "denied": [], "error_type": None, "model_id": "fake",
            },
        ):
            result = execute_scheduled_run_body(run_id, "celery-c1")
        assert result["status"] == "success"
        with pg_engine.connect() as conn:
            run = ScheduleRunsRepository(conn).get_internal(run_id)
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert run["status"] == "success"
        assert run["output"] == "done"
        assert sched["status"] == "completed"
        assert sched["next_run_at"] is None
