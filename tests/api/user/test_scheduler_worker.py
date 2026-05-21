"""Tests for execute_scheduled_run_body (mocked agent run)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from application.api.user.scheduler_worker import execute_scheduled_run_body
from application.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from application.storage.db.repositories.schedules import SchedulesRepository


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
        "application.api.user.scheduler_worker.get_engine",
        lambda: pg_engine,
    )
    monkeypatch.setattr(
        "application.api.user.scheduler_worker.settings",
        type("S", (), {
            "POSTGRES_URI": str(pg_engine.url),
            "SCHEDULE_AUTOPAUSE_FAILURES": 2,
        })(),
    )
    yield pg_engine


@pytest.fixture
def stub_events(monkeypatch):
    captured: list[tuple] = []

    def _fake_publish(user_id, event_type, payload, *, scope=None):
        captured.append((event_type, payload, scope))
        return "1-0"

    monkeypatch.setattr(
        "application.api.user.scheduler_worker.publish_user_event",
        _fake_publish,
    )
    return captured


class TestExecuteScheduledRunBody:
    def test_success_flow(self, pg_engine, patched_engine, stub_events):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "application.api.user.scheduler_worker.run_agent_headless",
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

    def test_agent_exception_marks_failed_and_bumps(
        self, pg_engine, patched_engine, stub_events,
    ):
        with pg_engine.begin() as conn:
            schedule, run, _ = _make_pending_run(conn)
        with patch(
            "application.api.user.scheduler_worker.run_agent_headless",
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
            "application.api.user.scheduler_worker.run_agent_headless",
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
            "application.api.user.scheduler_worker.run_agent_headless",
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
            "application.api.user.scheduler_worker.run_agent_headless", _fake_run,
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
            "application.api.user.scheduler_worker.run_agent_headless",
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
            "application.api.user.scheduler_worker.run_agent_headless",
            _fake_run,
        ):
            execute_scheduled_run_body(str(run["id"]), "celery-no-snap")
        cfg = captured["agent_config"]
        # ``tools`` MUST NOT be in the ephemeral shape — the runtime
        # toolset is rebuilt by ``ToolExecutor`` (which honours headless
        # filtering for chat-only tools like ``scheduler``).
        assert "tools" not in cfg

    def test_agentless_token_usage_row_has_null_agent_id(
        self, pg_engine, patched_engine, stub_events,
    ):
        """token_usage row for an agentless run carries ``agent_id IS NULL``."""
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
        with patch(
            "application.api.user.scheduler_worker.run_agent_headless",
            return_value={
                "answer": "yes",
                "tool_calls": [], "sources": [], "thought": "",
                "prompt_tokens": 11, "generated_tokens": 7,
                "denied": [], "error_type": None, "model_id": "fake",
            },
        ):
            execute_scheduled_run_body(str(run["id"]), "celery-tu")
        with pg_engine.connect() as conn:
            tu_row = conn.execute(
                text(
                    "SELECT * FROM token_usage "
                    "WHERE request_id = :r"
                ),
                {"r": str(run["id"])},
            ).fetchone()
        assert tu_row is not None
        assert tu_row._mapping["agent_id"] is None
        assert tu_row._mapping["source"] == "schedule"

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
            "application.api.user.scheduler_worker.run_agent_headless",
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
