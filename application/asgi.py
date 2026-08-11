"""ASGI entrypoint: Flask (WSGI) + FastMCP on the same process."""

from __future__ import annotations

from a2wsgi import WSGIMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from application.api.async_sse import async_sse_routes
from application.app import app as flask_app
from application.core.settings import settings
from application.mcp_server import mcp

_WSGI_THREADPOOL = int(settings.WSGI_THREADPOOL_WORKERS)

mcp_app = mcp.http_app(path="/")

asgi_app = Starlette(
    routes=[
        Mount("/mcp", app=mcp_app),
        # Native-async SSE readers intercept their exact paths before the
        # Flask catch-all, so a mostly-idle reconnect tail rides the event
        # loop instead of pinning a WSGI threadpool slot. Order matters:
        # Starlette matches routes top-to-bottom, so these must precede the
        # Mount("/") that hands everything else to Flask.
        *async_sse_routes,
        Mount("/", app=WSGIMiddleware(flask_app, workers=_WSGI_THREADPOOL)),
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
