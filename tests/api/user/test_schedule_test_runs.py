"""A schedule can run once as a test when it is created, without changing its cadence."""

from __future__ import annotations

import importlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

# Pre-import to stabilise the tool-loading import order (see tests/agents/tools/test_scheduler.py).
importlib.import_module("docsgpt.api.user.tools.mcp")

from docsgpt.agents.tools.scheduler import SchedulerTool  # noqa: E402
from docsgpt.api.user.scheduler_worker import execute_scheduled_run_body  # noqa: E402
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository  # noqa: E402
from docsgpt.storage.db.repositories.schedules import SchedulesRepository  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _make_agent(conn, user_id: str = "u1") -> str:
    row = conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status, default_model_id) "
            "VALUES (:u, 'a', 'draft', '') RETURNING id"
        ),
        {"u": user_id},
    ).fetchone()
    return str(row[0])


def _runs(conn, schedule_id: str) -> list[dict]:
    return ScheduleRunsRepository(conn).list_runs(schedule_id, "u1", limit=10, offset=0)


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def enqueued():
    """Run ids handed to the worker."""
    ids: list[str] = []

    def _apply_async(args=None, **_kw):
        ids.append(args[0])

    with patch(
        "docsgpt.api.user.tasks.execute_scheduled_run",
        type("T", (), {"apply_async": staticmethod(_apply_async)}),
    ):
        yield ids


@pytest.fixture
def broker_down():
    def _apply_async(**_kw):
        raise ConnectionError("broker down")

    with patch(
        "docsgpt.api.user.tasks.execute_scheduled_run",
        type("T", (), {"apply_async": staticmethod(_apply_async)}),
    ):
        yield


@contextmanager
def _routes_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.schedules.routes.db_session", _yield), patch(
        "docsgpt.api.user.schedules.routes.db_readonly", _yield,
    ):
        yield


def _create(app, conn, agent_id: str, body: dict):
    from docsgpt.api.user.schedules.routes import AgentSchedules

    with _routes_db(conn), app.test_request_context(
        f"/api/agents/{agent_id}/schedules", method="POST", json=body,
    ):
        from flask import request

        request.decoded_token = {"sub": "u1"}
        return AgentSchedules().post(agent_id)


RECURRING = {"instruction": "weekly digest", "cron": "0 9 * * 1", "timezone": "UTC"}


