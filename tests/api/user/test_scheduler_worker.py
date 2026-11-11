"""Tests for execute_scheduled_run_body (mocked agent run)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.user.scheduler_worker import execute_scheduled_run_body
from docsgpt.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from docsgpt.storage.db.repositories.schedules import SchedulesRepository


pytestmark = pytest.mark.fresh_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_agent(conn, user_id: str = "u1") -> str:
    row = conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status, default_model_id) "
            "VALUES (:u, 'a', 'draft', '') RETURNING id"
        ),
        {"u": user_id},
    ).fetchone()
    return str(row[0])


def _make_pending_run(conn, *, user_id="u1"):
    agent_id = _make_agent(conn, user_id)
    schedule = SchedulesRepository(conn).create(
        user_id=user_id, agent_id=agent_id, trigger_type="recurring",
        instruction="hello", cron="* * * * *",
        next_run_at=_now() + timedelta(minutes=5),
    )
    run = ScheduleRunsRepository(conn).record_pending(
        str(schedule["id"]),
        user_id,
        agent_id,
        _now(),
    )
    return schedule, run, agent_id


@pytest.fixture
def patched_engine(pg_engine, monkeypatch):
    monkeypatch.setattr(
        "docsgpt.api.user.scheduler_worker.get_engine",
        lambda: pg_engine,
    )
    monkeypatch.setattr(
        "docsgpt.api.user.scheduler_worker.settings",
        type("S", (), {
            "POSTGRES_URI": str(pg_engine.url),
            "SCHEDULE_AUTOPAUSE_FAILURES": 2,
            "SCHEDULE_NOTIFY_RECURRING_FAILURES": False,
        })(),
    )
    yield pg_engine


@pytest.fixture(autouse=True)
def quiet_notifications(monkeypatch):
    """No test here reaches presence, the unread mark or Web Push unless it records them itself."""
    monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: None)


@pytest.fixture
def stub_events(monkeypatch):
    captured: list[tuple] = []

    def _fake_publish(user_id, event_type, payload, *, scope=None):
        captured.append((event_type, payload, scope))
        return "1-0"

    monkeypatch.setattr(
        "docsgpt.api.user.scheduler_worker.publish_user_event",
        _fake_publish,
    )
    return captured


class TestExecuteScheduledRunBody:
    def test_success_flow(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "all done",
                "tool_calls": [],
                "sources": [],
                "thought": "",
                "prompt_tokens": 10,
                "generated_tokens": 5,
                "denied": [],
                "error_type": None,
                "model_id": "fake-model",
            },
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-1")
        assert result["status"] == "success"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "success"
        assert row["output"] == "all done"
        assert row["prompt_tokens"] == 10
        assert sched["consecutive_failure_count"] == 0
        event_types = [e[0] for e in stub_events]
        assert "schedule.run.completed" in event_types
        # Activity › Now lists the run from its start.
        assert event_types.index("schedule.run.started") < event_types.index("schedule.run.completed")

    def test_agent_exception_marks_failed_and_bumps(
        self, pg_engine, patched_engine, stub_events,
    ):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            side_effect=RuntimeError("boom"),
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-2")
        assert result["status"] == "failed"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "failed"
        assert row["error_type"] == "agent_error"
        assert sched["consecutive_failure_count"] == 1
        assert "schedule.run.failed" in {e[0] for e in stub_events}

    def test_quota_refusal_marks_budget_exceeded(
        self, pg_engine, patched_engine, stub_events,
    ):
        from datetime import datetime, timezone

        from docsgpt.quotas.service import QuotaExceeded, QuotaExceededError

        exceeded = QuotaExceeded(
            user_id="u1", bucket="all", budget="tokens", usage=10, limit=10,
            source="instance", source_id=None,
            resets_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        with pg_engine.begin() as conn:
            _, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            side_effect=QuotaExceededError(exceeded),
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-q")
        assert result["status"] == "failed"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["error_type"] == "budget_exceeded"
        assert "Usage quota reached" in row["error"]

    def test_autopause_after_threshold(
        self, pg_engine, patched_engine, stub_events,
    ):
        with pg_engine.begin() as conn:
            schedule, run, agent_id = _make_pending_run(conn)
            SchedulesRepository(conn).bump_failure_count(str(schedule["id"]))
            another_run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]),
                "u1",
                agent_id,
                _now() + timedelta(seconds=1),
            )
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            side_effect=RuntimeError("boom"),
        ):
            execute_scheduled_run_body(str(another_run["id"]), "celery-3")
        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert sched["status"] == "paused"
        assert "schedule.autopaused" in {e[0] for e in stub_events}

    def test_denied_with_empty_output_marks_tool_not_allowed(
        self, pg_engine, patched_engine, stub_events,
    ):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "",
                "tool_calls": [],
                "sources": [],
                "thought": "",
                "prompt_tokens": 1,
                "generated_tokens": 0,
                "denied": [{"tool_name": "telegram"}],
                "error_type": "tool_not_allowed",
                "model_id": "fake",
            },
        ):
            execute_scheduled_run_body(str(run["id"]), "celery-4")
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["status"] == "failed"
        assert row["error_type"] == "tool_not_allowed"

    def test_stream_error_from_runner_marks_failed(
        self, pg_engine, patched_engine, stub_events,
    ):
        """The runner's ``error_type`` must be honoured, not re-derived.

        Regression: the worker only ever inferred ``tool_not_allowed`` itself
        and never read ``outcome["error_type"]``, so a stream that failed
        mid-flight was recorded ``success``.
        """
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "",
                "tool_calls": [],
                "sources": [],
                "thought": "",
                "prompt_tokens": 9417,
                "generated_tokens": 0,
                "denied": [],
                "error_type": "stream_error",
                "error": "Fallback LLM also failed mid-stream; giving up",
                "model_id": "fake",
            },
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-se")
        assert result["status"] == "failed"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "failed"
        assert row["error_type"] == "stream_error"
        assert "Fallback LLM also failed" in (row["error"] or "")
        assert sched["consecutive_failure_count"] == 1
        assert "schedule.run.failed" in {e[0] for e in stub_events}

    def test_empty_output_run_marks_failed(
        self, pg_engine, patched_engine, stub_events,
    ):
        """A run that produced nothing at all is not a success.

        This is the exact prod shape: seven consecutive daily runs recorded
        ``success`` with NULL output and 0/0 tokens, so nothing surfaced that
        the user's scheduled agent had been dead since it was created. It is
        the backstop for silent paths that emit no error event either.
        """
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "",
                "tool_calls": [],
                "sources": [],
                "thought": "",
                "prompt_tokens": 0,
                "generated_tokens": 0,
                "denied": [],
                "error_type": None,
                "model_id": "fake",
            },
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-eo")
        assert result["status"] == "failed"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["status"] == "failed"
        assert row["error_type"] == "empty_output"

    def test_tool_call_only_run_is_not_empty_output(
        self, pg_engine, patched_engine, stub_events,
    ):
        """A run whose work was tool side effects still counts as a success.

        Guards the backstop against over-reach: "no prose answer" is normal
        for a schedule whose whole job is to call a tool (post to Slack, file
        a ticket), so tokens or tool calls are enough to call it a success.
        """
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "",
                "tool_calls": [{"tool_name": "telegram_send", "result": "ok"}],
                "sources": [],
                "thought": "",
                "prompt_tokens": 120,
                "generated_tokens": 8,
                "denied": [],
                "error_type": None,
                "model_id": "fake",
            },
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-tc")
        assert result["status"] == "success"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["status"] == "success"
        assert row["error_type"] is None

    def test_workflow_run_with_completed_steps_is_not_empty_output(
        self, pg_engine, patched_engine, stub_events,
    ):
        """A workflow that ran its nodes did work, however quiet the stream.

        Workflow tool calls never surface as ``tool_calls`` events (the engine
        keeps them in its execution log), and a workflow of code or state
        nodes calls no LLM at all. Such a workflow whose end node has no
        output template matches the empty-output shape exactly —
        ``steps_completed`` is what tells them apart. Without it, every such
        schedule fails and then autopauses.
        """
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "",
                "tool_calls": [],
                "sources": [],
                "thought": "",
                "prompt_tokens": 0,
                "generated_tokens": 0,
                "denied": [],
                "error_type": None,
                "steps_completed": 3,
                "model_id": "fake",
            },
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-wf")
        assert result["status"] == "success"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["status"] == "success"
        assert row["error_type"] is None

    def test_workflow_run_with_no_completed_steps_is_empty_output(
        self, pg_engine, patched_engine, stub_events,
    ):
        """A workflow that completed no node still did nothing."""
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "",
                "tool_calls": [],
                "sources": [],
                "thought": "",
                "prompt_tokens": 0,
                "generated_tokens": 0,
                "denied": [],
                "error_type": None,
                "steps_completed": 0,
                "model_id": "fake",
            },
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-wf0")
        assert result["status"] == "failed"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["error_type"] == "empty_output"

    def test_one_time_loads_chat_history(
        self, pg_engine, patched_engine, stub_events,
    ):
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=agent_id, trigger_type="once",
                instruction="follow up", run_at=_now() + timedelta(seconds=5),
                next_run_at=_now(),
            )
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, agent_id, name) "
                    "VALUES ('u1', CAST(:a AS uuid), 'origin') RETURNING id"
                ),
                {"a": agent_id},
            ).fetchone()[0]
            SchedulesRepository(conn).update_internal(
                str(schedule["id"]),
                {"origin_conversation_id": str(conv_id)},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO conversation_messages
                        (conversation_id, position, prompt, response, user_id)
                    VALUES (CAST(:c AS uuid), 0, 'hello', 'hi', 'u1')
                    """
                ),
                {"c": str(conv_id)},
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", agent_id, _now(),
            )
        captured: dict = {}
        def _fake_run(agent_config, query, **kwargs):
            captured.update(kwargs)
            return {
                "answer": "follow-up answer",
                "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 1, "generated_tokens": 1,
                "denied": [], "error_type": None, "model_id": "fake",
            }
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless", _fake_run,
        ):
            execute_scheduled_run_body(str(run["id"]), "celery-h")
        assert len(captured.get("chat_history", [])) == 1
        assert captured["chat_history"][0]["prompt"] == "hello"

    def test_agentless_schedule_uses_system_defaults_and_appends(
        self, pg_engine, patched_engine, stub_events,
    ):
        """Agentless ``once`` schedule → ephemeral classic agent → message appended."""
        with pg_engine.begin() as conn:
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, name) "
                    "VALUES ('u1', 'agentless-origin') RETURNING id"
                )
            ).fetchone()[0]
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=None, trigger_type="once",
                instruction="follow up agentless",
                run_at=_now() + timedelta(seconds=5),
                next_run_at=_now(),
                origin_conversation_id=str(conv_id),
                created_via="chat",
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", None, _now(),
            )
        captured: dict = {}

        def _fake_run(agent_config, query, **kwargs):
            captured["agent_config"] = agent_config
            captured["kwargs"] = kwargs
            return {
                "answer": "agentless ran",
                "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 4, "generated_tokens": 6,
                "denied": [], "error_type": None, "model_id": "fake",
            }

        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            _fake_run,
        ):
            result = execute_scheduled_run_body(str(run["id"]), "celery-agentless")
        assert result["status"] == "success"
        # Ephemeral classic config: no source, default retriever, no agent id.
        cfg = captured["agent_config"]
        assert cfg["id"] is None
        assert cfg["user_id"] == "u1"
        assert cfg["agent_type"] == "classic"
        assert cfg["retriever"] == "classic"
        assert cfg["prompt_id"] == "default"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            messages = conn.execute(
                text(
                    "SELECT * FROM conversation_messages "
                    "WHERE conversation_id = CAST(:c AS uuid)"
                ),
                {"c": str(conv_id)},
            ).fetchall()
        assert row["status"] == "success"
        assert row["output"] == "agentless ran"
        assert row["conversation_id"] is not None
        assert len(messages) == 1
        # The published event payload tolerates a NULL agent_id.
        appended_events = [e for e in stub_events if e[0] == "schedule.message.appended"]
        assert appended_events

    def test_agentless_ephemeral_config_omits_tools_snapshot(
        self, pg_engine, patched_engine, stub_events,
    ):
        """Dead ``tools`` snapshot dropped — toolset is rebuilt at fire time."""
        with pg_engine.begin() as conn:
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, name) "
                    "VALUES ('u1', 'no-tools-snap') RETURNING id"
                )
            ).fetchone()[0]
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=None, trigger_type="once",
                instruction="x", run_at=_now() + timedelta(seconds=5),
                next_run_at=_now(),
                origin_conversation_id=str(conv_id),
                created_via="chat",
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", None, _now(),
            )
        captured: dict = {}

        def _fake_run(agent_config, query, **kwargs):
            captured["agent_config"] = agent_config
            return {
                "answer": "ok", "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 1, "generated_tokens": 1,
                "denied": [], "error_type": None, "model_id": "fake",
            }

        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            _fake_run,
        ):
            execute_scheduled_run_body(str(run["id"]), "celery-no-snap")
        cfg = captured["agent_config"]
        # ``tools`` MUST NOT be in the ephemeral shape — the runtime
        # toolset is rebuilt by ``ToolExecutor`` (which honours headless
        # filtering for chat-only tools like ``scheduler``).
        assert "tools" not in cfg

    def test_each_llm_call_is_recorded_once(
        self, pg_engine, patched_engine, stub_events,
    ):
        """A run writes no total of its own: its calls' rows (written as they ran) are the only record."""
        with pg_engine.begin() as conn:
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, name) "
                    "VALUES ('u1', 'agentless-tu') RETURNING id"
                )
            ).fetchone()[0]
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=None, trigger_type="once",
                instruction="tu", run_at=_now() + timedelta(seconds=5),
                next_run_at=_now(),
                origin_conversation_id=str(conv_id),
                created_via="chat",
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", None, _now(),
            )
        def _run_with_one_llm_call(*args, **kwargs):
            # What the usage decorator writes for the run's one LLM call.
            with pg_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO token_usage (user_id, prompt_tokens, generated_tokens, source, model_id) "
                        "VALUES ('u1', 11, 7, 'agent_stream', 'fake')"
                    )
                )
            return {
                "answer": "yes",
                "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 11, "generated_tokens": 7,
                "denied": [], "error_type": None, "model_id": "fake",
            }

        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            side_effect=_run_with_one_llm_call,
        ):
            execute_scheduled_run_body(str(run["id"]), "celery-tu")
        with pg_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT source, prompt_tokens + generated_tokens AS tokens FROM token_usage WHERE user_id = 'u1'")
            ).fetchall()
            run_row = conn.execute(
                text("SELECT prompt_tokens, generated_tokens FROM schedule_runs WHERE id = CAST(:r AS uuid)"),
                {"r": str(run["id"])},
            ).one()
        assert [(row.source, row.tokens) for row in rows] == [("agent_stream", 18)]
        # The run keeps its own total on its row.
        assert (run_row.prompt_tokens, run_row.generated_tokens) == (11, 7)

    def test_one_time_appends_message(
        self, pg_engine, patched_engine, stub_events,
    ):
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=agent_id, trigger_type="once",
                instruction="hello", run_at=_now() + timedelta(seconds=5),
                next_run_at=_now(),
            )
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, agent_id, name) "
                    "VALUES ('u1', CAST(:a AS uuid), 'origin') RETURNING id"
                ),
                {"a": agent_id},
            ).fetchone()[0]
            SchedulesRepository(conn).update_internal(
                str(schedule["id"]),
                {"origin_conversation_id": str(conv_id)},
            )
            run = ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", agent_id, _now(),
            )
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "scheduled answer",
                "tool_calls": [],
                "sources": [],
                "thought": "",
                "prompt_tokens": 2,
                "generated_tokens": 3,
                "denied": [],
                "error_type": None,
                "model_id": "fake",
            },
        ):
            execute_scheduled_run_body(str(run["id"]), "celery-5")
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            messages = conn.execute(
                text(
                    "SELECT * FROM conversation_messages "
                    "WHERE conversation_id = CAST(:c AS uuid)"
                ),
                {"c": str(conv_id)},
            ).fetchall()
        assert row["conversation_id"] is not None
        assert row["message_id"] is not None
        assert len(messages) == 1
        meta = messages[0]._mapping["message_metadata"]
        assert meta.get("scheduled") is True
        assert "schedule.message.appended" in {e[0] for e in stub_events}


