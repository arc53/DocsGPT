"""GET /api/events — user-scoped Server-Sent Events endpoint.

Subscribe-then-snapshot pattern: subscribe to ``user:{user_id}``
pub/sub, snapshot the Redis Streams backlog past ``Last-Event-ID``
inside the SUBSCRIBE-ack callback, flush snapshot, then tail live
events (dedup'd by stream id). See ``docs/runbooks/sse-notifications.md``.

A native-async Starlette route mounted ahead of Flask in ``docsgpt/asgi.py``.
Every open browser tab holds this stream, so it runs on the event loop with
the async Redis client instead of pinning a WSGI threadpool slot per tab.
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import aclosing
from typing import AsyncIterator, Optional

import anyio
from redis.asyncio import Redis
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from docsgpt.api.asgi_auth import authenticate, bind_log_context, json_error
from docsgpt.api.asgi_stream import ClosingStreamingResponse
from docsgpt.cache import PUBSUB_SOCKET_TIMEOUT_SECONDS
from docsgpt.core.settings import settings
from docsgpt.core.shutdown import is_shutting_down
from docsgpt.events.keys import (
    replay_budget_key,
    stream_id_compare,
    stream_key,
    topic_name,
)
from docsgpt.streaming.async_broadcast_channel import AsyncTopic
from docsgpt.streaming.async_redis import get_async_redis_instance
from docsgpt.streaming.sse_leases import (
    StreamCapExceeded,
    acquire_stream_lease,
    hold_lease,
)

logger = logging.getLogger(__name__)

SUBSCRIBE_POLL_INTERVAL_SECONDS = 1.0

# Upper bound on the replay-budget check, so a stalled Redis connection fails
# open instead of holding the request.
_REDIS_OP_TIMEOUT_SECONDS = 5.0

# WHATWG SSE treats CRLF, CR, and LF equivalently as line terminators.
_SSE_LINE_SPLIT = re.compile(r"\r\n|\r|\n")

# Redis Streams ids are ``ms`` or ``ms-seq`` where both halves are decimal.
# Anything else is a corrupted client cookie / IndexedDB residue and must
# not be passed to XRANGE — Redis would reject it and our truncation gate
# would silently fail.
_STREAM_ID_RE = re.compile(r"^\d+(-\d+)?$")

_SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
    # Marks the response as served by the event loop. Purely diagnostic.
    "X-SSE-Transport": "async",
}

# Only emitted at most once per process so a misconfigured deployment
# doesn't drown the logs.
_local_user_warned = False


def _format_sse(data: str, *, event_id: Optional[str] = None) -> str:
    """Encode a payload as one SSE message terminated by a blank line.

    Splits on any line-terminator variant (``\\r\\n``, ``\\r``, ``\\n``)
    so a stray CR in upstream content can't smuggle a premature line
    boundary into the wire format.
    """
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    for line in _SSE_LINE_SPLIT.split(data):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _decode(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except Exception:
            return None
    return str(value)


async def _oldest_retained_id(redis_client: Redis, user_id: str) -> Optional[str]:
    """Return the id of the oldest entry still in the stream, or ``None``.

    Used to detect ``Last-Event-ID`` having slid off the back of the
    MAXLEN'd window.
    """
    try:
        info = await redis_client.xinfo_stream(stream_key(user_id))
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    # redis-py returns str-keyed dicts here; the bytes-key probe is
    # defence in depth in case ``decode_responses`` is ever flipped.
    first_entry = info.get("first-entry") or info.get(b"first-entry")
    if not first_entry:
        return None
    # XINFO STREAM returns first-entry as [id, [field, value, ...]]
    try:
        return _decode(first_entry[0])
    except Exception:
        return None


async def _allow_replay(
    redis_client: Optional[Redis], user_id: str, last_event_id: Optional[str]
) -> bool:
    """Per-user sliding-window snapshot-replay budget.

    Fails open on Redis errors, a stalled connection, or when the budget is
    disabled. No-cursor connects never consume budget: fresh sessions start
    live and do no snapshot work, so counting them only starved real
    reconnects (a burst of fresh tabs could 429 a user's cursor-bearing
    reconnect).
    """
    budget = int(settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW)
    if budget <= 0:
        return True
    if redis_client is None:
        return True
    if last_event_id is None:
        return True

    window = max(1, int(settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS))
    key = replay_budget_key(user_id)
    try:
        with anyio.fail_after(_REDIS_OP_TIMEOUT_SECONDS):
            used = int(await redis_client.incr(key))
            # Always (re)seed the TTL. Gating on ``used == 1`` would wedge
            # the counter forever if INCR succeeds but EXPIRE raises on
            # the seeding call. EXPIRE on an existing key resets the TTL
            # to ``window`` — within ±1s of the per-window budget semantic.
            await redis_client.expire(key, window)
    except Exception:
        logger.debug(
            "replay budget probe failed for user=%s; failing open",
            user_id,
        )
        return True
    return used <= budget


def _normalize_last_event_id(raw: Optional[str]) -> Optional[str]:
    """Validate the ``Last-Event-ID`` header / query param.

    Returns the value unchanged when it parses as a Redis Streams id,
    otherwise ``None`` — callers treat ``None`` as "client has nothing"
    and start the stream live (no snapshot). Invalid ids would
    otherwise pass straight to XRANGE and surface as a quiet replay
    failure plus broken truncation detection.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or not _STREAM_ID_RE.match(raw):
        return None
    return raw


