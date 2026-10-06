"""Reading and steering jobs, for the ``check_job`` tool and the job routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from docsgpt.background.events import publish_job_updated
from docsgpt.background.results import model_status
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversation_wakes import ConversationWakesRepository
from docsgpt.storage.db.session import db_session

logger = logging.getLogger(__name__)


def parse_time(value: Any) -> Optional[datetime]:
    """A row timestamp (datetime or ISO string) as a datetime, or None."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def elapsed_seconds(job: Dict[str, Any]) -> int:
    """Seconds the job has run, or ran (start to finish)."""
    started = parse_time(job.get("started_at"))
    if started is None:
        return 0
    finished = parse_time(job.get("finished_at")) or datetime.now(timezone.utc)
    return max(0, int((finished - started).total_seconds()))


def job_summary(job: Dict[str, Any]) -> Dict[str, Any]:
    """One job as the job card and a job listing show it (no result body).

    Args:
        job: The ``background_jobs`` row.

    Returns:
        ``{job_id, conversation_id, tool_name, action_name, status, status_message,
        progress, output_tail, elapsed_s, started_at, finished_at, delivery_state,
        cancel_requested}``.
    """
    return {
        "job_id": str(job.get("id")),
        "conversation_id": str(job["conversation_id"]) if job.get("conversation_id") else None,
        "tool_name": job.get("tool_name"),
        "action_name": job.get("action_name"),
        "status": job.get("status"),
        "status_message": job.get("status_message"),
        "progress": job.get("progress") or {},
        "output_tail": job.get("output_tail"),
        "elapsed_s": elapsed_seconds(job),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "delivery_state": job.get("delivery_state"),
        "auto_resume": bool(job.get("auto_resume")),
        "cancel_requested": bool(job.get("cancel_requested_at")),
    }


def model_summary(job: Dict[str, Any]) -> Dict[str, Any]:
    """One job as a model sees it in a listing."""
    return {
        "job_id": str(job.get("id")),
        "tool": f"{job.get('tool_name')}.{job.get('action_name')}",
        "status": model_status(job.get("status")),
        "elapsed_s": elapsed_seconds(job),
        "result_delivered": job.get("delivery_state") != "pending",
    }


def claim_for_poll(job_id: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Take a finished job's result for the turn that polled it, so no continuation repeats it.

    Args:
        job_id: The job.

    Returns:
        ``(row, claimed)``; ``claimed`` is False when another path delivered it first.
    """
    with db_session() as conn:
        repo = BackgroundJobsRepository(conn)
        claimed = repo.claim_delivery(job_id, "claimed_by_poll")
        if claimed is not None:
            ConversationWakesRepository(conn).supersede_for_ref("job", str(job_id))
            return claimed, True
        return repo.get(job_id), False


def cancel_job(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Ask a job to stop; it reaches ``cancelled`` once its work really stops.

    A detached sandbox run is stopped on its next poll (queued now), and so is
    a device command (the device is told to kill it; one it never picked up
    is taken off its queue); a queued worker call never starts; an
    in-process call can't be interrupted, so it ends ``cancelled`` when it
    returns.

    Args:
        job_id: The job.
        user_id: Its owner.

    Returns:
        The job row, or None when the user has no such job.
    """
    with db_session() as conn:
        row = BackgroundJobsRepository(conn).request_cancel(job_id, user_id)
    if row is None:
        return None
    if row.get("status") == "working" and row.get("runner") == "sandbox":
        from docsgpt.background.sandbox_runner import enqueue_poll

        enqueue_poll(str(row["id"]), 0)
    elif row.get("status") == "working" and row.get("runner") == "device":
        from docsgpt.background.device_runner import enqueue_poll as enqueue_device_poll

        enqueue_device_poll(str(row["id"]), 0)
    publish_job_updated(row)
    return row
