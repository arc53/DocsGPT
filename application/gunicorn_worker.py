"""Gunicorn worker that bounds uvicorn's graceful-shutdown drain.

``uvicorn_worker`` doesn't forward gunicorn's ``--graceful-timeout`` to uvicorn's
``timeout_graceful_shutdown``, so after a ``max_requests`` recycle the drain is
unbounded: a held-open SSE/long-poll connection (a Flask/WSGI generator in
a2wsgi's thread pool, which asyncio can't cancel) hangs the worker until the
``--timeout`` watchdog SIGKILLs it (mislabeled "Perhaps out of memory?").

This worker bounds the drain (``timeout_graceful_shutdown`` from settings) and
raises the shutdown flag at drain start — including the signal-less
``max_requests`` path — so generators stop within one poll tick. Wire in via
``-k application.gunicorn_worker.BoundedDrainUvicornWorker``.
"""

from __future__ import annotations

import socket
import sys
from typing import Any

from gunicorn.arbiter import Arbiter
from uvicorn.server import Server
from uvicorn_worker import UvicornWorker

from application.core.settings import settings
from application.core.shutdown import begin_shutdown


class _ShutdownAwareServer(Server):
    """uvicorn ``Server`` that raises the shutdown flag when a drain starts.

    ``serve()`` always calls ``shutdown()`` when its loop exits — including the
    signal-less ``max_requests`` recycle — so this is the reliable hook point.
    """

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        begin_shutdown()
        await super().shutdown(sockets=sockets)


class BoundedDrainUvicornWorker(UvicornWorker):
    """UvicornWorker with a bounded drain and shutdown-aware streaming."""

    CONFIG_KWARGS: dict[str, Any] = {
        "loop": "auto",
        "http": "auto",
        "timeout_graceful_shutdown": settings.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    }

    async def _serve(self) -> None:
        # Mirrors UvicornWorker._serve but swaps in the shutdown-aware Server.
        self.config.app = self.wsgi
        server = _ShutdownAwareServer(config=self.config)
        self._install_sigquit_handler()
        await server.serve(sockets=self.sockets)
        if not server.started:
            sys.exit(Arbiter.WORKER_BOOT_ERROR)
