"""Wire-level keepalive wrapper for synchronous SSE streaming routes."""

import contextvars
import logging
import queue
import threading
from typing import Generator, Optional

from application.core.settings import settings

logger = logging.getLogger(__name__)


def with_sse_keepalive(
    inner: Generator[str, None, None],
    interval_seconds: Optional[float] = None,
) -> Generator[str, None, None]:
    """Yield from ``inner``, emitting ``: keepalive`` SSE comments whenever it
    stays quiet for ``interval_seconds`` (defaults to
    ``settings.SSE_KEEPALIVE_SECONDS``).

    Long tool-argument generations, summary-less reasoning stretches, and
    server-side tool runs keep the origin busy for minutes without producing
    a single chunk; proxies in front of the API then cut the byte-silent
    connection (Cloudflare read-times-out at ~100s) while the origin
    finishes into a dead socket. SSE comment frames keep bytes flowing and
    are ignored by every SSE/OpenAI-compatible client — the same
    ``: keepalive`` convention used by
    ``application/streaming/async_event_replay.py``.

    ``inner`` is pumped from a daemon thread so this wrapper can time out on
    silence. Callers must pass generators that don't rely on Flask's request
    context (both chat stream routes return bare generators without
    ``stream_with_context``). The pump runs in a copy of the caller's
    contextvars context so request-scoped log bindings survive the thread
    hop. The queue is unbounded and the thread is a daemon: if the consumer
    disconnects mid-stream, the pump drains the upstream generator to
    completion — matching the production ASGI adapter's pre-existing
    disconnect behavior, where the WSGI iterable is drained before close().
    """
    if interval_seconds is None:
        interval_seconds = float(settings.SSE_KEEPALIVE_SECONDS)
    frames: queue.Queue = queue.Queue()

    def _pump() -> None:
        try:
            for item in inner:
                frames.put(("item", item))
        except BaseException as exc:
            # Logged here because after a client disconnect the consumer
            # loop is gone and nothing ever dequeues (or re-raises) this.
            logger.exception("SSE keepalive pump: upstream stream failed")
            frames.put(("error", exc))
        else:
            frames.put(("end", None))

    ctx = contextvars.copy_context()
    threading.Thread(
        target=ctx.run, args=(_pump,), daemon=True, name="sse-keepalive-pump"
    ).start()
    while True:
        try:
            kind, payload = frames.get(timeout=interval_seconds)
        except queue.Empty:
            yield ": keepalive\n\n"
            continue
        if kind == "item":
            yield payload
        elif kind == "error":
            raise payload
        else:
            return