class TestOneTimeRunNotifies:
    """A reminder lands in its conversation while the user may be elsewhere: they are notified like a wake."""

    def _once(self, conn, *, name=None):
        agent_id = _make_agent(conn)
        schedule = SchedulesRepository(conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="once", name=name,
            instruction="remind me to stretch", run_at=_now() + timedelta(seconds=5), next_run_at=_now(),
        )
        conv_id = conn.execute(
            text(
                "INSERT INTO conversations (user_id, agent_id, name) "
                "VALUES ('u1', CAST(:a AS uuid), 'origin') RETURNING id"
            ),
            {"a": agent_id},
        ).fetchone()[0]
        SchedulesRepository(conn).update_internal(str(schedule["id"]), {"origin_conversation_id": str(conv_id)})
        run = ScheduleRunsRepository(conn).record_pending(str(schedule["id"]), "u1", agent_id, _now())
        return str(conv_id), run

    def _execute(self, run, answer):
        outcome = {
            "answer": answer, "tool_calls": [], "sources": [], "thought": "", "prompt_tokens": 1,
            "generated_tokens": 1, "denied": [], "error_type": None, "model_id": "fake",
        }
        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", return_value=outcome):
            execute_scheduled_run_body(str(run["id"]), "celery-7")

    def test_the_appended_reminder_is_notified(self, pg_engine, patched_engine, stub_events, monkeypatch):
        notified = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: notified.append(kw))
        with pg_engine.begin() as conn:
            conv_id, run = self._once(conn, name="Stretch break")
        self._execute(run, "**Time to stretch!**\n\n- Stand up\n- Roll your shoulders")
        assert len(notified) == 1
        sent = notified[0]
        assert sent["kind"] == "schedule"
        assert sent["user_id"] == "u1"
        assert sent["conversation_id"] == conv_id
        assert sent["url"] == f"/c/{conv_id}"
        assert sent["title"] == "Stretch break"
        assert sent["body"] == "Time to stretch! Stand up Roll your shoulders"

    def test_an_unnamed_schedule_is_titled_by_its_instruction(self, pg_engine, patched_engine, stub_events,
                                                              monkeypatch):
        notified = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: notified.append(kw))
        with pg_engine.begin() as conn:
            _conv_id, run = self._once(conn)
        self._execute(run, "Stretch now.")
        assert notified[0]["title"] == "remind me to stretch"

    def test_a_run_that_appends_nothing_notifies_nobody(self, pg_engine, patched_engine, stub_events, monkeypatch):
        notified = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: notified.append(kw))
        with pg_engine.begin() as conn:
            _schedule, run, _agent = _make_pending_run(conn)
        self._execute(run, "recurring output")
        assert notified == []


