"""Minimal ASGI app for the worker graceful-shutdown drain e2e.

Mirrors production (a Flask SSE generator behind a2wsgi's thread pool) without
Postgres/Redis. ``/sse`` holds the connection open like an idle subscriber;
``DRAIN_HARNESS_COOPERATIVE=1`` makes it poll the real
``application.core.shutdown.is_shutting_down`` flag (the fix), else it
reproduces the pre-fix hang.
"""

from __future__ import annotations

import os
import time

from a2wsgi import WSGIMiddleware
from flask import Flask, Response
from starlette.applications import Starlette
from starlette.routing import Mount

from application.core.shutdown import is_shutting_down

_COOPERATIVE = os.environ.get("DRAIN_HARNESS_COOPERATIVE") == "1"
_POLL_SECONDS = 1.0
_MAX_HOLD_SECONDS = 120.0

flask_app = Flask(__name__)


@flask_app.get("/health")
def health() -> Response:
    return Response('{"ok": true}', mimetype="application/json")


@flask_app.get("/sse")
def sse() -> Response:
    def generate():
        # Emit headers immediately (like the real ": connected" frame) so the
        # client establishes the stream, then hold without writing further.
        yield ": connected\n\n"
        deadline = time.monotonic() + _MAX_HOLD_SECONDS
        while time.monotonic() < deadline:
            # Cooperative variant bails on the flag; non-cooperative pins the
            # a2wsgi thread to the deadline (the pre-fix hang).
            if _COOPERATIVE and is_shutting_down():
                break
            time.sleep(_POLL_SECONDS)

    return Response(generate(), mimetype="text/event-stream")


asgi_app = Starlette(routes=[Mount("/", app=WSGIMiddleware(flask_app, workers=8))])
