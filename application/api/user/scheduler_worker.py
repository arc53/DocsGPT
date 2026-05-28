"""Body of ``execute_scheduled_run`` — runs a single agent execution.

Not a DURABLE_TASK: agent runs have side effects (messages, CRM writes)
and blind auto-retry would double them. Failures after agent.gen starts
are terminal and recorded; only the pre-start load is retry-safe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import text as sql_text

from application.agents.headless_runner import run_agent_headless
from application.core.settings import settings
from application.events.publisher import publish_user_event
from application.storage.db.base_repository import row_to_dict
from application.storage.db.engine import get_engine
from application.storage.db.repositories.conversations import (
    ConversationsRepository,
)
from application.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from application.storage.db.repositories.schedules import SchedulesRepository
from application.storage.db.repositories.token_usage import TokenUsageRepository

logger = logging.getLogger(__name__)


# Cap output verbatim in the run log; beyond the cap we keep the head and stamp output_truncated.
_OUTPUT_CAP_CHARS = 24_000


def _agent_config_for_schedule(schedule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve the agent row (agent-bound) or build an ephemeral classic config.

    For agentless schedules (``agent_id IS NULL``), the worker constructs an
    in-memory agent shape carrying just enough fields for ``run_agent_headless``:
    classic agent type, system-default retriever/chunks/prompt, no source, and
    the optional ``model_id`` override. The runtime toolset is rebuilt by
    ``ToolExecutor`` at fire time (current ``user_tools`` + non-disabled,
    non-headless-excluded defaults), so a snapshot here would be dead code.
    """
    if schedule.get("agent_id"):
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT * FROM agents WHERE id = CAST(:id AS uuid)"),
                {"id": str(schedule["agent_id"])},
            ).fetchone()
        return row_to_dict(row) if row is not None else None
    return _ephemeral_agent_for_agentless(schedule)


