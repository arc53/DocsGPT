"""Native-async snapshot+tail iterator for chat-stream reconnect.

The sole reconnect reader: a ``: connected`` prelude, a snapshot flush
inside the SUBSCRIBE-ack callback, a dedup'd live tail, keepalive +
producer-liveness watchdog, and close-on-terminal — all as an async
generator driven off the event loop instead of a WSGI thread.

Wire format, dedup floor, and terminal detection come from
``event_replay`` (``read_snapshot_lines``, ``format_sse_event``,
``_decode_pubsub_message``, ``_payload_is_terminal``,
``_check_producer_liveness``), the same primitives the producer's journal
writes through — so the reader and writer cannot drift on wire shape. The
only sync I/O (snapshot read, watchdog DB probe) is pushed to a worker
thread via ``anyio.to_thread`` so it never blocks the loop.
"""

from __future__ import annotations

import logging
import time
from typing import AsyncIterator, Optional

import anyio

from application.streaming.async_broadcast_channel import AsyncTopic
from application.streaming.event_replay import (
    DEFAULT_KEEPALIVE_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_PRODUCER_IDLE_SECONDS,
    DEFAULT_WATCHDOG_INTERVAL_SECONDS,
    _check_producer_liveness,
    _decode_pubsub_message,
    _payload_is_terminal,
    format_sse_event,
    read_snapshot_lines,
)
from application.streaming.keys import message_topic_name

logger = logging.getLogger(__name__)

# The snapshot read and watchdog probe are the reader's only DB I/O; they run
# in worker threads and each borrows a connection from the app-wide SQLAlchemy
# pool (pool_size=10 + max_overflow=20 = 30). The reader scales to many
# concurrent event-loop streams, so without a bound a burst of aligned
# watchdog/snapshot ticks could exhaust the pool and starve every other route.
# Cap the reader's concurrent DB-thread usage well below the pool so it can
# never monopolise it; excess ticks queue briefly (watchdog cadence is 5s, so
# a short queue delay is harmless).
_MAX_CONCURRENT_DB_READS = 8
_db_read_limiter: Optional[anyio.CapacityLimiter] = None


def _get_db_read_limiter() -> anyio.CapacityLimiter:
    """Lazily build the shared limiter on the (single) event loop.

    Created on first use rather than at import so it binds to the running
    loop; creation is synchronous, so the single-worker loop has no race.
    """
    global _db_read_limiter
    if _db_read_limiter is None:
        _db_read_limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_DB_READS)
    return _db_read_limiter


async def build_message_event_stream_async(
    message_id: str,
    last_event_id: Optional[int] = None,
    *,
    user_id: Optional[str] = None,
    keepalive_seconds: float = DEFAULT_KEEPALIVE_SECONDS,
    poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
    watchdog_interval_seconds: float = DEFAULT_WATCHDOG_INTERVAL_SECONDS,
    producer_idle_seconds: float = DEFAULT_PRODUCER_IDLE_SECONDS,
) -> AsyncIterator[str]:
    """Yield SSE-formatted lines for one ``message_id`` reconnect stream.

    First frame is ``: connected``; subsequent frames are snapshot rows,
    live-tail events, or ``: keepalive`` comments. Runs until the client
    disconnects or a terminal event is delivered.
    """
    yield ": connected\n\n"

    replay_buffer: list[str] = []
    max_replayed_seq: Optional[int] = last_event_id
    replay_done = False
    replay_failed = False
    terminal_in_snapshot = False

    async def _load_snapshot() -> None:
        nonlocal max_replayed_seq, replay_failed, terminal_in_snapshot
        try:
            lines, max_seq, terminal = await anyio.to_thread.run_sync(
                read_snapshot_lines,
                message_id,
                last_event_id,
                user_id,
                limiter=_get_db_read_limiter(),
            )
        except Exception:
            logger.exception(
                "Snapshot read failed for message_id=%s last_event_id=%s",
                message_id,
                last_event_id,
            )
            replay_failed = True
            return
        replay_buffer.extend(lines)
        max_replayed_seq = max_seq
        terminal_in_snapshot = terminal

    async def _on_subscribe() -> None:
        # SUBSCRIBE acked — Postgres reads from this point capture every
        # committed row; pub/sub messages published after this are queued
        # at the connection level until the loop polls again.
        nonlocal replay_done
        try:
            await _load_snapshot()
        finally:
            replay_done = True

    topic = AsyncTopic(message_topic_name(message_id))
    last_keepalive = time.monotonic()
    last_watchdog_check = float("-inf")
    watchdog_synthetic_seq = -1

    try:
        async for payload in topic.subscribe(
            on_subscribe=_on_subscribe,
            poll_timeout=poll_timeout_seconds,
        ):
            # Flush snapshot exactly once after the SUBSCRIBE callback ran.
            if replay_done and replay_buffer:
                for line in replay_buffer:
                    yield line
                replay_buffer.clear()
                if terminal_in_snapshot:
                    # Original stream already finished; tailing would just
                    # emit keepalives forever.
                    return

            if replay_failed:
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
                # Idle tick — gate the watchdog on ``replay_done`` so we
                # don't race the snapshot read on the first iteration.
                if (
                    replay_done
                    and watchdog_interval_seconds >= 0
                    and now - last_watchdog_check >= watchdog_interval_seconds
                ):
                    last_watchdog_check = now
                    terminal_payload = await anyio.to_thread.run_sync(
                        _check_producer_liveness,
                        message_id,
                        user_id,
                        producer_idle_seconds,
                        limiter=_get_db_read_limiter(),
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
            max_replayed_seq = seq
            last_keepalive = now
            if _payload_is_terminal(inner, envelope.get("event_type")):
                return

        # Subscribe exited without yielding (Redis unavailable / subscribe
        # raised). The snapshot half is still in Postgres — read it
        # directly so a Redis-only outage doesn't cost the client their
        # backlog. Gate on ``replay_done`` so we don't double-read.
        if not replay_done:
            await _load_snapshot()
            replay_done = True
        for line in replay_buffer:
            yield line
        replay_buffer.clear()
        if replay_failed:
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
        if terminal_in_snapshot:
            return
    except Exception:
        # GeneratorExit / CancelledError are BaseException subclasses, so a
        # client disconnect bypasses this handler and propagates to close
        # the inner AsyncTopic generator (tearing its pubsub down in that
        # generator's finally). Only genuine bugs land here.
        logger.exception(
            "Async reconnect stream crashed for message_id=%s", message_id
        )
        return
