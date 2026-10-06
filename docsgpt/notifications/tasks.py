"""Celery tasks for notifications: Web Push is sent from a worker, never on a request path."""

from __future__ import annotations

import logging

from docsgpt.celery_init import celery

logger = logging.getLogger(__name__)


@celery.task(bind=True, acks_late=False, autoretry_for=(), max_retries=0, soft_time_limit=120, time_limit=180)
def send_web_push(self, user_id, payload):
    """Deliver one notification to every Web Push subscription of the user.

    At most once: a push delivered twice is noise, and a failed one is
    counted against its subscription instead of retried.

    Args:
        user_id: The user.
        payload: ``build_payload`` output.

    Returns:
        Delivery counts.
    """
    from docsgpt.notifications.push import deliver

    try:
        return deliver(str(user_id), dict(payload or {}))
    except Exception:  # noqa: BLE001 - a lost push must never fail loudly
        logger.exception("web push for user %s failed", user_id)
        return {"error": True}
