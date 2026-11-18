"""Beat sweeps over background jobs: lost leases, blown deadlines, retention.

* A job held by a process (``inprocess`` / ``celery``) whose heartbeat stopped
  is ``lost``: the process died with the call in it. Its delivery is the lost
  note, so the agent learns the work may or may not have happened.
* A job past its deadline is failed, whichever runner holds it; a device job
  whose device can't be reached to stop the command is lost instead.
* A ``sandbox`` or ``device`` job whose poll chain stopped is polled again
  (its work runs on elsewhere) before it is given up as lost.
* Finished jobs and settled wakes past retention are deleted (daily).

Locks are taken only to pick rows; each job is finished in its own
transaction by :func:`docsgpt.background.jobs.finalize`, whose write is
conditional, so a sweep racing a finishing call never overwrites its result.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from docsgpt.background import device_runner, jobs, pool, sandbox_runner
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

#: Heartbeat age after which a queued ``celery`` job no worker started is lost.
UNSTARTED_STALE_SECONDS = 900

#: Seconds an undelivered result waits before the sweep resumes its conversation again.
REDELIVER_AFTER_SECONDS = 300

#: Seconds a continuation may hold its claim before the sweep hands the events back.
CLAIM_STALE_SECONDS = 1800


def _pick(fetch) -> List[Dict[str, Any]]:
    """Run one locking SELECT in its own short transaction and return the rows."""
    with db_session() as conn:
        return fetch(BackgroundJobsRepository(conn))


def sweep() -> Dict[str, int]:
    """One reconciler tick over background jobs.

    Returns:
        Counts: ``lost``, ``revived`` (sandbox poll chains restarted), ``timed_out``,
        ``redelivered`` (conversations resumed again) and ``claims_released``.
    """
    summary = {"lost": 0, "timed_out": 0, "revived": 0}
    if not settings.POSTGRES_URI:
        return summary

    stale = _pick(
        lambda repo: repo.find_stale_working(
            stale_seconds=pool.stale_seconds(),
            runners=_LEASED_RUNNERS,
            unstarted_stale_seconds=UNSTARTED_STALE_SECONDS,
        )
    )
    for row in stale:
        if _mark_lost(row, stale_seconds=pool.stale_seconds() if row.get("lease_owner") else UNSTARTED_STALE_SECONDS):
            summary["lost"] += 1

    # A sandbox job's process runs on in the sandbox; a stale heartbeat means
    # its poll chain broke, so it is polled again before it is given up.
    broken = _pick(
        lambda repo: repo.find_stale_working(
            stale_seconds=sandbox_runner.POLL_STALE_SECONDS, runners=("sandbox",)
        )
    )
    for row in broken:
        if sandbox_runner.revive(row):
            summary["revived"] += 1
            continue
        _cancel_remote(row)
        if _mark_lost(row, stale_seconds=sandbox_runner.POLL_STALE_SECONDS):
            summary["lost"] += 1

    # Likewise a device job: the command runs on, on the device, whatever happened to its poll chain.
    adrift = _pick(
        lambda repo: repo.find_stale_working(stale_seconds=device_runner.POLL_STALE_SECONDS, runners=("device",))
    )
    for row in adrift:
        if device_runner.revive(row):
            summary["revived"] += 1
            continue
        _cancel_remote(row)
        if _mark_lost(row, stale_seconds=device_runner.POLL_STALE_SECONDS):
            summary["lost"] += 1

    late = _pick(lambda repo: repo.find_past_deadline(grace_seconds=DEADLINE_GRACE_SECONDS))
    for row in late:
        if row.get("runner") == "device":
            # Its poll chain normally ends it at the deadline; this is the backstop. Lost or timed out
            # depends on whether the device is there to stop the command.
            try:
                done = device_runner.on_deadline(row)
            except Exception:
                logger.exception("background job %s: ending the device job at its deadline failed", row.get("id"))
                continue
            if done is not None and done.get("status") == "failed":
                summary["timed_out"] += 1
            elif done is not None:
                summary["lost"] += 1
            continue
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

    summary.update(_redeliver())
    return summary


def _redeliver() -> Dict[str, int]:
    """Resume conversations whose results were not delivered (a lost task, a continuation that died)."""
    from docsgpt.background import wake

    with db_session() as conn:
        wakes_repo = ConversationWakesRepository(conn)
        released = wakes_repo.release_stale_claims(older_than_seconds=CLAIM_STALE_SECONDS)
        waiting = wakes_repo.pending_conversations(older_than_seconds=REDELIVER_AFTER_SECONDS)
        undelivered = BackgroundJobsRepository(conn).find_undelivered(older_than_seconds=REDELIVER_AFTER_SECONDS)
    for row in undelivered:
        # Queues the job's wake if it never was (deduplicated otherwise).
        wake.on_job_finished(row)
    for conversation_id, _user_id in waiting:
        wake.schedule_continuation(conversation_id)
    return {"redelivered": len(waiting), "claims_released": released}


def _mark_lost(row: Dict[str, Any], *, stale_seconds: int) -> bool:
    """Declare a job lost (its runner stopped reporting); True when this sweep did it."""
    done = jobs.finalize(
        str(row["id"]),
        status="lost",
        error={"type": "Lost", "message": LOST_NOTE},
        status_message="interrupted: the process running it stopped",
        stale_seconds=stale_seconds,
    )
    if done is None:
        return False
    logger.warning(
        "background job lost",
        extra={"alert": "background_job_lost", "job_id": str(row["id"]), "tool_name": row.get("tool_name")},
    )
    return True


def _cancel_remote(row: Dict[str, Any]) -> None:
    """Stop the work behind a job when its runner can (a detached sandbox run, a device command)."""
    runner = row.get("runner")
    if runner not in ("sandbox", "device"):
        return
    try:
        if runner == "sandbox":
            sandbox_runner.cancel_detached(row)
        else:
            device_runner.cancel_detached(row)
    except Exception:
        logger.exception("background job %s: stopping the %s command failed", row.get("id"), runner)


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
