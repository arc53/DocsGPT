"""``GET /api/devices/sessions/{session_id}/events`` — a paired device's command stream.

A native-async Starlette route mounted ahead of Flask in ``docsgpt/asgi.py``.
The CLI holds this stream open while it waits for commands, so it runs on the
event loop: the token check and ticket claim run in worker threads, then
commands arrive through the broker's async ``BLPOP`` and an idle session holds
no thread.
"""

from __future__ import annotations

import json
import logging
import time
from functools import partial
from typing import AsyncIterator, Optional

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from docsgpt.api.asgi_auth import bind_log_context
from docsgpt.api.asgi_stream import ClosingStreamingResponse
from docsgpt.api.devices.auth import authenticate_device
from docsgpt.core import log_context
from docsgpt.core.settings import settings
from docsgpt.core.shutdown import is_shutting_down
from docsgpt.devices.broker import DeviceBroker, SessionState, get_broker

logger = logging.getLogger(__name__)

# Upper bound on one broker poll, so a closed session, idle expiry or a
# server drain is noticed within this many seconds.
_POLL_TIMEOUT_SECONDS = 1.0

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _error(code: str, status_code: int) -> JSONResponse:
    """Return the ``{"success": false, "error": code}`` body the Flask device routes use."""
    return JSONResponse({"success": False, "error": code}, status_code=status_code)


def _sse_event(name: str, payload: dict, event_id: int) -> str:
    """Encode one SSE record with an event name, an id and a JSON data line."""
    return (
        f"event: {name}\n"
        f"id: {event_id}\n"
        f"data: {json.dumps(payload)}\n\n"
    )


def _signed_path(request: Request) -> str:
    """Return the path without the mount prefix, as the Flask device routes see it in ``PATH_INFO``."""
    path = request.scope["path"]
    root = request.scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root):]
    return path


def _claim_session(broker: DeviceBroker, device: dict, session_id: str) -> Optional[SessionState]:
    """Open the device's session iff ``session_id`` is its unexpired ticket; runs in a worker thread."""
    if not broker.validate_ticket(device["id"], session_id):
        return None
    return broker.register_session(device["id"], device["user_id"])


async def _close_session(broker: DeviceBroker, session_id: str) -> None:
    """Close the session once its response is over."""
    broker.close_session(session_id, reason="stream_end")


async def _session_stream(broker: DeviceBroker, sess: SessionState) -> AsyncIterator[str]:
    """Deliver queued commands until the session closes, idles out, or the server drains."""
    keepalive_interval = float(settings.SSE_KEEPALIVE_SECONDS)
    idle_seconds = float(settings.REMOTE_DEVICE_SESSION_IDLE_SECONDS)
    last_keepalive = time.time()
    # ``closed`` is set when the CLI reconnects and a newer session
    # replaces this one.
    while not sess.closed.is_set():
        # Break promptly on shutdown (see docsgpt/core/shutdown.py).
        if is_shutting_down():
            break
        if time.time() - sess.last_activity_at > idle_seconds:
            yield _sse_event(
                "session_end",
                {"reason": "inactivity_timeout"},
                sess.last_event_id + 1,
            )
            sess.last_event_id += 1
            broker.close_session(sess.session_id, reason="idle")
            return
        envelope = await broker.next_command_async(sess, timeout=_POLL_TIMEOUT_SECONDS)
        if envelope is None:
            if time.time() - last_keepalive >= keepalive_interval:
                last_keepalive = time.time()
                yield ": heartbeat\n\n"
            continue
        sess.last_event_id += 1
        sess.last_activity_at = time.time()
        yield _sse_event("invocation", envelope, sess.last_event_id)
        last_keepalive = time.time()


async def device_session_events(request: Request) -> Response:
    """Stream queued invocations to the device holding the poll-issued ticket.

    The ``session_id`` must be the ``session_ticket`` the device's own
    ``/poll`` just issued (the path it was handed as ``session_url``). A
    stale, mismatched, or fabricated ticket is rejected with ``410 Gone``
    before any stream is opened.
    """
    session_id = request.path_params["session_id"]
    bind_log_context("devices.session_events")
    device, failure = await anyio.to_thread.run_sync(
        partial(
            authenticate_device,
            request.headers,
            request.method,
            _signed_path(request),
            # Read only when a signature is checked, after the token is known
            # good, so an unauthenticated body is never buffered.
            lambda: anyio.from_thread.run(request.body),
        )
    )
    if failure is not None:
        return _error(*failure)
    log_context.bind(user_id=device["user_id"])
    broker = get_broker()
    # Claiming consumes the ticket, so it happens before the response opens and
    # ``on_close`` closes the session even if the body never starts. Shielded
    # so a cancellation can't leave a registered session with no response.
    with anyio.CancelScope(shield=True):
        sess = await anyio.to_thread.run_sync(_claim_session, broker, device, session_id)
    if sess is None:
        return _error("session_ticket_invalid", 410)
    return ClosingStreamingResponse(
        _session_stream(broker, sess),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
        on_close=partial(_close_session, broker, sess.session_id),
    )


# Mounted in ``docsgpt/asgi.py`` ahead of the Flask catch-all. The device's
# poll, ack and output endpoints stay on Flask (``session.py``).
device_session_routes = [
    Route(
        "/api/devices/sessions/{session_id}/events",
        device_session_events,
        methods=["GET"],
    ),
]
