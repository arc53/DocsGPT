"""Running monitors: the polled tick, webhook deliveries, ingest events, expiry, and the wake.

Polled monitors (webpage and tool sources) are claimed by
:func:`dispatch_due_monitors` on the schedule dispatcher's beat
(``SCHEDULE_DISPATCHER_INTERVAL``), which advances ``next_run_at`` in the
same transaction and fans each one out to a ``run_monitor_tick`` task.

A tick is cheap before it is expensive:

1. fetch the source (capped) and normalize it;
2. compare its hash with the stored one: unchanged is a *quiet tick* that
   only counts the check (no LLM, no run row, no wake);
3. run the deterministic check against the stored check state;
4. only when the check fires and the monitor has a ``condition``, ask the
   judge (:mod:`docsgpt.monitors.judge`);
5. wake the conversation once per dedupe key, through
   :func:`docsgpt.background.wake.wake_conversation`, and stop at
   ``max_wakes`` or at expiry. The baseline taken at creation never wakes.

An unreachable source (offline device, server down, timeout, 5xx) is a
skipped check, never a change; after ``MONITOR_UNREACHABLE_GRACE_SECONDS``
of it the agent is told once and the monitor pauses. Any other source error
counts toward ``SCHEDULE_AUTOPAUSE_FAILURES``, after which the agent is told
once and the monitor pauses. A monitor that wakes more than
``MONITOR_MAX_WAKES_PER_HOUR`` times in an hour is paused the same way.
Silence is never mistaken for success.

Webhook deliveries and ingest events run the same check, judge and wake
on the delivered data, each delivery on its own (``event`` mode).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.monitors.checks import CheckError, Content, Evaluation, evaluate
from docsgpt.monitors.events import publish_monitor_updated, wakes_left
from docsgpt.monitors.fetch import (
    SourceError,
    SourceRevoked,
    SourceUnreachable,
    canonical_json,
    content_from_text,
    fetch_webpage,
)
from docsgpt.monitors.spec import POLLED_SOURCES, bounded_state, next_tick, parse_iso
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerHitsRepository, TriggerLinksRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

#: A tick lease older than this belongs to a tick that died (a remote command may take 10 minutes).
LEASE_STALE_SECONDS = 900

#: Monitors one dispatcher pass claims.
DISPATCH_LIMIT = 200

#: Characters of the watched content a wake carries.
WAKE_EXCERPT_CHARS = 2000

#: Characters of the content kept as the excerpt in the state.
STATE_EXCERPT_CHARS = 4000

#: Wake keys remembered per monitor (dedupe through stored state, not model memory).
WAKE_KEYS_KEPT = 50

#: Seconds before a delivery whose task was lost is queued again.
STUCK_HIT_SECONDS = 300

#: Times a delivery waits for a busy monitor before it is queued again later by the sweep.
MAX_HIT_DEFERRALS = 5

#: Seconds before an event whose condition could not be judged is tried again, per attempt.
UNDECIDED_RETRY_SECONDS = 60

#: Why an event is dropped after ``MAX_HIT_DEFERRALS`` undecided tries.
UNDECIDED_NOTE = "the condition could not be judged after several tries"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _wake(**kwargs: Any) -> None:
    """Deliver through the one wake seam (looked up at call time, so tests can record it)."""
    from docsgpt.background import wake

    wake.wake_conversation(**kwargs)


def source_label(monitor: Dict[str, Any]) -> str:
    """What the monitor watches, for messages."""
    from docsgpt.monitors.service import source_summary

    return source_summary((monitor.get("monitor_spec") or {}).get("source") or {})


# ----------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------


def dispatch_due_monitors(now: Optional[datetime] = None) -> Dict[str, int]:
    """One dispatcher pass: tick due polled monitors, expire ended ones, requeue lost deliveries.

    Due rows are locked ``FOR UPDATE SKIP LOCKED`` and their ``next_run_at``
    advanced (jittered, never on :00 or :30) in the same transaction, so two
    dispatchers never tick a monitor twice for one slot.

    Args:
        now: The current time (for tests).

    Returns:
        Counts of ``ticked``, ``expired`` and ``requeued`` work.
    """
    counts = {"ticked": 0, "expired": 0, "requeued": 0}
    if not settings.POSTGRES_URI:
        return counts
    now = now or _now()
    to_tick: List[str] = []
    to_expire: List[str] = []
    with db_session() as conn:
        rows = conn.execute(
            text(
                """
                SELECT s.id, s.status, s.end_at, m.interval_seconds, m.source_type
                FROM schedules s JOIN monitors m ON m.schedule_id = s.id
                WHERE s.trigger_type = 'monitor'
                  AND ((s.status = 'active' AND s.next_run_at IS NOT NULL AND s.next_run_at <= :now)
                       OR (s.status IN ('active', 'paused') AND s.end_at IS NOT NULL AND s.end_at <= :now))
                ORDER BY s.next_run_at NULLS FIRST
                LIMIT :limit
                FOR UPDATE OF s SKIP LOCKED
                """
            ),
            {"now": now, "limit": DISPATCH_LIMIT},
        ).fetchall()
        repo = MonitorsRepository(conn)
        for row in rows:
            mapping = row._mapping
            monitor_id = str(mapping["id"])
            end_at = parse_iso(mapping["end_at"])
            if end_at is not None and end_at <= now:
                repo.set_schedule(monitor_id, next_run_at=None)
                to_expire.append(monitor_id)
            elif mapping["source_type"] in POLLED_SOURCES and mapping["interval_seconds"]:
                repo.set_schedule(monitor_id, next_run_at=next_tick(now, int(mapping["interval_seconds"]), end_at))
                to_tick.append(monitor_id)
            else:
                # Event-driven monitors wait for their event; the next pass is their expiry.
                repo.set_schedule(monitor_id, next_run_at=end_at)
    for monitor_id in to_expire:
        try:
            if expire(monitor_id, now=now):
                counts["expired"] += 1
        except Exception:
            logger.exception("monitor %s: expiring failed; the next pass retries", monitor_id)
    for monitor_id in to_tick:
        try:
            from docsgpt.api.user.tasks import run_monitor_tick

            run_monitor_tick.apply_async(args=[monitor_id], queue="docsgpt")
            counts["ticked"] += 1
        except Exception:
            logger.exception("monitor %s: could not queue its tick", monitor_id)
    counts["requeued"] = _requeue_stuck_hits()
    return counts


def _requeue_stuck_hits() -> int:
    """Queue again the deliveries whose task never ran (a worker died, the broker dropped it)."""
    try:
        with db_readonly() as conn:
            stuck = TriggerHitsRepository(conn).list_stuck(age_seconds=STUCK_HIT_SECONDS)
    except Exception:
        logger.exception("monitors: listing stuck deliveries failed")
        return 0
    queued = 0
    for hit in stuck:
        if enqueue_hit(str(hit["id"])):
            queued += 1
    return queued


def enqueue_hit(hit_id: str, *, countdown: float = 0, attempt: int = 0) -> bool:
    """Queue a delivery for the check pipeline; False when the broker is unavailable."""
    try:
        from docsgpt.api.user.tasks import process_trigger_hit

        process_trigger_hit.apply_async(args=[hit_id, attempt], countdown=countdown, queue="docsgpt")
        return True
    except Exception:
        logger.exception("trigger hit %s: could not be queued", hit_id)
        return False


# ----------------------------------------------------------------------
# Ending and pausing
# ----------------------------------------------------------------------


def _finish(monitor_id: str, status: str, reason: str) -> Optional[Dict[str, Any]]:
    """End or pause a monitor (revoking its links when it ends); returns it after, or None if unchanged."""
    with db_session() as conn:
        repo = MonitorsRepository(conn)
        if not repo.finish(monitor_id, status, reason=reason):
            return None
        if status != "paused":
            TriggerLinksRepository(conn).revoke_for_monitor(monitor_id)
        monitor = repo.get_internal(monitor_id)
    if monitor is not None:
        publish_monitor_updated(monitor)
    return monitor


#: The wake source (and notification kind) of a monitor that paused itself.
PAUSED_SOURCE = "monitor_paused"

#: The wake source (and notification kind) of a monitor or link whose lifetime ended without firing.
EXPIRED_SOURCE = "monitor_expired"


def _notice(monitor: Dict[str, Any], *, kind: str, title: str, body: str, payload: Optional[Dict[str, Any]],
            dedupe: str, source: Optional[str] = None) -> None:
    """Tell the agent something about the monitor itself (paused, unreachable, expired); never counts a wake."""
    source = source or ("approval" if monitor.get("source_type") == "approval" else "monitor")
    _wake(
        user_id=str(monitor["user_id"]),
        conversation_id=str(monitor["conversation_id"]),
        source=source,
        ref_id=str(monitor["id"]),
        title=title,
        body=body,
        payload=payload,
        dedupe_key=f"monitor:{monitor['id']}:{kind}:{dedupe}",
    )


def pause_with_notice(monitor: Dict[str, Any], *, kind: str, reason: str, detail: str,
                      payload: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
    """Pause a monitor and wake the agent once to say why (the user can resume it from Settings > Monitors).

    Args:
        monitor: The monitor row.
        kind: ``unreachable``, ``errors``, ``breaker``, ``revoked`` or ``budget`` (part of the dedupe key).
        reason: Short reason stored on the monitor (the Monitors page shows it).
        detail: What happened, for the agent: only text this code wrote, never outside text.
        payload: Outside data that came with it (fenced as data).
        error: The error message (it can quote a tool or a server, so it goes in the fenced data).
    """
    paused = _finish(str(monitor["id"]), "paused", reason)
    if paused is None:
        return
    if error:
        payload = {**(payload or {}), "error": error}
    body = (
        f'Monitor {monitor["id"]} ("{monitor.get("description")}", watching {source_label(monitor)}) is paused: '
        f"{detail} It checks nothing until the user resumes it in Settings > Monitors. Tell the user what "
        "happened and whether anything they wanted is now not being watched."
    )
    _notice(
        monitor,
        kind=kind,
        title=f"{monitor.get('description')}: paused ({reason})",
        body=body,
        payload=payload,
        dedupe=_iso(_now()) or "",
        source=PAUSED_SOURCE,
    )


def expire(monitor_id: str, *, now: Optional[datetime] = None) -> bool:
    """End a monitor whose lifetime is over; tells the agent once when it never fired.

    Returns:
        True when the monitor was ended now.
    """
    with db_readonly() as conn:
        before = MonitorsRepository(conn).get_internal(monitor_id)
    if before is None:
        return False
    after = _finish(monitor_id, "completed", "expired")
    if after is None:
        return False
    if before.get("status") == "active" and int(before.get("wake_count") or 0) == 0:
        checks = int(after.get("check_count") or 0)
        if before.get("source_type") == "approval":
            detail = "Nobody decided on the approval link before it expired; the link no longer works."
        elif before.get("source_type") == "webhook":
            detail = f"The webhook link expired after {checks} delivery check(s) without firing."
        else:
            detail = f"It expired after {checks} check(s) without its condition being met."
        _notice(
            before,
            kind="expired",
            title=f"{before.get('description')}: expired",
            body=(
                f'Monitor {monitor_id} ("{before.get("description")}", watching {source_label(before)}) ended. '
                f"{detail} Tell the user only if they were waiting on it."
            ),
            payload=None,
            dedupe="end",
            source=EXPIRED_SOURCE,
        )
    return True


# ----------------------------------------------------------------------
# Delivering a match
# ----------------------------------------------------------------------


def _recent_wakes(state: Dict[str, Any], now: datetime) -> List[str]:
    """The wake times of the last hour, from the state."""
    out = []
    for value in state.get("recent_wakes") or []:
        when = parse_iso(value)
        if when is not None and now - when < timedelta(hours=1):
            out.append(_iso(when))
    return out


#: Said in a wake whose check matched while the judge could not evaluate the condition.
UNJUDGED_NOTE = (
    "Its check matched, but its condition could not be evaluated (the judge model failed {count} times in a "
    "row), so this is the check's match alone: tell the user it may not meet the condition, and why."
)

#: Said instead when the judge's provider refused the content (a content filter or safety policy).
REFUSED_NOTE = (
    "Its check matched, but its condition could not be evaluated (the judge model's provider refused the "
    "content under its content policy), so this is the check's match alone: tell the user it may not meet the "
    "condition, and why."
)


def _wake_body(monitor: Dict[str, Any], *, left: int, note: Optional[str] = None) -> str:
    """The wake's trusted text: which monitor fired and what to do; what it found is in the fenced data."""
    on_match = (monitor.get("on_match") or "").strip()
    lines = [
        f'Monitor {monitor["id"]} ("{monitor.get("description")}", watching {source_label(monitor)}) fired. '
        "What it found is in the data below (its summary first).",
        note or "",
        f"What to do now (the instruction you wrote when it was set up): {on_match}" if on_match else "",
        (
            f"It may wake you {left} more time(s)."
            if left > 0
            else "That was its last wake; it has finished and checks nothing more."
        ),
    ]
    return "\n".join(line for line in lines if line)