class TestCreateWithTestRun:
    def test_a_recurring_schedule_queues_one_manual_run_and_keeps_its_next_run(
        self, app, pg_conn, enqueued,
    ):
        agent_id = _make_agent(pg_conn)

        resp = _create(app, pg_conn, agent_id, {**RECURRING, "test_run": True})

        assert resp.status_code == 201
        body = resp.get_json()
        schedule_id = body["schedule"]["id"]
        runs = _runs(pg_conn, schedule_id)
        assert len(runs) == 1
        assert runs[0]["trigger_source"] == "manual"
        assert runs[0]["status"] == "pending"
        assert body["test_run"]["id"] == str(runs[0]["id"])
        assert body["test_run"]["trigger_source"] == "manual"
        assert enqueued == [str(runs[0]["id"])]
        stored = SchedulesRepository(pg_conn).get_internal(schedule_id)
        assert stored["next_run_at"] == body["schedule"]["next_run_at"]
        assert stored["status"] == "active"

    def test_without_it_nothing_runs(self, app, pg_conn, enqueued):
        agent_id = _make_agent(pg_conn)

        resp = _create(app, pg_conn, agent_id, dict(RECURRING))

        body = resp.get_json()
        assert "test_run" not in body
        assert _runs(pg_conn, body["schedule"]["id"]) == []
        assert enqueued == []

    def test_only_a_true_value_asks_for_it(self, app, pg_conn, enqueued):
        agent_id = _make_agent(pg_conn)

        resp = _create(app, pg_conn, agent_id, {**RECURRING, "test_run": "false"})

        assert _runs(pg_conn, resp.get_json()["schedule"]["id"]) == []
        assert enqueued == []

    def test_a_one_time_task_due_later_is_tested(self, app, pg_conn, enqueued):
        agent_id = _make_agent(pg_conn)
        run_at = _iso(_now() + timedelta(hours=2))

        resp = _create(app, pg_conn, agent_id, {
            "instruction": "remind me", "trigger_type": "once", "run_at": run_at, "test_run": True,
        })

        body = resp.get_json()
        assert body["test_run"]["trigger_source"] == "manual"
        stored = SchedulesRepository(pg_conn).get_internal(body["schedule"]["id"])
        assert stored["status"] == "active"
        assert stored["next_run_at"] == body["schedule"]["next_run_at"]

    def test_a_one_time_task_due_before_a_run_could_finish_is_not_tested(
        self, app, pg_conn, enqueued,
    ):
        agent_id = _make_agent(pg_conn)
        run_at = _iso(_now() + timedelta(minutes=3))

        resp = _create(app, pg_conn, agent_id, {
            "instruction": "remind me", "trigger_type": "once", "run_at": run_at, "test_run": True,
        })

        assert resp.status_code == 201
        body = resp.get_json()
        assert body["test_run"] is None
        assert _runs(pg_conn, body["schedule"]["id"]) == []
        assert enqueued == []

    def test_a_refused_enqueue_fails_the_test_run_but_keeps_the_schedule(
        self, app, pg_conn, broker_down,
    ):
        agent_id = _make_agent(pg_conn)

        resp = _create(app, pg_conn, agent_id, {**RECURRING, "test_run": True})

        assert resp.status_code == 201
        body = resp.get_json()
        assert body["test_run"]["status"] == "failed"
        assert body["test_run"]["error_type"] == "internal"
        runs = _runs(pg_conn, body["schedule"]["id"])
        # No pending row is left to hold off the first real run.
        assert [r["status"] for r in runs] == ["failed"]
        stored = SchedulesRepository(pg_conn).get_internal(body["schedule"]["id"])
        assert stored["consecutive_failure_count"] == 0


@pytest.fixture
def tool_db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with patch("docsgpt.agents.tools.scheduler.db_session", _yield), patch(
        "docsgpt.agents.tools.scheduler.db_readonly", _yield,
    ):
        yield


def _tool(agent_id: str) -> SchedulerTool:
    return SchedulerTool(tool_config={"agent_id": agent_id}, user_id="u1")


class TestSchedulerToolTestRun:
    def test_returns_the_manual_run_id(self, pg_conn, tool_db, enqueued):
        agent_id = _make_agent(pg_conn)

        out = json.loads(_tool(agent_id).execute_action(
            "schedule_task", instruction="check the deploy", delay="2h", test_run=True,
        ))

        runs = _runs(pg_conn, out["task_id"])
        assert [r["trigger_source"] for r in runs] == ["manual"]
        assert out["test_run_id"] == str(runs[0]["id"])
        assert enqueued == [out["test_run_id"]]
        assert "test_run_error" not in out
        stored = SchedulesRepository(pg_conn).get_internal(out["task_id"])
        fire = datetime.fromisoformat(out["resolved_run_at"].replace("Z", "+00:00"))
        assert datetime.fromisoformat(str(stored["next_run_at"]).replace("Z", "+00:00")) == fire

    def test_no_test_run_unless_asked(self, pg_conn, tool_db, enqueued):
        agent_id = _make_agent(pg_conn)

        out = json.loads(_tool(agent_id).execute_action(
            "schedule_task", instruction="check the deploy", delay="2h",
        ))

        assert "test_run_id" not in out
        assert _runs(pg_conn, out["task_id"]) == []
        assert enqueued == []

    def test_a_task_due_soon_says_why_it_was_not_tested(self, pg_conn, tool_db, enqueued):
        agent_id = _make_agent(pg_conn)

        out = json.loads(_tool(agent_id).execute_action(
            "schedule_task", instruction="check the deploy", delay="2m", test_run=True,
        ))

        assert "test_run_id" not in out
        assert out["test_run_error"].startswith("not tested")
        assert _runs(pg_conn, out["task_id"]) == []

    def test_a_refused_enqueue_is_reported(self, pg_conn, tool_db, broker_down):
        agent_id = _make_agent(pg_conn)

        out = json.loads(_tool(agent_id).execute_action(
            "schedule_task", instruction="check the deploy", delay="2h", test_run=True,
        ))

        assert out["test_run_id"]
        assert out["test_run_error"]
        assert [r["status"] for r in _runs(pg_conn, out["task_id"])] == ["failed"]

    def test_the_action_offers_it(self):
        meta = next(a for a in _tool("x").get_actions_metadata() if a["name"] == "schedule_task")
        assert meta["parameters"]["properties"]["test_run"]["type"] == "boolean"


