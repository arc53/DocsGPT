"""The Activity › Calendar window: planned runs, past runs and what is watched.

Future slots come from each schedule's cron (or one-time ``run_at``); past and
in-flight slots come from ``schedule_runs`` with their real status, so a slot
the scheduler already handled shows how it went. A frequent schedule with more
events than one schedule may list is summed up per day in the viewer's time
zone (see ``_sum_up_days``). Monitors are ranges, not
events: a check every 30 minutes would bury the week. Knowledge syncs are
events too: each frequency's batch, every time its beat entry fires in the
window (future only; see ``activity.syncs``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.engine import Connection

from docsgpt.activity.common import as_datetime, parse_time, query_rows
from docsgpt.activity.syncs import calendar_slots, sync_schedule
from docsgpt.agents.scheduler_utils import (
    ScheduleValidationError,
    cron_interval_seconds,
    cron_runs,
    resolve_timezone,
)
from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)

#: The widest window one request may ask for (a month view plus its edges).
MAX_WINDOW = timedelta(days=62)

#: Planned slots, and past runs, one schedule may add to a window; a finer
#: cron is truncated to its first ones. A frequent schedule with more is
#: summed up per day instead.
MAX_SLOTS_PER_SCHEDULE = 1_000

#: Slots, and past runs, a frequent schedule may count in a window before it
#: is cut (a 5-minute cron over the widest window has about 17,900).
MAX_FREQUENT_SLOTS = 20_000

#: The states a frequent schedule's day sums up: routine ones. A failure, a
#: timeout and a run still going each stay an event of their own, to be opened.
SUMMED_STATES = frozenset({"planned", "paused", "missed", "success", "skipped"})

#: What only a single run has; a summed-up event leaves them out.
_RUN_FIELDS = ("run_id", "trigger_source", "error_type", "conversation_id")

#: A schedule this frequent or more is drawn as one block per day.
FREQUENT_SECONDS = 60 * 60

#: A past slot with no run is "missed" once it is this late: the dispatcher
#: ticks every minute and a run row appears as soon as it claims the slot.
MISSED_GRACE = timedelta(minutes=10)


class WindowError(ValueError):
    """The requested window is missing, malformed, reversed or too wide, or its time zone unknown."""


def parse_window(raw_from: Optional[str], raw_to: Optional[str]) -> Tuple[datetime, datetime]:
    """Read and check a ``from``/``to`` pair of ISO 8601 times.

    Args:
        raw_from: The window start.
        raw_to: The window end (exclusive).

    Returns:
        Both as aware UTC datetimes.

    Raises:
        WindowError: When either is missing or malformed, ``to`` is not after
            ``from``, or the window is wider than ``MAX_WINDOW``.
    """
    try:
        start = parse_time(raw_from)
        end = parse_time(raw_to)
    except (TypeError, ValueError) as exc:
        raise WindowError("from and to must be ISO 8601 times") from exc
    if end <= start:
        raise WindowError("to must be after from")
    if end - start > MAX_WINDOW:
        raise WindowError(f"the window can span at most {MAX_WINDOW.days} days")
    return start, end


def parse_zone(raw: Optional[str]) -> str:
    """Check the viewer's IANA time zone, the one days are split in.

    Args:
        raw: The zone name; empty means UTC.

    Returns:
        The zone name.

    Raises:
        WindowError: When the zone is unknown.
    """
    name = (raw or "UTC").strip() or "UTC"
    try:
        resolve_timezone(name)
    except ScheduleValidationError as exc:
        raise WindowError(str(exc)) from exc
    return name


def _utc_iso(value: datetime) -> str:
    """``value`` as ISO text in UTC."""
    return value.astimezone(timezone.utc).isoformat()


def _minute(value: datetime) -> datetime:
    """``value`` in UTC, cut to the minute, to line slots up with the runs that filled them."""
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _schedules(conn: Connection, user_id: str, end: datetime) -> List[Dict[str, Any]]:
    """The user's active and paused schedules, monitors left out, created before the window ends."""
    return query_rows(
        conn,
        """
        SELECT s.id, s.name, s.instruction, s.agent_id, s.trigger_type, s.status,
               s.cron, s.timezone, s.run_at, s.next_run_at, s.end_at,
               s.created_at, s.plan_changed_at,
               s.origin_conversation_id, a.name AS agent_name,
               c.name AS origin_conversation_name
        FROM schedules s
        LEFT JOIN agents a ON a.id = s.agent_id
        LEFT JOIN conversations c ON c.id = s.origin_conversation_id
        WHERE s.user_id = :user_id
          AND s.trigger_type <> 'monitor'
          AND s.status IN ('active', 'paused')
          AND s.created_at < :end
        """,
        {"user_id": user_id, "end": end},
    )


