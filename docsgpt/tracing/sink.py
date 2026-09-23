"""Write a finished trace to its two sinks: Postgres and OpenTelemetry."""

from __future__ import annotations

import logging
from typing import Optional

from docsgpt.tracing.core import Trace

logger = logging.getLogger(__name__)


def flush(trace: Optional[Trace], status: Optional[str] = None) -> None:
    """Finish ``trace`` and persist it once; later calls are no-ops.

    OTel replay runs first so the exported trace id can be stored with the
    row. Both sinks swallow their own failures: a trace is diagnostic data
    and must never fail the request that produced it.

    Args:
        trace: The trace to write; ``None`` is accepted and ignored.
        status: Final status; defaults to ``error`` when a top-level span
            failed, else ``ok``.
    """
    if trace is None or trace.flushed:
        return
    trace.flushed = True
    trace.finish(status)
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


def discard(trace: Optional[Trace]) -> None:
    """Drop ``trace`` without writing it (the request was rejected or superseded)."""
    if trace is None or trace.flushed:
        return
    trace.flushed = True
    trace.finish()
