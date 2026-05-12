"""Per-yield journal write for the chat-stream snapshot+tail pattern.

``complete_stream`` calls ``record_event`` once per SSE event it
yields. The hook does two things:

1. Insert a row into ``message_events`` (the durable snapshot used by
   reconnecting clients reading from a *different* connection).
2. Publish a JSON envelope to ``channel:{message_id}`` so any client
   currently subscribed receives the event live.

Both are best-effort: failures are logged and swallowed, never raised
back into the streaming loop. A missed journal write means a client
that reconnects between this event and the next won't see this one in
their snapshot — degraded UX, not corrupted state. A missed publish
means currently-subscribed reconnect viewers miss the live tick;
they'll catch up via the snapshot on their next reconnect (or after
their poll-timeout cycle if they're already attached).

Each ``record_event`` opens its own short-lived ``db_session()`` so
the INSERT commits before the matching publish — without that ordering
a fast-reconnecting client could hit the snapshot read on a separate
connection and miss the row that's still uncommitted on the streaming
connection.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from application.storage.db.repositories.message_events import (
    MessageEventsRepository,
)
from application.storage.db.session import db_session
from application.streaming.broadcast_channel import Topic
from application.streaming.event_replay import encode_pubsub_message
from application.streaming.keys import message_topic_name

logger = logging.getLogger(__name__)


def record_event(
    message_id: str,
    sequence_no: int,
    event_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> bool:
    """Journal one SSE event and publish it live. Best-effort.

    Returns ``True`` when the journal INSERT committed (the publish is
    attempted regardless of insert outcome and isn't reflected in the
    return value). Never raises — every failure path logs and swallows.
    """
    if not message_id or not event_type:
        logger.warning(
            "record_event called without message_id/event_type "
            "(message_id=%r, event_type=%r)",
            message_id,
            event_type,
        )
        return False

    materialised_payload = payload if isinstance(payload, dict) else {}

    journal_committed = False
    try:
        # Short-lived per-event transaction. Critical for visibility:
        # the reconnect endpoint reads the journal from a separate
        # connection and only sees committed rows.
        with db_session() as conn:
            MessageEventsRepository(conn).record(
                message_id, sequence_no, event_type, materialised_payload
            )
        journal_committed = True
    except Exception:
        logger.exception(
            "message_events INSERT failed: message_id=%s seq=%s type=%s",
            message_id,
            sequence_no,
            event_type,
        )

    try:
        wire = encode_pubsub_message(
            message_id, sequence_no, event_type, materialised_payload
        )
        Topic(message_topic_name(message_id)).publish(wire)
    except Exception:
        logger.exception(
            "channel:%s publish failed: seq=%s type=%s",
            message_id,
            sequence_no,
            event_type,
        )

    return journal_committed
