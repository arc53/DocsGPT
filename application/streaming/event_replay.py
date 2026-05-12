"""Snapshot+tail iterator for chat-stream reconnect-after-disconnect.

A client that drops mid-answer reconnects to
``GET /api/messages/<message_id>/events`` with the last
``sequence_no`` it saw as ``Last-Event-ID``. The endpoint passes that
cursor here. We:

1. Subscribe to ``channel:{message_id}`` (Phase 1A ``Topic``).
2. Inside the SUBSCRIBE-ack callback, read ``message_events`` rows
   ``WHERE sequence_no > last_event_id`` from Postgres.
3. Yield the snapshot to the client first (each row becomes one
   ``id: <seq>\\ndata: <json>\\n\\n`` SSE record).
4. Tail the live pub/sub topic, dropping any inbound message whose
   ``sequence_no`` is ``<= max_replayed`` (the snapshot already
   covered it).
5. Emit ``: keepalive`` comments while idle.

The subscribe-then-snapshot ordering is the same race-free pattern
the user-event SSE endpoint uses (``application/api/events/routes.py``):
any publish that fires between SUBSCRIBE-send and SUBSCRIBE-ack has
its journal row captured by the snapshot read AND its pub/sub message
buffered at the connection layer until we read it past the callback.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Iterator, Optional

from sqlalchemy import text as sql_text

from application.storage.db.repositories.message_events import (
    MessageEventsRepository,
)
from application.storage.db.session import db_readonly
from application.streaming.broadcast_channel import Topic
from application.streaming.keys import message_topic_name

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
    """Terminal if either the payload's ``type`` or the column-level
    ``event_type`` matches a known terminal sentinel. The column
    fallback covers journal writes that record the discriminator only
    in ``event_type`` (e.g. abort handlers using ``record_event(..., "end", {})``).
    """
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
    message_id: str, idle_seconds: float
) -> Optional[dict]:
    """Inspect ``conversation_messages`` and return a terminal SSE
    payload when the producer is no longer alive, else ``None``.

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
    try:
        with db_readonly() as conn:
            row = conn.execute(
                sql_text(
                    """
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
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": message_id, "idle_secs": float(idle_seconds)},
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


def build_message_event_stream(
    message_id: str,
    last_event_id: Optional[int] = None,
    *,
    keepalive_seconds: float = DEFAULT_KEEPALIVE_SECONDS,
    poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
    watchdog_interval_seconds: float = DEFAULT_WATCHDOG_INTERVAL_SECONDS,
    producer_idle_seconds: float = DEFAULT_PRODUCER_IDLE_SECONDS,
) -> Iterator[str]:
    """Yield SSE-formatted lines for one ``message_id`` reconnect stream.

    The first frame is a ``: connected`` comment so reverse proxies
    flush their buffers immediately. Subsequent frames are either:

    - replayed snapshot events (``id: <seq>\\ndata: <json>\\n\\n``)
    - live tail events from pub/sub (same shape, dedup'd by seq)
    - ``: keepalive`` comments at ``keepalive_seconds`` cadence

    The iterator runs until cancelled (client disconnect → SSE
    generator close → ``Topic.subscribe`` finally closes the pubsub).
    """
    yield ": connected\n\n"

    # Replay buffer — populated inside ``_on_subscribe`` (or the
    # Redis-unavailable fallback below), drained on the first iteration
    # of the subscribe loop after the callback runs.
    replay_buffer: list[str] = []
    # Dedup floor: seeded with the client's cursor so an empty snapshot
    # still rejects re-published live events with seq <= last_event_id.
    # Advanced by snapshot rows AND by yielded live events, so any
    # republish past the snapshot ceiling is also dropped.
    max_replayed_seq: Optional[int] = last_event_id
    replay_done = False
    replay_failed = False
    # Set when a snapshot row carries a terminal ``end`` / ``error``
    # event. After flushing the buffer the generator returns; if we
    # kept tailing we'd loop on keepalives forever for a stream that
    # already finished.
    terminal_in_snapshot = False

    def _read_snapshot_into_buffer() -> None:
        nonlocal max_replayed_seq, replay_failed, terminal_in_snapshot
        try:
            with db_readonly() as conn:
                rows = MessageEventsRepository(conn).read_after(
                    message_id, last_sequence_no=last_event_id
                )
            for row in rows:
                seq = int(row["sequence_no"])
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    # ``record_event`` rejects non-dict payloads at the
                    # write gate, so this can only be a legacy row from
                    # before that contract or a direct SQL insert. The
                    # original synthetic fallback (``{"type": event_type}``)
                    # used to ship a malformed envelope here — drop the
                    # row instead so a corrupt journal entry doesn't
                    # poison a reconnect.
                    logger.warning(
                        "Skipping non-dict payload from message_events: "
                        "message_id=%s seq=%s type=%s",
                        message_id,
                        seq,
                        row.get("event_type"),
                    )
                    continue
                replay_buffer.append(format_sse_event(payload, seq))
                if max_replayed_seq is None or seq > max_replayed_seq:
                    max_replayed_seq = seq
                if _payload_is_terminal(payload, row.get("event_type")):
                    terminal_in_snapshot = True
        except Exception:
            logger.exception(
                "Snapshot read failed for message_id=%s last_event_id=%s",
                message_id,
                last_event_id,
            )
            replay_failed = True

    def _on_subscribe() -> None:
        # SUBSCRIBE has been acked — Postgres reads from this point
        # capture every row that's been committed. Pub/sub messages
        # published after this point are queued at the connection level
        # until the outer loop calls ``get_message`` again.
        nonlocal replay_done
        try:
            _read_snapshot_into_buffer()
        finally:
            # Flip even on failure so the outer loop continues to live
            # tail and the client doesn't hang waiting for a snapshot
            # flush that will never come.
            replay_done = True

    topic = Topic(message_topic_name(message_id))
    last_keepalive = time.monotonic()
    # Rate-limit the watchdog's DB hit. ``-inf`` makes the first idle
    # tick after replay_done fire immediately so a snapshot-already-
    # terminal-in-DB case is surfaced before any keepalive cadence.
    # Subsequent checks are gated by ``watchdog_interval_seconds``.
    last_watchdog_check = float("-inf")
    # Synthetic terminal events emitted by the watchdog use the same
    # ``sequence_no=-1`` convention as the snapshot-failure path so the
    # frontend's strict ``\d+`` cursor regex rejects them as a
    # ``Last-Event-ID`` for any future reconnect. The chosen
    # discriminator ensures a manual page refresh after a watchdog-fired
    # error doesn't loop on the same synthetic id.
    watchdog_synthetic_seq = -1

    try:
        for payload in topic.subscribe(
            on_subscribe=_on_subscribe,
            poll_timeout=poll_timeout_seconds,
        ):
            # Flush snapshot exactly once after the SUBSCRIBE callback
            # has run and produced a buffer.
            if replay_done and replay_buffer:
                for line in replay_buffer:
                    yield line
                replay_buffer.clear()
                if terminal_in_snapshot:
                    # The original stream already finished; tailing
                    # would just emit keepalives forever and pin both a
                    # client reconnect promise and a server WSGI thread.
                    return

            if replay_failed:
                # Snapshot read failed (DB blip / transient timeout). Emit a
                # terminal ``error`` event and return — the client only
                # reconnects after the original stream has already moved on,
                # so without a snapshot there's nothing live left to tail and
                # holding the connection open would just emit keepalives
                # until the proxy idle-timeout fires. ``code`` preserves the
                # snapshot-vs-agent-loop distinction so a future client can
                # opt into a refetch instead of a hard failure.
                yield format_sse_event(
                    {
                        "type": "error",
                        "error": "Stream replay failed; please refresh to load the latest state.",
                        "code": "snapshot_failed",
                        "message_id": message_id,
                    },
                    sequence_no=-1,
                )
                return

            now = time.monotonic()
            if payload is None:
                # Idle tick — check both keepalive and watchdog. The
                # watchdog only kicks in once the snapshot half has been
                # flushed (``replay_done``) so we don't race the
                # snapshot read on the first iteration.
                if (
                    replay_done
                    and watchdog_interval_seconds >= 0
                    and now - last_watchdog_check >= watchdog_interval_seconds
                ):
                    last_watchdog_check = now
                    terminal_payload = _check_producer_liveness(
                        message_id, producer_idle_seconds
                    )
                    if terminal_payload is not None:
                        yield format_sse_event(
                            terminal_payload,
                            sequence_no=watchdog_synthetic_seq,
                        )
                        return
                if now - last_keepalive >= keepalive_seconds:
                    yield ": keepalive\n\n"
                    last_keepalive = now
                continue

            envelope = _decode_pubsub_message(payload)
            if envelope is None:
                continue
            seq = envelope.get("sequence_no")
            inner = envelope.get("payload")
            if (
                not isinstance(seq, int)
                or isinstance(seq, bool)
                or not isinstance(inner, dict)
            ):
                continue
            if max_replayed_seq is not None and seq <= max_replayed_seq:
                # Snapshot already covered this id — drop the duplicate.
                continue
            yield format_sse_event(inner, seq)
            # Advance the dedup floor on the live path too, so a stale
            # republish of an already-yielded seq (process restart, retry
            # tool, etc.) is dropped on a later iteration.
            max_replayed_seq = seq
            last_keepalive = now
            if _payload_is_terminal(inner, envelope.get("event_type")):
                # Live tail just delivered the terminal event — close
                # out the reconnect stream so the client's drain
                # promise resolves and the WSGI thread is freed.
                return

        # Subscribe exited without ever yielding (Redis unavailable,
        # ``pubsub.subscribe`` raised, or the inner loop died between
        # SUBSCRIBE-ack and the first poll). The snapshot half is in
        # Postgres and is still serviceable — read it directly so a
        # Redis-only outage doesn't cost the client their reconnect
        # backlog. Gate the read on ``replay_done`` rather than
        # ``subscribe_started``: if ``_on_subscribe`` already populated
        # the buffer, re-reading would append the same rows twice and
        # double the answer chunks on the client (the per-message
        # reconnect dispatcher does not dedup by ``id``).
        if not replay_done:
            _read_snapshot_into_buffer()
            replay_done = True
        for line in replay_buffer:
            yield line
        replay_buffer.clear()
        if replay_failed:
            # Mirror the live-tail branch: emit a terminal ``error`` so
            # the frontend's existing end/error handling drives the UI
            # to a failed state instead of relying on the proxy timeout.
            yield format_sse_event(
                {
                    "type": "error",
                    "error": "Stream replay failed; please refresh to load the latest state.",
                    "code": "snapshot_failed",
                    "message_id": message_id,
                },
                sequence_no=-1,
            )
            return
        # Same close-on-terminal contract as the live-tail branch.
        # Without it a Redis-down + already-completed-stream client
        # would also hang on a never-ending generator.
        if terminal_in_snapshot:
            return
    except GeneratorExit:
        # Client disconnect — let the underlying ``Topic.subscribe``
        # ``finally`` block tear down its pubsub cleanly.
        return


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
