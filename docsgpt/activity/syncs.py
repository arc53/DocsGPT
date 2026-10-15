"""Knowledge syncs for Activity: when each frequency syncs next, and which of a
user's sources sync then.

Sources don't sync on a clock time of their own: each frequency has one beat
entry (``schedule-syncs-daily`` / ``-weekly`` / ``-monthly``) that, when it
fires, dispatches every source of that frequency. RedBeat keeps each entry's
last run in Redis, so the next one is that plus the entry's interval. That is
not aligned to the wall clock (it counts from when beat first ran), but it is
known.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.storage.db.base_repository import row_to_dict

logger = logging.getLogger(__name__)

#: Sync frequencies, each with its beat entry in ``setup_periodic_tasks``.
FREQUENCIES = ("daily", "weekly", "monthly")

#: Sync slots one frequency may add to a calendar window.
MAX_SLOTS_PER_FREQUENCY = 100

#: How late a next time may be and still count as about to fire: beat runs an
#: entry a little after its time and only then moves ``last_run_at``. Later
#: than this, beat is taken as behind or stopped.
LATE_GRACE = timedelta(minutes=15)

#: How long one process reuses what it read from beat: every Now load and
#: calendar window asks, and the entries move at most once a day.
SCHEDULE_CACHE_SECONDS = 60

#: ``(read at, schedule)`` from the last read of beat, on ``time.monotonic``.
_cached: Optional[Tuple[float, Dict[str, Tuple[datetime, timedelta]]]] = None

#: Remote loaders that can only read with a connection; mirrors
#: ``docsgpt.worker._CONNECTION_ONLY_LOADERS`` (a test keeps them equal).
CONNECTION_ONLY_LOADERS = frozenset({"linear"})


def _load_entry(name: str) -> Any:
    """The RedBeat entry ``name``, or None when beat hasn't stored it."""
    from redbeat.schedulers import RedBeatSchedulerEntry, ensure_conf

    from docsgpt.celery_init import celery

    ensure_conf(celery)
    try:
        return RedBeatSchedulerEntry.from_key(RedBeatSchedulerEntry.generate_key(celery, name), app=celery)
    except KeyError:
        return None


def sync_schedule(load: Optional[Callable[[str], Any]] = None) -> Dict[str, Tuple[datetime, timedelta]]:
    """When each sync frequency fires next, and how often it fires.

    Args:
        load: Reads a beat entry by name (tests). Without it, RedBeat is read
            at most once per ``SCHEDULE_CACHE_SECONDS``.

    Returns:
        ``{frequency: (next time, interval)}`` for the frequencies beat has
        run at least once. A next time in the past means beat is behind or
        not running (RedBeat's own ``due_at`` would say "now" instead).
        Unknown frequencies are left out: no beat, no Redis, or an entry
        that never ran.
    """
    global _cached
    if load is not None:
        return _read_schedule(load)
    current = time.monotonic()
    cached = _cached
    if cached is not None and current - cached[0] < SCHEDULE_CACHE_SECONDS:
        return dict(cached[1])
    schedule = _read_schedule(_load_entry)
    _cached = (current, schedule)
    return dict(schedule)


def _read_schedule(load: Callable[[str], Any]) -> Dict[str, Tuple[datetime, timedelta]]:
    """``sync_schedule`` read through ``load``, uncached."""
    schedule: Dict[str, Tuple[datetime, timedelta]] = {}
    for frequency in FREQUENCIES:
        try:
            entry = load(f"schedule-syncs-{frequency}")
            last = getattr(entry, "last_run_at", None) if entry is not None else None
            every = getattr(getattr(entry, "schedule", None), "run_every", None)
            if last is None or every is None:
                continue
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            schedule[frequency] = (last + every, every)
        except Exception:
            logger.warning("activity: reading the %s sync schedule failed", frequency, exc_info=True)
    return schedule


def next_sync_times(load: Optional[Callable[[str], Any]] = None) -> Dict[str, datetime]:
    """When each sync frequency fires next (see ``sync_schedule``).

    Args:
        load: Reads a beat entry by name (tests); without it, the cached read.

    Returns:
        ``{frequency: time}`` for the frequencies with a known time.
    """
    return {frequency: at for frequency, (at, _) in sync_schedule(load).items()}


