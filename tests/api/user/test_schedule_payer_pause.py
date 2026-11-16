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


class TestRunEvents:
    """Every run that announced ``schedule.run.started`` announces how it ended, so the UI never shows it running."""

    @pytest.fixture
    def events(self, engine, monkeypatch):
        sent: list[tuple[str, dict]] = []

        def _publish(user_id, event_type, payload, **_kw):
            sent.append((event_type, payload))
            return "1-0"

        monkeypatch.setattr("docsgpt.api.user.scheduler_worker.publish_user_event", _publish)
        return sent

    @staticmethod
    def _allowance_refusal():
        from docsgpt.quotas.service import QuotaExceeded, QuotaExceededError

        return QuotaExceededError(QuotaExceeded(
            user_id=EDITOR, bucket="agent", budget="tokens", usage=10, limit=10, source="user", source_id=None,
            resets_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ))

    @pytest.mark.parametrize("refusal,reason", [
        ("allowance", "payer_out_of_allowance"),
        ("no_payer", "no_payer"),
    ])
    def test_a_pre_check_refusal_after_start_closes_the_run_as_skipped(self, engine, notified, events, refusal, reason):
        from docsgpt.quotas.service import NoPayerError

        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        _execute(run, self._allowance_refusal() if refusal == "allowance" else NoPayerError("team:x"))

        assert [kind for kind, _ in events] == ["schedule.run.started", "schedule.run.skipped"]
        closing = events[-1][1]
        assert closing["run_id"] == str(run["id"])
        assert closing["schedule_id"] == str(schedule["id"])
        assert (closing["status"], closing["error_type"]) == ("skipped", reason)

    @pytest.mark.parametrize("outcome,closing", [
        (_OK, "schedule.run.completed"),
        ({**_OK, "answer": "partial", "error_type": "payer_out_of_allowance", "error": "quota"}, "schedule.run.failed"),
        (RuntimeError("boom"), "schedule.run.failed"),
    ])
    def test_every_started_run_ends_with_one_closing_event(self, engine, notified, events, outcome, closing):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        _execute(run, outcome)

        assert [kind for kind, _ in events] == ["schedule.run.started", closing]

    def test_a_run_skipped_before_it_starts_announces_nothing(self, engine, notified, events):
        with engine.begin() as conn:
            tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)
            _set_role(conn, tid, EDITOR, None)

        _execute(run)

        assert events == []


def _once_schedule(conn, *, origin: str | None = None) -> tuple[str, dict]:
    """A one-time task on a team agent whose time has come: the dispatcher cleared its next run."""
    tid, principal = _team(conn)
    agent = AgentsRepository(conn).create(principal, "Bot", "published", agent_type="classic", default_model_id="m")
    schedule = SchedulesRepository(conn).create(
        user_id=EDITOR, agent_id=str(agent["id"]), trigger_type="once", instruction="hi", name="Reminder",
        run_at=_now() - timedelta(minutes=1), next_run_at=None, origin_conversation_id=origin,
    )
    return tid, schedule


def _take_over(conn, schedule: dict, user_id: str) -> None:
    """What the Take over route writes, in its own transaction."""
    SchedulesRepository(conn).lock_internal(str(schedule["id"]))
    SchedulesRepository(conn).take_over(str(schedule["id"]), user_id)
    ScheduleRunsRepository(conn).reassign_pending(str(schedule["id"]), user_id)


