"""Write a finished trace to its two sinks: Postgres and OpenTelemetry."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional

from docsgpt.tracing.core import Trace

logger = logging.getLogger(__name__)

# Writes handed off by ``flush(background=True)``. Two workers keep up with
# chat traffic (each write is one INSERT); the pool's threads are joined at
# interpreter exit, so queued traces are still written on a clean shutdown.
_writer: Optional[ThreadPoolExecutor] = None
_writer_lock = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _writer
    with _writer_lock:
        if _writer is None:
            _writer = ThreadPoolExecutor(max_workers=2, thread_name_prefix="trace-writer")
        return _writer


def _write(trace: Trace) -> None:
    """Export ``trace`` to OTel, then store it; each sink swallows its own failure.

    OTel replay runs first so the exported trace id can be stored with the
    row. A trace is diagnostic data and must never fail the request that
    produced it.
    """
    try:
        from docsgpt.tracing.otel import export_trace

        trace.otel_trace_id = export_trace(trace)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to export trace %s to OpenTelemetry", trace.id, exc_info=True)
    if not trace.spans:
        # Nothing ran worth showing (e.g. an early validation error).
        return
    try:
        from docsgpt.storage.db.repositories.request_traces import RequestTracesRepository
        from docsgpt.storage.db.session import db_session

        with db_session() as conn:
            RequestTracesRepository(conn).insert(trace.to_record())
    except Exception:  # noqa: BLE001
        logger.warning("Failed to store trace %s", trace.id, exc_info=True)


def flush(
    trace: Optional[Trace], status: Optional[str] = None, *, background: bool = False
) -> Optional[Future]:
    """Finish ``trace`` and persist it once; later calls are no-ops.

    The trace is frozen immediately, so nothing recorded afterwards is
    included, whichever way it is written.

    Args:
        trace: The trace to write; ``None`` is accepted and ignored.
        status: Final status; defaults to ``error`` when a top-level span
            failed, else ``ok``.
        background: Write on a writer thread instead of the caller's. A chat
            stream flushes this way so its connection closes without waiting
            on the OTel replay and the INSERT.

    Returns:
        The pending write when ``background`` is set, else ``None``.
    """
    if trace is None or trace.flushed:
        return None
    trace.flushed = True
    trace.finish(status)
    if background:
        try:
            return _executor().submit(_write, trace)
        except RuntimeError:
            # The pool is shut down (interpreter exit): write inline instead.
            pass
    _write(trace)
    return None


def discard(trace: Optional[Trace]) -> None:
    """Drop ``trace`` without writing it (the request was rejected or superseded)."""
    if trace is None or trace.flushed:
        return
    trace.flushed = True
    trace.finish()