def _outcome(answer: str, **extra) -> dict:
    """What ``run_agent_headless`` returns for a run that answered ``answer``."""
    return {
        "answer": answer, "tool_calls": [], "sources": [], "thought": "", "prompt_tokens": 40,
        "generated_tokens": 12, "denied": [], "error_type": None, "model_id": "fake", **extra,
    }


def _execute_with(run, outcome: dict) -> dict:
    """Run the worker over one run, the agent replaced by ``outcome``."""
    with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", return_value=outcome):
        return execute_scheduled_run_body(str(run["id"]), "celery-cc")


REASON = "Step 1 (open the site): no browser tool."
EXPLANATION = "I couldn't open the site: this agent has no browser tool. Nothing else was checked."


class TestCannotComplete:
    """An agent that reports it has no way to do the task fails the run, so the schedule can pause."""

    def test_a_report_fails_the_run_with_its_reason(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)

        result = _execute_with(run, _outcome(EXPLANATION, cannot_complete=REASON))

        assert result == {"status": "failed", "run_id": str(run["id"]), "error_type": "cannot_complete"}
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["status"] == "failed"
        assert row["error_type"] == "cannot_complete"
        assert row["error"] == REASON
        assert row["output"] == EXPLANATION
        assert sched["consecutive_failure_count"] == 1
        failed = next(e[1] for e in stub_events if e[0] == "schedule.run.failed")
        assert failed["error_type"] == "cannot_complete"
        assert failed["error"] == REASON

    def test_the_third_one_in_a_row_pauses_a_recurring_schedule(
        self, pg_engine, patched_engine, stub_events, monkeypatch,
    ):
        from docsgpt.api.user import scheduler_worker

        monkeypatch.setattr(scheduler_worker.settings, "SCHEDULE_AUTOPAUSE_FAILURES", 3)
        with pg_engine.begin() as conn:
            schedule, first, agent_id = _make_pending_run(conn)
            later = [
                ScheduleRunsRepository(conn).record_pending(
                    str(schedule["id"]), "u1", agent_id, _now() + timedelta(minutes=i),
                )
                for i in (1, 2)
            ]

        for index, run in enumerate([first, *later]):
            _execute_with(run, _outcome(EXPLANATION, cannot_complete="no email tool to send the report"))
            with pg_engine.connect() as conn:
                sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
            assert sched["consecutive_failure_count"] == index + 1
            assert sched["status"] == ("paused" if index == 2 else "active")
        assert [e[0] for e in stub_events].count("schedule.autopaused") == 1

    def test_a_run_with_no_report_succeeds(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
            SchedulesRepository(conn).bump_failure_count(str(schedule["id"]))
        answer = "The site is up. I cannot complete the login check without an account, so I skipped it."

        result = _execute_with(run, _outcome(answer, cannot_complete=None))

        assert result["status"] == "success"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            sched = SchedulesRepository(conn).get_internal(str(schedule["id"]))
        assert row["error_type"] is None
        assert row["output"] == answer
        assert sched["consecutive_failure_count"] == 0

    def test_a_run_that_already_failed_keeps_its_error(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            _schedule, run, _ = _make_pending_run(conn)

        _execute_with(run, _outcome("", cannot_complete="no email tool", error_type="stream_error", error="peer closed"))

        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["error_type"] == "stream_error"
        assert row["error"] == "peer closed"

    def test_a_one_time_task_from_a_chat_fails_but_still_explains_there(
        self, pg_engine, patched_engine, stub_events, monkeypatch,
    ):
        notified = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: notified.append(kw))
        with pg_engine.begin() as conn:
            conv_id, run = TestOneTimeRunNotifies()._once(conn, name="Morning check")

        result = _execute_with(run, _outcome(EXPLANATION, cannot_complete=REASON))

        assert result["status"] == "failed"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            messages = conn.execute(
                text("SELECT response FROM conversation_messages WHERE conversation_id = CAST(:c AS uuid)"),
                {"c": conv_id},
            ).fetchall()
            sched = SchedulesRepository(conn).get_internal(str(row["schedule_id"]))
        assert row["error_type"] == "cannot_complete"
        assert row["message_id"] is not None
        assert str(row["conversation_id"]) == conv_id
        assert [m[0] for m in messages] == [EXPLANATION]
        assert notified[0]["body"] == EXPLANATION
        assert sched["status"] == "completed"

    def test_a_report_with_no_answer_tells_the_chat_its_reason(
        self, pg_engine, patched_engine, stub_events, monkeypatch,
    ):
        # A bare marker, or a workflow node that reported but streamed nothing.
        notified = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: notified.append(kw))
        with pg_engine.begin() as conn:
            conv_id, run = TestOneTimeRunNotifies()._once(conn, name="Morning check")

        _execute_with(run, _outcome("", cannot_complete="Check site: no browser tool"))

        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            messages = conn.execute(
                text("SELECT response FROM conversation_messages WHERE conversation_id = CAST(:c AS uuid)"),
                {"c": conv_id},
            ).fetchall()
        assert [m[0] for m in messages] == ["Check site: no browser tool"]
        assert notified[0]["body"] == "Check site: no browser tool"
        assert row["output"] is None
        assert row["error"] == "Check site: no browser tool"