def deliver(
    monitor: Dict[str, Any],
    *,
    state: Dict[str, Any],
    fields: Dict[str, Any],
    source: str,
    key: str,
    summary: str,
    payload: Dict[str, Any],
    now: datetime,
    note: Optional[str] = None,
) -> str:
    """Wake the conversation for a match, once per key, then count it.

    Dedupe is by stored state (the monitor's recent wake keys) and again by
    ``wake_conversation``'s unique ``dedupe_key``. The circuit breaker pauses
    a monitor that would wake more than ``MONITOR_MAX_WAKES_PER_HOUR`` times
    in an hour (it tells the agent once instead). The monitor finishes when
    it has used ``max_wakes``.

    Args:
        monitor: The monitor row.
        state: The new ``monitor_state`` (stored here).
        fields: Other ``monitors`` columns to store (counters, timestamps).
        source: ``monitor`` or ``trigger``.
        key: What fired (stable for one fact).
        summary: One line for the agent.
        payload: Outside data for the wake (fenced as data).
        now: The current time.
        note: A line of this code's own text for the wake (why it is a partial match).

    Returns:
        ``woken``, ``duplicate`` or ``breaker``.
    """
    monitor_id = str(monitor["id"])
    dedupe_key = f"{source}:{monitor_id}:{key}"[:500]
    wake_keys = [k for k in state.get("wake_keys") or [] if isinstance(k, str)]
    recent = _recent_wakes(state, now)
    if dedupe_key in wake_keys:
        _store(monitor_id, state, fields)
        return "duplicate"
    if len(recent) >= int(settings.MONITOR_MAX_WAKES_PER_HOUR):
        _store(monitor_id, state, fields)
        pause_with_notice(
            monitor,
            kind="breaker",
            reason="woke too often",
            detail=(
                f"it fired {len(recent) + 1} times within an hour, more than the {settings.MONITOR_MAX_WAKES_PER_HOUR} "
                "allowed, so it was stopped before flooding the conversation. The latest match is in the data below."
            ),
            payload=payload,
        )
        return "breaker"
    left_after = wakes_left(monitor) - 1
    _wake(
        user_id=str(monitor["user_id"]),
        conversation_id=str(monitor["conversation_id"]),
        source=source,
        ref_id=monitor_id,
        title=str(monitor.get("description") or "Monitor"),
        body=_wake_body(monitor, left=max(0, left_after), note=note),
        payload=payload,
        dedupe_key=dedupe_key,
    )
    state = dict(state)
    state["wake_keys"] = (wake_keys + [dedupe_key])[-WAKE_KEYS_KEPT:]
    state["recent_wakes"] = (recent + [_iso(now)])[-20:]
    with db_session() as conn:
        repo = MonitorsRepository(conn)
        repo.update(monitor_id, {**fields, "monitor_state": bounded_state(state)})
        count = repo.add_wake(monitor_id, now)
        finished = count >= int(monitor.get("max_wakes") or 1)
        if finished:
            repo.finish(monitor_id, "completed", reason="used all its wakes")
            TriggerLinksRepository(conn).revoke_for_monitor(monitor_id)
        after = repo.get_internal(monitor_id)
    if after is not None:
        publish_monitor_updated(after)
    return "woken"


