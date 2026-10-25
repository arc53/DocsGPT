"""``notify_user``: tell a user something happened in one of their conversations.

The single notify API every feature calls: continuation turns (a finished
background job, a matched monitor, a hit trigger link, a human decision) and
anything else that wants the user's attention. Where the notification goes
depends on where the user is (see :mod:`docsgpt.notifications.presence`):

1. **Watching** that conversation (a visible tab shows it): nothing. The
   conversation's own events update the chat, and no unread mark is left.
2. **A tab open** elsewhere (a live event stream, or a visible tab on another
   page): the ``notification.created`` event, which the tab shows as a toast
   with an Open button.
3. **No tab**: Web Push to the user's subscribed browsers, when Web Push is
   configured. Sent from a Celery worker.

Unless the user is watching, the conversation is also marked unread, so it
shows in the sidebar when they come back. When presence can't be read (Redis
down) the user counts as away: the notification still goes out.
"""

from __future__ import annotations

import logging
from typing import Callable, ContextManager, Optional

from sqlalchemy import Connection

from docsgpt.core.settings import settings
from docsgpt.events.publisher import publish_user_event
from docsgpt.notifications import presence

logger = logging.getLogger(__name__)

NOTIFICATION_CREATED = "notification.created"

#: Where a notification went, for logs and tests.
WATCHING, TOAST, PUSH, STORED = "watching", "toast", "push", "stored"


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
        kind: What happened: a wake source (``job``, ``lost``, ``monitor``,
            ``monitor_paused``, ``monitor_expired``, ``trigger``, ``approval``),
            ``schedule`` for a scheduled run's answer, ``docs_gaps`` for the
            weekly docs-gap digest, or any other short word;
            the app shows a generic label for kinds it does not know.
        title: One short line.
        body: A short preview.
        url: Where Open goes, relative to the app (``/c/<conversation_id>``).
    """
    try:
        _notify(
            user_id=user_id, conversation_id=conversation_id, kind=kind, title=title, body=body, url=url
        )
    except Exception:
        logger.exception("notify_user failed for user %s", user_id)


def _notify(
    *, user_id: str, conversation_id: Optional[str], kind: str, title: str, body: str, url: str
) -> Optional[str]:
    """The body of :func:`notify_user`; returns where the notification went."""
    if not user_id:
        return None
    user_id = str(user_id)
    conversation_id = str(conversation_id) if conversation_id else None
    if conversation_id and presence.is_watching(user_id, conversation_id):
        logger.debug("notify: user %s is watching %s; nothing to send", user_id, conversation_id)
        # Seen on screen: read, so Activity won't mark it failed later.
        _mark_read(conversation_id, user_id)
        return WATCHING
    if conversation_id:
        _mark_unread(conversation_id, user_id)
    if settings.ENABLE_SSE_PUSH and presence.has_open_tab(user_id):
        payload = {
            "kind": kind,
            "title": title,
            "body": body,
            "url": url,
            "conversation_id": conversation_id,
        }
        scope = {"kind": "conversation", "id": conversation_id} if conversation_id else {"kind": "user"}
        if publish_user_event(user_id, NOTIFICATION_CREATED, payload, scope=scope) is not None:
            return TOAST
        # The event did not reach the stream; a push is the next best thing.
    if _queue_push(user_id, kind=kind, title=title, body=body, url=url, conversation_id=conversation_id):
        return PUSH
    return STORED


def mark_unread_unless_watching(
    conversation_id: str,
    user_id: str,
    begin: Callable[[], ContextManager[Connection]],
) -> bool:
    """Mark a chat unread for its owner, unless they are watching it.

    For an answer that failed: Activity counts a chat failed while it is
    unread and its last answer failed, and without the mark one that fails
    after the user left shows no failure anywhere. Call it after the failure
    is committed, outside any transaction: presence is a Redis read, which
    must not hold row locks. Never raises.

    Args:
        conversation_id: The chat (see ``listed_chat_of_message``).
        user_id: Its owner.
        begin: Opens the short transaction the write runs in
            (``db_session``, or an engine's ``begin``).

    Returns:
        True when the chat was marked.
    """
    from docsgpt.storage.db.repositories.conversation_unread import ConversationUnreadRepository

    try:
        if presence.is_watching(user_id, conversation_id):
            return False
        with begin() as conn:
            return ConversationUnreadRepository(conn).mark_unread(conversation_id, user_id)
    except Exception:
        logger.exception("marking conversation %s unread failed", conversation_id)
        return False


def _mark_read(conversation_id: str, user_id: str) -> None:
    """Mark a conversation read for its owner, who saw the news land on screen.

    Activity marks a chat failed only when its background job failed after
    the owner last read it. A failure never raises: the notification stands.

    Args:
        conversation_id: The conversation.
        user_id: Its owner.
    """
    from docsgpt.storage.db.repositories.conversation_unread import ConversationUnreadRepository
    from docsgpt.storage.db.session import db_session

    try:
        with db_session() as conn:
            ConversationUnreadRepository(conn).mark_read(conversation_id, user_id)
    except Exception:
        logger.exception("marking conversation %s read failed", conversation_id)


def _mark_unread(conversation_id: str, user_id: str) -> None:
    from docsgpt.storage.db.repositories.conversation_unread import ConversationUnreadRepository
    from docsgpt.storage.db.session import db_session

    try:
        with db_session() as conn:
            ConversationUnreadRepository(conn).mark_unread(conversation_id, user_id)
    except Exception:
        logger.exception("marking conversation %s unread failed", conversation_id)


def _queue_push(
    user_id: str, *, kind: str, title: str, body: str, url: str, conversation_id: Optional[str]
) -> bool:
    """Queue a Web Push delivery when push is configured and the user has a subscription."""
    from docsgpt.notifications.push import build_payload, push_enabled
    from docsgpt.storage.db.repositories.push_subscriptions import PushSubscriptionsRepository
    from docsgpt.storage.db.session import db_readonly

    if not push_enabled():
        return False
    try:
        with db_readonly() as conn:
            if PushSubscriptionsRepository(conn).count_for_user(user_id) == 0:
                return False
    except Exception:
        logger.exception("reading push subscriptions failed for user %s", user_id)
        return False
    payload = build_payload(kind=kind, title=title, body=body, url=url, conversation_id=conversation_id)
    try:
        from docsgpt.notifications.tasks import send_web_push

        send_web_push.delay(user_id, payload)
    except Exception:
        logger.exception("queueing a web push for user %s failed", user_id)
        return False
    return True