@pytest.mark.fresh_db
class TestManualRunsAndAutoPause:
    """A failed run started by hand is watched, so it doesn't count toward auto-pause."""

    @pytest.fixture
    def worker_engine(self, pg_engine, monkeypatch):
        monkeypatch.setattr("docsgpt.api.user.scheduler_worker.get_engine", lambda: pg_engine)
        monkeypatch.setattr(
            "docsgpt.api.user.scheduler_worker.settings",
            type("S", (), {"POSTGRES_URI": str(pg_engine.url), "SCHEDULE_AUTOPAUSE_FAILURES": 1})(),
        )
        monkeypatch.setattr("docsgpt.api.user.scheduler_worker.publish_user_event", lambda *a, **k: "1-0")
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: None)
        return pg_engine

    def _schedule_with_run(self, engine, trigger_source: str):
        with engine.begin() as conn:
            agent_id = _make_agent(conn)
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=agent_id, trigger_type="recurring",
                instruction="hello", cron="0 9 * * 1", next_run_at=_now() + timedelta(days=1),
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", agent_id, _now(), trigger_source=trigger_source,
            )
        return schedule, run

    def _fail(self, run, *, cannot_complete: str | None = None) -> None:
        outcome = {
            "answer": "I can't do this.", "tool_calls": [], "sources": [], "thought": "",
            "prompt_tokens": 5, "generated_tokens": 5, "denied": [], "error_type": None,
            "model_id": "fake", "cannot_complete": cannot_complete,
        }
        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", return_value=outcome):
            execute_scheduled_run_body(str(run["id"]), "celery-test")

    def test_a_failed_test_run_neither_counts_nor_pauses(self, worker_engine):
        schedule, run = self._schedule_with_run(worker_engine, "manual")

        self._fail(run, cannot_complete="no CRM tool to look the account up")

        with worker_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            stored = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "failed"
        assert row["error_type"] == "cannot_complete"
        assert row["error"] == "no CRM tool to look the account up"
        assert stored["consecutive_failure_count"] == 0
        assert stored["status"] == "active"
        assert stored["next_run_at"] == schedule["next_run_at"]

    def test_a_failed_scheduled_run_still_counts(self, worker_engine):
        schedule, run = self._schedule_with_run(worker_engine, "cron")

        self._fail(run, cannot_complete="no CRM tool")

        with worker_engine.connect() as conn:
            stored = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert stored["consecutive_failure_count"] == 1
        assert stored["status"] == "paused"


