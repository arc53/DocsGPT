"""How often each feature called the decision model, kept as counts in ``decision_usage``.

The guardrail journal records only what fired; these counts are the denominators: how many calls, states and
answers each feature had per day, by mode, model version and status, and how long they took. They hold no text,
no user and no request.

Each process adds to counters in memory and writes them every ``FLUSH_SECONDS`` as increments to the day's rows,
so a call never waits on the database. ``cleanup_decision_usage`` on beat keeps ``DECISION_USAGE_RETENTION_DAYS``.
"""

from __future__ import annotations

import atexit
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

#: Seconds between writes; 0 keeps the counts in memory until ``flush`` is called (tests).
FLUSH_SECONDS = 60.0

#: One row's counters, in ``decision_usage`` column order.
COUNTERS = ("calls", "states", "answered", "ms_total", "queue_ms_total")

_lock = threading.Lock()
#: ``(day, feature, mode, model_version, status)`` to the counters not yet written.
_counts: dict[tuple, list] = {}
_timer: Optional[threading.Timer] = None
_exit_hook = False


def count(feature: str, mode: str, model_version: Optional[str], status: str, *, states: int, answered: int,
          ms: float, queue_ms: float) -> None:
    """Add one call to today's counters.

    Args:
        feature: The calling feature's label.
        mode: ``local`` or ``api``.
        model_version: ``model_version()`` at the call; ``None`` when no model is configured.
        status: The call's status: ``ok``, ``partial``, ``timeout`` or ``unavailable``.
        states: States asked about.
        answered: States answered.
        ms: Wall time of the call.
        queue_ms: Time its states waited for the model, summed.
    """
    key = (datetime.now(timezone.utc).date(), feature, mode, model_version or "", status)
    with _lock:
        row = _counts.setdefault(key, [0, 0, 0, 0.0, 0.0])
        for i, value in enumerate((1, states, answered, ms, queue_ms)):
            row[i] += value
        _schedule()


def _schedule() -> None:
    """Start the write timer if none is pending; called under ``_lock``."""
    global _timer, _exit_hook
    if _timer is not None or FLUSH_SECONDS <= 0:
        return
    _timer = threading.Timer(FLUSH_SECONDS, _flush_due)
    _timer.daemon = True
    _timer.start()
    if not _exit_hook:  # a clean shutdown (a gunicorn recycle) writes what is left
        atexit.register(flush)
        _exit_hook = True


def _flush_due() -> None:
    global _timer
    with _lock:
        _timer = None
    flush()


def flush() -> int:
    """Write the counts gathered so far as increments; returns the rows written.

    A failed write keeps the counts for the next attempt.
    """
    global _counts
    with _lock:
        taken, _counts = _counts, {}
    if not taken:
        return 0
    rows = [
        {"day": day, "feature": feature, "mode": mode, "model_version": version, "status": status,
         **dict(zip(COUNTERS, values))}
        for (day, feature, mode, version, status), values in taken.items()
    ]
    try:
        from docsgpt.storage.db.repositories.decision_usage import DecisionUsageRepository
        from docsgpt.storage.db.session import db_session

        with db_session() as conn:
            DecisionUsageRepository(conn).add(rows)
        return len(rows)
    except Exception:  # noqa: BLE001 - usage counts must never break a call
        logger.warning("Could not write decision usage counts; keeping them for the next attempt", exc_info=True)
        with _lock:
            for key, values in taken.items():
                row = _counts.setdefault(key, [0, 0, 0, 0.0, 0.0])
                for i, value in enumerate(values):
                    row[i] += value
            _schedule()
        return 0


def reset() -> None:
    """Forget the counts and the timer; run in a forked child, which must not write its parent's counts."""
    global _lock, _counts, _timer
    _lock = threading.Lock()
    _counts = {}
    _timer = None