class TestOneTimeTaskPaused:
    """A one-time task skipped for its payer waits and runs once the pause clears, as a recurring one would."""

    def _assert_waits(self, engine, schedule, at: datetime) -> None:
        row = _schedule_row(engine, schedule)
        assert row["status"] == "active"
        assert row["next_run_at"] is not None
        next_run = row["next_run_at"]
        next_run = datetime.fromisoformat(next_run) if isinstance(next_run, str) else next_run
        assert abs((next_run - at).total_seconds()) < 60

    def test_a_payer_out_of_allowance_waits_for_the_reset(self, engine, notified):
        from docsgpt.quotas.pause import schedule_pause

        with engine.begin() as conn:
            _tid, schedule = _once_schedule(conn)
            run = _pending(conn, schedule)
            _out_of_allowance(conn, EDITOR)
        with engine.connect() as conn:
            agent = AgentsRepository(conn).get_by_id(str(schedule["agent_id"]))
            until = schedule_pause(conn, schedule, agent).until

        assert _execute(run)[0]["status"] == "skipped"

        self._assert_waits(engine, schedule, until)

    def test_a_setter_who_left_waits_and_a_take_over_runs_it_at_once(self, engine, notified):
        with engine.begin() as conn:
            tid, schedule = _once_schedule(conn)
            run = _pending(conn, schedule)
            _set_role(conn, tid, EDITOR, None)

        assert _execute(run)[0]["status"] == "skipped"
        self._assert_waits(engine, schedule, _now() + timedelta(seconds=settings.SCHEDULE_MIN_INTERVAL))

        with engine.begin() as conn:
            _take_over(conn, schedule, OWNER)
        self._assert_waits(engine, schedule, _now())

    def test_a_take_over_leaves_a_task_not_yet_due_alone(self, engine, notified):
        later = _now() + timedelta(days=2)
        with engine.begin() as conn:
            _tid, schedule = _once_schedule(conn)
            SchedulesRepository(conn).update_internal(str(schedule["id"]), {"run_at": later, "next_run_at": later})
            _take_over(conn, schedule, OWNER)

        self._assert_waits(engine, schedule, later)

    def test_a_task_that_ran_is_not_re_armed_by_a_take_over(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _once_schedule(conn)
            run = _pending(conn, schedule)
        assert _execute(run)[0]["status"] == "success"

        with engine.begin() as conn:
            _take_over(conn, schedule, OWNER)

        row = _schedule_row(engine, schedule)
        assert (row["status"], row["next_run_at"]) == ("completed", None)


class TestTakeOverAsTheRunStarts:
    """A take over committed after the worker picked the run up, but before it claimed it, decides who pays."""

    def _take_over_while_loading(self, engine, schedule):
        from docsgpt.api.user import scheduler_worker

        real = scheduler_worker._agent_config_for_schedule

        def _load(row):
            with engine.begin() as conn:
                _take_over(conn, schedule, OWNER)
            return real(row)

        return patch("docsgpt.api.user.scheduler_worker._agent_config_for_schedule", _load)

    def test_the_taker_pays_and_the_run_is_theirs(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            run = _pending(conn, schedule)

        with self._take_over_while_loading(engine, schedule):
            result, headless = _execute(run)

        assert result["status"] == "success"
        assert headless.call_args.kwargs["payer"] == OWNER
        assert _run_row(engine, run)["user_id"] == OWNER

    def test_a_one_time_task_no_longer_reads_the_old_setters_chat(self, engine, notified):
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository

        with engine.begin() as conn:
            tid, _ = _team(conn)
            chat = ConversationsRepository(conn).create(EDITOR, "Private", team_id=tid)
            ConversationsRepository(conn).append_message(
                str(chat["id"]), {"prompt": "secret plan", "response": "noted", "metadata": {}},
            )
            _tid, schedule = _once_schedule(conn, origin=str(chat["id"]))
            run = _pending(conn, schedule)

        with self._take_over_while_loading(engine, schedule):
            result, headless = _execute(run)

        assert result["status"] == "success"
        kwargs = headless.call_args.kwargs
        assert kwargs["payer"] == OWNER
        assert kwargs["conversation_id"] is None
        assert kwargs["chat_history"] == []
        with engine.connect() as conn:
            assert len(ConversationsRepository(conn).get_messages(str(chat["id"]))) == 1


class TestTakerAlsoOutOfAllowance:
    def test_a_new_payers_pause_is_its_own_streak_and_tells_them(self, engine, notified):
        with engine.begin() as conn:
            _tid, schedule = _team_schedule(conn)
            first = _pending(conn, schedule)
            second = _pending(conn, schedule, minutes=5)
            _out_of_allowance(conn, EDITOR)
            _out_of_allowance(conn, OWNER)
        assert _execute(first)[0]["status"] == "skipped"
        with engine.begin() as conn:
            _take_over(conn, schedule, OWNER)

        assert _execute(second)[0]["status"] == "skipped"

        row = _run_row(engine, second)
        assert (row["status"], row["error_type"], row["user_id"]) == ("skipped", "payer_out_of_allowance", OWNER)
        assert [n["user_id"] for n in notified] == [EDITOR, OWNER]
