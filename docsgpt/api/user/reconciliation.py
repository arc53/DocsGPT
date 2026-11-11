"""Reconciler tick: sweep stuck rows and escalate to terminal status + alert."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional, TYPE_CHECKING

from sqlalchemy import Connection, Engine

from docsgpt.api.user.idempotency import MAX_TASK_ATTEMPTS
from docsgpt.core.settings import settings
from docsgpt.notifications.notify import mark_unread_unless_watching
from docsgpt.parser import ingest_resume
from docsgpt.storage.db.engine import get_engine
from docsgpt.storage.db.repositories.conversation_unread import ConversationUnreadRepository
from docsgpt.storage.db.repositories.idempotency import IdempotencyRepository
from docsgpt.storage.db.repositories.pending_tool_state import (
    PendingToolStateRepository,
)
from docsgpt.storage.db.repositories.reconciliation import (
    ReconciliationRepository,
)
from docsgpt.storage.db.repositories.stack_logs import StackLogsRepository

if TYPE_CHECKING:
    from docsgpt.storage.db.repositories.schedules import SchedulesRepository

logger = logging.getLogger(__name__)


MAX_MESSAGE_RECONCILE_ATTEMPTS = 3


def zero_summary() -> Dict[str, int]:
    """The counter keys every tick reports, all at zero.

    Single source of truth so the early-return and the caller's error
    fallback cannot drift from the sweeps that actually populate them.
    """
    return {
        "messages_failed": 0,
        "tool_calls_failed": 0,
        "ingests_stalled": 0,
        "ingests_resumed": 0,
        "idempotency_pending_failed": 0,
        "schedule_runs_failed": 0,
        "archive_members_failed": 0,
    }


def run_reconciliation() -> Dict[str, Any]:
    """Single tick of the reconciler. Every sweep uses FOR UPDATE SKIP LOCKED.

    Stuck ``executed`` tool calls always flip to ``failed`` — operators
    handle cleanup manually via the structured alert. The side effect is
    assumed to have committed; no automated rollback is attempted.

    Stuck ``task_dedup`` rows (lease expired AND attempts >= max)
    promote to ``failed`` so a same-key retry can re-claim instead of
    sitting in ``pending`` until 24 h TTL.
    """
    if not settings.POSTGRES_URI:
        return {**zero_summary(), "skipped": "POSTGRES_URI not set"}

    engine = get_engine()
    summary: Dict[str, Any] = zero_summary()
    # User-facing events to fan out once their DB writes have committed
    # (publish-after-commit). Each item is
    # ``(user_id, event_type, payload, scope)``.
    events: list[tuple] = []

    # Each sweep below commits in its own transaction, and the queued
    # user-facing events are fanned out once, at the end. The ``finally`` is
    # what makes a LATER sweep's failure non-destructive: without it, a
    # transient DB error discards events whose writes already landed — and the
    # loss is permanent, because every sweep filters out the rows it just made
    # terminal (``find_and_lock_stalled_ingests`` looks only at
    # ``status='active'``, ``find_and_lock_stuck_messages`` only at
    # pending/streaming), so no later tick re-finds them to re-emit. The user
    # is left with an upload toast spinning on "Training..." forever. Seen
    # live on 2026-08-21 when an Azure DNS blip took Postgres unreachable
    # mid-tick.
    #
    # Publish-after-commit is preserved by ``_sweep``: each sweep stages its
    # own events and they only reach ``events`` once that sweep's transaction
    # has committed. A sweep that raises PARTWAY THROUGH takes its staged
    # events down with its rolled-back writes, which is the point — otherwise
    # the ``finally`` would fan out terminal events for rows that are still
    # active, and the next tick would re-find those rows and emit a duplicate.
    try:
        return _run_sweeps(engine, summary, events)
    finally:
        _publish_events(events)


@contextmanager
def _sweep(engine: Engine, events: list[tuple]) -> Iterator[tuple[Connection, list[tuple]]]:
    """Open one sweep transaction, staging its events until it commits.

    Yields ``(conn, staged)``. Append user-facing events to ``staged``, never
    to ``events`` directly: ``staged`` is merged into ``events`` only after the
    ``engine.begin()`` block exits cleanly, so a sweep that raises mid-loop
    publishes nothing for the writes Postgres just rolled back.
    """
    staged: list[tuple] = []
    with engine.begin() as conn:
        yield conn, staged
    events.extend(staged)


def _run_sweeps(engine: Engine, summary: Dict[str, Any], events: list[tuple]) -> Dict[str, Any]:
    """Run every reconciler sweep, appending user-facing events to ``events``.

    Split out of :func:`run_reconciliation` so the caller can guarantee that
    events from sweeps that already COMMITTED are published even when a later
    sweep raises. Each sweep stages into its own list via :func:`_sweep`; see
    the comment in :func:`run_reconciliation` for why staging matters.
    """
    # Chats of the answers failed below, marked unread once the sweep has
    # committed: whether their owner is watching is a Redis read, which must
    # not hold the sweep's row locks.
    failed_chats: list[tuple[str, str]] = []
    with _sweep(engine, events) as (conn, staged):
        repo = ReconciliationRepository(conn)
        pt_repo = PendingToolStateRepository(conn)
        unread_repo = ConversationUnreadRepository(conn)
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
                failed_chat = unread_repo.listed_chat_of_message(str(msg["id"]))
                if failed_chat is not None:
                    failed_chats.append(failed_chat)
                # Revoke any awaiting-approval prompt: the resumable state
                # dies with the message, so the durable
                # ``tool.approval.required`` envelope must be cleared or the
                # UI toast lingers on reconnect. Only emit when a row was
                # actually deleted so non-approval failures stay quiet. Only
                # this message's pause: the row is per conversation, and a
                # later turn's live pause must survive an earlier turn's sweep.
                user_id = msg.get("user_id")
                conversation_id = msg.get("conversation_id")
                if (
                    user_id
                    and conversation_id
                    and pt_repo.delete_state(
                        str(conversation_id), str(user_id), message_id=str(msg["id"])
                    )
                ):
                    # Mark the row as having had its approval revoked. A late
                    # finalize is allowed to reclaim a reconciler-failed row
                    # (see ``finalize_message``), but must not reclaim this
                    # one: the resumable state is gone and the UI has already
                    # been told the approval was cleared, so landing an answer
                    # here would contradict what the user was shown.
                    repo.mark_message_approval_cleared(msg["id"])
                    staged.append(
                        (
                            str(user_id),
                            "tool.approval.cleared",
                            {
                                "conversation_id": str(conversation_id),
                                "message_id": str(msg["id"]),
                                "reason": "failed",
                            },
                            {"kind": "conversation", "id": str(conversation_id)},
                        )
                    )
                _emit_alert(
                    conn,
                    name="reconciler_message_failed",
                    user_id=msg.get("user_id"),
                    detail={
                        "message_id": str(msg["id"]),
                        "attempts": new_count,
                    },
                )

    for conversation_id, user_id in failed_chats:
        mark_unread_unless_watching(conversation_id, user_id, begin=engine.begin)

    with _sweep(engine, events) as (conn, staged):
        repo = ReconciliationRepository(conn)
        for row in repo.find_and_lock_proposed_tool_calls():
            repo.mark_tool_call_failed(
                row["call_id"],
                error=(
                    "reconciler: never advanced past 'proposed' for >5 min. "
                    "The row is written immediately before the tool runs, so "
                    "either the tool is still executing or the stream was "
                    "abandoned before it reported back; in the abandoned case "
                    "no side effect was committed."
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

    with _sweep(engine, events) as (conn, staged):
        repo = ReconciliationRepository(conn)
        for row in repo.find_and_lock_executed_tool_calls():
            repo.mark_tool_call_failed(
                row["call_id"],
                error=(
                    "reconciler: executed but not confirmed within 15 min. "
                    "The tool SUCCEEDED and its side effect is committed; "
                    "the parent stream has no fresh heartbeat and confirmation "
                    "never arrived. Verify the result before retrying."
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

    # Q4: ingest checkpoints whose heartbeat has gone silent. A restart or
    # OOM that killed the task leaves nothing to run it again once the
    # broker's redelivery is spent, so an ingest that stored its dispatch
    # is queued again (on the ingest queue, under its own task id) and
    # resumes from the checkpoint. One that cannot be resumed — no stored
    # dispatch, its files gone, its task finished, or out of resumes — is
    # escalated to terminal ``status='stalled'`` and alerted once, with no
    # worker kill and no rollback of the partial embed. The 'stalled' flag
    # ends the re-alert loop and drives the "indexing failed" badge the
    # sources list derives from this row. A task still holding its lease
    # (reading its files before the first chunk) is left alone.
    resumes: list[tuple[dict, str, str]] = []
    with _sweep(engine, events) as (conn, staged):
        repo = ReconciliationRepository(conn)
        dedup = IdempotencyRepository(conn)
        for row in repo.find_and_lock_stalled_ingests():
            source_id = str(row["source_id"])
            dispatch = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else None
            key = ingest_resume.guard_key(dispatch) if dispatch else None
            if key and dedup.live_lease_keys([key]):
                continue
            reason = _ingest_resume_refusal(dedup, row, dispatch, key)
            if reason is None:
                task_id = str(row.get("attempt_id") or uuid.uuid4())
                if not dedup.reset_for_resume(key, task_id) and dedup.get_task(key) is not None:
                    # A worker took the lease since the check above: it runs.
                    continue
                repo.mark_ingest_resumed(source_id, restart=settings.VECTOR_STORE == "faiss")
                resumes.append((dispatch, task_id, source_id))
                summary["ingests_resumed"] += 1
                logger.warning(
                    "reconciler: queuing stalled ingest of %s again", source_id,
                    extra={
                        "source_id": source_id,
                        "task_id": task_id,
                        "resume_attempt": int(row.get("resume_attempts") or 0) + 1,
                        "embedded_chunks": row.get("embedded_chunks"),
                        "total_chunks": row.get("total_chunks"),
                    },
                )
                continue
            summary["ingests_stalled"] += 1
            _emit_alert(
                conn,
                name="reconciler_ingest_stalled",
                user_id=row.get("user_id"),
                detail={
                    "source_id": source_id,
                    "embedded_chunks": row.get("embedded_chunks"),
                    "total_chunks": row.get("total_chunks"),
                    "last_updated": str(row.get("last_updated")),
                    "resume_attempts": row.get("resume_attempts"),
                    "reason": reason,
                },
            )
            repo.mark_ingest_stalled(source_id)
            # Tell the upload toast the ingest is done-for. Without it the
            # toast spins on "Training…" for the whole live session; only
            # ``source.ingest.failed`` flips it to a terminal error. A first
            # upload has no sources row yet: its stored dispatch names the user.
            stored = (dispatch or {}).get("kwargs") or {}
            user_id = row.get("user_id") or stored.get("user")
            if user_id:
                staged.append(
                    (
                        str(user_id),
                        "source.ingest.failed",
                        {
                            "source_id": source_id,
                            "filename": row.get("source_name") or stored.get("filename")
                            or stored.get("job_name") or "",
                            "operation": "upload",
                            "error": reason,
                        },
                        {"kind": "source", "id": source_id},
                    )
                )
    for dispatch, task_id, source_id in resumes:
        try:
            ingest_resume.requeue(dispatch, task_id)
        except Exception:
            # Counted already: the row comes back after the stale window
            # and is queued again, or given up once out of resumes.
            logger.exception("reconciler: could not queue the ingest of %s again", source_id)

    # Q5: idempotency rows whose lease expired with attempts exhausted.
    # The wrapper's poison-loop guard normally finalises these, but if
    # the wrapper itself died mid-task (worker SIGKILL, OOM during
    # heartbeat) the row sits in ``pending`` blocking same-key retries
    # via ``_lookup_completed`` returning None for the whole 24 h TTL.
    # Promote to ``failed`` so a retry can re-claim and either resume
    # or fail loudly.
    with _sweep(engine, events) as (conn, staged):
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
    from docsgpt.storage.db.repositories.schedule_runs import (
        ScheduleRunsRepository,
    )
    from docsgpt.storage.db.repositories.schedules import SchedulesRepository
    from docsgpt.core.settings import settings as _settings

    stuck_age = max(
        15, int(_settings.SCHEDULE_RUN_TIMEOUT // 60) + 5,
    )
    with _sweep(engine, events) as (conn, staged):
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
            # A Run now neither counts toward auto-pause nor closes a
            # one-time task, whose own run is still to come.
            manual = run.get("trigger_source") == "manual"
            if not manual:
                schedules_repo.bump_failure_count(str(run["schedule_id"]))
            flipped = not manual and _terminal_flip_once_schedule(
                schedules_repo, str(run["schedule_id"]),
            )
            summary["schedule_runs_failed"] += 1
            staged.extend(
                _schedule_terminal_events(
                    run,
                    error_type="timeout",
                    error=(
                        "reconciler: schedule_run stuck in 'running' past "
                        f"{stuck_age} min"
                    ),
                    once_completed=flipped,
                )
            )
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
    with _sweep(engine, events) as (conn, staged):
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
            # A Run now neither counts toward auto-pause nor closes a
            # one-time task, whose own run is still to come.
            manual = run.get("trigger_source") == "manual"
            if not manual:
                schedules_repo.bump_failure_count(str(run["schedule_id"]))
            flipped = not manual and _terminal_flip_once_schedule(
                schedules_repo, str(run["schedule_id"]),
            )
            summary["schedule_runs_failed"] += 1
            staged.extend(
                _schedule_terminal_events(
                    run,
                    error_type="internal",
                    error=(
                        "reconciler: schedule_run stuck in 'pending' past "
                        f"{stuck_age} min (worker_never_started)"
                    ),
                    once_completed=flipped,
                )
            )
            _emit_alert(
                conn,
                name="reconciler_schedule_run_pending",
                user_id=run.get("user_id"),
                detail={
                    "run_id": str(run["id"]),
                    "schedule_id": str(run["schedule_id"]),
                },
            )

    # Q8: zip attachment members queued past ATTACHMENT_ARCHIVE_MEMBER_TIMEOUT
    # with no outcome — their task was lost, so the zip would stay
    # "processing" (and the composer chip spinning) forever. Each is failed
    # with a reason; that frees its slot for the next member or completes
    # the zip, whose ``attachment.completed`` goes out after the commit.
    # Freed members are dispatched after the commit too, like the worker does.
    from docsgpt import worker as _worker

    member_dispatches: list = []
    with _sweep(engine, events) as (conn, staged):
        failed, member_dispatches, archive_events = _worker.sweep_stuck_archive_members(
            conn, timeout_seconds=int(_settings.ATTACHMENT_ARCHIVE_MEMBER_TIMEOUT),
        )
        staged.extend(archive_events)
        if failed:
            summary["archive_members_failed"] += failed
            _emit_alert(
                conn,
                name="reconciler_archive_members_failed",
                user_id=None,
                detail={
                    "members": failed,
                    "timeout_seconds": int(_settings.ATTACHMENT_ARCHIVE_MEMBER_TIMEOUT),
                },
            )
    for member_info, user_id in member_dispatches:
        try:
            # A member that cannot be queued is failed with the reason there.
            _worker._dispatch_archive_members([member_info], user_id)
        except Exception:
            # Stamped as dispatched: a member left without a task times out
            # on a later tick instead of stalling the zip.
            logger.exception("reconciler: failed to dispatch zip member %s", member_info.get("attachment_id"))

    return summary


_INGEST_STALLED = "Indexing stopped after a stall."


def _ingest_resume_refusal(
    dedup: IdempotencyRepository,
    row: Dict[str, Any],
    dispatch: Optional[dict],
    key: Optional[str],
) -> Optional[str]:
    """Why a stalled ingest cannot be queued again, or ``None`` when it can.

    Args:
        dedup: Repository on the sweep's connection.
        row: The locked progress row.
        dispatch: Its stored dispatch, if any.
        key: The dispatch's guard key, if any.

    Returns:
        The reason the user is shown, or ``None``.
    """
    if dispatch is None or key is None:
        return _INGEST_STALLED
    cap = int(settings.INGEST_RESUME_MAX_ATTEMPTS)
    attempts = int(row.get("resume_attempts") or 0)
    if cap <= 0:
        return _INGEST_STALLED
    if attempts >= cap:
        return f"Indexing stopped after {attempts} restarts."
    claim = dedup.get_task(key)
    if claim is not None and claim.get("status") != "pending":
        return _INGEST_STALLED
    if not ingest_resume.inputs_available(dispatch):
        return "Indexing stopped after a stall, and its files are no longer available."
    return None


def _terminal_flip_once_schedule(
    schedules_repo: "SchedulesRepository", schedule_id: str,
) -> bool:
    """Flip a once-schedule to 'completed' after its run terminates.

    Recurring schedules keep firing; once-schedules would otherwise read
    'active forever' since next_run_at is already NULL. Returns ``True``
    when the flip happened so the caller can publish a status event.
    """
    schedule = schedules_repo.get_internal(schedule_id)
    if schedule is None or schedule.get("trigger_type") != "once":
        return False
    if schedule.get("status") in {"completed", "cancelled"}:
        return False
    schedules_repo.update_internal(
        schedule_id, {"status": "completed", "next_run_at": None},
    )
    return True


def _schedule_terminal_events(
    run: Dict[str, Any],
    *,
    error_type: str,
    error: str,
    once_completed: bool,
) -> list:
    """Build the user-facing events for a reconciler-failed schedule run.

    Always a ``schedule.run.failed`` (so a watching run-log updates live),
    plus ``schedule.completed`` when a once-schedule flipped terminal — the
    UI otherwise shows it 'active' with stale Edit/Cancel actions until a
    manual refresh.
    """
    user_id = run.get("user_id")
    schedule_id = run.get("schedule_id")
    if not user_id or not schedule_id:
        return []
    scope = {"kind": "schedule", "id": str(schedule_id)}
    out: list = [
        (
            str(user_id),
            "schedule.run.failed",
            {
                "run_id": str(run["id"]),
                "schedule_id": str(schedule_id),
                "status": "failed",
                "error_type": error_type,
                "error": error,
            },
            scope,
        )
    ]
    if once_completed:
        out.append(
            (
                str(user_id),
                "schedule.completed",
                {"schedule_id": str(schedule_id), "status": "completed"},
                scope,
            )
        )
    return out


def _publish_events(events: list) -> None:
    """Fan out user-facing events after their DB writes have committed.

    Each item is ``(user_id, event_type, payload, scope)``. Best-effort:
    a publish miss is swallowed per event so one failure can't strand the
    rest, and notifications never surface as a reconciler-task failure.
    """
    if not events:
        return
    from docsgpt.events.publisher import publish_user_event

    for user_id, event_type, payload, scope in events:
        try:
            publish_user_event(user_id, event_type, payload, scope=scope)
        except Exception:
            logger.exception(
                "reconciler: failed to publish %s for user=%s",
                event_type,
                user_id,
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
