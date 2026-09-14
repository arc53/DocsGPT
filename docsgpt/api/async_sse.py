"""Native-async (ASGI) SSE reader routes, mounted ahead of the Flask app.

These Starlette routes serve the chat-stream *reconnect* path on the event
loop, so a long-lived, mostly-idle tail costs a coroutine instead of one of
the a2wsgi threadpool slots (see ``docsgpt/asgi.py``). They are the
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
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from docsgpt.api.asgi_auth import authenticate
from docsgpt.api.asgi_stream import ClosingStreamingResponse
from docsgpt.core.settings import settings
from docsgpt.storage.db.session import db_readonly
from docsgpt.streaming.async_event_replay import (
    build_message_event_stream_async,
)
from docsgpt.streaming.async_redis import get_async_redis_instance
from docsgpt.streaming.event_replay import (
    DEFAULT_KEEPALIVE_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
)
from docsgpt.streaming.sse_leases import (
    StreamCapExceeded,
    acquire_stream_lease,
    hold_lease,
)

logger = logging.getLogger(__name__)

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


async def stream_message_events(request: Request) -> Response:
    """GET /api/messages/{message_id}/events — async reconnect tail.

    Mirrors the Flask handler's gates (auth → id format → ownership →
    cursor → per-user connection cap) then streams snapshot+tail off the
    event loop.
    """
    # Same JWT decoder and OIDC revocation check as the Flask routes. With
    # AUTH_TYPE unset the caller resolves to ``{"sub": "local"}``.
    decoded, error = await authenticate(request)
    if error is not None:
        return error
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return _json("Authentication required", 401)

    message_id = request.path_params["message_id"]
    if not _MESSAGE_ID_RE.match(message_id):
        return _json("Invalid message id", 400)

    # Ownership check is a sync DB read — push it off the loop.
    owns = await anyio.to_thread.run_sync(_user_owns_message, message_id, user_id)
    if not owns:
        # Same opaque 404 as the Flask route — don't disclose existence.
        return _json("Not found", 404)

    # Per-user connection cap, shared with /api/events so it bounds a user's
    # total live SSE footprint. Reserved before the response opens so an
    # over-cap caller gets a clean 429 instead of a mid-stream cutoff.
    try:
        lease = await acquire_stream_lease(await get_async_redis_instance(), user_id)
    except StreamCapExceeded:
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
    return ClosingStreamingResponse(
        hold_lease(stream, lease),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
        # Released once the response is over, however it ended.
        on_close=lease.release if lease is not None else None,
    )


# Mounted in ``docsgpt/asgi.py`` ahead of the Flask catch-all. Keep
# each route's path identical to the Flask blueprint it shadows.
async_sse_routes = [
    Route(
        "/api/messages/{message_id}/events",
        stream_message_events,
        methods=["GET"],
    ),
]
