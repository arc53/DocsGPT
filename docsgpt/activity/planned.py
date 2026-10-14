"""The Activity › Calendar window: planned runs, past runs and what is watched.

Future slots come from each schedule's cron (or one-time ``run_at``); past and
in-flight slots come from ``schedule_runs`` with their real status, so a slot
the scheduler already handled shows how it went. Monitors are ranges, not
events: a check every 30 minutes would bury the week. Knowledge syncs are
events too: each frequency's batch, every time its beat entry fires in the
window (future only; see ``activity.syncs``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.activity.syncs import calendar_slots, sync_schedule
from docsgpt.agents.scheduler_utils import (
    ScheduleValidationError,
    cron_interval_seconds,
    cron_runs,
)
from docsgpt.storage.db.base_repository import row_to_dict

logger = logging.getLogger(__name__)

#: The widest window one request may ask for (a month view plus its edges).
MAX_WINDOW = timedelta(days=62)

#: Planned slots, and past runs, one schedule may add to a window; a finer
#: cron is truncated to its first ones.
MAX_SLOTS_PER_SCHEDULE = 1_000

#: A schedule this frequent or more is drawn as one block per day.
FREQUENT_SECONDS = 60 * 60

#: A past slot with no run is "missed" once it is this late: the dispatcher
#: ticks every minute and a run row appears as soon as it claims the slot.
MISSED_GRACE = timedelta(minutes=10)


class WindowError(ValueError):
    """The requested window is missing, malformed, reversed or too wide."""


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
        start = _parse(raw_from)
        end = _parse(raw_to)
    except (TypeError, ValueError) as exc:
        raise WindowError("from and to must be ISO 8601 times") from exc
    if end <= start:
        raise WindowError("to must be after from")
    if end - start > MAX_WINDOW:
        raise WindowError(f"the window can span at most {MAX_WINDOW.days} days")
    return start, end


def _parse(value: Any) -> datetime:
    """``value`` (a datetime or ISO text) as an aware datetime; naive means UTC. Raises on bad text."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_datetime(value: Any) -> Optional[datetime]:
    """Like ``_parse``, but ``None`` for an empty or unreadable value."""
    if value in (None, ""):
        return None
    try:
        return _parse(value)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime) -> str:
    """``value`` as ISO text in UTC."""
    return value.astimezone(timezone.utc).isoformat()


