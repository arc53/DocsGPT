"""ASGI entrypoint: Flask (WSGI) + FastMCP on the same process."""

from __future__ import annotations

from a2wsgi import WSGIMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from application.app import app as flask_app
from application.mcp_server import mcp

_WSGI_THREADPOOL = 32

mcp_app = mcp.http_app(path="/")

asgi_app = Starlette(
    routes=[
        Mount("/mcp", app=mcp_app),
        Mount("/", app=WSGIMiddleware(flask_app, workers=_WSGI_THREADPOOL)),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "Mcp-Session-Id"],
            expose_headers=["Mcp-Session-Id"],
        ),
    ],
    lifespan=mcp_app.lifespan,
)
