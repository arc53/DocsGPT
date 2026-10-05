"""Beat sweeps over background jobs: lost leases, blown deadlines, retention.

* A job held by a process (``inprocess`` / ``celery``) whose heartbeat stopped
  is ``lost``: the process died with the call in it. Its delivery is the lost
  note, so the agent learns the work may or may not have happened.
* A job past its deadline is failed, whichever runner holds it.
* Finished jobs and settled wakes past retention are deleted (daily).

Locks are taken only to pick rows; each job is finished in its own
transaction by :func:`docsgpt.background.jobs.finalize`, whose write is
conditional, so a sweep racing a finishing call never overwrites its result.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from docsgpt.background import jobs, pool
from docsgpt.background.results import LOST_NOTE
from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversation_wakes import ConversationWakesRepository
from docsgpt.storage.db.session import db_session

logger = logging.getLogger(__name__)

#: Seconds past ``deadline_at`` before a running job is failed.
DEADLINE_GRACE_SECONDS = 60

#: Runners whose liveness is this process's heartbeat.
_LEASED_RUNNERS = ("inprocess", "celery")


def _pick(fetch) -> List[Dict[str, Any]]:
    """Run one locking SELECT in its own short transaction and return the rows."""
    with db_session() as conn:
        return fetch(BackgroundJobsRepository(conn))


def sweep() -> Dict[str, int]:
    """One reconciler tick over background jobs.

    Returns:
        Counts: ``lost`` and ``timed_out``.
    """
    summary = {"lost": 0, "timed_out": 0}
    if not settings.POSTGRES_URI:
        return summary

    stale = _pick(lambda repo: repo.find_stale_working(stale_seconds=pool.STALE_SECONDS, runners=_LEASED_RUNNERS))
    for row in stale:
        done = jobs.finalize(
            str(row["id"]),
            status="lost",
            error={"type": "Lost", "message": LOST_NOTE},
            status_message="interrupted: the process running it stopped",
            stale_seconds=pool.STALE_SECONDS,
        )
        if done is not None:
            summary["lost"] += 1
            logger.warning(
                "background job lost",
                extra={"alert": "background_job_lost", "job_id": str(row["id"]), "tool_name": row.get("tool_name")},
            )

    late = _pick(lambda repo: repo.find_past_deadline(grace_seconds=DEADLINE_GRACE_SECONDS))
    for row in late:
        _cancel_remote(row)
        limit = int(settings.BACKGROUND_JOB_MAX_SECONDS)
        done = jobs.finalize(
            str(row["id"]),
            status="failed",
            error={
                "type": "TimeoutError",
                "message": f"The job ran past its {limit}s limit and was stopped; it may have partly run.",
            },
            status_message="timed out",
        )
        if done is not None:
            summary["timed_out"] += 1
    return summary


def _cancel_remote(row: Dict[str, Any]) -> None:
    """Stop the work behind a job when its runner can (a detached sandbox command)."""
    if row.get("runner") != "sandbox":
        return
    try:
        from docsgpt.background.sandbox_runner import cancel_detached

        cancel_detached(row)
    except ImportError:
        return
    except Exception:
        logger.exception("background job %s: stopping the sandbox command failed", row.get("id"))


def cleanup() -> Dict[str, int]:
    """Delete finished jobs past retention and settled wakes older than it.

    Returns:
        Counts: ``jobs`` and ``wakes`` deleted.
    """
    if not settings.POSTGRES_URI:
        return {"jobs": 0, "wakes": 0}
    days = int(settings.BACKGROUND_RESULT_RETENTION_DAYS)
    with db_session() as conn:
        deleted_jobs = BackgroundJobsRepository(conn).cleanup_expired()
        deleted_wakes = ConversationWakesRepository(conn).cleanup_older_than(days)
    return {"jobs": deleted_jobs, "wakes": deleted_wakes}
