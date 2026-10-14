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
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.storage.db.base_repository import row_to_dict

logger = logging.getLogger(__name__)

#: Sync frequencies, each with its beat entry in ``setup_periodic_tasks``.
FREQUENCIES = ("daily", "weekly", "monthly")

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


def next_sync_times(load: Callable[[str], Any] = _load_entry) -> Dict[str, datetime]:
    """When each sync frequency fires next.

    Args:
        load: Reads a beat entry by name (tests).

    Returns:
        ``{frequency: time}`` for the frequencies beat has run at least once.
        A time in the past means beat is behind or not running (RedBeat's own
        ``due_at`` would say "now" instead). Unknown frequencies are left out:
        no beat, no Redis, or an entry that never ran.
    """
    times: Dict[str, datetime] = {}
    for frequency in FREQUENCIES:
        try:
            entry = load(f"schedule-syncs-{frequency}")
            last = getattr(entry, "last_run_at", None) if entry is not None else None
            every = getattr(getattr(entry, "schedule", None), "run_every", None)
            if last is None or every is None:
                continue
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            times[frequency] = last + every
        except Exception:
            logger.warning("activity: reading the %s sync schedule failed", frequency, exc_info=True)
    return times


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
    rows = [
        row_to_dict(r)
        for r in conn.execute(
            text(
                """
                SELECT name, type, connection_id, metadata, sync_frequency
                FROM sources
                WHERE user_id = :user_id AND sync_frequency = ANY(:frequencies)
                ORDER BY name ASC
                """
            ),
            {"user_id": user_id, "frequencies": list(due)},
        ).fetchall()
    ]
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


def next_sync_at(times: Dict[str, datetime], frequency: Optional[str]) -> Optional[str]:
    """When sources of ``frequency`` sync next, as ISO 8601, if known."""
    at = times.get(frequency or "")
    return at.isoformat() if at is not None else None