def _blocked(row: Dict[str, Any]) -> bool:
    """Whether the sync worker would skip this source (it needs a reconnect).

    Mirrors ``sync_worker``: a connector source with no connection, a source
    whose connection needs signing in again, a connection-only loader whose
    connection was removed.
    """
    source_type = row.get("type") or ""
    has_connection = bool(row.get("connection_id"))
    if source_type.startswith("connector"):
        return not has_connection
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    if has_connection and isinstance(metadata, dict) and metadata.get("sync_state") == "paused_reconnect":
        return True
    return source_type in CONNECTION_ONLY_LOADERS and not has_connection


def _members(conn: Connection, user_id: str, frequencies: List[str]) -> List[Dict[str, Any]]:
    """The user's sources that sync at any of ``frequencies``, by name."""
    return [
        row_to_dict(r)
        for r in conn.execute(
            text(
                """
                SELECT id, name, type, connection_id, metadata, sync_frequency, date
                FROM sources
                WHERE user_id = :user_id AND sync_frequency = ANY(:frequencies)
                ORDER BY name ASC
                """
            ),
            {"user_id": user_id, "frequencies": frequencies},
        ).fetchall()
    ]


def due_batches(
    conn: Connection,
    user_id: str,
    start: datetime,
    end: datetime,
    times: Dict[str, datetime],
) -> List[Dict[str, Any]]:
    """The user's sync batches due before ``end``, one per frequency.

    Args:
        conn: A read-only connection.
        user_id: Whose sources.
        start: The window start; an earlier time is overdue and still listed.
        end: The window end (exclusive).
        times: ``next_sync_times()``.

    Returns:
        Items for Up next, soonest first: ``{kind: "sync", id, frequency,
        next_run_at, sources, blocked}``, where ``sources`` names the sources
        that sync and ``blocked`` the ones that need a reconnect first.
    """
    due = {frequency: at for frequency, at in times.items() if at < end}
    if not due:
        return []
    rows = _members(conn, user_id, list(due))
    batches = []
    for frequency, at in sorted(due.items(), key=lambda item: item[1]):
        members = [row for row in rows if row.get("sync_frequency") == frequency]
        if not members:
            continue
        batches.append(
            {
                "kind": "sync",
                "id": f"sync:{frequency}",
                "frequency": frequency,
                "next_run_at": at.isoformat(),
                "sources": [row.get("name") for row in members if not _blocked(row)],
                "blocked": [row.get("name") for row in members if _blocked(row)],
            }
        )
    return batches


def calendar_slots(
    conn: Connection,
    user_id: str,
    start: datetime,
    end: datetime,
    schedule: Dict[str, Tuple[datetime, timedelta]],
    *,
    now: datetime,
) -> List[Dict[str, Any]]:
    """The user's sync batches as calendar events, each time one fires in the window.

    Only future firings: a sync's outcome isn't recorded per run, and a next
    time past by more than ``LATE_GRACE`` (beat behind or stopped) plans
    nothing. One less late is about to fire and keeps its time.

    Args:
        conn: A read-only connection.
        user_id: Whose sources.
        start: Window start.
        end: Window end (exclusive).
        schedule: ``sync_schedule()``.
        now: The current time.

    Returns:
        Events shaped like the calendar's schedule slots (``kind: "sync"``,
        ``schedule_id: "sync:<frequency>"`` as the series key, ``state:
        "planned"``) plus ``frequency`` and ``sources``: ``{id, name, type,
        blocked, last_synced_at}`` per source.
    """
    upcoming = {
        frequency: plan for frequency, plan in schedule.items() if now - LATE_GRACE <= plan[0] < end
    }
    if not upcoming:
        return []
    rows = _members(conn, user_id, list(upcoming))
    events = []
    for frequency, (first, every) in upcoming.items():
        members = [row for row in rows if row.get("sync_frequency") == frequency]
        if not members or every <= timedelta(0):
            continue
        sources = [
            {
                "id": str(row["id"]),
                "name": row.get("name"),
                "type": row.get("type"),
                "blocked": _blocked(row),
                "last_synced_at": row.get("date"),
            }
            for row in members
        ]
        at = first
        if at < start:
            at += every * -(-(start - at) // every)
        count = 0
        while at < end and count < MAX_SLOTS_PER_FREQUENCY:
            events.append(
                {
                    "kind": "sync",
                    "schedule_id": f"sync:{frequency}",
                    "name": None,
                    "agent_id": None,
                    "agent_name": None,
                    "frequent": False,
                    "at": at.isoformat(),
                    "state": "planned",
                    "frequency": frequency,
                    "sources": sources,
                }
            )
            at += every
            count += 1
    return events
