"""The ``device`` runner: a command on a paired remote device, followed by a Celery poller.

When a turn hands off a ``remote_device.run_command`` call (it outlived the
yield window, or the model passed ``background=true``), :func:`detach_job`
moves the job to this runner. The command keeps running on the device; a
chain of short Celery tasks (:func:`poll_job`, re-enqueued with a countdown)
reads the invocation's state and output from the device broker, applies the
job's ``watch``, and once the device reports the exit code finishes the job
with the result a foreground call would have returned. Nothing waits in a
worker between polls, and an API restart loses nothing: the command runs on
the device, its output waits in Redis, the handles live on the job row.

A device that stops reporting is told apart from a command that is just
slow by the device's ``last_seen_at`` (it polls every few seconds while
connected):

* offline: the job shows "waiting for the device" and keeps waiting, up to
  its deadline (``DEVICE_JOB_MAX_SECONDS``), for the device to come back and
  report;
* online but silent past the command's own timeout, or never picking the
  command up: the report was lost, so the job is ``lost``;
* unpaired, or still silent at the deadline: ``lost``.

A lost job's delivery is the verify-before-retrying note, like any other.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from docsgpt.background import jobs, pool
from docsgpt.background.events import publish_job_updated
from docsgpt.background.results import LOST_NOTE, stored_result, tail_of
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

#: First poll after a hand-off, and the longest gap between polls of a connected device.
FIRST_POLL_SECONDS = 2.0
MAX_POLL_SECONDS = 10.0

#: Gap between polls while the device is offline.
OFFLINE_POLL_SECONDS = 15.0

#: ``last_seen_at`` age after which the device counts as offline (it polls every 10 s while connected).
OFFLINE_AFTER_SECONDS = 90

#: Seconds past the command's own timeout (or a connected device not picking it up) before the report is lost.
REPORT_GRACE_SECONDS = 120

#: Seconds a cancelled command has to confirm it stopped.
CANCEL_CONFIRM_SECONDS = 30

#: Gap between polls while a cancel waits for its confirmation.
CANCEL_POLL_SECONDS = 2.0

#: Consecutive failed polls (Redis or the database unreachable) after which the job is failed.
MAX_POLL_FAILURES = 12

#: Heartbeat age after which a device job's poll chain is restarted.
POLL_STALE_SECONDS = 120

#: Restarts of a broken poll chain before the job is declared lost.
MAX_REVIVES = 10

#: Shown on the job (and to the model) while the device is offline.
WAITING_NOTE = "waiting for the device to reconnect"


def job_max_seconds() -> int:
    """A device job's lifetime (``DEVICE_JOB_MAX_SECONDS``)."""
    from docsgpt.core.settings import settings

    return int(settings.DEVICE_JOB_MAX_SECONDS)


def key_ttl_seconds() -> int:
    """How long a device job's broker keys live: its lifetime plus a margin for a late report."""
    from docsgpt.agents.tools.remote_device import KEY_MARGIN_SECONDS

    return job_max_seconds() + KEY_MARGIN_SECONDS


def next_delay(attempt: int) -> float:
    """Seconds before the next poll: 2 s growing by half each poll up to 10 s."""
    return min(MAX_POLL_SECONDS, FIRST_POLL_SECONDS * (1.5 ** max(0, attempt)))


def _broker():
    from docsgpt.devices.broker import get_broker

    return get_broker()


def detach_job(job_id: str, external: Dict[str, Any]) -> bool:
    """Move a handed-off ``remote_device`` job to this runner and start its poll chain.

    The job's deadline becomes ``started_at + DEVICE_JOB_MAX_SECONDS`` and the
    invocation's broker keys are kept that long.

    Args:
        job_id: The job.
        external: ``invocation_id``, ``device_id``, ``device_name``,
            ``timeout_ms`` and ``dispatched_at`` (plus ``secret_refs`` when the
            command carried secrets).

    Returns:
        False when the job is no longer running (the caller keeps following the command).
    """
    try:
        with db_session() as conn:
            moved = BackgroundJobsRepository(conn).set_runner(
                job_id,
                runner="device",
                external={**external, "cursor": "0-0", "out_chars": 0, "polls": 0, "poll_failures": 0},
                lease_owner=None,
                max_seconds=job_max_seconds(),
            )
    except Exception:
        logger.exception("background job %s: moving to the device runner failed", job_id)
        return False
    if not moved:
        return False
    if not _broker().extend_invocation(str(external.get("invocation_id")), key_ttl_seconds()):
        logger.warning("background job %s: could not extend its invocation's lifetime", job_id)
    pool.release(job_id)
    enqueue_poll(job_id, FIRST_POLL_SECONDS)
    return True