def _runs(conn: Connection, user_id: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """The user's schedule runs whose slot falls in the window, oldest first.

    Each schedule keeps its first ``MAX_FREQUENT_SLOTS``; ``rank`` numbers a
    schedule's runs and ``in_window`` says how many it had in all, so the
    caller cuts a schedule that is not frequent sooner.
    """
    return query_rows(
        conn,
        """
        SELECT * FROM (
            SELECT sr.id, sr.schedule_id, sr.status, sr.scheduled_for, sr.started_at,
                   sr.finished_at, sr.trigger_source, sr.error_type, sr.conversation_id,
                   s.name, s.instruction, s.agent_id, s.trigger_type, s.cron, s.timezone,
                   s.origin_conversation_id, a.name AS agent_name,
                   c.name AS origin_conversation_name,
                   ROW_NUMBER() OVER (PARTITION BY sr.schedule_id ORDER BY sr.scheduled_for, sr.id) AS rank,
                   COUNT(*) OVER (PARTITION BY sr.schedule_id) AS in_window
            FROM schedule_runs sr
            JOIN schedules s ON s.id = sr.schedule_id
            LEFT JOIN agents a ON a.id = s.agent_id
            LEFT JOIN conversations c ON c.id = s.origin_conversation_id
            WHERE sr.user_id = :user_id
              AND sr.scheduled_for >= :start AND sr.scheduled_for < :end
        ) runs
        WHERE rank <= :limit
        ORDER BY scheduled_for ASC
        """,
        {"user_id": user_id, "start": start, "end": end, "limit": MAX_FREQUENT_SLOTS},
    )


def _base(row: Dict[str, Any], frequent: bool) -> Dict[str, Any]:
    """The fields every calendar event of one schedule shares, from a schedule or run row."""
    schedule_id = row.get("schedule_id") or row.get("id")
    return {
        "kind": "schedule",
        "schedule_id": str(schedule_id),
        "name": row.get("name") or (row.get("instruction") or "")[:80] or None,
        "agent_id": str(row["agent_id"]) if row.get("agent_id") else None,
        "agent_name": row.get("agent_name"),
        "trigger_type": row.get("trigger_type"),
        "cron": row.get("cron"),
        "timezone": row.get("timezone"),
        "origin_conversation_id": (
            str(row["origin_conversation_id"]) if row.get("origin_conversation_id") else None
        ),
        "origin_conversation_name": row.get("origin_conversation_name"),
        "frequent": frequent,
    }


def _is_frequent(row: Dict[str, Any], cache: Dict[str, bool]) -> bool:
    """Whether a recurring schedule fires every ``FREQUENT_SECONDS`` or more often.

    Such a schedule is drawn as one block rather than a slot per run. The
    answer is cached per cron and timezone; an invalid cron counts as not
    frequent.
    """
    if row.get("trigger_type") != "recurring" or not row.get("cron"):
        return False
    key = f"{row['cron']}|{row.get('timezone')}"
    if key not in cache:
        try:
            cache[key] = cron_interval_seconds(row["cron"], row.get("timezone")) <= FREQUENT_SECONDS
        except ScheduleValidationError:
            cache[key] = False
    return cache[key]


def _planned_slots(
    row: Dict[str, Any],
    start: datetime,
    end: datetime,
    limit: Optional[int] = None,
    expansions: Optional[Dict[Tuple[Any, ...], List[datetime]]] = None,
) -> Tuple[List[datetime], bool]:
    """Future fire times of one schedule inside ``[start, end)``.

    Args:
        row: The schedule.
        start: Window start.
        end: Window end (exclusive).
        limit: The most times listed (default ``MAX_SLOTS_PER_SCHEDULE``).
        expansions: Cron expansions already made for this window, by cron,
            zone, bounds and limit; schedules with the same timing share one.

    Returns:
        ``(times, truncated)``; ``truncated`` when the cap cut the list.
    """
    limit = MAX_SLOTS_PER_SCHEDULE if limit is None else limit
    stop = end
    end_at = as_datetime(row.get("end_at"))
    if end_at is not None:
        # The dispatcher still runs a slot at end_at itself; the window's
        # own end stays exclusive.
        stop = min(stop, end_at + timedelta(microseconds=1))
    if row.get("trigger_type") == "once":
        fire = as_datetime(row.get("next_run_at") or row.get("run_at"))
        if row.get("status") == "paused":
            fire = as_datetime(row.get("run_at"))
        return ([fire] if fire is not None and start <= fire < stop else []), False
    if not row.get("cron"):
        return [], False
    key = (row["cron"], row.get("timezone"), start, stop, limit)
    times = expansions.get(key) if expansions is not None else None
    if times is None:
        try:
            # One past the cap tells a full window from a cut one.
            times = cron_runs(
                row["cron"], row.get("timezone"),
                after=start - timedelta(seconds=1), until=stop, limit=limit + 1,
            )
        except ScheduleValidationError:
            logger.warning("activity: schedule %s has an invalid cron", row.get("id"))
            return [], False
        if expansions is not None:
            expansions[key] = times
    return times[:limit], len(times) > limit


def _past_slots(
    row: Dict[str, Any],
    start: datetime,
    end: datetime,
    limit: Optional[int] = None,
    expansions: Optional[Dict[Tuple[Any, ...], List[datetime]]] = None,
) -> Tuple[List[datetime], bool]:
    """Fire times a schedule should have had in ``[start, end)``.

    A one-time task counts only while it is still waiting (``next_run_at``
    set): once it ran, its run row covers the slot. ``limit`` and
    ``expansions`` are as for ``_planned_slots``.
    """
    if row.get("trigger_type") == "once":
        fire = as_datetime(row.get("next_run_at"))
        return ([fire] if fire is not None and start <= fire < end else []), False
    return _planned_slots({**row, "trigger_type": "recurring"}, start, end, limit, expansions)


def _sum_up_days(
    runs: List[Dict[str, Any]],
    slots: List[Tuple[datetime, str]],
    base: Optional[Dict[str, Any]],
    zone: Any,
) -> List[Dict[str, Any]]:
    """One schedule's events, summed up per local day and state when it is frequent and over the cap.

    Only the states in ``SUMMED_STATES`` are summed; each such event keeps
    the day's first ``at``, adds ``until`` (the last) and ``count``, and
    drops the fields only a single run has. A schedule under the cap keeps
    an event per slot, so a week stays one event per run. Slots come in as
    pairs and become events only when shown on their own: a frequent
    schedule has thousands in a month, and one schedule at a time is summed
    so a request never holds them all.

    Args:
        runs: The schedule's runs, as events.
        slots: Its slots no run filled, as ``(at, state)``; each is
            planned, paused or missed, all summed states.
        base: Its fields (see ``_base``); ``None`` when it has only runs.
        zone: The viewer's time zone, which days are split in.

    Returns:
        The schedule's events.
    """
    frequent = (base or (runs[0] if runs else {})).get("frequent")
    if not frequent or len(runs) + len(slots) <= MAX_SLOTS_PER_SCHEDULE:
        return runs + [{**base, "at": _utc_iso(at), "state": state} for at, state in slots]
    out = [e for e in runs if e["state"] not in SUMMED_STATES]
    summed = [(parse_time(e["at"]), e["state"], e) for e in runs if e["state"] in SUMMED_STATES]
    summed += [(at, state, base) for at, state in slots]
    summed.sort(key=lambda entry: entry[0])
    days: Dict[Tuple[Any, str], Dict[str, Any]] = {}
    for at, state, fields in summed:
        key = (at.astimezone(zone).date(), state)
        day = days.get(key)
        if day is None:
            day = {k: v for k, v in fields.items() if k not in _RUN_FIELDS}
            day.update(at=_utc_iso(at), state=state, count=0)
            days[key] = day
            out.append(day)
        day["count"] += 1
        day["until"] = at
    for day in days.values():
        day["until"] = _utc_iso(day["until"])
    return out


def _monitors(conn: Connection, user_id: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """The user's monitors that overlap the window, drawn as ranges."""
    rows = query_rows(
        conn,
        """
        SELECT s.id, s.status, s.end_at, s.created_at, m.description, m.source_type,
               m.interval_seconds, m.conversation_id, m.last_checked_at
        FROM schedules s
        JOIN monitors m ON m.schedule_id = s.id
        WHERE s.user_id = :user_id
          AND s.trigger_type = 'monitor'
          AND s.status IN ('active', 'paused')
          AND s.created_at < :end
          AND (s.end_at IS NULL OR s.end_at > :start)
        ORDER BY s.created_at ASC
        """,
        {"user_id": user_id, "start": start, "end": end},
    )
    return [
        {
            "monitor_id": str(r["id"]),
            "description": r.get("description"),
            "source_type": r.get("source_type"),
            "status": r.get("status"),
            "interval_seconds": r.get("interval_seconds"),
            "conversation_id": str(r["conversation_id"]) if r.get("conversation_id") else None,
            "starts_at": r.get("created_at"),
            "ends_at": r.get("end_at"),
            "last_checked_at": r.get("last_checked_at"),
        }
        for r in rows
    ]


def build_planned(
    conn: Connection,
    user_id: str,
    start: datetime,
    end: datetime,
    *,
    now: Optional[datetime] = None,
    tz: Optional[str] = None,
) -> Dict[str, Any]:
    """Collect the calendar of one window.

    Args:
        conn: A read-only connection.
        user_id: Whose calendar.
        start: Window start.
        end: Window end (exclusive).
        now: The current time (tests).
        tz: The viewer's IANA time zone (default UTC); a frequent schedule's
            days are summed up in it.

    Returns:
        ``{from, to, events, monitors, truncated}``. Each event has a
        ``kind`` (``schedule`` or ``sync``, see ``calendar_slots``) and a
        ``state``: ``planned`` or ``paused`` for a future slot (or one less
        than ``MISSED_GRACE`` late), ``missed`` for an older slot of an
        active schedule that has no run, else the run's
        status (``pending``, ``running``, ``success``, ``failed``,
        ``skipped``, ``timeout``), plus ``run_id`` for a run. A summed-up
        event (see ``_sum_up_days``) has ``count`` and ``until`` instead.

    Raises:
        WindowError: When ``tz`` is unknown.
    """
    zone = resolve_timezone(parse_zone(tz))
    current = now or datetime.now(timezone.utc)
    frequent_cache: Dict[str, bool] = {}
    expansions: Dict[Tuple[Any, ...], List[datetime]] = {}
    events: List[Dict[str, Any]] = []
    # Each schedule's runs, until its slots are known (see ``_sum_up_days``).
    runs: Dict[str, List[Dict[str, Any]]] = {}
    taken: set = set()
    truncated: List[str] = []
    # Schedules whose runs were cut, to the last run kept: the slots after it
    # had runs too, so none of them is missed.
    runs_cut_at: Dict[str, datetime] = {}

    for run in _runs(conn, user_id, start, end):
        at = as_datetime(run.get("scheduled_for"))
        if at is None:
            continue
        schedule_id = str(run["schedule_id"])
        frequent = _is_frequent(run, frequent_cache)
        cap = MAX_FREQUENT_SLOTS if frequent else MAX_SLOTS_PER_SCHEDULE
        if (run.get("rank") or 0) > cap:
            continue
        if (run.get("in_window") or 0) > cap:
            truncated.append(schedule_id)
            runs_cut_at[schedule_id] = max(at, runs_cut_at.get(schedule_id, at))
        taken.add((schedule_id, _minute(at)))
        runs.setdefault(schedule_id, []).append(
            {
                **_base(run, frequent),
                "at": _utc_iso(at),
                "state": run.get("status"),
                "run_id": str(run["id"]),
                "trigger_source": run.get("trigger_source"),
                "error_type": run.get("error_type"),
                "conversation_id": str(run["conversation_id"]) if run.get("conversation_id") else None,
            }
        )

    # A slot inside the grace period is still planned, so the calendar
    # keeps it until its run appears or it turns missed.
    missed_until = min(end, current - MISSED_GRACE)
    # Older runs are trimmed (``cleanup_schedule_runs``), so an older slot
    # with no run may have run: none of them counts as missed.
    retained_since = current - timedelta(days=settings.SCHEDULE_RUN_OUTPUT_RETENTION_DAYS)
    future_start = max(start, current - MISSED_GRACE)
    for row in _schedules(conn, user_id, end):
        frequent = _is_frequent(row, frequent_cache)
        limit = MAX_FREQUENT_SLOTS if frequent else MAX_SLOTS_PER_SCHEDULE
        ahead, cut = _planned_slots(row, future_start, end, limit, expansions)
        if cut:
            truncated.append(str(row["id"]))
        state = "paused" if row.get("status") == "paused" else "planned"
        schedule_id = str(row["id"])
        slots = [(at, state) for at in ahead if (schedule_id, _minute(at)) not in taken]
        # Past slots that never got a run: the scheduler was down or behind.
        # Only within run retention, only for active schedules (pause history isn't kept, so a paused
        # one's quiet slots may be its pause), and only since its plan last
        # changed: an older timing fired at other times, and before a resume
        # it was paused. Not ``updated_at``: every dispatcher write moves it.
        since = max(
            start,
            as_datetime(row.get("plan_changed_at")) or start,
            as_datetime(row.get("created_at")) or start,
            retained_since,
        )
        if row.get("status") == "active" and since < missed_until:
            past, cut = _past_slots(row, since, missed_until, limit, expansions)
            if cut:
                truncated.append(schedule_id)
            cut_at = runs_cut_at.get(schedule_id)
            slots += [
                (at, "missed")
                for at in past
                if (schedule_id, _minute(at)) not in taken and (cut_at is None or at <= cut_at)
            ]
        events += _sum_up_days(runs.pop(schedule_id, []), slots, _base(row, frequent), zone)
    # Runs of schedules that have since ended (completed, cancelled).
    for schedule_runs in runs.values():
        events += _sum_up_days(schedule_runs, [], None, zone)

    events += calendar_slots(conn, user_id, start, end, sync_schedule(), now=current)
    events.sort(key=lambda event: event["at"])
    return {
        "from": _utc_iso(start),
        "to": _utc_iso(end),
        "events": events,
        "monitors": _monitors(conn, user_id, start, end),
        "truncated": list(dict.fromkeys(truncated)),
    }
