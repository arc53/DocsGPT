"""GET /api/events — user-scoped Server-Sent Events endpoint.

Per-connection flow:

1. Authenticate via the ``decoded_token`` Flask before-request middleware.
2. Read the optional ``Last-Event-ID`` header (or ``last_event_id`` query).
3. Subscribe to ``user:{user_id}`` pub/sub. Inside the SUBSCRIBE-ack
   callback, snapshot the durable backlog from
   ``XRANGE user:{user_id}:stream (last_event_id +``. This ordering is
   the central correctness invariant: any publisher firing between the
   moment we issue SUBSCRIBE and the moment we finish XRANGE has its
   pub/sub message buffered at the connection layer until we read it,
   and its stream entry captured by XRANGE — so neither path drops it.
4. Flush the snapshot to the client first.
5. Tail live pub/sub, deduplicating any message whose stream id is
   ``<= max_replayed_id`` (covered by snapshot already).
6. Emit an SSE keepalive comment every ``SSE_KEEPALIVE_SECONDS`` to
   defeat reverse-proxy and mobile-network idle closes.

A separate ``XINFO STREAM`` check at connect time catches the
``Last-Event-ID`` sat older than the oldest retained entry case (i.e.
the backlog window has slid past the client) — we surface a
``backlog.truncated`` event so the frontend can do a full state
refetch instead of silently missing data.

Concurrency: a per-user Redis counter caps simultaneous SSE connections
so one runaway tab can't starve the WSGI thread pool. The counter is
INCR'd at connect, DECR'd in the generator's ``finally``, with a TTL as
a belt-and-suspenders against orphaned counts after a hard crash.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Iterator, Optional

from flask import Blueprint, Response, jsonify, make_response, request, stream_with_context

from application.cache import get_redis_instance
from application.core.settings import settings
from application.events.keys import (
    connection_counter_key,
    replay_budget_key,
    stream_id_compare,
    stream_key,
    topic_name,
)
from application.streaming.broadcast_channel import Topic

logger = logging.getLogger(__name__)

events = Blueprint("event_stream", __name__)

SUBSCRIBE_POLL_INTERVAL_SECONDS = 1.0

# WHATWG SSE treats CRLF, CR, and LF equivalently as line terminators.
_SSE_LINE_SPLIT = re.compile(r"\r\n|\r|\n")

# Redis Streams ids are ``ms`` or ``ms-seq`` where both halves are decimal.
# Anything else is a corrupted client cookie / IndexedDB residue and must
# not be passed to XRANGE — Redis would reject it and our truncation gate
# would silently fail.
_STREAM_ID_RE = re.compile(r"^\d+(-\d+)?$")

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


def _oldest_retained_id(redis_client, user_id: str) -> Optional[str]:
    """Return the id of the oldest entry still in the stream, or ``None``.

    Used to detect ``Last-Event-ID`` having slid off the back of the
    MAXLEN'd window.
    """
    try:
        info = redis_client.xinfo_stream(stream_key(user_id))
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    # redis-py 7.4 returns str-keyed dicts here; the bytes-key probe is
    # defence in depth in case ``decode_responses`` is ever flipped.
    first_entry = info.get("first-entry") or info.get(b"first-entry")
    if not first_entry:
        return None
    # XINFO STREAM returns first-entry as [id, [field, value, ...]]
    try:
        return _decode(first_entry[0])
    except Exception:
        return None


def _allow_replay(
    redis_client, user_id: str, last_event_id: Optional[str]
) -> bool:
    """Per-user sliding-window snapshot-replay budget.

    Increments a Redis counter under
    ``user:{user_id}:replay_count`` with a TTL equal to the window
    size; returns ``False`` once the count exceeds the budget. When
    Redis is unavailable, fails open — the existing per-user
    concurrency cap still bounds parallel enumeration. Returns
    ``True`` when the budget setting is 0 (disabled) or non-positive.

    Budget is only consumed when the connect can plausibly do snapshot
    work. A fresh client (``last_event_id is None``) connecting to an
    empty backlog (``XLEN == 0``) returns ``True`` without INCR'ing —
    this catches the React-StrictMode dev-burst case where double
    mounts of an empty-backlog user would otherwise trip 429 in 5
    seconds and lock out further connects until the window rolls.
    """
    budget = int(settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW)
    if budget <= 0:
        return True
    if redis_client is None:
        return True

    # Cheap pre-check: only INCR when we might actually replay. XLEN
    # is one Redis op; the alternative (INCR every connect) is two
    # ops AND wrongly counts no-op probes. The check is conservative:
    # if ``last_event_id`` is set we always INCR, even if the cursor
    # has already overtaken the latest entry — that case is rare and
    # short-lived, and probing further would mean a redundant XRANGE.
    if last_event_id is None:
        try:
            if int(redis_client.xlen(stream_key(user_id))) == 0:
                return True
        except Exception:
            # XLEN probe failed; fall through to the INCR path so a
            # transient Redis hiccup can't bypass the budget.
            logger.debug(
                "XLEN probe failed for replay budget check user=%s; "
                "proceeding to INCR",
                user_id,
            )

    window = max(1, int(settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS))
    key = replay_budget_key(user_id)
    try:
        used = int(redis_client.incr(key))
        # First increment in this window seeds the TTL. Subsequent
        # increments leave the TTL alone so the window slides
        # naturally rather than reset on every replay.
        if used == 1:
            redis_client.expire(key, window)
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
    and replay from the start of the retained window. Invalid ids would
    otherwise pass straight to XRANGE and surface as a quiet replay
    failure plus broken truncation detection.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or not _STREAM_ID_RE.match(raw):
        return None
    return raw


def _replay_backlog(
    redis_client, user_id: str, last_event_id: Optional[str], max_count: int
) -> Iterator[tuple[str, str]]:
    """Yield ``(entry_id, sse_line)`` for backlog entries past ``last_event_id``.

    Caps the result at ``max_count`` rows so a single request can't
    move the entire MAXLEN'd backlog over the wire. A client that
    falls behind by more than ``max_count`` entries catches up over
    several reconnects: each delivered entry carries an ``id:``
    header that advances the frontend's ``lastEventId``, so the next
    reconnect sends ``last_event_id=<max_replayed>`` and resumes
    naturally. The route deliberately does NOT emit a synthetic
    ``backlog.truncated`` on cap-hit (which would clear the slice
    cursor and re-trip the same oldest-N replay forever).

    Entries with parse failures are skipped rather than aborting replay.
    The stored envelope is missing ``id`` (the Streams id is only known
    after XADD); we inject it here so replay and live tail produce
    structurally identical envelopes.
    """
    # Exclusive start: '(<id>' skips the already-delivered entry.
    start = f"({last_event_id}" if last_event_id else "-"
    try:
        entries = redis_client.xrange(
            stream_key(user_id), min=start, max="+", count=max_count
        )
    except Exception as exc:
        logger.warning(
            "xrange replay failed for user=%s last_id=%s err=%s",
            user_id,
            last_event_id or "-",
            exc,
        )
        return

    for entry_id, fields in entries:
        entry_id_str = _decode(entry_id)
        if not entry_id_str:
            continue
        # decode_responses=False on the cache client ⇒ field keys/values
        # are bytes. The string-key fallback covers a future flip of that
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
        yield entry_id_str, _format_sse(event_str, event_id=entry_id_str)


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


@events.route("/api/events", methods=["GET"])
def stream_events() -> Response:
    decoded = getattr(request, "decoded_token", None)
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return make_response(
            jsonify({"success": False, "message": "Authentication required"}),
            401,
        )

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

    raw_last_event_id = request.headers.get("Last-Event-ID") or request.args.get(
        "last_event_id"
    )
    last_event_id = _normalize_last_event_id(raw_last_event_id)
    last_event_id_invalid = raw_last_event_id is not None and last_event_id is None

    keepalive_seconds = float(settings.SSE_KEEPALIVE_SECONDS)
    push_enabled = settings.ENABLE_SSE_PUSH
    cap = int(settings.SSE_MAX_CONCURRENT_PER_USER)

    redis_client = get_redis_instance()
    counter_key = connection_counter_key(user_id)
    counted = False

    if push_enabled and redis_client is not None and cap > 0:
        try:
            current = int(redis_client.incr(counter_key))
            counted = True
        except Exception:
            current = 0
            logger.debug(
                "SSE connection counter INCR failed for user=%s", user_id
            )
        if counted:
            # 1h safety TTL — orphaned counts from hard crashes self-heal.
            # EXPIRE failure must NOT clobber ``current`` and bypass the cap.
            try:
                redis_client.expire(counter_key, 3600)
            except Exception:
                logger.debug(
                    "SSE connection counter EXPIRE failed for user=%s", user_id
                )
            if current > cap:
                try:
                    redis_client.decr(counter_key)
                except Exception:
                    logger.debug(
                        "SSE connection counter DECR failed for user=%s",
                        user_id,
                    )
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Too many concurrent SSE connections",
                        }
                    ),
                    429,
                )

    # Replay budget is checked here, before the generator opens the
    # stream, so a denial can surface as HTTP 429 instead of a silent
    # snapshot skip. The earlier in-generator skip lost events between
    # the client's cursor and the first live-tailed entry: the live
    # tail still carried ``id:`` headers, the frontend advanced
    # ``lastEventId`` to one of those ids, and the events in between
    # were never reachable on the next reconnect. 429 keeps the
    # cursor pinned and lets the frontend back off until the window
    # slides (eventStreamClient.ts treats 429 as escalated backoff).
    if push_enabled and redis_client is not None and not _allow_replay(
        redis_client, user_id, last_event_id
    ):
        if counted:
            try:
                redis_client.decr(counter_key)
            except Exception:
                logger.debug(
                    "SSE connection counter DECR failed for user=%s",
                    user_id,
                )
        return make_response(
            jsonify(
                {
                    "success": False,
                    "message": "Replay budget exhausted",
                }
            ),
            429,
        )

    @stream_with_context
    def generate() -> Iterator[str]:
        connect_ts = time.monotonic()
        replayed_count = 0
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
            # truncation notice synchronously *before* the subscribe
            # loop. Buffering it into ``replay_lines`` would lose it
            # when ``Topic.subscribe`` returns immediately (Redis down)
            # — the loop body never runs, and the flush at line ~335
            # never fires.
            if last_event_id_invalid:
                yield _truncation_notice_line("")
                replayed_count += 1

            def _on_subscribe_callback() -> None:
                # Runs synchronously inside Topic.subscribe after the
                # SUBSCRIBE is acked. By doing XRANGE here, any publisher
                # firing between SUBSCRIBE-send and SUBSCRIBE-ack has its
                # XADD captured by XRANGE *and* its PUBLISH buffered at
                # the connection layer until we read it — closing the
                # replay/subscribe race the design doc warns about.
                #
                # Truncation contract: ``backlog.truncated`` is emitted
                # ONLY when the client's ``Last-Event-ID`` has slid off
                # the MAXLEN'd window — that's the case where the
                # journal is genuinely gone past the cursor and the
                # frontend should clear its slice cursor and refetch
                # state. Cap-hit skips the snapshot silently: the
                # cursor advances via the per-entry ``id:`` headers
                # and the frontend's slice keeps the latest id so the
                # next reconnect resumes from there. Budget-exhausted
                # never reaches this callback — the route 429s before
                # opening the stream, keeping the cursor pinned.
                # Conflating these with stale-cursor truncation would
                # tell the client to clear its cursor and re-receive
                # the same oldest-N entries on every reconnect —
                # locking the user out of entries past N.
                nonlocal max_replayed_id, replay_done
                try:
                    if redis_client is None:
                        return
                    oldest = _oldest_retained_id(redis_client, user_id)
                    if (
                        last_event_id
                        and oldest
                        and stream_id_compare(last_event_id, oldest) < 0
                    ):
                        # The Last-Event-ID has slid off the MAXLEN window.
                        # Tell the client so it can fetch full state.
                        replay_lines.append(_truncation_notice_line(oldest))
                    replay_cap = int(settings.EVENTS_REPLAY_MAX_PER_REQUEST)
                    for entry_id, sse_line in _replay_backlog(
                        redis_client, user_id, last_event_id, replay_cap
                    ):
                        replay_lines.append(sse_line)
                        max_replayed_id = entry_id
                finally:
                    # Always flip the flag — even on partial-replay failure
                    # the outer loop must reach the flush step so we don't
                    # silently strand whatever entries did land.
                    replay_done = True

            topic = Topic(topic_name(user_id))
            last_keepalive = time.monotonic()
            for payload in topic.subscribe(
                on_subscribe=_on_subscribe_callback,
                poll_timeout=SUBSCRIBE_POLL_INTERVAL_SECONDS,
            ):
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
                        # ids (``ms`` or ``ms-seq``). A malformed or
                        # adversarial publisher could otherwise pin
                        # dedupe forever — a lex-greater bogus id would
                        # make every legitimate later id compare ``<=``
                        # and get dropped silently.
                        if isinstance(candidate, str) and _STREAM_ID_RE.match(
                            candidate
                        ):
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

            # Topic.subscribe exited before the first yield (transient
            # Redis hiccup between SUBSCRIBE-ack and the first poll, or
            # an immediate Redis-down return). The callback may already
            # have populated the snapshot — flush it so the client gets
            # the backlog instead of a silent drop. Safe no-op when the
            # in-loop flush ran (it clear()'d the buffer) and when the
            # callback never fired (replay_done stays False).
            if replay_done and replay_lines:
                for line in replay_lines:
                    yield line
                    replayed_count += 1
                replay_lines.clear()
        except GeneratorExit:
            return
        except Exception:
            logger.exception(
                "SSE event-stream generator crashed for user=%s", user_id
            )
        finally:
            duration_s = time.monotonic() - connect_ts
            logger.info(
                "event.disconnect user=%s duration_s=%.1f replayed=%d",
                user_id,
                duration_s,
                replayed_count,
            )
            if counted and redis_client is not None:
                try:
                    redis_client.decr(counter_key)
                except Exception:
                    logger.debug(
                        "SSE connection counter DECR failed for user=%s on disconnect",
                        user_id,
                    )

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    logger.info(
        "event.connect user=%s last_event_id=%s%s",
        user_id,
        last_event_id or "-",
        " (rejected_invalid)" if last_event_id_invalid else "",
    )
    return response
