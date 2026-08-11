"""Native-async (ASGI) SSE reader routes, mounted ahead of the Flask app.

These Starlette routes serve the chat-stream *reconnect* path on the event
loop, so a long-lived, mostly-idle tail costs a coroutine instead of one of
the 32 a2wsgi threadpool slots (see ``application/asgi.py``). They are the
sole reconnect reader — the old Flask blueprint has been removed. The heavy
*producer* (``POST /api/answer/stream`` → agent → LLM) stays on the sync
path untouched.

Auth, message-id validation, ``Last-Event-ID`` parsing and ownership are
done here; the snapshot/tail wire format is shared with the producer's
journal via ``build_message_event_stream_async`` → ``format_sse_event``.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import anyio
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from application.api.oidc.denylist import is_denied as oidc_session_denied
from application.auth import handle_auth
from application.core.settings import settings
from application.events.keys import connection_counter_key
from application.storage.db.session import db_readonly
from application.streaming.async_event_replay import (
    build_message_event_stream_async,
)
from application.streaming.async_redis import get_async_redis_instance
from application.streaming.event_replay import (
    DEFAULT_KEEPALIVE_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

# Per-user concurrent-connection counter TTL (seconds) — orphaned counts
# from a hard crash self-heal after this window, mirroring the /api/events
# notification stream. The reconnect reader shares the same counter key, so
# the cap bounds a user's *total* live SSE footprint.
_COUNTER_TTL_SECONDS = 3600

# A message_id is the canonical UUID hex format. Reject anything else before
# the SQL layer so a malformed cookie can't surface as a 500.
_MESSAGE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# ``sequence_no`` is a non-negative decimal integer. Anything else is corrupt
# client state — fall through to a fresh-replay cursor.
_SEQUENCE_NO_RE = re.compile(r"^\d+$")


def _normalise_last_event_id(raw: Optional[str]) -> Optional[int]:
    """Parse a ``Last-Event-ID`` cursor; ``None`` for missing/invalid."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or not _SEQUENCE_NO_RE.match(raw):
        return None
    return int(raw)