def _replay_floor_id() -> Optional[str]:
    """Oldest stream id the snapshot replay may reach, or ``None``.

    Streams ids are millisecond timestamps, so an age ceiling maps
    directly to an id floor. MAXLEN caps the stream by count, not time —
    for a low-traffic user 1000 entries can span weeks, and shipping
    that on reconnect helps no one.
    """
    max_age_hours = int(settings.EVENTS_REPLAY_MAX_AGE_HOURS)
    if max_age_hours <= 0:
        return None
    floor_ms = int(time.time() * 1000) - max_age_hours * 3600 * 1000
    return f"{floor_ms}-0"


async def _replay_backlog(
    redis_client: Redis, user_id: str, last_event_id: Optional[str], max_count: int
) -> list[tuple[str, str]]:
    """Return ``(entry_id, sse_line)`` pairs for backlog entries past ``last_event_id``.

    Capped at ``max_count`` rows; clients catch up across reconnects.
    Parse failures are skipped; the Streams id is injected into the
    envelope so replay matches live-tail shape.
    """
    floor = _replay_floor_id()
    if last_event_id is None:
        start = floor or "-"
    elif floor and stream_id_compare(last_event_id, floor) < 0:
        # Cursor is past the age ceiling: clamp to the floor (inclusive).
        # The caller emits ``backlog.truncated`` for this case.
        start = floor
    else:
        # Exclusive start: '(<id>' skips the already-delivered entry.
        start = f"({last_event_id}"
    try:
        entries = await redis_client.xrange(
            stream_key(user_id), min=start, max="+", count=max_count
        )
    except Exception as exc:
        logger.warning(
            "xrange replay failed for user=%s last_id=%s err=%s",
            user_id,
            last_event_id or "-",
            exc,
        )
        return []

    lines: list[tuple[str, str]] = []
    for entry_id, fields in entries:
        entry_id_str = _decode(entry_id)
        if not entry_id_str:
            continue
        # decode_responses=False on the client ⇒ field keys/values are
        # bytes. The string-key fallback covers a future flip of that
        # default without a forced refactor here.
        raw_event = None
        if isinstance(fields, dict):
            raw_event = fields.get(b"event")
            if raw_event is None:
                raw_event = fields.get("event")
        event_str = _decode(raw_event)
        if not event_str:
            continue
        try:
            envelope = json.loads(event_str)
            if isinstance(envelope, dict):
                envelope["id"] = entry_id_str
                event_str = json.dumps(envelope)
        except Exception:
            logger.debug(
                "Replay envelope parse failed for entry %s; passing through raw",
                entry_id_str,
            )
        lines.append((entry_id_str, _format_sse(event_str, event_id=entry_id_str)))
    return lines


def _truncation_notice_line(oldest_id: str) -> str:
    """SSE event the frontend can react to with a full-state refetch."""
    return _format_sse(
        json.dumps(
            {
                "type": "backlog.truncated",
                "payload": {"oldest_retained_id": oldest_id},
            }
        )
    )