def _store(monitor_id: str, state: Optional[Dict[str, Any]], fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Store a check's outcome and tell the owner's tabs."""
    update = dict(fields)
    if state is not None:
        update["monitor_state"] = bounded_state(state)
    with db_session() as conn:
        repo = MonitorsRepository(conn)
        repo.update(monitor_id, update)
        after = repo.get_internal(monitor_id)
    if after is not None:
        publish_monitor_updated(after)
    return after


# ----------------------------------------------------------------------
# Failures
# ----------------------------------------------------------------------


def _unreachable(monitor: Dict[str, Any], exc: SourceError, now: datetime) -> str:
    """A skipped check: record it, and after the grace period tell the agent once and pause."""
    since = parse_iso(monitor.get("unreachable_since")) or now
    message = str(exc)[:500]
    _store(str(monitor["id"]), None, {"last_error": message, "unreachable_since": since})
    if (now - since).total_seconds() >= int(settings.MONITOR_UNREACHABLE_GRACE_SECONDS):
        pause_with_notice(
            monitor,
            kind="unreachable",
            reason=f"unreachable since {_iso(since)}",
            detail=f"its source can't be reached since {_iso(since)} (the latest error is in the data below).",
            error=message,
        )
        return "paused"
    return "unreachable"


def _strike(monitor: Dict[str, Any], message: str) -> int:
    """Count one failed check and record why; returns the failures in a row."""
    monitor_id = str(monitor["id"])
    with db_session() as conn:
        repo = MonitorsRepository(conn)
        count = repo.bump_failures(monitor_id)
        repo.update(monitor_id, {"last_error": message[:500], "unreachable_since": None})
        after = repo.get_internal(monitor_id)
    if after is not None:
        publish_monitor_updated(after)
    return count


def _failed(monitor: Dict[str, Any], message: str) -> str:
    """A counted source error: after ``SCHEDULE_AUTOPAUSE_FAILURES`` in a row, tell the agent once and pause."""
    message = message[:500]
    count = _strike(monitor, message)
    if count >= int(settings.SCHEDULE_AUTOPAUSE_FAILURES):
        pause_with_notice(
            monitor,
            kind="errors",
            reason="repeated errors",
            detail=f"its last {count} checks failed (the latest error is in the data below).",
            error=message,
        )
        return "paused"
    return "error"


#: Columns a check that worked clears.
_HEALTHY = {"last_error": None, "unreachable_since": None}


def _reset_failures(monitor: Dict[str, Any], *, force: bool = False) -> None:
    """End an error streak: called only once a check got all the way through (``force``: counted this tick)."""
    if force or monitor.get("consecutive_failure_count"):
        with db_session() as conn:
            MonitorsRepository(conn).set_schedule(str(monitor["id"]), consecutive_failure_count=0)


# ----------------------------------------------------------------------
# Judge
# ----------------------------------------------------------------------


def _judge(monitor: Dict[str, Any], evaluation: Evaluation, content: Content) -> Tuple[str, Any]:
    """Ask the judge; returns ``("match"|"no_match", verdict)``, ``("budget", None)``, ``("quota", None)``
    or ``("error", message)``."""
    from docsgpt.monitors import judge
    from docsgpt.quotas.service import QuotaService

    budget = int(monitor.get("token_budget") or 0)
    if budget and int(monitor.get("judge_tokens") or 0) >= budget:
        return "budget", None
    if QuotaService.check(str(monitor["user_id"]), "direct") is not None:
        return "quota", None
    spec = monitor.get("monitor_spec") or {}
    try:
        verdict = judge.judge(
            user_id=str(monitor["user_id"]),
            monitor_id=str(monitor["id"]),
            description=str(monitor.get("description") or ""),
            condition=str(spec.get("condition") or ""),
            check_summary=evaluation.summary,
            content=content.text,
        )
    except judge.JudgeError as exc:
        # A content-policy refusal won't change on a retry: the same content is refused again.
        return ("refused" if exc.refused else "error"), str(exc)
    with db_session() as conn:
        MonitorsRepository(conn).add_judge_tokens(str(monitor["id"]), verdict.tokens)
    return ("match" if verdict.match else "no_match"), verdict


def _decide(
    monitor: Dict[str, Any], evaluation: Evaluation, content: Content
) -> Tuple[str, Optional[str], Optional[str]]:
    """Run the judge when the monitor has a condition.

    Returns:
        ``(outcome, key, summary)``: outcome is ``fire``, ``quiet``, ``retry`` (keep the old
        state so the next check judges again), ``paused``, ``refused`` (the judge's provider refused the
        content under its content policy: deliver the match with :data:`REFUSED_NOTE` at once, no strike)
        or ``unjudged`` (the check matched and
        the judge failed ``SCHEDULE_AUTOPAUSE_FAILURES`` times in a row: deliver the match with
        :data:`UNJUDGED_NOTE` rather than pause, so a broken judge never hides a match).
    """
    spec = monitor.get("monitor_spec") or {}
    if not spec.get("condition"):
        return "fire", None, evaluation.summary
    outcome, verdict = _judge(monitor, evaluation, content)
    if outcome == "match":
        return "fire", f"j:{verdict.key}", verdict.summary or evaluation.summary
    if outcome == "no_match":
        return "quiet", None, None
    if outcome == "budget":
        pause_with_notice(
            monitor,
            kind="budget",
            reason="judge budget used up",
            detail="judging its condition used up the monitor's token budget (MONITOR_JUDGE_TOKEN_BUDGET).",
        )
        return "paused", None, None
    if outcome == "quota":
        _store(str(monitor["id"]), None, {"last_error": "the user's usage quota is used up; the condition waits"})
        return "retry", None, None
    if outcome == "refused":
        return "refused", None, None
    count = _strike(monitor, f"the condition could not be judged: {verdict}")
    if count >= int(settings.SCHEDULE_AUTOPAUSE_FAILURES):
        return "unjudged", None, None
    return "retry", None, None


def _payload(evaluation: Evaluation, content: Content, summary: str, extra: Optional[Dict[str, Any]] = None,
             *, excerpt: bool = True) -> Dict[str, Any]:
    """The wake's data: what the check found, an excerpt of the content, and the event's own fields."""
    payload: Dict[str, Any] = {"summary": summary}
    for name in ("value", "matches", "new_items", "new_count"):
        if name in evaluation.detail:
            payload[name] = evaluation.detail[name]
    text_excerpt = content.text[:WAKE_EXCERPT_CHARS] if excerpt else ""
    if text_excerpt:
        payload["excerpt"] = text_excerpt
    if extra:
        payload.update(extra)
    return payload


# ----------------------------------------------------------------------
# The polled tick
# ----------------------------------------------------------------------


def _resumable(monitor: Dict[str, Any]) -> bool:
    """Whether the monitor's conversation still takes wakes (it was shared, or its agent changed hands)."""
    from docsgpt.background.context import auto_resume_allowed

    with db_readonly() as conn:
        return auto_resume_allowed(conn, str(monitor["conversation_id"]), str(monitor["user_id"]))


def _fetch(monitor: Dict[str, Any], now: datetime) -> Content:
    source = (monitor.get("monitor_spec") or {}).get("source") or {}
    if source.get("type") == "webpage":
        return fetch_webpage(source["url"], source.get("css_selector"))
    approval = monitor.get("approval")
    if not approval:
        raise SourceRevoked("the monitor has no approved call to replay")
    from docsgpt.monitors import sources

    return sources.run_call(
        user_id=str(monitor["user_id"]),
        agent_id=str(monitor["agent_id"]) if monitor.get("agent_id") else None,
        conversation_id=str(monitor["conversation_id"]),
        approval=approval,
        args_template=source.get("args") or {},
        placeholders={
            "now": now,
            "last_checked_at": monitor.get("last_checked_at"),
            "last_changed_at": monitor.get("last_changed_at"),
        },
        call_tag=str(monitor["id"]),
    )


def run_tick(monitor_id: str) -> Dict[str, Any]:
    """Check one polled monitor (the ``run_monitor_tick`` task); never two ticks of one monitor at once.

    Returns:
        ``{"state": ...}``: ``busy``, ``skipped``, ``expired``, ``quiet``, ``checked``, ``woken``,
        ``duplicate``, ``unreachable``, ``error``, ``paused``, ``retry`` or ``breaker``.
    """
    with db_session() as conn:
        acquired = MonitorsRepository(conn).acquire_tick(monitor_id, stale_seconds=LEASE_STALE_SECONDS)
    if not acquired:
        return {"state": "busy"}
    try:
        return {"state": _tick(monitor_id)}
    finally:
        with db_session() as conn:
            MonitorsRepository(conn).release_tick(monitor_id)


def _tick(monitor_id: str) -> str:
    with db_readonly() as conn:
        monitor = MonitorsRepository(conn).get_internal(monitor_id)
    if monitor is None or monitor.get("status") != "active" or monitor.get("source_type") not in POLLED_SOURCES:
        return "skipped"
    now = _now()
    end_at = parse_iso(monitor.get("end_at"))
    if end_at is not None and now >= end_at:
        expire(monitor_id, now=now)
        return "expired"
    if not _resumable(monitor):
        _finish(monitor_id, "cancelled", "its conversation can no longer be resumed")
        return "cancelled"
    try:
        content = _fetch(monitor, now)
    except SourceRevoked as exc:
        pause_with_notice(
            monitor,
            kind="revoked",
            reason="source no longer allowed",
            detail="its source call is no longer allowed or available.",
            error=str(exc),
        )
        return "paused"
    except SourceUnreachable as exc:
        return _unreachable(monitor, exc, now)
    except SourceError as exc:
        return _failed(monitor, str(exc))
    except Exception as exc:
        logger.exception("monitor %s: checking the source failed", monitor_id)
        return _failed(monitor, f"checking the source failed ({type(exc).__name__})")

    state = dict(monitor.get("monitor_state") or {})
    counted: Dict[str, Any] = {"check_count": int(monitor.get("check_count") or 0) + 1, "last_checked_at": now}
    fields: Dict[str, Any] = {**_HEALTHY, **counted}
    if content.digest == state.get("hash"):
        _reset_failures(monitor)
        _store(monitor_id, None, fields)
        return "quiet"

    spec = monitor.get("monitor_spec") or {}
    try:
        evaluation = evaluate(spec.get("check"), content, state.get("check"), mode="poll")
    except CheckError as exc:
        return _failed(monitor, f"the check doesn't fit what the source returned: {exc}")
    fields["last_changed_at"] = now
    new_state = {
        **state,
        "hash": content.digest,
        "excerpt": content.text[:STATE_EXCERPT_CHARS],
        "check": evaluation.state,
    }
    if not evaluation.fire:
        _reset_failures(monitor)
        _store(monitor_id, new_state, fields)
        return "checked"
    outcome, judge_key, summary = _decide(monitor, evaluation, content)
    if outcome == "retry":
        # The change is judged again on the next check: keep the old hash (and the error just recorded).
        _store(monitor_id, None, counted)
        return "retry"
    if outcome == "paused":
        return "paused"
    note = _unjudged_note(monitor, refused=outcome == "refused") if outcome in ("unjudged", "refused") else None
    _reset_failures(monitor, force=note is not None)
    if outcome == "quiet":
        _store(monitor_id, new_state, fields)
        return "checked"
    kind = (spec.get("check") or {}).get("type") or "changed"
    if judge_key:
        key = judge_key
    elif kind == "changed":
        key = f"c:{content.digest[:16]}:{fields['check_count']}"
    else:
        key = evaluation.key
    summary = summary or evaluation.summary
    payload = _payload(evaluation, content, summary, _source_ref(monitor))
    return deliver(
        monitor, state=new_state, fields=fields, source="monitor", key=key, summary=summary, payload=payload, now=now,
        note=note,
    )


def _unjudged_note(monitor: Dict[str, Any], *, refused: bool = False) -> str:
    if refused:
        return REFUSED_NOTE
    return UNJUDGED_NOTE.format(count=int(settings.SCHEDULE_AUTOPAUSE_FAILURES))


def _source_ref(monitor: Dict[str, Any]) -> Dict[str, Any]:
    source = (monitor.get("monitor_spec") or {}).get("source") or {}
    if source.get("type") == "webpage":
        return {"url": source.get("url")}
    if source.get("type") == "tool":
        return {"tool": source.get("tool")}
    return {}


# ----------------------------------------------------------------------
# Events: webhook deliveries and ingests
# ----------------------------------------------------------------------


def _lease(monitor_id: str) -> bool:
    with db_session() as conn:
        return MonitorsRepository(conn).acquire_tick(monitor_id, stale_seconds=LEASE_STALE_SECONDS)


def _release(monitor_id: str) -> None:
    with db_session() as conn:
        MonitorsRepository(conn).release_tick(monitor_id)


def _event(monitor: Dict[str, Any], content: Content, *, source: str, key: str, summary: str,
           extra: Optional[Dict[str, Any]] = None) -> str:
    """Run an event (one delivery) through the check, the judge and the wake.

    Args:
        monitor: The monitor row.
        content: The delivered data.
        source: ``trigger`` (a webhook delivery) or ``monitor`` (an ingest).
        key: Identifies the event (dedupe).
        summary: What happened, when no check or judge says more.
        extra: The event's own data for the wake (fenced as data).
    """
    now = _now()
    spec = monitor.get("monitor_spec") or {}
    state = dict(monitor.get("monitor_state") or {})
    fields: Dict[str, Any] = {"check_count": int(monitor.get("check_count") or 0) + 1, "last_checked_at": now,
                              "last_changed_at": now}
    try:
        evaluation = evaluate(spec.get("check"), content, state.get("check"), mode="event")
    except CheckError as exc:
        _unfit(monitor, state, fields, exc, source=source, extra=extra)
        return "unfit"
    new_state = {**state, "check": evaluation.state}
    if not evaluation.fire:
        _store(str(monitor["id"]), new_state, {**fields, "last_error": None})
        return "ignored"
    outcome, judge_key, judged = _decide(monitor, evaluation, content)
    if outcome in ("retry", "paused"):
        return outcome
    note = None
    if outcome in ("unjudged", "refused"):
        note = _unjudged_note(monitor, refused=outcome == "refused")
        _reset_failures(monitor, force=True)
    if outcome == "quiet":
        _store(str(monitor["id"]), new_state, {**fields, "last_error": None})
        return "ignored"
    if judge_key:
        summary = judged or summary
    elif (spec.get("check") or {}).get("type") not in (None, "changed"):
        summary = f"{summary}; {evaluation.summary}"
    payload = _payload(evaluation, content, summary, extra, excerpt=False)
    return deliver(
        monitor, state=new_state, fields={**fields, "last_error": None}, source=source,
        key=f"{key}:{judge_key}" if judge_key else key, summary=summary, payload=payload, now=now, note=note,
    )


#: The wake source of the notice that a webhook call didn't fit its monitor's check.
UNFIT_SOURCE = "trigger"


def _unfit(monitor: Dict[str, Any], state: Dict[str, Any], fields: Dict[str, Any], exc: CheckError, *,
           source: str, extra: Optional[Dict[str, Any]]) -> None:
    """Record an event the check could not read; the first webhook call like that wakes the agent to say so.

    A status check guessed for a payload shape the caller doesn't send would
    otherwise drop every call in silence. The notice is not a match: it uses
    no wake, and later calls that don't fit stay silent (``last_error`` keeps
    the latest reason).
    """
    message = f"a delivery didn't fit the check: {exc}"[:500]
    tell = source == "trigger" and not state.get("unfit_told")
    new_state = {**state, "unfit_told": True} if tell else None
    _store(str(monitor["id"]), new_state, {**fields, "last_error": message})
    if not tell:
        return
    _notice(
        monitor,
        kind="unfit",
        title=f"{monitor.get('description')}: a call didn't fit the check",
        body=(
            f'Monitor {monitor["id"]} ("{monitor.get("description")}") got a webhook call its check could not '
            "read (the reason and the call are in the data below), so it did not count as a match. Tell the user "
            "what the call was missing, and offer to re-create the monitor to fit what the caller sends. Later "
            "calls that don't fit stay silent."
        ),
        payload={"error": str(exc)[:500], **(extra or {})},
        dedupe="first",
        source=UNFIT_SOURCE,
    )


def delivery_content(payload: Dict[str, Any]) -> Content:
    """The content a check sees for a stored delivery: the parsed body, or its text."""
    body = payload.get("body")
    if isinstance(body, (dict, list)):
        return Content(text=canonical_json(body), data=body)
    return content_from_text(str(body or ""))


def process_hit(hit_id: str, attempt: int = 0) -> Dict[str, Any]:
    """Run one accepted webhook delivery through the pipeline (the ``process_trigger_hit`` task).

    Returns:
        ``{"state": ...}``.
    """
    with db_readonly() as conn:
        hit = TriggerHitsRepository(conn).get(hit_id)
        link = TriggerLinksRepository(conn).get(str(hit["link_id"])) if hit else None
        monitor = MonitorsRepository(conn).get_internal(str(link["monitor_id"])) if link else None
    if hit is None or hit.get("status") != "pending":
        return {"state": "gone"}
    if monitor is None or monitor.get("status") != "active":
        with db_session() as conn:
            TriggerHitsRepository(conn).mark(hit_id, "ignored", "the monitor is not active")
        return {"state": "ignored"}
    monitor_id = str(monitor["id"])
    if not _lease(monitor_id):
        if attempt + 1 < MAX_HIT_DEFERRALS:
            enqueue_hit(hit_id, countdown=2 * (attempt + 1), attempt=attempt + 1)
        return {"state": "busy"}
    try:
        with db_session() as conn:
            claimed = TriggerHitsRepository(conn).claim(hit_id)
            monitor = MonitorsRepository(conn).get_internal(monitor_id)
        if claimed is None:
            return {"state": "gone"}
        if monitor is None or monitor.get("status") != "active":
            with db_session() as conn:
                TriggerHitsRepository(conn).mark(hit_id, "ignored", "the monitor is not active")
            return {"state": "ignored"}
        payload = claimed.get("payload") or {}
        try:
            outcome = _event(
                monitor,
                delivery_content(payload),
                source="trigger",
                key=f"hit:{claimed['dedupe_key']}",
                summary="the webhook link received a delivery",
                extra={
                    key: value
                    for key, value in (
                        ("delivery", payload.get("body")),
                        ("content_type", payload.get("content_type")),
                        ("event", payload.get("event")),
                    )
                    if value is not None
                },
            )
        except Exception as exc:
            logger.exception("trigger hit %s: processing failed", hit_id)
            with db_session() as conn:
                TriggerHitsRepository(conn).mark(hit_id, "failed", type(exc).__name__)
            return {"state": "failed"}
        if outcome in ("ignored", "unfit"):
            with db_session() as conn:
                TriggerHitsRepository(conn).mark(hit_id, "ignored", None if outcome == "ignored" else "unfit")
        if outcome == "retry":
            # A delivery happens once: unlike a polled change, no later check sees it again.
            return {"state": _retry_hit(hit_id, attempt)}
        return {"state": outcome}
    finally:
        _release(monitor_id)


def _retry_hit(hit_id: str, attempt: int) -> str:
    """Put an undecided delivery back in the queue, or record it as failed once its tries are used up."""
    with db_session() as conn:
        repo = TriggerHitsRepository(conn)
        if attempt + 1 >= MAX_HIT_DEFERRALS:
            repo.mark(hit_id, "failed", UNDECIDED_NOTE)
            return "failed"
        repo.release(hit_id)
    enqueue_hit(hit_id, countdown=UNDECIDED_RETRY_SECONDS * (attempt + 1), attempt=attempt + 1)
    return "retry"


def _requeue_event(monitor_id: str, event: Dict[str, Any], attempt: int, countdown: float) -> bool:
    """Queue an ingest event for this monitor again.

    An ingest event lives only in its task, so when it can't be queued again
    the monitor's ``last_error`` says it was dropped instead of losing it silently.

    Returns:
        True when queued.
    """
    try:
        from docsgpt.api.user.tasks import process_monitor_event

        process_monitor_event.apply_async(args=[monitor_id, event, attempt + 1], countdown=countdown, queue="docsgpt")
        return True
    except Exception:
        logger.exception("monitor %s: could not requeue its ingest event", monitor_id)
    try:
        _store(monitor_id, None, {"last_error": "an ingest event was dropped: it could not be queued again"})
    except Exception:
        logger.exception("monitor %s: recording the dropped ingest event failed", monitor_id)
    return False


INGEST_EVENTS = ("source.ingest.completed", "source.ingest.failed")


def on_ingest_event(user_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    """Queue the ingest monitors watching a source whose ingest just ended; never raises.

    Called for every user event; only the terminal ingest events do anything.

    Args:
        user_id: The source's owner.
        event_type: The event published.
        payload: The event payload (``source_id``, ``filename``, ``error``...).
    """
    if event_type not in INGEST_EVENTS or not settings.MONITORS_ENABLED:
        return
    source_id = (payload or {}).get("source_id")
    if not source_id or not settings.POSTGRES_URI:
        return
    try:
        with db_readonly() as conn:
            monitors = MonitorsRepository(conn).find_ingest_monitors(str(user_id), str(source_id))
    except Exception:
        logger.exception("ingest monitors lookup failed for source %s", source_id)
        return
    event = {
        "event": "completed" if event_type.endswith("completed") else "failed",
        "source_id": str(source_id),
        "filename": payload.get("filename"),
        "operation": payload.get("operation"),
        "error": payload.get("error"),
        # Names this ingest run, so a repeated delivery of the same event wakes once.
        "event_id": uuid.uuid4().hex,
    }
    for monitor in monitors:
        try:
            from docsgpt.api.user.tasks import process_monitor_event

            process_monitor_event.apply_async(args=[str(monitor["id"]), event], queue="docsgpt")
        except Exception:
            logger.exception("monitor %s: could not queue its ingest event", monitor.get("id"))


def process_event(monitor_id: str, event: Dict[str, Any], attempt: int = 0) -> Dict[str, Any]:
    """Run an ingest event for one monitor (the ``process_monitor_event`` task)."""
    if not _lease(monitor_id):
        if attempt + 1 < MAX_HIT_DEFERRALS and not _requeue_event(monitor_id, event, attempt, 2 * (attempt + 1)):
            return {"state": "failed"}
        return {"state": "busy"}
    try:
        with db_readonly() as conn:
            monitor = MonitorsRepository(conn).get_internal(monitor_id)
        if monitor is None or monitor.get("status") != "active" or monitor.get("source_type") != "ingest":
            return {"state": "skipped"}
        status = event.get("event")
        summary_text = (
            f"the ingest of source {event.get('source_id')} {'finished' if status == 'completed' else 'failed'}"
        )
        if event.get("error"):
            summary_text += f": {str(event['error'])[:300]}"
        event_id = event.get("event_id")
        data = {k: v for k, v in event.items() if k != "event_id"}
        content = Content(text=canonical_json(data), data=data)
        outcome = _event(
            monitor,
            content,
            source="monitor",
            # Stable per event; an event queued before event_id existed falls back to the check count.
            key=f"ingest:{event_id}" if event_id else f"ingest:{int(monitor.get('check_count') or 0) + 1}",
            summary=summary_text,
            extra={"ingest": data},
        )
        if outcome == "retry":
            # An ingest ends once: no later check sees this event again.
            if attempt + 1 >= MAX_HIT_DEFERRALS:
                _store(monitor_id, None, {"last_error": f"an ingest event was dropped: {UNDECIDED_NOTE}"})
                return {"state": "failed"}
            if not _requeue_event(monitor_id, event, attempt, UNDECIDED_RETRY_SECONDS * (attempt + 1)):
                return {"state": "failed"}
        return {"state": outcome}
    finally:
        _release(monitor_id)