class TestPauseNotifies:
    """A recurring schedule that pauses itself tells its owner once, with why."""

    @pytest.fixture
    def notified(self, monkeypatch):
        from docsgpt.api.user import scheduler_worker

        sent: list[dict] = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: sent.append(kw))
        monkeypatch.setattr(scheduler_worker.settings, "SCHEDULE_AUTOPAUSE_FAILURES", 3)
        return sent

    def _recurring(self, conn, *, name=None, instruction="Post the nightly CRM digest"):
        agent_id = _make_agent(conn)
        schedule = SchedulesRepository(conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring", name=name,
            instruction=instruction, cron="0 2 * * *", next_run_at=_now() + timedelta(hours=1),
        )
        return schedule, agent_id

    def _runs(self, conn, schedule, agent_id, count, *, start=0, trigger_source="cron"):
        return [
            ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", agent_id, _now() + timedelta(minutes=start + i),
                trigger_source=trigger_source,
            )
            for i in range(count)
        ]

    def _resume(self, conn, schedule):
        SchedulesRepository(conn).update_internal(
            str(schedule["id"]), {"status": "active", "next_run_at": _now() + timedelta(hours=1)},
        )
        SchedulesRepository(conn).reset_failure_count(str(schedule["id"]))

    def test_the_failure_that_pauses_it_notifies_once_with_the_reason(
        self, pg_engine, patched_engine, stub_events, notified,
    ):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn, name="Nightly CRM digest")
            runs = self._runs(conn, schedule, agent_id, 3)

        for index, run in enumerate(runs):
            _execute_with(run, _outcome(EXPLANATION, cannot_complete=f"No CRM tool on run {index + 1}."))
            assert len(notified) == (1 if index == 2 else 0)

        schedule_id = str(schedule["id"])
        assert notified[0] == {
            "user_id": "u1",
            "conversation_id": None,
            "kind": "schedule_paused",
            "title": "Nightly CRM digest",
            "body": "No CRM tool on run 3.",
            "url": f"/activity/schedules?schedule={schedule_id}",
            "schedule_id": schedule_id,
        }

    def test_failures_below_the_threshold_notify_nobody(self, pg_engine, patched_engine, stub_events, notified):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn)
            runs = self._runs(conn, schedule, agent_id, 2)

        for run in runs:
            with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", side_effect=RuntimeError("boom")):
                execute_scheduled_run_body(str(run["id"]), "celery-p")

        assert notified == []

    def test_a_resumed_schedule_that_pauses_again_notifies_again(
        self, pg_engine, patched_engine, stub_events, notified,
    ):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn, name="Digest")
            first = self._runs(conn, schedule, agent_id, 3)
        for run in first:
            _execute_with(run, _outcome("", cannot_complete="No CRM tool."))
        with pg_engine.begin() as conn:
            self._resume(conn, schedule)
            second = self._runs(conn, schedule, agent_id, 3, start=10)
        for run in second:
            _execute_with(run, _outcome("", cannot_complete="Still no CRM tool."))

        assert [(n["kind"], n["body"]) for n in notified] == [
            ("schedule_paused", "No CRM tool."),
            ("schedule_paused", "Still no CRM tool."),
        ]

    def test_a_run_on_a_paused_schedule_does_not_notify_again(
        self, pg_engine, patched_engine, stub_events, notified,
    ):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn)
            runs = self._runs(conn, schedule, agent_id, 3)
            manual = self._runs(conn, schedule, agent_id, 1, start=10, trigger_source="manual")
        for run in [*runs, *manual]:
            _execute_with(run, _outcome("", cannot_complete="No CRM tool."))

        assert len(notified) == 1

    def test_an_unnamed_schedule_is_titled_by_its_instruction(
        self, pg_engine, patched_engine, stub_events, notified,
    ):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn, instruction="Check **every** open ticket\nand ping owners")
            runs = self._runs(conn, schedule, agent_id, 3)
        for run in runs:
            _execute_with(run, _outcome("", cannot_complete="No ticket tool."))

        assert notified[0]["title"] == "Check every open ticket and ping owners"

    def test_a_refused_tool_is_named_in_the_body(self, pg_engine, patched_engine, stub_events, notified):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn)
            runs = self._runs(conn, schedule, agent_id, 3)
        refused = _outcome(
            "", error_type="tool_not_allowed", error="headless allowlist blocked required tool: crm_update",
        )
        for run in runs:
            _execute_with(run, refused)

        assert notified[0]["body"] == "headless allowlist blocked required tool: crm_update"

    def test_a_timeout_says_so(self, pg_engine, patched_engine, stub_events, notified):
        from celery.exceptions import SoftTimeLimitExceeded

        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn)
            runs = self._runs(conn, schedule, agent_id, 3)
        for run in runs:
            with patch(
                "docsgpt.api.user.scheduler_worker.run_agent_headless", side_effect=SoftTimeLimitExceeded(),
            ):
                execute_scheduled_run_body(str(run["id"]), "celery-t")

        assert notified[0]["kind"] == "schedule_paused"
        assert notified[0]["body"] == "run exceeded soft time limit"

    def test_the_body_is_the_errors_first_line(self, pg_engine, patched_engine, stub_events, notified):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._recurring(conn)
            runs = self._runs(conn, schedule, agent_id, 3)
        long_error = "Upstream refused the token\n  File \"x.py\", line 3\n" + "detail " * 200
        for run in runs:
            with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", side_effect=RuntimeError(long_error)):
                execute_scheduled_run_body(str(run["id"]), "celery-l")

        assert notified[0]["body"] == "Upstream refused the token"

    def test_a_one_time_task_is_never_paused_or_notified_as_paused(
        self, pg_engine, patched_engine, stub_events, notified,
    ):
        with pg_engine.begin() as conn:
            agent_id = _make_agent(conn)
            schedule = SchedulesRepository(conn).create(
                user_id="u1", agent_id=agent_id, trigger_type="once", instruction="once",
                run_at=_now() + timedelta(seconds=5), next_run_at=_now(),
            )
            for _ in range(3):
                SchedulesRepository(conn).bump_failure_count(str(schedule["id"]))
            run = ScheduleRunsRepository(conn).record_pending(str(schedule["id"]), "u1", agent_id, _now())
        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", side_effect=RuntimeError("boom")):
            execute_scheduled_run_body(str(run["id"]), "celery-o")

        assert notified == []