async def _event_stream(
    redis_client: Optional[Redis],
    user_id: str,
    last_event_id: Optional[str],
    last_event_id_invalid: bool,
    push_enabled: bool,
) -> AsyncIterator[str]:
    """Yield the prelude, the replayed backlog, then live events until the stream ends."""
    connect_ts = time.monotonic()
    replayed_count = 0
    keepalive_seconds = float(settings.SSE_KEEPALIVE_SECONDS)
    try:
        # First frame primes intermediaries (Cloudflare, nginx) so they
        # don't sit on a buffer waiting for body bytes.
        yield ": connected\n\n"

        if not push_enabled:
            yield ": push_disabled\n\n"
            return

        replay_lines: list[str] = []
        max_replayed_id: Optional[str] = None
        replay_done = False

        # If the client sent a malformed Last-Event-ID, surface the
        # truncation notice before the subscribe loop. Buffering it into
        # ``replay_lines`` would lose it when ``subscribe`` returns
        # immediately (Redis down) and the loop body never runs.
        if last_event_id_invalid:
            yield _truncation_notice_line("")
            replayed_count += 1

        async def _on_subscribe() -> None:
            # Runs inside AsyncTopic.subscribe after the SUBSCRIBE is
            # acked. Reading the backlog here means any publisher firing
            # between SUBSCRIBE-send and SUBSCRIBE-ack has its XADD captured
            # by XRANGE *and* its PUBLISH buffered at the connection layer
            # until we read it — closing the replay/subscribe race.
            #
            # Truncation contract: ``backlog.truncated`` is emitted ONLY
            # when the client's ``Last-Event-ID`` has slid off the MAXLEN'd
            # window or the age floor — the journal is genuinely gone past
            # the cursor, so the frontend should clear its cursor and
            # refetch state. Cap-hit skips silently: the cursor advances via
            # the per-entry ``id:`` headers. Budget exhaustion never reaches
            # this callback — the route 429s before opening the stream.
            nonlocal max_replayed_id, replay_done
            try:
                if redis_client is None or last_event_id is None:
                    # Fresh session: start live. Replaying the whole
                    # retained window shipped weeks-old entries on every
                    # tab-open (MAXLEN caps by count, not age).
                    return
                oldest = await _oldest_retained_id(redis_client, user_id)
                floor = _replay_floor_id()
                # The snapshot can't reach past whichever is newer: the
                # MAXLEN'd window edge or the age floor.
                effective_oldest = oldest
                if floor and (
                    effective_oldest is None
                    or stream_id_compare(floor, effective_oldest) > 0
                ):
                    effective_oldest = floor
                if (
                    effective_oldest
                    and stream_id_compare(last_event_id, effective_oldest) < 0
                ):
                    replay_lines.append(_truncation_notice_line(effective_oldest))
                replay_cap = int(settings.EVENTS_REPLAY_MAX_PER_REQUEST)
                for entry_id, sse_line in await _replay_backlog(
                    redis_client, user_id, last_event_id, replay_cap
                ):
                    replay_lines.append(sse_line)
                    max_replayed_id = entry_id
            finally:
                # Always flip the flag — even on partial-replay failure the
                # outer loop must reach the flush step so we don't silently
                # strand whatever entries did land.
                replay_done = True

        topic = AsyncTopic(topic_name(user_id))
        last_keepalive = time.monotonic()
        subscription = topic.subscribe(
            on_subscribe=_on_subscribe,
            poll_timeout=SUBSCRIBE_POLL_INTERVAL_SECONDS,
            liveness_timeout=PUBSUB_SOCKET_TIMEOUT_SECONDS,
        )
        async with aclosing(subscription):
            async for payload in subscription:
                if is_shutting_down():
                    break

                # Flush snapshot on the first iteration after the SUBSCRIBE
                # callback ran. This runs at most once per connection.
                if replay_done and replay_lines:
                    for line in replay_lines:
                        yield line
                        replayed_count += 1
                    replay_lines.clear()

                now = time.monotonic()
                if payload is None:
                    if now - last_keepalive >= keepalive_seconds:
                        yield ": keepalive\n\n"
                        last_keepalive = now
                    continue

                event_str = _decode(payload) or ""
                event_id: Optional[str] = None
                try:
                    envelope = json.loads(event_str)
                    if isinstance(envelope, dict):
                        candidate = envelope.get("id")
                        # Only trust ids that look like real Redis Streams
                        # ids. A malformed or adversarial publisher could
                        # otherwise pin dedupe forever — a lex-greater bogus
                        # id would make every later id compare ``<=``.
                        if isinstance(candidate, str) and _STREAM_ID_RE.match(candidate):
                            event_id = candidate
                except Exception:
                    pass

                # Dedupe: if this id was already covered by replay, drop it.
                if (
                    event_id is not None
                    and max_replayed_id is not None
                    and stream_id_compare(event_id, max_replayed_id) <= 0
                ):
                    continue

                yield _format_sse(event_str, event_id=event_id)
                last_keepalive = now

        # The subscription exited before the first yield (transient Redis
        # hiccup between SUBSCRIBE-ack and the first poll, or an immediate
        # Redis-down return). The callback may already have populated the
        # snapshot — flush it so the client gets the backlog.
        if replay_done and replay_lines:
            for line in replay_lines:
                yield line
                replayed_count += 1
            replay_lines.clear()
    except Exception:
        # Client disconnect (cancellation / GeneratorExit) is a BaseException
        # and passes straight through; only genuine bugs land here.
        logger.exception("SSE event-stream generator crashed for user=%s", user_id)
    finally:
        logger.info(
            "event.disconnect user=%s duration_s=%.1f replayed=%d",
            user_id,
            time.monotonic() - connect_ts,
            replayed_count,
        )


