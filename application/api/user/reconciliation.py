"""Reconciler tick: sweep stuck rows and escalate to terminal status + alert."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import Connection

from application.api.user.idempotency import MAX_TASK_ATTEMPTS
from application.core.settings import settings
from application.storage.db.engine import get_engine
from application.storage.db.repositories.reconciliation import (
    ReconciliationRepository,
)
from application.storage.db.repositories.stack_logs import StackLogsRepository

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

    # Q4: ingest checkpoints whose heartbeat has gone silent. The
    # reconciler only escalates (alerts) — it doesn't kill the worker
    # or roll back the partial embed. The next dispatch resumes from
    # ``last_index`` thanks to the per-chunk checkpoint, so this is an
    # observability sweep, not a recovery action.
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
            # Bump the heartbeat so we don't re-alert every tick.
            repo.touch_ingest_progress(str(row["source_id"]))

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

    return summary


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
