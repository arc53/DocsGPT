"""Process-wide graceful-shutdown flag.

Raised by ``BoundedDrainUvicornWorker`` when a drain starts and polled by the
SSE/long-poll generators (which run in a2wsgi threads asyncio can't cancel) so
they return promptly instead of hanging the worker until the ``--timeout``
watchdog kills it. Standalone module so the worker can import it without the app.
"""

from __future__ import annotations

import threading

_shutting_down = threading.Event()


def begin_shutdown() -> None:
    """Mark the process as shutting down so streaming generators stop looping."""
    _shutting_down.set()


def is_shutting_down() -> bool:
    """Return ``True`` once the server has begun a graceful shutdown."""
    return _shutting_down.is_set()


def reset_shutdown() -> None:
    """Clear the shutdown flag. Intended for tests only."""
    _shutting_down.clear()
