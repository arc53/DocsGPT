"""ASGI entrypoint: Flask (WSGI) + FastMCP on the same process."""

from __future__ import annotations

from a2wsgi import WSGIMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

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


class _McpWithoutSlash:
    """Serve ``/mcp`` exactly as ``/mcp/``, without a redirect.

    ``Mount("/mcp")`` only matches ``/mcp/...``, so a bare ``/mcp`` would fall
    through to the web-UI catch-all. A redirect is no answer either: many HTTP
    clients replay a redirected POST as a GET. This rewrites the scope to what
    the mount would have produced for ``/mcp/`` and hands it to the same app.
    It is a class, not a function, so ``Route`` treats it as a raw ASGI app
    and passes every method through.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Forward the request to the FastMCP app as ``/mcp/``.

        Args:
            scope: The ASGI connection scope for ``/mcp``.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        root_path = scope.get("root_path", "")
        child_scope = {
            **scope,
            "path": scope["path"] + "/",
            "raw_path": (scope.get("raw_path") or scope["path"].encode()) + b"/",
            "app_root_path": scope.get("app_root_path", root_path),
            "root_path": root_path + "/mcp",
        }
        await mcp_app(child_scope, receive, send)


# The web UI, when the package ships one (docsgpt/static) and SERVE_UI is on:
# files are served directly, Flask's own path prefixes pass through, and any
# other GET renders index.html for the client-side router.
_backend = StaticUI.wrap(
    WSGIMiddleware(flask_app, workers=_WSGI_THREADPOOL), flask_app.url_map, enabled=settings.SERVE_UI
)

asgi_app = Starlette(
    routes=[
        # Exact /mcp first: Mount("/mcp") never matches the bare path, and the
        # Mount("/") catch-all below would otherwise take it.
        Route("/mcp", endpoint=_McpWithoutSlash()),
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
