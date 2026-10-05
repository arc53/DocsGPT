"""The ``sandbox`` runner: a detached code run followed by a Celery poller.

When a turn hands off a ``run_code`` call that runs detached (every run on
Daytona, a ``background`` run on Jupyter), :func:`detach_job` moves the job to
this runner. A chain of short Celery tasks (:func:`poll_job`, re-enqueued
with a countdown) then checks the process, keeps the sandbox active, and once
it exits captures its files and finishes the job with the same payload the
turn would have returned. Nothing waits in a worker between polls, and an API
restart loses nothing: the process runs in the sandbox, the handles live on
the job row.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

from docsgpt.background import jobs, pool
from docsgpt.background.results import stored_result
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

#: First poll after a hand-off, and the longest gap between polls.
FIRST_POLL_SECONDS = 2.0
MAX_POLL_SECONDS = 10.0

#: Consecutive failed polls after which the job is failed.
MAX_POLL_FAILURES = 12

#: Heartbeat age after which a sandbox job's poll chain is restarted.
POLL_STALE_SECONDS = 120

#: Restarts of a broken poll chain before the job is declared lost.
MAX_REVIVES = 10

_backend_lock = threading.Lock()
_backend: Optional[Tuple[int, Any]] = None


def _poll_backend() -> Any:
    """This process's sandbox backend for polling: separate from the session manager's, never closed."""
    global _backend
    with _backend_lock:
        if _backend is None or _backend[0] != os.getpid():
            from docsgpt.core.settings import settings
            from docsgpt.sandbox.sandbox_creator import SandboxCreator

            _backend = (os.getpid(), SandboxCreator.create_backend(settings.SANDBOX_BACKEND))
        return _backend[1]


def next_delay(attempt: int) -> float:
    """Seconds before the next poll: 2 s growing by half each poll up to 10 s."""
    return min(MAX_POLL_SECONDS, FIRST_POLL_SECONDS * (1.5 ** max(0, attempt)))


def detach_job(job_id: str, external: Dict[str, Any]) -> bool:
    """Move a handed-off job to the sandbox runner and start its poll chain.

    Args:
        job_id: The job.
        external: The detached run (``session_id``, ``run``, ``finish``, ``tool``).

    Returns:
        False when the job is no longer running (the caller keeps the run).
    """
    try:
        with db_session() as conn:
            moved = BackgroundJobsRepository(conn).set_runner(
                job_id, runner="sandbox", external={**external, "polls": 0}, lease_owner=None
            )
    except Exception:
        logger.exception("background job %s: moving to the sandbox runner failed", job_id)
        return False
    if not moved:
        return False
    pool.release(job_id)
    enqueue_poll(job_id, FIRST_POLL_SECONDS)
    return True


def enqueue_poll(job_id: str, countdown: float) -> None:
    """Queue the next poll; a failure is left to the reconciler, which restarts stale chains."""
    try:
        from docsgpt.api.user.tasks import poll_background_sandbox_job

        poll_background_sandbox_job.apply_async(args=[job_id], countdown=countdown)
    except Exception:
        logger.exception("background job %s: queueing its poll failed; the sweep restarts it", job_id)


def _load(job_id: str) -> Optional[Dict[str, Any]]:
    with db_readonly() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


def _merge(job_id: str, fields: Dict[str, Any]) -> None:
    with db_session() as conn:
        BackgroundJobsRepository(conn).merge_external(job_id, fields)


def poll_job(job_id: str) -> Dict[str, Any]:
    """One poll of a detached run: finish the job if the process exited, else poll again later.

    Args:
        job_id: The job.

    Returns:
        A summary for the task result: ``state`` and, when finished, ``status``.
    """
    row = _load(job_id)
    if row is None or row.get("status") != "working" or row.get("runner") != "sandbox":
        return {"state": "gone"}
    external = row.get("external") or {}
    run = dict(external.get("run") or {})
    session_id = external.get("session_id")
    if not run or not session_id:
        jobs.finalize(job_id, status="failed", error={"type": "Internal", "message": "the job lost its run handle"})
        return {"state": "failed"}

    backend = _poll_backend()
    try:
        created = backend.adopt(session_id, run) or {}
        if created:
            run.update(created)
            _merge(job_id, {"run": run})
    except Exception as exc:
        return _poll_failed(job_id, external, exc)

    if row.get("cancel_requested_at"):
        _stop(backend, session_id, run)
        _release(backend, session_id, run)
        jobs.finalize(job_id, status="cancelled", status_message="cancelled")
        return {"state": "cancelled"}

    watch = row.get("watch") if isinstance(row.get("watch"), dict) else None
    try:
        state = backend.poll_detached(session_id, run, with_output=bool(watch))
        try:
            backend.refresh_activity(session_id)
        except Exception:
            logger.debug("background job %s: activity refresh failed", job_id, exc_info=True)
    except Exception as exc:
        return _poll_failed(job_id, external, exc)

    with db_session() as conn:
        repo = BackgroundJobsRepository(conn)
        repo.touch(job_id)
        polls = int(external.get("polls") or 0) + 1
        repo.merge_external(job_id, {"polls": polls, "poll_failures": 0})

    if not state.done:
        enqueue_poll(job_id, next_delay(polls))
        return {"state": "running"}

    result = finish_detached(row, backend, state)
    _release(backend, session_id, run)
    return {"state": "finished", "status": (result or {}).get("status")}


def finish_detached(row: Dict[str, Any], backend: Any, state: Any) -> Optional[Dict[str, Any]]:
    """Capture a finished detached run's files and finish its job with the turn's payload.

    Args:
        row: The job row.
        backend: The adopted sandbox backend.
        state: The run's final ``DetachedState``.

    Returns:
        The finished job row, or None when another path finished it.
    """
    from docsgpt.agents.tools.code_executor import CodeExecutorTool, PreparedRun

    external = row.get("external") or {}
    tool_state = external.get("tool") or {}
    tool = CodeExecutorTool(tool_config=dict(tool_state.get("config") or {}), user_id=tool_state.get("user_id"))
    prepared = PreparedRun.from_state(external.get("finish") or {})
    try:
        payload = tool.finish_run(backend, prepared, state.result)
    except Exception as exc:
        logger.exception("background job %s: finishing the detached run failed", row.get("id"))
        return jobs.finalize(
            str(row["id"]), status="failed", error={"type": type(exc).__name__, "message": str(exc)}
        )
    tool.drain_native_parts()
    if not prepared.keep_alive and external.get("run", {}).get("backend") == "daytona":
        # The model asked to close the session after this run.
        try:
            backend.close(prepared.session_id)
        except Exception:
            logger.warning("background job %s: closing the session failed", row.get("id"), exc_info=True)
    status = "completed" if payload.get("status") == "ok" else "failed"
    return jobs.finalize(
        str(row["id"]),
        status=status,
        result=stored_result(
            json.dumps(payload, default=str),
            status="completed" if status == "completed" else "error",
            artifacts=tool.get_artifacts("run_code"),
            artifact_id=tool.get_artifact_id("run_code"),
        ),
        output_tail=(state.output or None),
    )


def _poll_failed(job_id: str, external: Dict[str, Any], exc: BaseException) -> Dict[str, Any]:
    """Count a failed poll; retry later, or fail the job after ``MAX_POLL_FAILURES`` in a row."""
    failures = int(external.get("poll_failures") or 0) + 1
    logger.warning("background job %s: poll %d failed: %s", job_id, failures, exc)
    if failures >= MAX_POLL_FAILURES:
        jobs.finalize(
            job_id,
            status="failed",
            error={"type": type(exc).__name__, "message": f"lost contact with the sandbox: {exc}"},
        )
        return {"state": "failed"}
    try:
        _merge(job_id, {"poll_failures": failures})
    except Exception:
        logger.debug("background job %s: recording a failed poll failed", job_id, exc_info=True)
    enqueue_poll(job_id, next_delay(failures))
    return {"state": "retry"}


def _stop(backend: Any, session_id: str, run: Dict[str, Any]) -> None:
    try:
        backend.cancel_detached(session_id, run)
    except Exception:
        logger.warning("stopping a detached run failed", exc_info=True)


def _release(backend: Any, session_id: str, run: Dict[str, Any]) -> None:
    release = getattr(backend, "release_adopted", None)
    if callable(release):
        try:
            release(session_id, run)
        except Exception:
            logger.debug("releasing an adopted sandbox handle failed", exc_info=True)


def cancel_detached(row: Dict[str, Any]) -> None:
    """Stop the process behind a sandbox job (its deadline passed, or it was cancelled).

    Args:
        row: The job row.
    """
    external = row.get("external") or {}
    run = dict(external.get("run") or {})
    session_id = external.get("session_id")
    if not run or not session_id:
        return
    backend = _poll_backend()
    backend.adopt(session_id, run)
    _stop(backend, session_id, run)
    _release(backend, session_id, run)


def revive(row: Dict[str, Any]) -> bool:
    """Restart a sandbox job whose poll chain broke (a lost task message, a worker that died).

    The process may still be running in the sandbox, so the job is polled
    again rather than declared lost, up to ``MAX_REVIVES`` times.

    Args:
        row: The job row.

    Returns:
        True when a poll was queued, False when the job was declared lost.
    """
    if int(row.get("attempts") or 0) >= MAX_REVIVES:
        return False
    with db_session() as conn:
        BackgroundJobsRepository(conn).bump_attempts(str(row["id"]))
    enqueue_poll(str(row["id"]), 0)
    return True