def enqueue_poll(job_id: str, countdown: float) -> None:
    """Queue the next poll; a failure is left to the reconciler, which restarts stale chains."""
    try:
        from docsgpt.api.user.tasks import poll_background_device_job

        poll_background_device_job.apply_async(args=[job_id], countdown=countdown)
    except Exception:
        logger.exception("background job %s: queueing its poll failed; the sweep restarts it", job_id)


def _load(job_id: str) -> Optional[Dict[str, Any]]:
    with db_readonly() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


def _merge(job_id: str, fields: Dict[str, Any]) -> None:
    with db_session() as conn:
        BackgroundJobsRepository(conn).merge_external(job_id, fields)


def _timestamp(value: Any) -> Optional[float]:
    """A row timestamp (datetime or ISO string) as Unix time."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return None


def device_state(row: Dict[str, Any], *, now: Optional[float] = None) -> str:
    """Where the job's device stands: ``online``, ``offline`` or ``gone`` (unpaired or deleted).

    Args:
        row: The job row (``external.device_id``, ``user_id``).
        now: The current Unix time (for tests).
    """
    from docsgpt.storage.db.repositories.devices import DevicesRepository

    external = row.get("external") or {}
    with db_readonly() as conn:
        device = DevicesRepository(conn).get(str(external.get("device_id") or ""), user_id=str(row.get("user_id")))
    if device is None or device.get("status") != "active":
        return "gone"
    seen = _timestamp(device.get("last_seen_at"))
    current = time.time() if now is None else now
    if seen is None or current - seen > OFFLINE_AFTER_SECONDS:
        return "offline"
    return "online"


def poll_job(job_id: str) -> Dict[str, Any]:
    """One poll of a device job: finish it if the command reported, else poll again later.

    Args:
        job_id: The job.

    Returns:
        A summary for the task result: ``state`` and, when finished, ``status``.
    """
    row = _load(job_id)
    if row is None or row.get("status") != "working" or row.get("runner") != "device":
        return {"state": "gone"}
    external = row.get("external") or {}
    invocation_id = external.get("invocation_id")
    if not invocation_id:
        jobs.finalize(job_id, status="failed", error={"type": "Internal", "message": "the job lost its command"})
        return {"state": "failed"}
    if row.get("cancel_requested_at"):
        return _cancel_step(row)

    broker = _broker()
    try:
        invocation = broker.get_invocation(invocation_id, strict=True)
        chunks, cursor = broker.read_output(invocation_id, str(external.get("cursor") or "0-0"))
        state = device_state(row)
    except Exception as exc:
        return _poll_failed(job_id, external, exc)

    if invocation is not None and (invocation.completed or any(c.get("stream") == "control" for c in chunks)):
        done = finish(row)
        return {"state": "finished", "status": (done or {}).get("status")}
    if invocation is None:
        _lose(row, "the device broker no longer has this command")
        return {"state": "lost"}

    fresh = "".join(str(c.get("chunk") or "") for c in chunks if c.get("stream") in ("stdout", "stderr"))
    polls = int(external.get("polls") or 0) + 1
    out_chars = int(external.get("out_chars") or 0) + len(fresh)
    fields: Dict[str, Any] = {"cursor": cursor, "out_chars": out_chars, "polls": polls, "poll_failures": 0}
    if fresh:
        _observe(row, fresh, out_chars)

    now = time.time()
    if state == "gone":
        _lose(row, "the device was unpaired before the command reported back")
        return {"state": "lost"}
    deadline = _timestamp(row.get("deadline_at"))
    if deadline is not None and now >= deadline:
        _merge(job_id, fields)
        done = on_deadline({**row, "external": {**external, **fields}}, state=state)
        status = (done or {}).get("status")
        return {"state": "lost" if status == "lost" else "finished", "status": status}

    if state == "offline":
        if not external.get("offline_since"):
            fields["offline_since"] = now
            _set_waiting(row, True)
        _merge(job_id, fields)
        _touch(job_id)
        enqueue_poll(job_id, OFFLINE_POLL_SECONDS)
        return {"state": "waiting"}

    if external.get("offline_since"):
        fields["offline_since"] = None
        fields["online_since"] = now
        _set_waiting(row, False)
    online_since = _timestamp(fields.get("online_since") or external.get("online_since")) or 0.0
    lost = _report_lost(external, invocation, now=now, online_since=online_since)
    if lost:
        _merge(job_id, fields)
        if not invocation.acked:
            # Never picked up: take it off the queue so it can't start after the job gave up on it.
            broker.request_cancel(invocation_id)
        _lose(row, lost)
        return {"state": "lost"}
    _merge(job_id, fields)
    _touch(job_id)
    enqueue_poll(job_id, next_delay(polls))
    return {"state": "running"}


def _report_lost(external: Dict[str, Any], invocation: Any, *, now: float, online_since: float) -> Optional[str]:
    """Why a connected device's command will never report, or None while it still may.

    Args:
        external: The job's handles (``timeout_ms``, ``dispatched_at``).
        invocation: The broker snapshot.
        now: The current Unix time.
        online_since: When the device was seen coming back (0 when it never left).

    Returns:
        A short reason, or None.
    """
    timeout_s = int(external.get("timeout_ms") or 0) / 1000.0
    if not invocation.acked:
        # A connected device takes a queued command within seconds of its next poll.
        waited_from = max(float(external.get("dispatched_at") or 0), online_since)
        if waited_from and now - waited_from > REPORT_GRACE_SECONDS:
            return "the device is connected but never picked the command up"
        return None
    started = max(float(invocation.started_at or 0), float(external.get("dispatched_at") or 0))
    # A device that just came back gets the grace to send what it held while offline.
    expected_by = max(started + timeout_s, online_since)
    if started and now - expected_by > REPORT_GRACE_SECONDS:
        return "the device is connected but never reported how the command ended"
    return None


def _observe(row: Dict[str, Any], fresh: str, out_chars: int) -> None:
    """Show the new output on the job, and apply its ``watch`` to it."""
    output = (row.get("output_tail") or "") + fresh
    watch = row.get("watch") if isinstance(row.get("watch"), dict) else None
    try:
        if watch:
            from docsgpt.background.watch import observe_output

            observe_output(row, output, out_chars)
            return
        with db_session() as conn:
            BackgroundJobsRepository(conn).update_progress(str(row["id"]), output_tail=tail_of(output))
    except Exception:
        logger.exception("background job %s: recording its output failed", row.get("id"))


def _set_waiting(row: Dict[str, Any], waiting: bool) -> None:
    """Mark (or clear) a job as waiting for its device, and tell the open tabs."""
    progress = {"waiting_for": "device" if waiting else None}
    message = WAITING_NOTE if waiting else ""
    try:
        with db_session() as conn:
            BackgroundJobsRepository(conn).update_progress(
                str(row["id"]), progress=progress, status_message=message
            )
    except Exception:
        logger.exception("background job %s: recording the device state failed", row.get("id"))
        return
    publish_job_updated({**row, "progress": {**(row.get("progress") or {}), **progress}, "status_message": message})


def _touch(job_id: str) -> None:
    try:
        with db_session() as conn:
            BackgroundJobsRepository(conn).touch(job_id)
    except Exception:
        logger.debug("background job %s: heartbeat failed", job_id, exc_info=True)


def finish(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Finish a job whose command reported, with the result a foreground call returns.

    Args:
        row: The job row.

    Returns:
        The finished row, or None when another path finished it.
    """
    from docsgpt.agents.tool_executor import bound_result_full, result_status, sanitize_tool_result
    from docsgpt.agents.tools.remote_device import command_result

    external = row.get("external") or {}
    invocation_id = str(external.get("invocation_id"))
    broker = _broker()
    try:
        value = command_result(broker, invocation_id, external.get("device_name"))
    finally:
        broker.cleanup_invocation(invocation_id)
    value = sanitize_tool_result(value)
    output = "".join(part for part in (value.get("stdout"), value.get("stderr")) if isinstance(part, str))
    text_value = bound_result_full(jobs.result_text(value))
    in_band = result_status(value)
    jobs.record_final_progress(row, output)
    return jobs.finalize(
        str(row["id"]),
        status="completed" if in_band == "completed" else "failed",
        result=stored_result(text_value, status=in_band),
        output_tail=tail_of(output) or None,
    )