class TestFirstFailureNotifies:
    """With ``SCHEDULE_NOTIFY_RECURRING_FAILURES`` on, the first failure after a success is notified too."""

    @pytest.fixture
    def notified(self, monkeypatch):
        from docsgpt.api.user import scheduler_worker

        sent: list[dict] = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: sent.append(kw))
        monkeypatch.setattr(scheduler_worker.settings, "SCHEDULE_AUTOPAUSE_FAILURES", 3)
        monkeypatch.setattr(scheduler_worker.settings, "SCHEDULE_NOTIFY_RECURRING_FAILURES", True)
        return sent

    def _execute_all(self, pg_engine, outcomes, *, trigger_source="cron"):
        helper = TestPauseNotifies()
        with pg_engine.begin() as conn:
            schedule, agent_id = helper._recurring(conn, name="Digest")
            runs = helper._runs(conn, schedule, agent_id, len(outcomes), trigger_source=trigger_source)
        for run, outcome in zip(runs, outcomes):
            _execute_with(run, outcome)
        return schedule

    def test_the_first_failure_after_a_success_is_notified_once(
        self, pg_engine, patched_engine, stub_events, notified,
    ):
        fail = _outcome("", cannot_complete="No CRM tool.")
        schedule = self._execute_all(pg_engine, [_outcome("done"), fail, fail, _outcome("done"), fail])

        url = f"/activity/schedules?schedule={schedule['id']}"
        assert [(n["kind"], n["title"], n["body"], n["url"]) for n in notified] == [
            ("schedule_failed", "Digest", "No CRM tool.", url),
            ("schedule_failed", "Digest", "No CRM tool.", url),
        ]

    def test_the_pause_still_notifies_as_a_pause(self, pg_engine, patched_engine, stub_events, notified):
        fail = _outcome("", cannot_complete="No CRM tool.")
        self._execute_all(pg_engine, [fail, fail, fail])

        assert [n["kind"] for n in notified] == ["schedule_failed", "schedule_paused"]

    def test_a_run_started_by_hand_is_not_notified_as_failed(
        self, pg_engine, patched_engine, stub_events, notified,
    ):
        self._execute_all(pg_engine, [_outcome("", cannot_complete="No CRM tool.")], trigger_source="manual")

        assert notified == []

    def test_off_by_default(self, pg_engine, patched_engine, stub_events, notified, monkeypatch):
        from docsgpt.api.user import scheduler_worker
        from docsgpt.core.settings.scheduler import SchedulerSettings

        assert SchedulerSettings.model_fields["SCHEDULE_NOTIFY_RECURRING_FAILURES"].default is False
        monkeypatch.setattr(scheduler_worker.settings, "SCHEDULE_NOTIFY_RECURRING_FAILURES", False)
        self._execute_all(pg_engine, [_outcome("", cannot_complete="No CRM tool.")])

        assert notified == []


