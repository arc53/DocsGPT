"""Beat-side helpers for monitors, kept out of ``docsgpt/api/user/tasks.py`` so its edits stay one-liners."""

from __future__ import annotations

import logging
from typing import Dict

from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)


def dispatch_monitors_safely() -> Dict[str, int]:
    """Run one monitor dispatch pass; a failure is logged and never breaks the schedule dispatcher.

    Returns:
        The pass's counts, or ``{"error": 1}``.
    """
    if not settings.MONITORS_ENABLED:
        return {}
    try:
        from docsgpt.monitors.tick import dispatch_due_monitors

        return dispatch_due_monitors()
    except Exception:
        logger.exception("monitor dispatch failed; the next beat retries")
        return {"error": 1}


def cleanup_hits() -> Dict[str, int]:
    """Delete settled webhook deliveries older than ``BACKGROUND_RESULT_RETENTION_DAYS``."""
    if not settings.POSTGRES_URI:
        return {"deleted": 0}
    from docsgpt.storage.db.repositories.trigger_links import TriggerHitsRepository
    from docsgpt.storage.db.session import db_session

    days = max(1, int(settings.BACKGROUND_RESULT_RETENTION_DAYS))
    with db_session() as conn:
        deleted = TriggerHitsRepository(conn).cleanup_older_than(days)
    return {"deleted": deleted, "days": days}
