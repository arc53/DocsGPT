"""``notify_user``: tell a user something happened in one of their conversations.

The single notify API every feature calls (continuation turns now; monitors,
trigger and approval links later). This first version only publishes the
``notification.created`` SSE event, which open tabs turn into a toast. The
presence-aware version (no toast for a user watching the conversation, Web
Push for one with no tab open, an unread marker always) replaces this body
and keeps the signature.
"""

from __future__ import annotations

import logging
from typing import Optional

from docsgpt.events.publisher import publish_user_event

logger = logging.getLogger(__name__)

NOTIFICATION_CREATED = "notification.created"


def notify_user(
    *,
    user_id: str,
    conversation_id: Optional[str],
    kind: str,
    title: str,
    body: str,
    url: str,
) -> None:
    """Notify a user; never raises.

    Args:
        user_id: Who to notify.
        conversation_id: The conversation it is about, if any.
        kind: What happened (``continuation``, ``monitor``, ``approval``, ...).
        title: One short line.
        body: A short preview.
        url: Where Open goes, relative to the app (``/c/<conversation_id>``).
    """
    if not user_id:
        return
    payload = {
        "kind": kind,
        "title": title,
        "body": body,
        "url": url,
        "conversation_id": str(conversation_id) if conversation_id else None,
    }
    scope = {"kind": "conversation", "id": str(conversation_id)} if conversation_id else {"kind": "user"}
    try:
        publish_user_event(str(user_id), NOTIFICATION_CREATED, payload, scope=scope)
    except Exception:
        logger.exception("notification publish failed for user %s", user_id)