class TestRunAsOwnerAccessRecheck:
    """A schedule someone set on another user's agent re-checks their access
    on every run; the run itself always executes as the agent's owner."""

    def _member_run(self, conn, *, grant: bool):
        import uuid as _uuid

        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        agent_id = _make_agent(conn, "owner-x")
        if grant:
            team = TeamsRepository(conn).create("T", f"t-{_uuid.uuid4().hex[:8]}", "owner-x")
            TeamMembersRepository(conn).add_member(str(team["id"]), "member-y")
            TeamResourceGrantsRepository(conn).grant(
                str(team["id"]), "agent", agent_id, "owner-x", "owner-x",
                access_level="viewer",
            )
        schedule = SchedulesRepository(conn).create(
            user_id="member-y", agent_id=agent_id, trigger_type="recurring",
            instruction="hello", cron="* * * * *",
            next_run_at=_now() + timedelta(minutes=5),
        )
        run = ScheduleRunsRepository(conn).record_pending(
            str(schedule["id"]), "member-y", agent_id, _now(),
        )
        return run

    def test_revoked_member_run_fails_without_running(
        self, pg_engine, patched_engine, stub_events,
    ):
        with pg_engine.begin() as conn:
            run = self._member_run(conn, grant=False)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
        ) as headless:
            result = execute_scheduled_run_body(str(run["id"]), "celery-r")
        headless.assert_not_called()
        assert result["status"] == "failed"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["status"] == "failed"
        assert row["error"] == "agent access revoked"

    def test_revoked_access_pauses_the_schedule_and_tells_its_user(
        self, pg_engine, patched_engine, stub_events, monkeypatch,
    ):
        from docsgpt.api.user import scheduler_worker

        notified: list[dict] = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: notified.append(kw))
        monkeypatch.setattr(scheduler_worker.settings, "SCHEDULE_NOTIFY_RECURRING_FAILURES", True)
        with pg_engine.begin() as conn:
            first = self._member_run(conn, grant=False)
            second = ScheduleRunsRepository(conn).record_pending(
                str(first["schedule_id"]), "member-y", str(first["agent_id"]), _now() + timedelta(minutes=1),
            )

        for run in (first, second):
            execute_scheduled_run_body(str(run["id"]), "celery-r")

        with pg_engine.connect() as conn:
            sched = SchedulesRepository(conn).get_internal(str(first["schedule_id"]))
        assert sched["status"] == "paused"
        assert "schedule.autopaused" in {e[0] for e in stub_events}
        assert [(n["kind"], n["user_id"], n["body"]) for n in notified] == [
            ("schedule_failed", "member-y", "agent access revoked"),
            ("schedule_paused", "member-y", "agent access revoked"),
        ]

    def test_member_with_grant_runs(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            run = self._member_run(conn, grant=True)
        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "ok", "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 1, "generated_tokens": 1, "denied": [],
                "error_type": None, "model_id": "m",
            },
        ) as headless:
            result = execute_scheduled_run_body(str(run["id"]), "celery-g")
        assert result["status"] == "success"
        # Runs with the owner's agent row (owner's context).
        assert headless.call_args.args[0]["user_id"] == "owner-x"


_OK = {
    "answer": "ok", "tool_calls": [], "sources": [], "thought": "",
    "prompt_tokens": 1, "generated_tokens": 1, "denied": [],
    "error_type": None, "model_id": "m",
}


