"""The ``monitor.updated`` SSE event: a monitor was checked, woke the agent, paused or ended."""

from __future__ import annotations

import logging
from typing import Any, Dict

from docsgpt.events.publisher import publish_user_event

logger = logging.getLogger(__name__)

MONITOR_UPDATED = "monitor.updated"


def wakes_left(monitor: Dict[str, Any]) -> int:
    """Wakes the monitor may still use."""
    return max(0, int(monitor.get("max_wakes") or 0) - int(monitor.get("wake_count") or 0))


def publish_monitor_updated(monitor: Dict[str, Any]) -> None:
    """Tell the owner's tabs about a monitor: ``{monitor_id, status, wakes_left, last_checked_at, ...}``.

    Best-effort; a publish failure is logged and never raised.

    Args:
        monitor: The monitor row (joined with its schedule) after the change.
    """
    user_id = monitor.get("user_id")
    if not user_id:
        return
    conversation_id = monitor.get("conversation_id")
    payload = {
        "monitor_id": str(monitor.get("id") or monitor.get("schedule_id")),
        "status": monitor.get("status"),
        "wakes_left": wakes_left(monitor),
        "last_checked_at": monitor.get("last_checked_at"),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "check_count": int(monitor.get("check_count") or 0),
        "last_error": monitor.get("last_error"),
        # Why it paused or ended ("decided", "expired"), so a link's card can say so live.
        "paused_reason": monitor.get("paused_reason"),
    }
    try:
        publish_user_event(
            str(user_id), MONITOR_UPDATED, payload, scope={"kind": "monitor", "id": payload["monitor_id"]}
        )
    except Exception:
        logger.exception("monitor.updated publish failed for %s", payload["monitor_id"])
