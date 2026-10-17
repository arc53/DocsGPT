"""Repository for ``monitor_events``: ingest events waiting for (or done with) the monitor that watches them.

An ingest event used to live only in its Celery task, so a task the broker
lost, or one that could not be queued again, dropped the event. Each event is
now a row first; the task claims it, and the dispatcher's sweep queues again
any row still pending after a while. The lifecycle matches ``trigger_hits``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes


def _dump(value: Any) -> str:
    return json.dumps(strip_null_bytes(value or {}), cls=PGNativeJSONEncoder)


class MonitorEventsRepository:
    """Store, claim and settle the events event-driven monitors run on."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, monitor_id: str, dedupe_key: str, payload: Dict[str, Any]) -> Optional[dict]:
        """Store an event once per ``(monitor, dedupe_key)``; None for a repeat."""
        row = self._conn.execute(
            text(
                """
                INSERT INTO monitor_events (monitor_id, dedupe_key, payload)
                VALUES (CAST(:monitor_id AS uuid), :dedupe_key, CAST(:payload AS jsonb))
                ON CONFLICT ON CONSTRAINT monitor_events_monitor_dedupe_uidx DO NOTHING
                RETURNING *
                """
            ),
            {"monitor_id": str(monitor_id), "dedupe_key": dedupe_key[:300], "payload": _dump(payload)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, event_id: str) -> Optional[dict]:
        if not looks_like_uuid(str(event_id)):
            return None
        row = self._conn.execute(
            text("SELECT * FROM monitor_events WHERE id = CAST(:id AS uuid)"), {"id": str(event_id)}
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def claim(self, event_id: str) -> Optional[dict]:
        """Take a pending event for processing (exactly once)."""
        if not looks_like_uuid(str(event_id)):
            return None
        row = self._conn.execute(
            text(
                "UPDATE monitor_events SET status = 'processed', processed_at = now() "
                "WHERE id = CAST(:id AS uuid) AND status = 'pending' RETURNING *"
            ),
            {"id": str(event_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def release(self, event_id: str) -> int:
        """Hand a claimed event back to ``pending`` for another try; returns its tries so far."""
        row = self._conn.execute(
            text(
                "UPDATE monitor_events SET status = 'pending', processed_at = NULL, attempts = attempts + 1 "
                "WHERE id = CAST(:id AS uuid) AND status = 'processed' RETURNING attempts"
            ),
            {"id": str(event_id)},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def mark(self, event_id: str, status: str, error: Optional[str] = None) -> None:
        """Record how an event ended (``processed``, ``ignored`` or ``failed``)."""
        self._conn.execute(
            text(
                "UPDATE monitor_events SET status = :status, error = :error, processed_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(event_id), "status": status, "error": (error or None) and strip_null_bytes(error)[:500]},
        )

    def list_stuck(self, *, age_seconds: int, limit: int = 50) -> List[dict]:
        """Pending events older than ``age_seconds`` (their task was lost or could not be queued)."""
        rows = self._conn.execute(
            text(
                "SELECT * FROM monitor_events WHERE status = 'pending' "
                "AND received_at < now() - make_interval(secs => :age) ORDER BY received_at LIMIT :limit"
            ),
            {"age": int(age_seconds), "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def bump(self, event_id: str) -> int:
        """Count one more try of a pending event (the sweep queued it again); returns the tries so far."""
        row = self._conn.execute(
            text(
                "UPDATE monitor_events SET attempts = attempts + 1, received_at = now() "
                "WHERE id = CAST(:id AS uuid) AND status = 'pending' RETURNING attempts"
            ),
            {"id": str(event_id)},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def cleanup_older_than(self, days: int) -> int:
        """Delete settled events older than ``days``; returns how many."""
        result = self._conn.execute(
            text(
                "DELETE FROM monitor_events WHERE status <> 'pending' "
                "AND received_at < now() - make_interval(days => :days)"
            ),
            {"days": int(days)},
        )
        return int(result.rowcount or 0)
