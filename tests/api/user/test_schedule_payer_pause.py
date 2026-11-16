"""A schedule pauses for its payer instead of failing.

While the person who set it (and pays for it) is out of allowance, has left the team or lost the role on a team
agent, or nobody can be billed, each run is skipped with that reason: it counts toward no auto-pause, sends no
failure notice and keeps the cadence, so the schedule runs again by itself once the reason clears. A paused streak
keeps one run row, and the payer hears of an allowance pause once per streak.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.user.scheduler_worker import execute_scheduled_run_body
from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.workspaces.principal import principal_id

pytestmark = pytest.mark.fresh_db

OWNER, EDITOR = "pp-alice", "pp-eddie"

_OK = {
    "answer": "done", "tool_calls": [], "sources": [], "thought": "", "prompt_tokens": 1,
    "generated_tokens": 1, "denied": [], "error_type": None, "model_id": "fake",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def engine(pg_engine, monkeypatch):
    monkeypatch.setattr("docsgpt.api.user.scheduler_worker.get_engine", lambda: pg_engine)
    monkeypatch.setattr(settings, "SCHEDULE_AUTOPAUSE_FAILURES", 2, raising=False)
    monkeypatch.setattr(settings, "SCHEDULE_NOTIFY_RECURRING_FAILURES", True, raising=False)
    monkeypatch.setattr(settings, "QUOTA_PERIOD", "month", raising=False)
    monkeypatch.setattr("docsgpt.api.user.scheduler_worker.publish_user_event", lambda *a, **k: "1-0")
    return pg_engine


@pytest.fixture
def notified(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: sent.append(kw))
    return sent


def _team(conn) -> tuple[str, str]:
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", OWNER)
    tid = str(team["id"])
    TeamMembersRepository(conn).add_member(tid, OWNER, role="team_admin")
    TeamMembersRepository(conn).add_member(tid, EDITOR, role="team_editor")
    return tid, principal_id(tid)


def _set_role(conn, team_id: str, user_id: str, role) -> None:
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _team_schedule(conn, setter: str = EDITOR) -> tuple[str, dict]:
    """A recurring schedule on a team agent, stored under ``setter`` (a principal for the legacy no-payer case)."""
    tid, principal = _team(conn)
    agent = AgentsRepository(conn).create(principal, "Bot", "published", agent_type="classic", default_model_id="m")
    schedule = SchedulesRepository(conn).create(
        user_id=principal if setter == "principal" else setter, agent_id=str(agent["id"]),
        trigger_type="recurring", instruction="hi", cron="*/5 * * * *", name="Morning report",
        next_run_at=_now() + timedelta(minutes=5),
    )
    return tid, schedule


def _pending(conn, schedule: dict, *, minutes: int = 0, source: str = "cron") -> dict:
    return ScheduleRunsRepository(conn).record_pending(
        str(schedule["id"]), schedule["user_id"], str(schedule["agent_id"]), _now() + timedelta(minutes=minutes),
        trigger_source=source,
    )


def _out_of_allowance(conn, user_id: str, *, when: datetime | None = None) -> None:
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user_id, token_limit=100)
    TokenUsageRepository(conn).insert(user_id=user_id, api_key="k", prompt_tokens=150, timestamp=when or _now())


def _execute(run: dict, outcome=_OK, **kwargs):
    with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", **({"side_effect": outcome}
               if isinstance(outcome, BaseException) else {"return_value": outcome}), **kwargs) as headless:
        result = execute_scheduled_run_body(str(run["id"]), "celery-pp")
    return result, headless


def _run_row(engine, run: dict):
    with engine.connect() as conn:
        return ScheduleRunsRepository(conn).get_internal(str(run["id"]))


def _schedule_row(engine, schedule: dict):
    with engine.connect() as conn:
        return SchedulesRepository(conn).get_internal(str(schedule["id"]))


class TestOutOfAllowance:
    def test_the_run_is_skipped_counts_nothing_and_tells_the_payer(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)
            _out_of_allowance(conn, EDITOR)

        result, headless = _execute(run)

        headless.assert_not_called()
        assert result["status"] == "skipped"
        row = _run_row(engine, run)
        assert (row["status"], row["error_type"], row["error"]) == (
            "skipped", "payer_out_of_allowance", "payer_out_of_allowance",
        )
        sched = _schedule_row(engine, schedule)
        assert sched["consecutive_failure_count"] == 0
        assert sched["status"] == "active"
        assert [(n["kind"], n["user_id"], n["schedule_id"]) for n in notified] == [
            ("schedule_paused", EDITOR, str(schedule["id"])),
        ]
        assert notified[0]["title"] == "Morning report"
        assert notified[0]["body"].startswith("Paused: you're out of allowance until ")

    def test_the_streak_keeps_one_row_and_notifies_once(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            runs = [_pending(conn, schedule, minutes=i * 5) for i in range(3)]
            _out_of_allowance(conn, EDITOR)

        results = [_execute(run)[0] for run in runs]

        assert [r["status"] for r in results] == ["skipped"] * 3
        with engine.connect() as conn:
            stored = conn.execute(
                text("SELECT id, status, error_type FROM schedule_runs WHERE schedule_id = CAST(:s AS uuid)"),
                {"s": str(schedule["id"])},
            ).fetchall()
        assert [(str(r.id), r.status, r.error_type) for r in stored] == [
            (str(runs[0]["id"]), "skipped", "payer_out_of_allowance"),
        ]
        assert len(notified) == 1
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 0

    def test_a_new_window_runs_again_with_nothing_written(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            first = _pending(conn, schedule)
            second = _pending(conn, schedule, minutes=5)
            _out_of_allowance(conn, EDITOR)
        assert _execute(first)[0]["status"] == "skipped"
        before = _schedule_row(engine, schedule)

        # The spend now lies in the previous window; nobody touched the schedule.
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE token_usage SET timestamp = :t WHERE user_id = :u"),
                {"t": _now() - timedelta(days=40), "u": EDITOR},
            )
        result, headless = _execute(second)

        headless.assert_called_once()
        assert result["status"] == "success"
        after = _schedule_row(engine, schedule)
        assert (after["status"], after["consecutive_failure_count"]) == (before["status"], 0)

    def test_a_refusal_from_the_runs_own_pre_check_is_a_pause_too(self, engine, notified):
        from docsgpt.quotas.service import QuotaExceeded, QuotaExceededError

        exceeded = QuotaExceeded(
            user_id=EDITOR, bucket="agent", budget="tokens", usage=10, limit=10, source="user", source_id=None,
            resets_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        result, _ = _execute(run, QuotaExceededError(exceeded))

        assert result["status"] == "skipped"
        row = _run_row(engine, run)
        assert (row["status"], row["error_type"]) == ("skipped", "payer_out_of_allowance")
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 0
        assert [n["kind"] for n in notified] == ["schedule_paused"]


class TestPayerLeft:
    @pytest.mark.parametrize("role", [None, "team_viewer"])
    def test_a_setter_who_left_or_is_a_viewer_is_skipped_without_a_notice(self, engine, notified, role):
        with engine.begin() as conn:
            tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)
            _set_role(conn, tid, EDITOR, role)

        result, headless = _execute(run)

        headless.assert_not_called()
        assert result["status"] == "skipped"
        row = _run_row(engine, run)
        assert (row["status"], row["error_type"]) == ("skipped", "payer_left")
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 0
        assert notified == []

    def test_re_adding_the_setter_runs_it_again(self, engine, notified):
        with engine.begin() as conn:
            tid, schedule = _team_schedule(conn)
            first = _pending(conn, schedule)
            second = _pending(conn, schedule, minutes=5)
            _set_role(conn, tid, EDITOR, None)
        assert _execute(first)[0]["status"] == "skipped"

        with engine.begin() as conn:
            _set_role(conn, tid, EDITOR, "team_editor")
        result, headless = _execute(second)

        headless.assert_called_once()
        assert result["status"] == "success"
        assert headless.call_args.kwargs["payer"] == EDITOR


class TestNoPayer:
    def test_a_schedule_stored_under_the_principal_is_skipped_as_no_payer(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn, setter="principal")
            run = _pending(conn, schedule)

        result, headless = _execute(run)

        headless.assert_not_called()
        assert result["status"] == "skipped"
        assert _run_row(engine, run)["error_type"] == "no_payer"
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 0
        assert notified == []

    def test_a_no_payer_refusal_from_the_pre_check_is_skipped(self, engine, notified):
        from docsgpt.quotas.service import NoPayerError

        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        result, _ = _execute(run, NoPayerError("team:x"))

        assert result["status"] == "skipped"
        assert _run_row(engine, run)["error_type"] == "no_payer"
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 0


class TestStreaks:
    def test_a_different_reason_starts_a_new_row(self, engine, notified):
        with engine.begin() as conn:
            tid, schedule = _team_schedule(conn)
            first = _pending(conn, schedule)
            second = _pending(conn, schedule, minutes=5)
            _set_role(conn, tid, EDITOR, None)
        _execute(first)
        with engine.begin() as conn:
            _set_role(conn, tid, EDITOR, "team_editor")
            _out_of_allowance(conn, EDITOR)

        _execute(second)

        assert _run_row(engine, first)["error_type"] == "payer_left"
        assert _run_row(engine, second)["error_type"] == "payer_out_of_allowance"
        assert [n["kind"] for n in notified] == ["schedule_paused"]

    def test_a_run_in_between_ends_the_streak(self, engine, notified):
        with engine.begin() as conn:
            tid, schedule = _team_schedule(conn)
            runs = [_pending(conn, schedule, minutes=i * 5) for i in range(3)]
            _set_role(conn, tid, EDITOR, None)
        _execute(runs[0])
        with engine.begin() as conn:
            _set_role(conn, tid, EDITOR, "team_editor")
        assert _execute(runs[1])[0]["status"] == "success"
        with engine.begin() as conn:
            _set_role(conn, tid, EDITOR, None)

        _execute(runs[2])

        assert [_run_row(engine, run)["status"] for run in runs] == ["skipped", "success", "skipped"]

    def test_a_run_started_by_hand_keeps_its_row(self, engine, notified):
        with engine.begin() as conn:
            tid, schedule = _team_schedule(conn)
            cron = _pending(conn, schedule)
            manual = _pending(conn, schedule, minutes=1, source="manual")
            _set_role(conn, tid, EDITOR, None)
        _execute(cron)

        result, _ = _execute(manual)

        assert result["status"] == "skipped"
        assert _run_row(engine, manual)["error_type"] == "payer_left"

    def test_an_owner_inactive_streak_keeps_one_row(self, engine, notified):
        from docsgpt.storage.db.repositories.users import UsersRepository

        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            first = _pending(conn, schedule)
            second = _pending(conn, schedule, minutes=5)
            UsersRepository(conn).upsert(EDITOR)
            conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": EDITOR})

        _execute(first)
        _execute(second)

        assert _run_row(engine, first)["error_type"] == "owner_inactive"
        assert _run_row(engine, second) is None


class TestMidRunStop:
    def test_a_stop_for_the_payers_allowance_fails_keeps_output_and_counts_nothing(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            SchedulesRepository(conn).bump_failure_count(str(schedule["id"]))
            run = _pending(conn, schedule)
        outcome = {
            **_OK, "answer": "partial answer", "error_type": "payer_out_of_allowance",
            "error": "Usage quota reached",
        }

        result, _ = _execute(run, outcome)

        assert result["status"] == "failed"
        row = _run_row(engine, run)
        assert (row["status"], row["error_type"], row["output"]) == (
            "failed", "payer_out_of_allowance", "partial answer",
        )
        sched = _schedule_row(engine, schedule)
        # One failure was already counted; with a threshold of two, counting this one would pause it.
        assert sched["consecutive_failure_count"] == 1
        assert sched["status"] == "active"
        assert notified == []

    def test_the_agents_own_limit_mid_run_still_counts_as_budget_exceeded(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        _execute(run, {**_OK, "answer": "partial", "error_type": "budget_exceeded", "error": "limit"})

        assert _run_row(engine, run)["error_type"] == "budget_exceeded"
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 1

    def test_the_agent_limit_before_start_records_budget_exceeded(self, engine, notified):
        from docsgpt.quotas.agent_limits import AgentLimitExceeded, AgentLimitExceededError

        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        result, _ = _execute(run, AgentLimitExceededError(
            AgentLimitExceeded(agent_id=None, dimension="requests", usage=5, limit=5),
        ))

        assert result["status"] == "failed"
        assert _run_row(engine, run)["error_type"] == "budget_exceeded"
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 1

    def test_a_mid_run_stop_that_escapes_the_runner_is_still_a_failure_that_counts_nothing(self, engine, notified):
        from docsgpt.quotas.service import QuotaExceeded, QuotaExceededError

        class _Stopped(QuotaExceededError):
            stops_run = True

            def __init__(self, exceeded):
                self.exceeded = exceeded
                Exception.__init__(self, "Usage quota reached")

        exceeded = QuotaExceeded(
            user_id=EDITOR, bucket="agent", budget="tokens", usage=10, limit=10, source="user", source_id=None,
            resets_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        result, _ = _execute(run, _Stopped(exceeded))

        assert result["status"] == "failed"
        assert _run_row(engine, run)["error_type"] == "payer_out_of_allowance"
        assert _schedule_row(engine, schedule)["consecutive_failure_count"] == 0
