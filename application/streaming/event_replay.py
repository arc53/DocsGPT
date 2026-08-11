"""Shared snapshot/replay primitives for chat-stream reconnect.

The reconnect reader itself is the native-async generator in
``async_event_replay.build_message_event_stream_async``; this module holds
the pieces both it and the producer's journal depend on: the SSE wire
format (``format_sse_event``), the ``message_events`` snapshot read
(``read_snapshot_lines``), the producer-liveness watchdog probe
(``_check_producer_liveness``), and the pub/sub envelope encode/decode.
Keeping them here lets the async reader and the sync journal agree on the
exact wire shape and dedup/terminal rules. See
``docs/runbooks/sse-notifications.md``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlalchemy import text as sql_text

from application.storage.db.repositories.message_events import (
    MessageEventsRepository,
)
from application.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

DEFAULT_KEEPALIVE_SECONDS = 15.0
DEFAULT_POLL_TIMEOUT_SECONDS = 1.0
# When the live tail has no events and no terminal in snapshot, fall
# back to checking ``conversation_messages`` directly. If the row has
# already gone terminal (worker journaled ``end``/``error`` to the DB
# but the matching pub/sub publish was lost, or the row was finalized
# without a journal write at all) we surface a terminal event so the
# client doesn't hang on keepalives. If the row is still non-terminal
# but the producer heartbeat is older than ``PRODUCER_IDLE_SECONDS``
# the producer is presumed dead (worker crash / recycle between chunks
# and finalize) and we emit a terminal ``error`` so the UI can recover.
DEFAULT_WATCHDOG_INTERVAL_SECONDS = 5.0
# 1.5× the route's 60s heartbeat interval — long enough that a normal
# heartbeat skew doesn't false-positive, short enough that a stuck
# stream surfaces before the 5-minute reconciler sweep escalates.
DEFAULT_PRODUCER_IDLE_SECONDS = 90.0

# WHATWG SSE accepts CRLF, CR, LF — split on any of them so a stray CR
# can't smuggle a record boundary into the wire format.
_SSE_LINE_SPLIT_PATTERN = re.compile(r"\r\n|\r|\n")

# Event types that mark the end of a chat answer. After delivering one
# we close the reconnect stream — keeping the connection open past a
# terminal event would leak both the client's reconnect promise and
# the server's WSGI thread waiting on keepalives that the user no
# longer cares about. The agent loop emits ``end`` for normal /
# tool-paused completion and ``error`` for the catch-all failure path
# (which doesn't get a trailing ``end``).
_TERMINAL_EVENT_TYPES = frozenset({"end", "error"})


def _payload_is_terminal(
    payload: object, event_type: Optional[str] = None
) -> bool:
    """True if ``payload['type']`` or ``event_type`` is a terminal sentinel."""
    if isinstance(payload, dict) and payload.get("type") in _TERMINAL_EVENT_TYPES:
        return True
    return event_type in _TERMINAL_EVENT_TYPES


def format_sse_event(payload: dict, sequence_no: int) -> str:
    """Encode a journal event as one ``id:``/``data:`` SSE record.

    The body is the payload's JSON serialisation. ``complete_stream``
    payloads are flat JSON dicts with no embedded newlines, so a
    single ``data:`` line is sufficient — but we still split on any
    line terminator in case a future caller passes a multi-line string.
    """
    body = json.dumps(payload)
    lines = [f"id: {sequence_no}"]
    for line in _SSE_LINE_SPLIT_PATTERN.split(body):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _check_producer_liveness(
    message_id: str, user_id: Optional[str], idle_seconds: float
) -> Optional[dict]:
    """Inspect ``conversation_messages`` and return a terminal SSE
    payload when the producer is no longer alive, else ``None``.

    When ``user_id`` is given the lookup is scoped to ``AND user_id = :u``
    (defence in depth: this long-lived re-read re-asserts the ownership the
    route gated on, so a stream cannot keep tailing a row it no longer
    owns). A non-matching row reads as missing → a terminal ``error``.

    Three terminal cases collapse into a single DB round-trip:

    - ``status='complete'`` — the live finalize ran but its journal
      terminal write didn't reach us (or never happened). Synthesise
      ``end`` so the client closes cleanly on the row's user-visible
      state.
    - ``status='failed'`` — same, but for the failure path. Carry the
      stashed ``error`` from ``message_metadata`` so the UI shows the
      real reason.
    - non-terminal status and ``last_heartbeat_at`` (or ``timestamp``)
      older than ``idle_seconds`` — the producing worker is gone.
      Synthesise ``error`` so the client doesn't hang on keepalives
      until the proxy idle-timeout kicks in.
    """
    owner_clause = " AND user_id = :u" if user_id is not None else ""
    params = {"id": message_id, "idle_secs": float(idle_seconds)}
    if user_id is not None:
        params["u"] = user_id
    try:
        with db_readonly() as conn:
            row = conn.execute(
                sql_text(
                    # ``owner_clause`` is a fixed literal (no user input in the
                    # SQL string); ``user_id`` is bound via ``:u``.
                    f"""
                    SELECT
                        status,
                        message_metadata->>'error' AS err,
                        GREATEST(
                            timestamp,
                            COALESCE(
                                (message_metadata->>'last_heartbeat_at')
                                    ::timestamptz,
                                timestamp
                            )
                        ) < now() - make_interval(secs => :idle_secs)
                            AS is_stale
                    FROM conversation_messages
                    WHERE id = CAST(:id AS uuid){owner_clause}
                    """
                ),
                params,
            ).first()
    except Exception:
        logger.exception(
            "Watchdog liveness check failed for message_id=%s", message_id
        )
        return None

    if row is None:
        # Row deleted out from under us — treat as terminal so the
        # client doesn't keep tailing a message that no longer exists.
        return {
            "type": "error",
            "error": "Message no longer exists; please refresh.",
            "code": "message_missing",
            "message_id": message_id,
        }

    status, err, is_stale = row[0], row[1], bool(row[2])
    if status == "complete":
        return {"type": "end"}
    if status == "failed":
        return {
            "type": "error",
            "error": err or "Stream failed; please try again.",
            "code": "producer_failed",
            "message_id": message_id,
        }
    if is_stale:
        return {
            "type": "error",
            "error": (
                "Stream producer is no longer responding; please try again."
            ),
            "code": "producer_stale",
            "message_id": message_id,
        }
    return None


def read_snapshot_lines(
    message_id: str, last_event_id: Optional[int], user_id: Optional[str] = None
) -> tuple[list[str], Optional[int], bool]:
    """Read journal rows after ``last_event_id`` as SSE-formatted lines.

    Returns ``(lines, max_sequence_no, terminal)``: ``max_sequence_no`` is
    seeded with ``last_event_id`` and advanced past every row read,
    ``terminal`` is True if any row carried a terminal ``end``/``error``.
    Raises on DB error so the caller can drive its replay-failed path.

    Used by ``async_event_replay.build_message_event_stream_async`` (the
    reconnect reader); it shares ``format_sse_event`` / ``_payload_is_terminal``
    with the producer's journal writer so reader and writer never drift on
    wire shape or terminal semantics.
    """
    lines: list[str] = []
    max_seq = last_event_id
    terminal = False
    with db_readonly() as conn:
        rows = MessageEventsRepository(conn).read_after(
            message_id, last_sequence_no=last_event_id, user_id=user_id
        )
    for row in rows:
        seq = int(row["sequence_no"])
        payload = row.get("payload")
        if not isinstance(payload, dict):
            # ``record_event`` rejects non-dict payloads at the write gate,
            # so this is a legacy/direct-SQL row — drop it rather than ship
            # a malformed envelope that would poison a reconnect.
            logger.warning(
                "Skipping non-dict payload from message_events: "
                "message_id=%s seq=%s type=%s",
                message_id,
                seq,
                row.get("event_type"),
            )
            continue
        lines.append(format_sse_event(payload, seq))
        if max_seq is None or seq > max_seq:
            max_seq = seq
        if _payload_is_terminal(payload, row.get("event_type")):
            terminal = True
    return lines, max_seq, terminal


def _decode_pubsub_message(raw) -> Optional[dict]:
    """Parse a ``Topic.publish`` payload to ``{sequence_no, payload, ...}``.

    Returns ``None`` for malformed messages (drop silently — the
    journal is still authoritative on reconnect).
    """
    try:
        if isinstance(raw, (bytes, bytearray)):
            text_value = raw.decode("utf-8")
        else:
            text_value = str(raw)
        envelope = json.loads(text_value)
    except Exception:
        return None
    if not isinstance(envelope, dict):
        return None
    return envelope


def encode_pubsub_message(
    message_id: str,
    sequence_no: int,
    event_type: str,
    payload: dict,
) -> str:
    """Build the JSON envelope used for ``channel:{message_id}`` publishes.

    Kept here (not in ``message_journal.py``) so the encode/decode pair
    stays in one file — replay's ``_decode_pubsub_message`` and the
    journal's publish must agree on the shape exactly.
    """
    return json.dumps(
        {
            "message_id": str(message_id),
            "sequence_no": int(sequence_no),
            "event_type": event_type,
            "payload": payload,
        }
    )
