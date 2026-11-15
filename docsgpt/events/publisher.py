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

An event addressed to a team principal (the owner of a team's items,
whose stream nobody reads) is rerouted to people instead
(``workspaces.principal.route_owner_notice``): the person who started
the work (``actor_id``), else for a failure the team's admins and
owner, else nobody. Nothing is ever written to a principal's stream.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from docsgpt.cache import get_redis_instance
from docsgpt.core.settings import settings
from docsgpt.events.keys import stream_key, topic_name
from docsgpt.streaming.broadcast_channel import Topic
from docsgpt.workspaces.principal import is_principal_id, route_owner_notice

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    """ISO 8601 UTC with millisecond precision and Z suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _notify_monitors(user_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Let ingest monitors see a source's ingest end (whether or not SSE is on); never raises."""
    if not event_type.startswith("source.ingest."):
        return
    try:
        from docsgpt.monitors.tick import on_ingest_event

        on_ingest_event(user_id, event_type, payload)
    except Exception:
        logger.exception("ingest monitors hook failed for %s", event_type)


def _track_activity(user_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Keep Activity's marker of a running ingest (whether or not SSE is on); never raises."""
    if not event_type.startswith("source.ingest."):
        return
    try:
        from docsgpt.activity import flags

        flags.track_ingest_event(user_id, event_type, payload)
    except Exception:
        logger.exception("activity ingest marker failed for %s", event_type)


def notice_recipients(owner_id: str, actor_id: Optional[str], kind: str) -> list[str]:
    """The people a notice addressed to a team principal goes to; never raises.

    Args:
        owner_id: The principal the notice was addressed to.
        actor_id: The person who started the work, if any.
        kind: The event or notice kind (failures reach the team's admins).

    Returns:
        Person ids, sorted; empty to drop the notice (also when the lookup fails:
        a notice is dropped rather than written where nobody reads it).
    """
    from docsgpt.storage.db.session import db_readonly

    try:
        with db_readonly() as conn:
            recipients = route_owner_notice(conn, owner_id, actor_id, kind)
    except Exception:
        logger.exception("routing a notice for %s (%s) failed; it is dropped", owner_id, kind)
        return []
    return [r for r in recipients if r and not is_principal_id(r)]


def publish_user_event(
    user_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    scope: Optional[dict[str, Any]] = None,
    actor_id: Optional[str] = None,
) -> Optional[str]:
    """Publish a user-scoped event; return the Redis Streams id or ``None``.

    Fire-and-forget: never raises. ``None`` means the event reached
    neither the journal nor live subscribers (see runbook for causes).

    Args:
        user_id: Who the event is for: usually the owner of the item it is about.
        event_type: The event type.
        payload: Its payload.
        scope: What the event is about, for the client's routing.
        actor_id: The person who started the work. Read only when ``user_id`` is a
            team principal: the event then goes to that person instead (see the module docstring).

    Returns:
        The stream id of the (first) delivery, or None.
    """
    if not user_id or not event_type:
        logger.warning(
            "publish_user_event called without user_id or event_type "
            "(user_id=%r, event_type=%r)",
            user_id,
            event_type,
        )
        return None
    # Ingest monitors match by source and see each event once, under the item's owner.
    _notify_monitors(user_id, event_type, payload)
    if is_principal_id(user_id):
        _track_activity(user_id, event_type, payload)
        delivered = None
        for recipient in notice_recipients(user_id, actor_id, event_type):
            _track_activity(recipient, event_type, payload)
            stream_id = _deliver(recipient, event_type, payload, scope)
            delivered = delivered or stream_id
        return delivered
    _track_activity(user_id, event_type, payload)
    return _deliver(user_id, event_type, payload, scope)


def _deliver(
    user_id: str,
    event_type: str,
    payload: dict[str, Any],
    scope: Optional[dict[str, Any]],
) -> Optional[str]:
    """Write the event to a person's backlog and fan it out live; return the stream id or None."""
    if not settings.ENABLE_SSE_PUSH or is_principal_id(user_id):
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
