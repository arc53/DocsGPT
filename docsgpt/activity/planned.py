"""The Activity › Calendar window: planned runs, past runs and what is watched.

Future slots come from each schedule's cron (or one-time ``run_at``); past and
in-flight slots come from ``schedule_runs`` with their real status, so a slot
the scheduler already handled shows how it went. Monitors are ranges, not
events: a check every 30 minutes would bury the week. Knowledge syncs have no
clock time (every source of a frequency syncs when its beat task fires), so
they are listed by frequency only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.agents.scheduler_utils import (
    ScheduleValidationError,
    cron_interval_seconds,
    next_cron_run,
)
from docsgpt.storage.db.base_repository import row_to_dict

logger = logging.getLogger(__name__)

#: The widest window one request may ask for (a month view plus its edges).
MAX_WINDOW = timedelta(days=62)

#: Planned slots one schedule may add to a window; a finer cron is truncated.
MAX_SLOTS_PER_SCHEDULE = 1_000

#: A schedule this frequent or more is drawn as one block per day.
FREQUENT_SECONDS = 60 * 60

#: Past runs one window lists.
MAX_RUNS = 5_000


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
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        return _parse(value)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _minute(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _rows(conn: Connection, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [row_to_dict(r) for r in conn.execute(text(sql), params).fetchall()]


def _schedules(conn: Connection, user_id: str, end: datetime) -> List[Dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT s.id, s.name, s.instruction, s.agent_id, s.trigger_type, s.status,
               s.cron, s.timezone, s.run_at, s.next_run_at, s.end_at,
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
    return _rows(
        conn,
        """
        SELECT sr.id, sr.schedule_id, sr.status, sr.scheduled_for, sr.started_at,
               sr.finished_at, sr.trigger_source, sr.error_type, sr.conversation_id,
               s.name, s.instruction, s.agent_id, s.trigger_type, s.cron, s.timezone,
               s.origin_conversation_id, a.name AS agent_name,
               c.name AS origin_conversation_name
        FROM schedule_runs sr
        JOIN schedules s ON s.id = sr.schedule_id
        LEFT JOIN agents a ON a.id = s.agent_id
        LEFT JOIN conversations c ON c.id = s.origin_conversation_id
        WHERE sr.user_id = :user_id
          AND sr.scheduled_for >= :start AND sr.scheduled_for < :end
        ORDER BY sr.scheduled_for ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "start": start, "end": end, "limit": MAX_RUNS},
    )


def _base(row: Dict[str, Any], frequent: bool) -> Dict[str, Any]:
    schedule_id = row.get("schedule_id") or row.get("id")
    return {
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
    times: List[datetime] = []
    try:
        fire = next_cron_run(row["cron"], row.get("timezone"), after=start - timedelta(seconds=1))
        while fire < stop:
            if len(times) >= MAX_SLOTS_PER_SCHEDULE:
                return times, True
            times.append(fire)
            fire = next_cron_run(row["cron"], row.get("timezone"), after=fire)
    except ScheduleValidationError:
        logger.warning("activity: schedule %s has an invalid cron", row.get("id"))
    return times, False


def _monitors(conn: Connection, user_id: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
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


def _syncs(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT id, name, sync_frequency, date
        FROM sources
        WHERE user_id = :user_id AND sync_frequency IN ('daily', 'weekly', 'monthly')
        ORDER BY name ASC
        """,
        {"user_id": user_id},
    )
    return [
        {
            "source_id": str(r["id"]),
            "name": r.get("name"),
            "frequency": r.get("sync_frequency"),
            "last_synced_at": r.get("date"),
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
        ``{from, to, events, monitors, syncs, truncated}``. Each event has a
        ``state``: ``planned`` or ``paused`` for a future slot, else the run's
        status (``pending``, ``running``, ``success``, ``failed``,
        ``skipped``, ``timeout``), plus ``run_id`` for a run.
    """
    current = now or datetime.now(timezone.utc)
    frequent_cache: Dict[str, bool] = {}
    events: List[Dict[str, Any]] = []
    taken: set = set()

    for run in _runs(conn, user_id, start, end):
        at = _as_datetime(run.get("scheduled_for"))
        if at is None:
            continue
        taken.add((str(run["schedule_id"]), _minute(at)))
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

    truncated: List[str] = []
    future_start = max(start, current)
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

    events.sort(key=lambda event: event["at"])
    return {
        "from": _iso(start),
        "to": _iso(end),
        "events": events,
        "monitors": _monitors(conn, user_id, start, end),
        "syncs": _syncs(conn, user_id),
        "truncated": truncated,
    }