class TestCallerRules:
    """A scheduled run acts as the owner but keeps the rules of whoever set it."""

    def _run(self, conn, *, owner="owner-x", user="owner-x", shared=False, created_via="ui", grant=False):
        import uuid as _uuid

        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        agent_id = _make_agent(conn, owner)
        conn.execute(text("UPDATE agents SET shared = :s WHERE id = CAST(:id AS uuid)"),
                     {"s": shared, "id": agent_id})
        if grant:
            team = TeamsRepository(conn).create("T", f"t-{_uuid.uuid4().hex[:8]}", owner)
            TeamMembersRepository(conn).add_member(str(team["id"]), user)
            TeamResourceGrantsRepository(conn).grant(
                str(team["id"]), "agent", agent_id, owner, owner, access_level="viewer",
            )
        schedule = SchedulesRepository(conn).create(
            user_id=user, agent_id=agent_id, trigger_type="once", instruction="hello",
            run_at=_now(), next_run_at=_now(), created_via=created_via,
        )
        return ScheduleRunsRepository(conn).record_pending(str(schedule["id"]), user, agent_id, _now())

    def _caller(self, pg_engine, **kwargs):
        with pg_engine.begin() as conn:
            run = self._run(conn, **kwargs)
        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", return_value=_OK) as headless:
            assert execute_scheduled_run_body(str(run["id"]), "celery-c")["status"] == "success"
        return {k: headless.call_args.kwargs.get(k) for k in ("external_caller", "public_link_caller")}

    def test_public_link_users_schedule_runs_as_a_public_link_caller(self, pg_engine, patched_engine, stub_events):
        assert self._caller(pg_engine, user="stranger", shared=True) == {
            "external_caller": False, "public_link_caller": True,
        }

    def test_team_members_schedule_runs_as_a_teammate(self, pg_engine, patched_engine, stub_events):
        assert self._caller(pg_engine, user="member-y", shared=True, grant=True) == {
            "external_caller": False, "public_link_caller": False,
        }

    def test_schedule_set_through_the_api_runs_as_an_external_caller(self, pg_engine, patched_engine, stub_events):
        assert self._caller(pg_engine, created_via="api") == {
            "external_caller": True, "public_link_caller": False,
        }

    def test_owners_own_schedule_runs_as_the_owner(self, pg_engine, patched_engine, stub_events):
        assert self._caller(pg_engine) == {"external_caller": False, "public_link_caller": False}


def _cannot_start(monkeypatch, reason: str) -> None:
    """Make the worker stop before running the agent, for ``reason``."""
    from docsgpt.api.user import scheduler_worker

    if reason == "agent missing":
        monkeypatch.setattr(scheduler_worker, "_agent_config_for_schedule", lambda schedule: None)
    else:
        monkeypatch.setattr(scheduler_worker, "_scheduler_still_allowed", lambda schedule, agent: False)