def _user_owns_message(message_id: str, user_id: str) -> bool:
    """Return True iff ``message_id`` belongs to ``user_id``."""
    try:
        with db_readonly() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT 1 FROM conversation_messages
                    WHERE id = CAST(:id AS uuid)
                      AND user_id = :u
                    LIMIT 1
                    """
                ),
                {"id": message_id, "u": user_id},
            ).first()
        return row is not None
    except Exception:
        logger.exception(
            "Ownership lookup failed for message_id=%s user_id=%s",
            message_id,
            user_id,
        )
        return False

_SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
    # Marks the response as served by the event-loop reader rather than the
    # WSGI-threaded Flask fallback. Purely diagnostic — the frontend reads
    # the body via fetch+getReader and ignores response headers.
    "X-SSE-Transport": "async",
}


def _json(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"success": False, "message": message}, status_code=status_code
    )


async def _acquire_stream_slot(user_id: str):
    """Reserve a per-user connection slot; returns ``(redis, key)`` to release.

    Mirrors the ``/api/events`` cap (INCR + safety TTL, reject when the
    post-increment count exceeds ``SSE_MAX_CONCURRENT_PER_USER``). Returns
    ``(None, None)`` when the cap is disabled or Redis is unavailable
    (fail-open, like the notification stream). Raises ``_CapExceeded`` when
    the user is over the cap so the caller can 429.
    """
    cap = int(getattr(settings, "SSE_MAX_CONCURRENT_PER_USER", 0))
    if cap <= 0:
        return None, None
    redis = await get_async_redis_instance()
    if redis is None:
        return None, None
    key = connection_counter_key(user_id)
    try:
        current = int(await redis.incr(key))
    except Exception:
        logger.debug("async SSE counter INCR failed for user=%s", user_id)
        return None, None
    # EXPIRE failure must not bypass the cap, so it's best-effort after INCR.
    try:
        await redis.expire(key, _COUNTER_TTL_SECONDS)
    except Exception:
        logger.debug("async SSE counter EXPIRE failed for user=%s", user_id)
    if current > cap:
        await _release_stream_slot(redis, key)
        raise _CapExceeded()
    return redis, key


async def _release_stream_slot(redis, key) -> None:
    if redis is None or key is None:
        return
    try:
        await redis.decr(key)
    except Exception:
        logger.debug("async SSE counter DECR failed for key=%s", key)


class _CapExceeded(Exception):
    """Raised when a user is over their concurrent-stream cap."""


async def _counted_stream(inner, redis, key):
    """Wrap the reader so the per-user slot is released when it ends.

    The slot is reserved before the response starts (so over-cap surfaces as
    HTTP 429, not mid-stream); the release runs in ``finally`` on terminal
    close, client disconnect, or error. Shielded so a disconnect-cancellation
    can't skip the DECR and leak the count.
    """
    try:
        async for line in inner:
            yield line
    finally:
        with anyio.CancelScope(shield=True):
            await _release_stream_slot(redis, key)


async def stream_message_events(request: Request) -> JSONResponse | StreamingResponse:
    """GET /api/messages/{message_id}/events — async reconnect tail.

    Mirrors the Flask handler's gates (auth → id format → ownership →
    cursor → per-user connection cap) then streams snapshot+tail off the
    event loop.
    """
    # ``handle_auth`` only reads ``request.headers.get("Authorization")``;
    # Starlette's headers are case-insensitive, so the Flask helper works
    # verbatim. With AUTH_TYPE unset it returns ``{"sub": "local"}``.
    decoded = handle_auth(request)
    if isinstance(decoded, dict) and "error" in decoded:
        return _json("Authentication error: invalid token", 401)
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return _json("Authentication required", 401)
    if settings.AUTH_TYPE == "oidc" and await anyio.to_thread.run_sync(
        oidc_session_denied, decoded
    ):
        return _json("Authentication error: session revoked", 401)

    message_id = request.path_params["message_id"]
    if not _MESSAGE_ID_RE.match(message_id):
        return _json("Invalid message id", 400)

    # Ownership check is a sync DB read — push it off the loop.
    owns = await anyio.to_thread.run_sync(_user_owns_message, message_id, user_id)
    if not owns:
        # Same opaque 404 as the Flask route — don't disclose existence.
        return _json("Not found", 404)

    # Per-user concurrent-connection cap — reserve before the response opens
    # so an over-cap caller gets a clean 429 instead of a mid-stream cutoff.
    try:
        redis, counter_key = await _acquire_stream_slot(user_id)
    except _CapExceeded:
        logger.warning("sse.reconnect.rejected user_id=%s (over cap)", user_id)
        return _json("Too many concurrent SSE connections", 429)

    raw_cursor = request.headers.get("Last-Event-ID") or request.query_params.get(
        "last_event_id"
    )
    last_event_id = _normalise_last_event_id(raw_cursor)
    keepalive_seconds = float(
        getattr(settings, "SSE_KEEPALIVE_SECONDS", DEFAULT_KEEPALIVE_SECONDS)
    )

    logger.info(
        "message.event.connect.async message_id=%s user_id=%s last_event_id=%s",
        message_id,
        user_id,
        last_event_id if last_event_id is not None else "-",
    )

    stream = build_message_event_stream_async(
        message_id,
        last_event_id=last_event_id,
        user_id=user_id,
        keepalive_seconds=keepalive_seconds,
        poll_timeout_seconds=DEFAULT_POLL_TIMEOUT_SECONDS,
    )
    return StreamingResponse(
        _counted_stream(stream, redis, counter_key),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# Mounted in ``application/asgi.py`` ahead of the Flask catch-all. Keep
# each route's path identical to the Flask blueprint it shadows.
async_sse_routes = [
    Route(
        "/api/messages/{message_id}/events",
        stream_message_events,
        methods=["GET"],
    ),
]