async def stream_events(request: Request) -> Response:
    """``GET /api/events`` — the caller's live notification stream."""
    decoded, error = await authenticate(request)
    if error is not None:
        return error
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return json_error("Authentication required", 401)
    bind_log_context("event_stream", user_id)

    # In dev deployments without AUTH_TYPE configured, every request
    # resolves to user_id="local" and shares one stream. Surface this so
    # an accidentally-multi-user dev box doesn't silently cross-stream.
    global _local_user_warned
    if user_id == "local" and not _local_user_warned:
        logger.warning(
            "SSE serving user_id='local' (AUTH_TYPE not set). "
            "All clients on this deployment will share one event stream."
        )
        _local_user_warned = True

    raw_last_event_id = request.headers.get("Last-Event-ID") or request.query_params.get(
        "last_event_id"
    )
    last_event_id = _normalize_last_event_id(raw_last_event_id)
    last_event_id_invalid = raw_last_event_id is not None and last_event_id is None

    push_enabled = settings.ENABLE_SSE_PUSH
    redis_client = await get_async_redis_instance() if push_enabled else None

    # Reserve a per-user connection slot before the response opens, so an
    # over-cap caller gets a clean 429 instead of a mid-stream cutoff.
    try:
        lease = await acquire_stream_lease(redis_client, user_id)
    except StreamCapExceeded:
        return json_error("Too many concurrent SSE connections", 429)

    # Replay budget is checked before the stream opens so a denial surfaces
    # as HTTP 429 instead of a silent snapshot skip: a live tail carrying
    # ``id:`` headers would advance the client's cursor past the entries it
    # never received. 429 keeps the cursor pinned and the frontend backs off.
    if redis_client is not None and not await _allow_replay(redis_client, user_id, last_event_id):
        if lease is not None:
            await lease.release()
        return json_error("Replay budget exhausted", 429)

    logger.info(
        "event.connect user=%s last_event_id=%s%s",
        user_id,
        last_event_id or "-",
        " (rejected_invalid)" if last_event_id_invalid else "",
    )
    stream = _event_stream(redis_client, user_id, last_event_id, last_event_id_invalid, push_enabled)
    return ClosingStreamingResponse(
        hold_lease(stream, lease),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
        # Released once the response is over, however it ended.
        on_close=lease.release if lease is not None else None,
    )


# Mounted in ``docsgpt/asgi.py`` ahead of the Flask catch-all.
event_stream_routes = [
    Route("/api/events", stream_events, methods=["GET"]),
]