class TestRunStartedByHand:
    """A failed Run now is watched by whoever started it, so it doesn't count toward auto-pause."""

    def _schedule(self, conn, *, failures: int = 0):
        agent_id = _make_agent(conn)
        schedule = SchedulesRepository(conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="Post the nightly CRM digest", cron="0 2 * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        for _ in range(failures):
            SchedulesRepository(conn).bump_failure_count(str(schedule["id"]))
        return schedule, agent_id

    def _runs(self, conn, schedule, agent_id, count, trigger_source):
        return [
            ScheduleRunsRepository(conn).record_pending(
                str(schedule["id"]), "u1", agent_id, _now() + timedelta(minutes=i),
                trigger_source=trigger_source,
            )
            for i in range(count)
        ]

    def _stored(self, pg_engine, schedule):
        with pg_engine.connect() as conn:
            return SchedulesRepository(conn).get_internal(str(schedule["id"]))

    def test_failed_manual_runs_neither_count_nor_pause(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._schedule(conn)
            runs = self._runs(conn, schedule, agent_id, 3, "manual")

        for run in runs:
            result = _execute_with(run, _outcome("", cannot_complete="No CRM tool."))
            assert result["error_type"] == "cannot_complete"

        stored = self._stored(pg_engine, schedule)
        assert stored["consecutive_failure_count"] == 0
        assert stored["status"] == "active"
        assert stored["next_run_at"] == schedule["next_run_at"]
        assert "schedule.autopaused" not in {e[0] for e in stub_events}

    def test_failed_scheduled_runs_still_count_and_pause(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._schedule(conn)
            runs = self._runs(conn, schedule, agent_id, 2, "cron")

        for run in runs:
            _execute_with(run, _outcome("", cannot_complete="No CRM tool."))

        stored = self._stored(pg_engine, schedule)
        assert stored["consecutive_failure_count"] == 2
        assert stored["status"] == "paused"

    def test_a_manual_run_that_errors_does_not_count(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._schedule(conn, failures=1)
            (run,) = self._runs(conn, schedule, agent_id, 1, "manual")

        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", side_effect=RuntimeError("boom")):
            assert execute_scheduled_run_body(str(run["id"]), "celery-m")["status"] == "failed"

        stored = self._stored(pg_engine, schedule)
        assert stored["consecutive_failure_count"] == 1
        assert stored["status"] == "active"

    def test_a_manual_run_that_times_out_does_not_count(self, pg_engine, patched_engine, stub_events):
        from celery.exceptions import SoftTimeLimitExceeded

        with pg_engine.begin() as conn:
            schedule, agent_id = self._schedule(conn, failures=1)
            (run,) = self._runs(conn, schedule, agent_id, 1, "manual")

        with patch(
            "docsgpt.api.user.scheduler_worker.run_agent_headless", side_effect=SoftTimeLimitExceeded(),
        ):
            assert execute_scheduled_run_body(str(run["id"]), "celery-t")["status"] == "timeout"

        stored = self._stored(pg_engine, schedule)
        assert stored["consecutive_failure_count"] == 1
        assert stored["status"] == "active"

    @pytest.mark.parametrize("reason", ["agent missing", "agent access revoked"])
    def test_a_manual_run_that_cannot_start_does_not_count(
        self, pg_engine, patched_engine, stub_events, monkeypatch, reason,
    ):
        _cannot_start(monkeypatch, reason)
        with pg_engine.begin() as conn:
            schedule, agent_id = self._schedule(conn, failures=1)
            (run,) = self._runs(conn, schedule, agent_id, 1, "manual")

        assert execute_scheduled_run_body(str(run["id"]), "celery-s") == {"status": "failed", "reason": reason}

        stored = self._stored(pg_engine, schedule)
        assert stored["consecutive_failure_count"] == 1
        assert stored["status"] == "active"

    @pytest.mark.parametrize("reason", ["agent missing", "agent access revoked"])
    def test_a_scheduled_run_that_cannot_start_still_counts(
        self, pg_engine, patched_engine, stub_events, monkeypatch, reason,
    ):
        _cannot_start(monkeypatch, reason)
        with pg_engine.begin() as conn:
            schedule, agent_id = self._schedule(conn, failures=1)
            (run,) = self._runs(conn, schedule, agent_id, 1, "cron")

        execute_scheduled_run_body(str(run["id"]), "celery-s")

        stored = self._stored(pg_engine, schedule)
        assert stored["consecutive_failure_count"] == 2
        assert stored["status"] == "paused"

    def test_a_successful_manual_run_still_resets_the_count(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, agent_id = self._schedule(conn, failures=1)
            (run,) = self._runs(conn, schedule, agent_id, 1, "manual")

        assert _execute_with(run, _outcome("done"))["status"] == "success"

        assert self._stored(pg_engine, schedule)["consecutive_failure_count"] == 0


# What the fake provider reports for each agent node's one call.
_NODE_CALLS = {"Fetch prices": (1200, 300), "Write summary": (900, 250)}


def _fake_llm_class():
    """An LLM that streams a canned reply and reports the node's usage, as a provider would."""
    from docsgpt.llm.base import BaseLLM

    class _FakeLLM(BaseLLM):
        def __init__(self, *args, **kwargs):
            super().__init__(
                decoded_token=kwargs.get("decoded_token"),
                agent_id=kwargs.get("agent_id"),
                model_id=kwargs.get("model_id"),
            )
            self.user_api_key = kwargs.get("user_api_key")
            self.stateless = False

        def _supports_tools(self):
            return False

        def _raw_gen(self, baseself, model, messages, stream, tools=None, **kw):
            return "ok"

        def _raw_gen_stream(self, baseself, model, messages, stream, tools=None, **kw):
            system = str(messages[0].get("content", "")) if messages else ""
            title = next((t for t in _NODE_CALLS if t in system), None)
            prompt, completion = _NODE_CALLS.get(title, (10, 2))
            self._last_usage = {"prompt_tokens": prompt, "completion_tokens": completion}
            self._last_usage_claimed = False
            yield f"{title or 'reply'}: done."

    return _FakeLLM


class TestWorkflowRunTokens:
    """A workflow's node agents own their LLMs; the run row and the budget see their sum."""

    def _pending_workflow_run(self, conn, token_budget):
        from docsgpt.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
        from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        wf_id = str(WorkflowsRepository(conn).create("u1", "Nightly prices")["id"])
        nodes = WorkflowNodesRepository(conn).bulk_create(wf_id, 1, [
            {"node_id": "start", "node_type": "start", "title": "Start"},
            {"node_id": "fetch", "node_type": "agent", "title": "Fetch prices",
             "config": {"agent_type": "classic", "system_prompt": "Fetch prices", "stream_to_user": False}},
            {"node_id": "summary", "node_type": "agent", "title": "Write summary",
             "config": {"agent_type": "classic", "system_prompt": "Write summary"}},
            {"node_id": "end", "node_type": "end", "title": "End"},
        ])
        ids = {n["node_id"]: str(n["id"]) for n in nodes}
        WorkflowEdgesRepository(conn).bulk_create(wf_id, 1, [
            {"edge_id": f"e{i}", "from_node_id": ids[a], "to_node_id": ids[b]}
            for i, (a, b) in enumerate([("start", "fetch"), ("fetch", "summary"), ("summary", "end")])
        ])
        agent_id = str(conn.execute(
            text(
                "INSERT INTO agents (user_id, name, status, agent_type, workflow_id, default_model_id) "
                "VALUES ('u1', 'Prices', 'published', 'workflow', CAST(:w AS uuid), '') RETURNING id"
            ),
            {"w": wf_id},
        ).scalar())
        schedule = SchedulesRepository(conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring", instruction="Run the nightly report",
            cron="0 2 * * *", next_run_at=_now() + timedelta(days=1), token_budget=token_budget,
        )
        return ScheduleRunsRepository(conn).record_pending(str(schedule["id"]), "u1", agent_id, _now())

    def _execute(self, pg_engine, monkeypatch, token_budget=None):
        monkeypatch.setattr(
            "docsgpt.agents.base.LLMCreator.create_llm",
            classmethod(lambda cls, *a, **kw: _fake_llm_class()(*a, **kw)),
        )
        with pg_engine.begin() as conn:
            run = self._pending_workflow_run(conn, token_budget)
        result = execute_scheduled_run_body(str(run["id"]), "celery-wf-tokens")
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
            billed = conn.execute(
                text("SELECT prompt_tokens, generated_tokens FROM token_usage WHERE user_id = 'u1' ORDER BY id")
            ).fetchall()
        return result, row, [tuple(b) for b in billed]

    def test_the_run_row_sums_both_agent_nodes(self, pg_engine, patched_engine, stub_events, monkeypatch):
        result, row, billed = self._execute(pg_engine, monkeypatch)

        assert result["status"] == "success"
        assert (row["prompt_tokens"], row["generated_tokens"]) == (2100, 550)
        # Each node's call is billed once, as it ran; the run adds no row of its own.
        assert billed == [(1200, 300), (900, 250)]

    def test_a_workflow_over_its_token_budget_fails(self, pg_engine, patched_engine, stub_events, monkeypatch):
        result, row, billed = self._execute(pg_engine, monkeypatch, token_budget=1000)

        assert result["status"] == "failed"
        assert row["error_type"] == "budget_exceeded"
        assert row["error"] == "used 2650 tokens exceeds budget 1000"
        assert billed == [(1200, 300), (900, 250)]
