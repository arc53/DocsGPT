"""Reconciler tick: sweep stuck rows and escalate to terminal status + alert."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from sqlalchemy import Connection

from application.api.user.idempotency import MAX_TASK_ATTEMPTS
from application.core.settings import settings
from application.storage.db.engine import get_engine
from application.storage.db.repositories.reconciliation import (
    ReconciliationRepository,
)
from application.storage.db.repositories.stack_logs import StackLogsRepository

if TYPE_CHECKING:
    from application.storage.db.repositories.schedules import SchedulesRepository

logger = logging.getLogger(__name__)


MAX_MESSAGE_RECONCILE_ATTEMPTS = 3


def run_reconciliation() -> Dict[str, Any]:
    """Single tick of the reconciler. Five sweeps, FOR UPDATE SKIP LOCKED.

    Stuck ``executed`` tool calls always flip to ``failed`` — operators
    handle cleanup manually via the structured alert. The side effect is
    assumed to have committed; no automated rollback is attempted.

    Stuck ``task_dedup`` rows (lease expired AND attempts >= max)
    promote to ``failed`` so a same-key retry can re-claim instead of
    sitting in ``pending`` until 24 h TTL.
    """
    if not settings.POSTGRES_URI:
        return {
            "messages_failed": 0,
            "tool_calls_failed": 0,
            "skipped": "POSTGRES_URI not set",
        }

    engine = get_engine()
    summary = {
        "messages_failed": 0,
        "tool_calls_failed": 0,
        "ingests_stalled": 0,
        "idempotency_pending_failed": 0,
        "schedule_runs_failed": 0,
    }

    with engine.begin() as conn:
        repo = ReconciliationRepository(conn)
        for msg in repo.find_and_lock_stuck_messages():
            new_count = repo.increment_message_reconcile_attempts(msg["id"])
            if new_count >= MAX_MESSAGE_RECONCILE_ATTEMPTS:
                repo.mark_message_failed(
                    msg["id"],
                    error=(
                        "reconciler: stuck in pending/streaming for >5 min "
                        f"after {new_count} attempts"
                    ),
                )
                summary["messages_failed"] += 1
                _emit_alert(
                    conn,
                    name="reconciler_message_failed",
                    user_id=msg.get("user_id"),
                    detail={
                        "message_id": str(msg["id"]),
                        "attempts": new_count,
                    },
                )

    with engine.begin() as conn:
        repo = ReconciliationRepository(conn)
        for row in repo.find_and_lock_proposed_tool_calls():
            repo.mark_tool_call_failed(
                row["call_id"],
                error=(
                    "reconciler: stuck in 'proposed' for >5 min; "
                    "side effect status unknown"
                ),
            )
            summary["tool_calls_failed"] += 1
            _emit_alert(
                conn,
                name="reconciler_tool_call_failed_proposed",
                user_id=None,
                detail={
                    "call_id": row["call_id"],
                    "tool_name": row.get("tool_name"),
                },
            )

    with engine.begin() as conn:
        repo = ReconciliationRepository(conn)
        for row in repo.find_and_lock_executed_tool_calls():
            repo.mark_tool_call_failed(
                row["call_id"],
                error=(
                    "reconciler: executed-not-confirmed; side effect "
                    "assumed committed, manual cleanup required"
                ),
            )
            summary["tool_calls_failed"] += 1
            _emit_alert(
                conn,
                name="reconciler_tool_call_failed_executed",
                user_id=None,
                detail={
                    "call_id": row["call_id"],
                    "tool_name": row.get("tool_name"),
                    "action_name": row.get("action_name"),
                },
            )

    # Q4: ingest checkpoints whose heartbeat has gone silent. Each is
    # escalated to terminal ``status='stalled'`` and alerted once — no
    # worker kill, no rollback of the partial embed. The 'stalled' flag
    # ends the re-alert loop and drives the "indexing failed" badge the
    # sources list derives from this row.
    with engine.begin() as conn:
        repo = ReconciliationRepository(conn)
        for row in repo.find_and_lock_stalled_ingests():
            summary["ingests_stalled"] += 1
            _emit_alert(
                conn,
                name="reconciler_ingest_stalled",
                user_id=None,
                detail={
                    "source_id": str(row.get("source_id")),
                    "embedded_chunks": row.get("embedded_chunks"),
                    "total_chunks": row.get("total_chunks"),
                    "last_updated": str(row.get("last_updated")),
                },
            )
            repo.mark_ingest_stalled(str(row["source_id"]))

    # Q5: idempotency rows whose lease expired with attempts exhausted.
    # The wrapper's poison-loop guard normally finalises these, but if
    # the wrapper itself died mid-task (worker SIGKILL, OOM during
    # heartbeat) the row sits in ``pending`` blocking same-key retries
    # via ``_lookup_completed`` returning None for the whole 24 h TTL.
    # Promote to ``failed`` so a retry can re-claim and either resume
    # or fail loudly.
    with engine.begin() as conn:
        repo = ReconciliationRepository(conn)
        for row in repo.find_stuck_idempotency_pending(
            max_attempts=MAX_TASK_ATTEMPTS,
        ):
            error_msg = (
                "reconciler: idempotency lease expired with attempts "
                f"({row['attempt_count']}) >= {MAX_TASK_ATTEMPTS}; "
                "task abandoned"
            )
            repo.mark_idempotency_pending_failed(
                row["idempotency_key"], error=error_msg,
            )
            summary["idempotency_pending_failed"] += 1
            _emit_alert(
                conn,
                name="reconciler_idempotency_pending_failed",
                user_id=None,
                detail={
                    "idempotency_key": row["idempotency_key"],
                    "task_name": row.get("task_name"),
                    "task_id": row.get("task_id"),
                    "attempts": row.get("attempt_count"),
                },
            )

    # Q6: scheduler runs stuck in 'running' past the soft-time-limit window.
    from application.storage.db.repositories.schedule_runs import (
        ScheduleRunsRepository,
    )
    from application.storage.db.repositories.schedules import SchedulesRepository
    from application.core.settings import settings as _settings

    stuck_age = max(
        15, int(_settings.SCHEDULE_RUN_TIMEOUT // 60) + 5,
    )
    with engine.begin() as conn:
        runs_repo = ScheduleRunsRepository(conn)
        schedules_repo = SchedulesRepository(conn)
        for run in runs_repo.list_stuck_running(age_minutes=stuck_age):
            runs_repo.update(
                run["id"],
                {
                    "status": "timeout",
                    "finished_at": datetime.now(timezone.utc),
                    "error_type": "timeout",
                    "error": (
                        "reconciler: schedule_run stuck in 'running' past "
                        f"{stuck_age} min"
                    ),
                },
            )
            schedules_repo.bump_failure_count(str(run["schedule_id"]))
            _terminal_flip_once_schedule(
                schedules_repo, str(run["schedule_id"]),
            )
            summary["schedule_runs_failed"] += 1
            _emit_alert(
                conn,
                name="reconciler_schedule_run_timeout",
                user_id=run.get("user_id"),
                detail={
                    "run_id": str(run["id"]),
                    "schedule_id": str(run["schedule_id"]),
                },
            )

    # Q7: scheduler runs orphaned in 'pending' — dispatcher committed but
    # apply_async failed (broker outage / crash mid-dispatch).
    with engine.begin() as conn:
        runs_repo = ScheduleRunsRepository(conn)
        schedules_repo = SchedulesRepository(conn)
        for run in runs_repo.list_stuck_pending(age_minutes=stuck_age):
            runs_repo.update(
                run["id"],
                {
                    "status": "failed",
                    "finished_at": datetime.now(timezone.utc),
                    "error_type": "internal",
                    "error": (
                        "reconciler: schedule_run stuck in 'pending' past "
                        f"{stuck_age} min (worker_never_started)"
                    ),
                },
            )
            schedules_repo.bump_failure_count(str(run["schedule_id"]))
            _terminal_flip_once_schedule(
                schedules_repo, str(run["schedule_id"]),
            )
            summary["schedule_runs_failed"] += 1
            _emit_alert(
                conn,
                name="reconciler_schedule_run_pending",
                user_id=run.get("user_id"),
                detail={
                    "run_id": str(run["id"]),
                    "schedule_id": str(run["schedule_id"]),
                },
            )

    return summary


def _terminal_flip_once_schedule(
    schedules_repo: "SchedulesRepository", schedule_id: str,
) -> None:
    """Flip a once-schedule to 'completed' after its run terminates.

    Recurring schedules keep firing; once-schedules would otherwise read
    'active forever' since next_run_at is already NULL.
    """
    schedule = schedules_repo.get_internal(schedule_id)
    if schedule is None or schedule.get("trigger_type") != "once":
        return
    if schedule.get("status") in {"completed", "cancelled"}:
        return
    schedules_repo.update_internal(
        schedule_id, {"status": "completed", "next_run_at": None},
    )


def _emit_alert(
    conn: Connection,
    *,
    name: str,
    user_id: Optional[str],
    detail: Dict[str, Any],
) -> None:
    """Structured ``logger.error`` plus a ``stack_logs`` row for operators."""
    extra = {"alert": name, **detail}
    logger.error("reconciler alert: %s", name, extra=extra)
    try:
        StackLogsRepository(conn).insert(
            activity_id=str(uuid.uuid4()),
            endpoint="reconciliation_worker",
            level="ERROR",
            user_id=user_id,
            query=name,
            stacks=[extra],
        )
    except Exception:
        logger.exception("reconciler: failed to write stack_logs row for %s", name)