def _ephemeral_agent_for_agentless(
    schedule: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build an agent-shaped config for a schedule with no parent agent."""
    # ``agent_config["tools"]`` is intentionally omitted: ``run_agent_headless``
    # never reads it. The runtime toolset is rebuilt by
    # ``ToolExecutor._get_user_tools(owner)`` at fire time — same dereference
    # the agent-bound path uses, so a tool added/disabled after creation is
    # reflected. Headless mode there filters chat-only tools (``scheduler``).
    user_id = schedule.get("user_id")
    if not user_id:
        return None
    return {
        "id": None,
        "user_id": user_id,
        "agent_type": "classic",
        "retriever": "classic",
        "chunks": 2,
        "prompt_id": "default",
        "source_id": None,
        "default_model_id": schedule.get("model_id") or "",
    }


def _load_chat_history(schedule: Dict[str, Any]) -> list:
    """Originating conversation history (one-time only; recurring has none)."""
    origin = schedule.get("origin_conversation_id")
    if not origin or schedule.get("trigger_type") != "once":
        return []
    user_id = schedule.get("user_id")
    if not user_id:
        return []
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conv = ConversationsRepository(conn).get_any(str(origin), user_id)
            if conv is None:
                return []
            messages = ConversationsRepository(conn).get_messages(str(conv["id"]))
    except Exception:
        logger.exception("scheduler: failed loading chat history")
        return []
    history: list = []
    for msg in messages:
        if msg.get("prompt") and msg.get("response"):
            history.append({
                "prompt": msg["prompt"],
                "response": msg["response"],
            })
    return history


def _publish_run_event(
    event_type: str, run: Dict[str, Any], schedule: Dict[str, Any], **extra: Any
) -> None:
    """Best-effort SSE publish for a scheduler run state transition."""
    user_id = run.get("user_id") or schedule.get("user_id")
    if not user_id:
        return
    agent_id_raw = schedule.get("agent_id")
    payload = {
        "run_id": str(run["id"]),
        "schedule_id": str(schedule["id"]),
        "agent_id": str(agent_id_raw) if agent_id_raw else None,
        "trigger_type": schedule.get("trigger_type"),
        "status": run.get("status"),
        **extra,
    }
    try:
        publish_user_event(
            user_id,
            event_type,
            payload,
            scope={"kind": "schedule", "id": str(schedule["id"])},
        )
    except Exception:
        logger.exception(
            "scheduler: SSE publish failed event=%s run=%s",
            event_type, run.get("id"),
        )


def _publish_message_appended(
    user_id: str,
    conversation_id: str,
    message: Dict[str, Any],
    schedule_id: str,
    run_id: str,
) -> None:
    """SSE message-appended event for a one-time run's chat turn."""
    try:
        publish_user_event(
            user_id,
            "schedule.message.appended",
            {
                "conversation_id": str(conversation_id),
                "message_id": str(message["id"]),
                "schedule_id": str(schedule_id),
                "run_id": str(run_id),
                "position": int(message.get("position", 0)),
            },
            scope={"kind": "conversation", "id": str(conversation_id)},
        )
    except Exception:
        logger.exception(
            "scheduler: message.appended publish failed run=%s", run_id,
        )


def _append_one_time_turn(
    schedule: Dict[str, Any],
    run: Dict[str, Any],
    outcome: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Insert an assistant turn in the originating conversation (once only)."""
    origin = schedule.get("origin_conversation_id")
    if not origin:
        return None
    engine = get_engine()
    user_id = schedule.get("user_id")
    metadata = {
        "scheduled": True,
        "schedule_id": str(schedule["id"]),
        "run_id": str(run["id"]),
        "scheduled_run_at": (
            run.get("scheduled_for")
            if isinstance(run.get("scheduled_for"), str)
            else None
        ),
    }
    with engine.begin() as conn:
        conv = ConversationsRepository(conn).get_any(str(origin), user_id)
        if conv is None:
            return None
        message = ConversationsRepository(conn).append_message(
            str(conv["id"]),
            {
                "prompt": schedule.get("instruction") or "",
                "response": outcome.get("answer") or "",
                "thought": outcome.get("thought") or "",
                "sources": outcome.get("sources") or [],
                "tool_calls": outcome.get("tool_calls") or [],
                "model_id": outcome.get("model_id"),
                "metadata": metadata,
            },
        )
    return message


def execute_scheduled_run_body(run_id: str, celery_task_id: Optional[str]) -> Dict[str, Any]:
    """Execute one scheduled run by id; returns a result dict for tracing."""
    if not settings.POSTGRES_URI:
        return {"status": "skipped", "reason": "POSTGRES_URI not set"}

    engine = get_engine()

    with engine.connect() as conn:
        run = ScheduleRunsRepository(conn).get_internal(run_id)
        if run is None:
            return {"status": "skipped", "reason": "run not found"}
        schedule = SchedulesRepository(conn).get_internal(str(run["schedule_id"]))
    if schedule is None:
        return {"status": "skipped", "reason": "schedule not found"}

    # Refuse non-runnable terminal states; manual run-now bypasses.
    if run.get("status") != "pending":
        return {"status": "skipped", "reason": f"run status={run.get('status')}"}
    if schedule.get("status") in {"cancelled", "completed"} and run.get(
        "trigger_source"
    ) != "manual":
        with engine.begin() as conn:
            ScheduleRunsRepository(conn).update(
                run_id,
                {
                    "status": "skipped",
                    "finished_at": datetime.now(timezone.utc),
                    "error_type": "internal",
                    "error": "schedule no longer active",
                },
            )
        return {"status": "skipped", "reason": "schedule terminal"}

    agent_config = _agent_config_for_schedule(schedule)
    if agent_config is None:
        with engine.begin() as conn:
            updated = ScheduleRunsRepository(conn).update(
                run_id,
                {
                    "status": "failed",
                    "finished_at": datetime.now(timezone.utc),
                    "error_type": "internal",
                    "error": "agent missing",
                },
            )
            SchedulesRepository(conn).bump_failure_count(str(schedule["id"]))
        _publish_run_event("schedule.run.failed", updated or run, schedule,
                           error="agent missing")
        return {"status": "failed", "reason": "agent missing"}

    with engine.begin() as conn:
        if not ScheduleRunsRepository(conn).mark_running(run_id, celery_task_id):
            return {"status": "skipped", "reason": "lost race to mark_running"}

    started = datetime.now(timezone.utc)
    instruction = schedule.get("instruction") or ""
    allowlist = schedule.get("tool_allowlist") or []
    chat_history = _load_chat_history(schedule)
    outcome: Dict[str, Any]
    error_type: Optional[str] = None
    error_text: Optional[str] = None
    timed_out = False
    try:
        outcome = run_agent_headless(
            agent_config,
            instruction,
            tool_allowlist=allowlist,
            model_id_override=schedule.get("model_id"),
            endpoint="schedule",
            conversation_id=schedule.get("origin_conversation_id"),
            chat_history=chat_history,
        )
    except SoftTimeLimitExceeded:
        timed_out = True
        outcome = {"answer": "", "tool_calls": [], "sources": [], "thought": ""}
        error_type = "timeout"
        error_text = "run exceeded soft time limit"
    except Exception as exc:
        outcome = {"answer": "", "tool_calls": [], "sources": [], "thought": ""}
        error_type = "agent_error"
        error_text = str(exc)
        logger.exception("scheduler: agent run failed run=%s", run_id)

    finished = datetime.now(timezone.utc)

    # Headless denial with no usable output → tool_not_allowed.
    if (
        error_type is None
        and (outcome.get("denied") or [])
        and not (outcome.get("answer") or "").strip()
    ):
        error_type = "tool_not_allowed"
        error_text = "headless allowlist blocked required tool"

    prompt_tokens = int(outcome.get("prompt_tokens", 0) or 0)
    generated_tokens = int(outcome.get("generated_tokens", 0) or 0)
    used_tokens = prompt_tokens + generated_tokens
    if (
        schedule.get("token_budget") is not None
        and int(schedule["token_budget"]) > 0
        and used_tokens > int(schedule["token_budget"])
    ):
        error_type = "budget_exceeded"
        error_text = (
            f"used {used_tokens} tokens exceeds budget "
            f"{schedule['token_budget']}"
        )

    answer = outcome.get("answer") or ""
    truncated = False
    if len(answer) > _OUTPUT_CAP_CHARS:
        answer = answer[:_OUTPUT_CAP_CHARS]
        truncated = True

    new_status = (
        "timeout" if timed_out else ("failed" if error_type else "success")
    )

    with engine.begin() as conn:
        update_fields: Dict[str, Any] = {
            "status": new_status,
            "started_at": started,
            "finished_at": finished,
            "output": answer or None,
            "output_truncated": truncated,
            "prompt_tokens": prompt_tokens,
            "generated_tokens": generated_tokens,
        }
        if error_type:
            update_fields["error_type"] = error_type
            update_fields["error"] = error_text
        updated_run = ScheduleRunsRepository(conn).update(run_id, update_fields)
        if used_tokens > 0:
            agent_id_raw = schedule.get("agent_id")
            try:
                TokenUsageRepository(conn).insert(
                    user_id=schedule.get("user_id"),
                    api_key=None,
                    prompt_tokens=prompt_tokens,
                    generated_tokens=generated_tokens,
                    timestamp=finished,
                    agent_id=str(agent_id_raw) if agent_id_raw else None,
                    source="schedule",
                    request_id=str(run_id),
                    model_id=outcome.get("model_id"),
                )
            except Exception:
                logger.exception(
                    "scheduler: token_usage insert failed run=%s", run_id,
                )
        schedules_repo = SchedulesRepository(conn)
        autopaused = False
        if new_status == "success":
            schedules_repo.reset_failure_count(str(schedule["id"]))
        elif new_status in ("failed", "timeout"):
            count = schedules_repo.bump_failure_count(str(schedule["id"]))
            if (
                settings.SCHEDULE_AUTOPAUSE_FAILURES > 0
                and count >= settings.SCHEDULE_AUTOPAUSE_FAILURES
                and schedule.get("trigger_type") == "recurring"
            ):
                autopaused = schedules_repo.autopause(str(schedule["id"]))
        # Once: terminal-flip on cron-fired runs only; manual runs on a
        # still-active once-schedule leave the future cadence intact.
        if (
            schedule.get("trigger_type") == "once"
            and run.get("trigger_source") != "manual"
            and schedule.get("status") == "active"
        ):
            schedules_repo.update_internal(
                str(schedule["id"]),
                {"status": "completed", "next_run_at": None},
            )

    appended: Optional[Dict[str, Any]] = None
    if (
        schedule.get("trigger_type") == "once"
        and new_status == "success"
        and schedule.get("origin_conversation_id")
    ):
        try:
            appended = _append_one_time_turn(schedule, updated_run or run, outcome)
        except Exception:
            logger.exception(
                "scheduler: append turn failed run=%s", run_id,
            )
        if appended is not None:
            with engine.begin() as conn:
                ScheduleRunsRepository(conn).update(
                    run_id,
                    {
                        "conversation_id": str(appended["conversation_id"]),
                        "message_id": str(appended["id"]),
                    },
                )
            _publish_message_appended(
                schedule.get("user_id"),
                str(appended["conversation_id"]),
                appended,
                str(schedule["id"]),
                run_id,
            )

    if new_status == "success":
        _publish_run_event("schedule.run.completed", updated_run or run, schedule)
    else:
        _publish_run_event(
            "schedule.run.failed",
            updated_run or run,
            schedule,
            error_type=error_type,
            error=error_text,
        )

    if autopaused:
        _publish_run_event(
            "schedule.autopaused",
            updated_run or run,
            schedule,
            consecutive_failure_count=settings.SCHEDULE_AUTOPAUSE_FAILURES,
        )

    return {
        "status": new_status,
        "run_id": run_id,
        "error_type": error_type,
    }
