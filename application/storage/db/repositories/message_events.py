"""Repository for ``message_events`` — the chat-stream snapshot journal.

``record`` / ``bulk_record`` write per-yield events; ``read_after``
replays rows past a cursor for reconnect snapshots. Composite PK
``(message_id, sequence_no)`` raises ``IntegrityError`` on duplicates.
Callers must use short-lived per-call transactions — long-lived
transactions hide writes from reconnecting clients on a separate
connection and turn one bad row into ``InFailedSqlTransaction``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict

logger = logging.getLogger(__name__)


class MessageEventsRepository:
    """Read/write helpers for ``message_events``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record(
        self,
        message_id: str,
        sequence_no: int,
        event_type: str,
        payload: Optional[Any] = None,
    ) -> None:
        """Append a single event to the journal.

        At this raw repo layer ``payload`` is preserved as-is when not
        ``None`` (lists, scalars, and dicts all round-trip via JSONB);
        ``None`` substitutes an empty object so the column's NOT NULL
        invariant holds. The streaming-route wrapper
        ``application/streaming/message_journal.py::record_event``
        tightens this contract to dicts only — the live and replay
        paths reconstruct non-dict payloads differently, so the wrapper
        rejects them at the gate. Direct callers of this repo method
        (cleanup tasks, tests, future ad-hoc consumers) keep the wider
        JSONB-compatible surface.

        Raises ``sqlalchemy.exc.IntegrityError`` on duplicate
        ``(message_id, sequence_no)`` and ``DataError`` on a malformed
        ``message_id`` UUID. Both abort the surrounding transaction —
        callers must run inside a short-lived per-event session
        (see module docstring).
        """
        if not event_type:
            raise ValueError("event_type must be a non-empty string")
        materialised_payload = payload if payload is not None else {}
        self._conn.execute(
            text(
                """
                INSERT INTO message_events (
                    message_id, sequence_no, event_type, payload
                ) VALUES (
                    CAST(:message_id AS uuid), :sequence_no, :event_type,
                    CAST(:payload AS jsonb)
                )
                """
            ),
            {
                "message_id": str(message_id),
                "sequence_no": int(sequence_no),
                "event_type": event_type,
                "payload": json.dumps(materialised_payload),
            },
        )

    def bulk_record(
        self,
        message_id: str,
        events: list[tuple[int, str, dict]],
    ) -> None:
        """Append multiple events for ``message_id`` in one INSERT.

        ``events`` is a list of ``(sequence_no, event_type, payload)``
        tuples. SQLAlchemy ``executemany`` issues one bulk INSERT;
        Postgres treats the whole batch as one statement, so an
        IntegrityError on any row aborts the entire batch.

        Caller contract: on IntegrityError, do NOT retry this method
        with the same batch — fall back to per-row ``record()`` calls
        (each in its own short-lived session) so a single colliding
        seq doesn't drop the rest of the batch. ``BatchedJournalWriter``
        in ``application/streaming/message_journal.py`` is the canonical
        consumer.
        """
        if not events:
            return
        params = [
            {
                "message_id": str(message_id),
                "sequence_no": int(seq),
                "event_type": event_type,
                "payload": json.dumps(payload if payload is not None else {}),
            }
            for seq, event_type, payload in events
        ]
        self._conn.execute(
            text(
                """
                INSERT INTO message_events (
                    message_id, sequence_no, event_type, payload
                ) VALUES (
                    CAST(:message_id AS uuid), :sequence_no, :event_type,
                    CAST(:payload AS jsonb)
                )
                """
            ),
            params,
        )

    def read_after(
        self,
        message_id: str,
        last_sequence_no: Optional[int] = None,
    ) -> list[dict]:
        """Return events with ``sequence_no > last_sequence_no``.

        ``last_sequence_no=None`` returns the full backlog. Rows are
        returned in ascending ``sequence_no`` order. The composite PK
        is the snapshot read index for this scan — Postgres typically
        picks an in-order index range scan, though for highly mixed
        data the planner may pick a bitmap+sort. Either way the result
        is sorted on ``sequence_no``.

        Returns a ``list`` (not a generator) so the underlying
        ``Result`` is fully drained before the caller can issue
        another query on the same connection.
        """
        cursor = -1 if last_sequence_no is None else int(last_sequence_no)
        rows = self._conn.execute(
            text(
                """
                SELECT message_id, sequence_no, event_type, payload, created_at
                FROM message_events
                WHERE message_id = CAST(:message_id AS uuid)
                  AND sequence_no > :cursor
                ORDER BY sequence_no ASC
                """
            ),
            {"message_id": str(message_id), "cursor": cursor},
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def cleanup_older_than(self, ttl_days: int) -> int:
        """Delete journal rows older than ``ttl_days``. Returns row count.

        Reconnect-replay is meaningful only for streams the client
        could plausibly still be waiting on, so old rows are dead
        weight. The ``message_events_created_at_idx`` btree makes the
        range delete a cheap index scan even on large tables.
        """
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        result = self._conn.execute(
            text(
                """
                DELETE FROM message_events
                WHERE created_at < now() - make_interval(days => :ttl_days)
                """
            ),
            {"ttl_days": int(ttl_days)},
        )
        return int(result.rowcount or 0)

    def reconstruct_partial(self, message_id: str) -> dict:
        """Rebuild partial response/thought/sources/tool_calls from journal events.

        ``answer``/``thought`` chunks concat in seq order; ``source``/
        ``tool_calls`` carry the full list at emit time (last-wins).
        """
        rows = self._conn.execute(
            text(
                """
                SELECT sequence_no, event_type, payload
                FROM message_events
                WHERE message_id = CAST(:message_id AS uuid)
                ORDER BY sequence_no ASC
                """
            ),
            {"message_id": str(message_id)},
        ).fetchall()

        response_parts: list[str] = []
        thought_parts: list[str] = []
        sources: list = []
        tool_calls: list = []

        for row in rows:
            payload = row.payload
            if not isinstance(payload, dict):
                continue
            etype = row.event_type
            if etype == "answer":
                chunk = payload.get("answer")
                if isinstance(chunk, str):
                    response_parts.append(chunk)
            elif etype == "thought":
                chunk = payload.get("thought")
                if isinstance(chunk, str):
                    thought_parts.append(chunk)
            elif etype == "source":
                src = payload.get("source")
                if isinstance(src, list):
                    sources = src
            elif etype == "tool_calls":
                tcs = payload.get("tool_calls")
                if isinstance(tcs, list):
                    tool_calls = tcs

        return {
            "response": "".join(response_parts),
            "thought": "".join(thought_parts),
            "sources": sources,
            "tool_calls": tool_calls,
        }

    def latest_sequence_no(self, message_id: str) -> Optional[int]:
        """Largest ``sequence_no`` recorded for ``message_id``, or ``None``.

        Used by the route to seed the per-stream allocator on retry /
        process restart so a re-run continues numbering instead of
        trampling earlier entries with duplicate sequence_no.
        """
        # ``MAX`` always returns one row — NULL when the journal is
        # empty — so we test the value, not the row presence.
        row = self._conn.execute(
            text(
                """
                SELECT MAX(sequence_no) AS s
                FROM message_events
                WHERE message_id = CAST(:message_id AS uuid)
                """
            ),
            {"message_id": str(message_id)},
        ).first()
        value = row[0] if row is not None else None
        return int(value) if value is not None else None
