"""User-scoped event publisher: durable backlog + live fan-out.

Each ``publish_user_event`` call writes twice:

1. ``XADD user:{user_id}:stream MAXLEN ~ <cap> * event <json>`` — the
   durable backlog used by SSE reconnect (``Last-Event-ID``) and stream
   replay. Bounded by ``EVENTS_STREAM_MAXLEN`` (~24h at typical event
   rates) so the per-user footprint stays predictable.
2. ``PUBLISH user:{user_id} <json-with-id>`` — live fan-out to every
   currently connected SSE generator for the user, across instances.

Together they give a snapshot-plus-tail story: a reconnecting client
reads ``XRANGE`` from its last seen id and then transitions onto the
live pub/sub. The Redis Streams entry id (e.g. ``1735682400000-0``) is
the canonical, monotonically increasing event id and is what
``Last-Event-ID`` carries.

Failures are logged and swallowed: the caller is typically a Celery
task whose primary work has already succeeded, and a notification
delivery miss should not surface as a task failure.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from application.cache import get_redis_instance
from application.core.settings import settings
from application.events.keys import stream_key, topic_name
from application.streaming.broadcast_channel import Topic

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    """ISO 8601 UTC with millisecond precision and Z suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def publish_user_event(
    user_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    scope: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Publish a user-scoped event; return the Redis Streams id or ``None``.

    Args:
        user_id: typically ``decoded_token["sub"]``; the per-user Redis
            stream / pub-sub channel keys are derived from this value.
        event_type: dotted name, e.g. ``"source.ingest.progress"``.
        payload: event-specific dict; must be JSON-serializable.
        scope: optional ``{"kind": "source", "id": "..."}`` resource
            pointer that lets the frontend filter without parsing the
            payload.

    Never raises. Returns ``None`` when push is disabled, the payload
    fails to serialize, Redis is unavailable, or both writes fail. A
    non-``None`` return implies the event reached the durable backlog.
    """
    if not user_id or not event_type:
        logger.warning(
            "publish_user_event called without user_id or event_type "
            "(user_id=%r, event_type=%r)",
            user_id,
            event_type,
        )
        return None
    if not settings.ENABLE_SSE_PUSH:
        return None

    envelope_partial: dict[str, Any] = {
        "type": event_type,
        "ts": _iso_now(),
        "user_id": user_id,
        "topic": topic_name(user_id),
        "scope": scope or {},
        "payload": payload,
    }

    try:
        envelope_partial_json = json.dumps(envelope_partial)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "publish_user_event payload not JSON-serializable: "
            "user=%s type=%s err=%s",
            user_id,
            event_type,
            exc,
        )
        return None

    redis = get_redis_instance()
    if redis is None:
        logger.debug("Redis unavailable; skipping publish_user_event")
        return None

    maxlen = settings.EVENTS_STREAM_MAXLEN
    stream_id: Optional[str] = None
    try:
        # Auto-id ('*') gives a monotonic ms-seq id that doubles as the
        # SSE event id. ``approximate=True`` lets Redis trim in chunks
        # for performance; the cap is treated as ~MAXLEN, never <.
        result = redis.xadd(
            stream_key(user_id),
            {"event": envelope_partial_json},
            maxlen=maxlen,
            approximate=True,
        )
        stream_id = (
            result.decode("utf-8")
            if isinstance(result, (bytes, bytearray))
            else str(result)
        )
    except Exception:
        logger.exception(
            "xadd failed for user=%s event_type=%s", user_id, event_type
        )

    # If the durable journal write failed there is no canonical id to
    # ship — publishing the envelope live would put an id-less record
    # on the wire that bypasses the SSE route's dedup floor and breaks
    # ``Last-Event-ID`` semantics for any reconnect. Best-effort
    # delivery means dropping consistently, not delivering inconsistent
    # state.
    if stream_id is None:
        return None

    envelope = dict(envelope_partial)
    envelope["id"] = stream_id

    try:
        Topic(topic_name(user_id)).publish(json.dumps(envelope))
    except Exception:
        logger.exception(
            "publish failed for user=%s event_type=%s", user_id, event_type
        )

    logger.debug(
        "event.published topic=%s type=%s id=%s",
        topic_name(user_id),
        event_type,
        stream_id,
    )

    return stream_id