@pytest.mark.fresh_db
class TestStuckTestRunOfAOneTimeTask:
    """The reconciler fails a stuck test run but leaves its one-time task to run at its time."""

    @pytest.fixture
    def reconcile_engine(self, pg_engine, monkeypatch):
        monkeypatch.setattr("docsgpt.api.user.reconciliation.get_engine", lambda: pg_engine)
        monkeypatch.setattr(
            "docsgpt.api.user.reconciliation.settings",
            type("S", (), {"POSTGRES_URI": str(pg_engine.url), "SCHEDULE_RUN_TIMEOUT": 60})(),
        )
        return pg_engine

    def _stuck(self, engine, *, running: bool):
        with engine.begin() as conn:
            agent_id = _make_agent(conn)
            fire = _now() + timedelta(days=1)
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=agent_id, trigger_type="once",
                instruction="check the deploy", run_at=fire, next_run_at=fire,
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", agent_id, _now(), trigger_source="manual",
            )
            if running:
                ScheduleRunsRepository(conn).mark_running(str(run["id"]), "t1")
                aged = "UPDATE schedule_runs SET started_at = now() - interval '120 minutes' WHERE id = CAST(:i AS uuid)"
            else:
                aged = "UPDATE schedule_runs SET created_at = now() - interval '120 minutes' WHERE id = CAST(:i AS uuid)"
            conn.execute(text(aged), {"i": str(run["id"])})
        return schedule, run

    @pytest.mark.parametrize("running", [False, True])
    def test_the_task_stays_active_with_its_next_run(self, reconcile_engine, running):
        from docsgpt.api.user.reconciliation import run_reconciliation

        schedule, run = self._stuck(reconcile_engine, running=running)

        run_reconciliation()

        with reconcile_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            stored = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == ("timeout" if running else "failed")
        assert stored["status"] == "active"
        assert stored["next_run_at"] == schedule["next_run_at"]
        assert stored["consecutive_failure_count"] == 0


@pytest.mark.fresh_db
class TestOneTimeTaskDueDuringItsTestRun:
    """A one-time task that comes due while its test run is still going waits for it instead of being skipped."""

    @pytest.fixture
    def dispatch_engine(self, pg_engine, monkeypatch):
        monkeypatch.setattr("docsgpt.api.user.scheduler_dispatcher.get_engine", lambda: pg_engine)
        monkeypatch.setattr(
            "docsgpt.api.user.scheduler_dispatcher.settings",
            type("S", (), {"POSTGRES_URI": str(pg_engine.url), "SCHEDULE_MISFIRE_GRACE": 60})(),
        )
        return pg_engine

    def test_it_runs_once_the_test_ends(self, dispatch_engine, enqueued):
        from docsgpt.api.user.scheduler_dispatcher import dispatch_due_runs

        with dispatch_engine.begin() as conn:
            agent_id = _make_agent(conn)
            due = _now() - timedelta(seconds=5)
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=agent_id, trigger_type="once",
                instruction="check the deploy", run_at=due, next_run_at=due,
            )
            test = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", agent_id, _now() - timedelta(minutes=1), trigger_source="manual",
            )

        dispatch_due_runs()

        with dispatch_engine.connect() as conn:
            runs = _runs(conn, str(schedule["id"]))
            stored = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert [r["trigger_source"] for r in runs] == ["manual"]
        assert stored["next_run_at"] == schedule["next_run_at"]
        assert enqueued == []

        with dispatch_engine.begin() as conn:
            ScheduleRunsRepository(conn).update(str(test["id"]), {"status": "success"})
        dispatch_due_runs()

        with dispatch_engine.connect() as conn:
            runs = _runs(conn, str(schedule["id"]))
        cron = [r for r in runs if r["trigger_source"] == "cron"]
        assert [r["status"] for r in cron] == ["pending"]
        assert enqueued == [str(cron[0]["id"])]


def test_a_failed_enqueue_whose_status_cannot_be_saved_still_returns_the_run():
    from docsgpt.api.user.scheduler_dispatcher import enqueue_test_run

    @contextmanager
    def _down():
        raise ConnectionError("database down")
        yield  # pragma: no cover

    run = {"id": "00000000-0000-0000-0000-000000000001", "schedule_id": "s1", "status": "pending"}

    def _apply_async(**_kw):
        raise ConnectionError("broker down")

    with patch(
        "docsgpt.api.user.tasks.execute_scheduled_run",
        type("T", (), {"apply_async": staticmethod(_apply_async)}),
    ):
        out = enqueue_test_run(run, _down)

    assert out["id"] == run["id"]
    assert out["status"] == "failed"
    assert out["error_type"] == "internal"