def _minute(value: datetime) -> datetime:
    """``value`` in UTC, cut to the minute, to line slots up with the runs that filled them."""
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _rows(conn: Connection, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run ``sql`` and return its rows as dicts."""
    return [row_to_dict(r) for r in conn.execute(text(sql), params).fetchall()]


def _schedules(conn: Connection, user_id: str, end: datetime) -> List[Dict[str, Any]]:
    """The user's active and paused schedules, monitors left out, created before the window ends."""
    return _rows(
        conn,
        """
        SELECT s.id, s.name, s.instruction, s.agent_id, s.trigger_type, s.status,
               s.cron, s.timezone, s.run_at, s.next_run_at, s.end_at,
               s.created_at, s.updated_at,
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

    Each schedule keeps its first ``MAX_SLOTS_PER_SCHEDULE``, as its planned
    slots do; ``in_window`` on every row says how many it had in all.
    """
    return _rows(
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
        {"user_id": user_id, "start": start, "end": end, "limit": MAX_SLOTS_PER_SCHEDULE},
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


def _planned_slots(row: Dict[str, Any], start: datetime, end: datetime) -> Tuple[List[datetime], bool]:
    """Future fire times of one schedule inside ``[start, end)``.

    Returns:
        ``(times, truncated)``; ``truncated`` when the cap cut the list.
    """
    stop = end
    end_at = _as_datetime(row.get("end_at"))
    if end_at is not None:
        stop = min(stop, end_at)
    if row.get("trigger_type") == "once":
        fire = _as_datetime(row.get("next_run_at") or row.get("run_at"))
        if row.get("status") == "paused":
            fire = _as_datetime(row.get("run_at"))
        return ([fire] if fire is not None and start <= fire < stop else []), False
    if not row.get("cron"):
        return [], False
    try:
        # One past the cap tells a full window from a cut one.
        times = cron_runs(
            row["cron"], row.get("timezone"),
            after=start - timedelta(seconds=1), until=stop, limit=MAX_SLOTS_PER_SCHEDULE + 1,
        )
    except ScheduleValidationError:
        logger.warning("activity: schedule %s has an invalid cron", row.get("id"))
        return [], False
    return times[:MAX_SLOTS_PER_SCHEDULE], len(times) > MAX_SLOTS_PER_SCHEDULE


def _past_slots(row: Dict[str, Any], start: datetime, end: datetime) -> Tuple[List[datetime], bool]:
    """Fire times a schedule should have had in ``[start, end)``.

    A one-time task counts only while it is still waiting (``next_run_at``
    set): once it ran, its run row covers the slot.
    """
    if row.get("trigger_type") == "once":
        fire = _as_datetime(row.get("next_run_at"))
        return ([fire] if fire is not None and start <= fire < end else []), False
    return _planned_slots({**row, "trigger_type": "recurring"}, start, end)


def _monitors(conn: Connection, user_id: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """The user's monitors that overlap the window, drawn as ranges."""
    rows = _rows(
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
) -> Dict[str, Any]:
    """Collect the calendar of one window.

    Args:
        conn: A read-only connection.
        user_id: Whose calendar.
        start: Window start.
        end: Window end (exclusive).
        now: The current time (tests).

    Returns:
        ``{from, to, events, monitors, truncated}``. Each event has a
        ``kind`` (``schedule`` or ``sync``, see ``calendar_slots``) and a
        ``state``: ``planned`` or ``paused`` for a future slot, ``missed`` for
        a past slot of an active schedule that has no run, else the run's
        status (``pending``, ``running``, ``success``, ``failed``,
        ``skipped``, ``timeout``), plus ``run_id`` for a run.
    """
    current = now or datetime.now(timezone.utc)
    frequent_cache: Dict[str, bool] = {}
    events: List[Dict[str, Any]] = []
    taken: set = set()
    truncated: List[str] = []
    # Schedules whose runs were cut, to the last run kept: the slots after it
    # had runs too, so none of them is missed.
    runs_cut_at: Dict[str, datetime] = {}

    for run in _runs(conn, user_id, start, end):
        at = _as_datetime(run.get("scheduled_for"))
        if at is None:
            continue
        schedule_id = str(run["schedule_id"])
        if (run.get("in_window") or 0) > MAX_SLOTS_PER_SCHEDULE:
            truncated.append(schedule_id)
            runs_cut_at[schedule_id] = max(at, runs_cut_at.get(schedule_id, at))
        taken.add((schedule_id, _minute(at)))
        events.append(
            {
                **_base(run, _is_frequent(run, frequent_cache)),
                "at": _iso(at),
                "state": run.get("status"),
                "run_id": str(run["id"]),
                "trigger_source": run.get("trigger_source"),
                "error_type": run.get("error_type"),
                "conversation_id": str(run["conversation_id"]) if run.get("conversation_id") else None,
            }
        )

    future_start = max(start, current)
    missed_until = min(end, current - MISSED_GRACE)
    for row in _schedules(conn, user_id, end):
        slots, cut = _planned_slots(row, future_start, end)
        if cut:
            truncated.append(str(row["id"]))
        frequent = _is_frequent(row, frequent_cache)
        state = "paused" if row.get("status") == "paused" else "planned"
        for at in slots:
            if (str(row["id"]), _minute(at)) in taken:
                continue
            events.append({**_base(row, frequent), "at": _iso(at), "state": state})
        # Past slots that never got a run: the scheduler was down or behind.
        # Only for active schedules (pause history isn't kept, so a paused
        # one's quiet slots may be its pause), and only since its last edit
        # (an older cron fired at other times).
        if row.get("status") != "active":
            continue
        since = max(
            start,
            _as_datetime(row.get("updated_at")) or start,
            _as_datetime(row.get("created_at")) or start,
        )
        if since >= missed_until:
            continue
        past, cut = _past_slots(row, since, missed_until)
        if cut:
            truncated.append(str(row["id"]))
        cut_at = runs_cut_at.get(str(row["id"]))
        for at in past:
            if (str(row["id"]), _minute(at)) in taken or (cut_at is not None and at > cut_at):
                continue
            events.append({**_base(row, frequent), "at": _iso(at), "state": "missed"})

    events += calendar_slots(conn, user_id, start, end, sync_schedule(), now=current)
    events.sort(key=lambda event: event["at"])
    return {
        "from": _iso(start),
        "to": _iso(end),
        "events": events,
        "monitors": _monitors(conn, user_id, start, end),
        "truncated": list(dict.fromkeys(truncated)),
    }
