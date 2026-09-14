"""ASGI entrypoint: Flask (WSGI) + FastMCP on the same process."""

from __future__ import annotations

from a2wsgi import WSGIMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from docsgpt.api.async_sse import async_sse_routes
from docsgpt.api.devices.session_events import device_session_routes
from docsgpt.api.events.routes import event_stream_routes
from docsgpt.api.user.artifacts.download import artifact_download_routes
from docsgpt.app import app as flask_app
from docsgpt.core.settings import settings
from docsgpt.mcp_server import mcp
from docsgpt.ui import StaticUI

_WSGI_THREADPOOL = int(settings.WSGI_THREADPOOL_WORKERS)

mcp_app = mcp.http_app(path="/")

# The web UI, when the package ships one (docsgpt/static) and SERVE_UI is on:
# files are served directly, Flask's own path prefixes pass through, and any
# other GET renders index.html for the client-side router.
_backend = StaticUI.wrap(
    WSGIMiddleware(flask_app, workers=_WSGI_THREADPOOL), flask_app.url_map, enabled=settings.SERVE_UI
)

asgi_app = Starlette(
    routes=[
        Mount("/mcp", app=mcp_app),
        # Native-async routes intercept their exact paths before the Flask
        # catch-all. Each holds its response open for a long time (the chat
        # reconnect tail, the notification stream, a device's command stream,
        # large artifact downloads), so it rides the event loop instead of
        # pinning a WSGI threadpool slot. Order matters: Starlette matches
        # routes top-to-bottom, so these must precede the Mount("/") that
        # hands everything else to Flask.
        *async_sse_routes,
        *event_stream_routes,
        *device_session_routes,
        *artifact_download_routes,
        Mount("/", app=_backend),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Content-Type",
                "Authorization",
                "Mcp-Session-Id",
                "Idempotency-Key",
            ],
            expose_headers=["Mcp-Session-Id"],
        ),
    ],
    lifespan=mcp_app.lifespan,
)
