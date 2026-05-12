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

from sqlalchemy.exc import IntegrityError

from application.storage.db.repositories.message_events import (
    MessageEventsRepository,
)
from application.storage.db.session import db_readonly, db_session
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

    ``payload`` must be a ``dict`` (or ``None``). Passing a list,
    scalar, or any other shape is a contract violation: the live path
    in ``base.py::_emit`` and the replay path in
    ``event_replay`` previously reconstructed non-dicts differently
    (``{"value": payload}`` vs. ``{"type": event_type}``), so a
    reconnecting client would receive a different envelope than the
    one originally streamed. Rejecting non-dicts at this gate keeps
    the two paths byte-identical.

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

    if payload is None:
        materialised_payload: dict[str, Any] = {}
    elif isinstance(payload, dict):
        materialised_payload = payload
    else:
        logger.warning(
            "record_event called with non-dict payload "
            "(message_id=%s seq=%s type=%s payload_type=%s) — dropping",
            message_id,
            sequence_no,
            event_type,
            type(payload).__name__,
        )
        return False

    journal_committed = False
    # The seq we actually managed to write. Diverges from
    # ``sequence_no`` only on the IntegrityError-retry path below.
    materialised_seq = sequence_no
    try:
        # Short-lived per-event transaction. Critical for visibility:
        # the reconnect endpoint reads the journal from a separate
        # connection and only sees committed rows.
        with db_session() as conn:
            MessageEventsRepository(conn).record(
                message_id, sequence_no, event_type, materialised_payload
            )
        journal_committed = True
    except IntegrityError:
        # Composite-PK collision on (message_id, sequence_no). Most
        # likely cause is a stale ``latest_sequence_no`` seed on a
        # continuation retry — the route read MAX(seq) from a separate
        # connection before another writer committed past it. Look up
        # the live latest and retry once with latest+1 so the event is
        # not silently lost. Bounded to a single retry — if two
        # writers keep racing in lockstep the route-level retry will
        # converge them across attempts.
        try:
            with db_readonly() as conn:
                latest = MessageEventsRepository(conn).latest_sequence_no(
                    message_id
                )
            materialised_seq = (latest if latest is not None else -1) + 1
            with db_session() as conn:
                MessageEventsRepository(conn).record(
                    message_id,
                    materialised_seq,
                    event_type,
                    materialised_payload,
                )
            journal_committed = True
            logger.info(
                "record_event: collision at seq=%s recovered → wrote at "
                "seq=%s message_id=%s type=%s",
                sequence_no,
                materialised_seq,
                message_id,
                event_type,
            )
        except IntegrityError:
            # Second collision under the same retry — give up and log.
            # The route's nonlocal counter will continue at
            # ``sequence_no+1`` on the next emit; the next call may
            # land cleanly past the contended window.
            logger.warning(
                "record_event: IntegrityError persists after seq+1 retry; "
                "dropping. message_id=%s original_seq=%s retry_seq=%s "
                "type=%s",
                message_id,
                sequence_no,
                materialised_seq,
                event_type,
            )
        except Exception:
            logger.exception(
                "record_event: retry path failed unexpectedly "
                "(message_id=%s seq=%s type=%s)",
                message_id,
                sequence_no,
                event_type,
            )
    except Exception:
        logger.exception(
            "message_events INSERT failed: message_id=%s seq=%s type=%s",
            message_id,
            sequence_no,
            event_type,
        )

    try:
        # Publish using ``materialised_seq`` so the live pubsub frame
        # matches the journal row that other clients will snapshot on
        # reconnect. The original POST stream's SSE ``id:`` still
        # carries the caller's ``sequence_no`` — a reconnect from that
        # client will receive the same event at ``materialised_seq``
        # on the snapshot, which is a benign duplicate (the slice's
        # ``max_replayed_seq`` advances past it). No-collision case:
        # ``materialised_seq == sequence_no`` and this is identical to
        # the prior behaviour.
        wire = encode_pubsub_message(
            message_id, materialised_seq, event_type, materialised_payload
        )
        Topic(message_topic_name(message_id)).publish(wire)
    except Exception:
        logger.exception(
            "channel:%s publish failed: seq=%s type=%s",
            message_id,
            materialised_seq,
            event_type,
        )

    return journal_committed