def on_deadline(row: Dict[str, Any], *, state: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """End a device job at its deadline: failed if the device is there to stop it, else lost.

    A command that reported in the meantime finishes normally. A connected
    device that picked the command up gets a cancel and the job fails as
    timed out; a device that is offline, unpaired or never took the command
    can't say what happened, so the job is lost.

    Args:
        row: The job row.
        state: The device state if the caller already read it.

    Returns:
        The finished row, or None when another path finished it.
    """
    external = row.get("external") or {}
    invocation_id = str(external.get("invocation_id") or "")
    broker = _broker()
    try:
        invocation = broker.get_invocation(invocation_id, strict=True) if invocation_id else None
    except Exception:
        invocation = None
    if invocation is not None and invocation.completed:
        return finish(row)
    if state is None:
        try:
            state = device_state(row)
        except Exception:
            state = "offline"
    if invocation_id:
        broker.request_cancel(invocation_id)
        broker.retire_invocation(invocation_id)
    if state == "online" and invocation is not None and invocation.acked:
        limit = job_max_seconds()
        return jobs.finalize(
            str(row["id"]),
            status="failed",
            error={
                "type": "TimeoutError",
                "message": f"The command ran past the {limit}s device job limit and was stopped; it may have partly run.",
            },
            status_message="timed out",
        )
    return _lose(row, "the device did not report back before the job's time limit", retire=False)


def _lose(row: Dict[str, Any], why: str, *, retire: bool = True) -> Optional[Dict[str, Any]]:
    """Declare a device job lost: it will never report, and may or may not have run.

    Returns:
        The finished row, or None when another path finished it first.
    """
    invocation_id = (row.get("external") or {}).get("invocation_id")
    if retire and invocation_id:
        _broker().retire_invocation(str(invocation_id))
    done = jobs.finalize(
        str(row["id"]),
        status="lost",
        error={"type": "Lost", "message": f"{LOST_NOTE} ({why})"},
        status_message=f"interrupted: {why}",
    )
    if done is not None:
        logger.warning(
            "background device job lost",
            extra={"alert": "background_job_lost", "job_id": str(row["id"]), "reason": why},
        )
    return done


def _cancel_step(row: Dict[str, Any]) -> Dict[str, Any]:
    """Advance a cancelled job: stop the command, then wait briefly for the device to confirm."""
    job_id = str(row["id"])
    external = row.get("external") or {}
    invocation_id = str(external.get("invocation_id"))
    broker = _broker()
    now = time.time()
    sent_at = _timestamp(external.get("cancel_sent_at"))
    if sent_at is None:
        outcome = broker.request_cancel(invocation_id)
        if outcome != "sent":
            broker.cleanup_invocation(invocation_id)
            message = "cancelled before the device started it" if outcome == "unqueued" else "cancelled"
            jobs.finalize(job_id, status="cancelled", status_message=message)
            return {"state": "cancelled"}
        _merge(job_id, {"cancel_sent_at": now})
        _touch(job_id)
        enqueue_poll(job_id, CANCEL_POLL_SECONDS)
        return {"state": "cancelling"}
    invocation = broker.get_invocation(invocation_id)
    if invocation is not None and invocation.completed:
        # finalize turns the result into ``cancelled`` (cancel_requested_at is set) and keeps the output.
        finish(row)
        return {"state": "cancelled"}
    if now - sent_at >= CANCEL_CONFIRM_SECONDS:
        broker.retire_invocation(invocation_id)
        jobs.finalize(
            job_id,
            status="cancelled",
            status_message=(
                "cancelled; the device did not confirm it stopped the command (its docsgpt-cli may be too old "
                "to cancel), so check the machine"
            ),
        )
        return {"state": "cancelled"}
    _touch(job_id)
    enqueue_poll(job_id, CANCEL_POLL_SECONDS)
    return {"state": "cancelling"}


def cancel_detached(row: Dict[str, Any]) -> None:
    """Stop the command behind a device job (its deadline passed with the sweep, or it was given up).

    Args:
        row: The job row.
    """
    invocation_id = (row.get("external") or {}).get("invocation_id")
    if not invocation_id:
        return
    broker = _broker()
    broker.request_cancel(str(invocation_id))
    broker.retire_invocation(str(invocation_id))


def _poll_failed(job_id: str, external: Dict[str, Any], exc: BaseException) -> Dict[str, Any]:
    """Count a failed poll; retry later, or fail the job after ``MAX_POLL_FAILURES`` in a row."""
    failures = int(external.get("poll_failures") or 0) + 1
    logger.warning("background job %s: device poll %d failed: %s", job_id, failures, exc)
    if failures >= MAX_POLL_FAILURES:
        jobs.finalize(
            job_id,
            status="lost",
            error={"type": "Lost", "message": f"{LOST_NOTE} (lost contact with the device broker: {exc})"},
            status_message="interrupted: lost contact with the device broker",
        )
        return {"state": "lost"}
    try:
        _merge(job_id, {"poll_failures": failures})
    except Exception:
        logger.debug("background job %s: recording a failed poll failed", job_id, exc_info=True)
    enqueue_poll(job_id, next_delay(failures))
    return {"state": "retry"}


def revive(row: Dict[str, Any]) -> bool:
    """Restart a device job whose poll chain broke (a lost task message, a worker that died).

    The command may still be running on the device, so the job is polled
    again rather than declared lost, up to ``MAX_REVIVES`` times.

    Args:
        row: The job row.

    Returns:
        True when a poll was queued, False when the job should be declared lost.
    """
    if int(row.get("attempts") or 0) >= MAX_REVIVES:
        return False
    with db_session() as conn:
        BackgroundJobsRepository(conn).bump_attempts(str(row["id"]))
    enqueue_poll(str(row["id"]), 0)
    return True
