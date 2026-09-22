"""Shared audit-trail helper for recording data-plane and identity events.

Identity and access events (login, role grants, provisioning) have been
audited since ``auth_events`` was introduced. Data-plane actions — creating and
deleting sources, agents, agent keys and conversations — were not, which left
the trail unable to answer "who deleted that source". :func:`record_event` is
the one-line hook those routes use.

Two properties matter and are enforced here rather than at every call site:

1. **An audit write can never fail the action it records.** The insert runs in
   a SAVEPOINT so a rejected row rolls back alone, and any exception is
   swallowed with a log line.
2. **Request context is optional.** Celery tasks (ingestion finishing, a
   scheduled run) have no Flask request; the row simply records without an IP
   or user agent instead of raising.

The event → category taxonomy the admin activity feed filters on lives in
``docsgpt/audit_events.py``, which the storage layer needs too.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import has_request_context, request

from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository

logger = logging.getLogger(__name__)


def record_event(
    conn,
    event: str,
    *,
    actor: Optional[str],
    target: Optional[str] = None,
    **metadata: Any,
) -> None:
    """Append one audit event, best-effort, inside the caller's transaction.

    Args:
        conn: Open database connection, inside the action's transaction so the
            audit row commits atomically with the change it describes.
        event: Dotted event name (``source.deleted``, ``agent.created``).
        actor: Who performed the action; ``"unknown"`` when unauthenticated.
        target: The user acted upon, when the event is about a user. Data-plane
            events act on a resource, not an account, so they leave this None.
        **metadata: Free-form detail for the audit drill-down. ``None`` values
            are dropped so the stored object only carries what was known.
    """
    detail = {key: value for key, value in metadata.items() if value is not None}
    ip = request.remote_addr if has_request_context() else None
    user_agent = request.headers.get("User-Agent") if has_request_context() else None
    resolved_actor = actor or "unknown"
    try:
        with conn.begin_nested():
            AuthEventsRepository(conn).insert(
                # ``user_id`` is the per-user feed key: the target when the
                # event is about someone, else the actor's own trail.
                user_id=target or resolved_actor,
                event=event,
                ip=ip,
                user_agent=user_agent,
                metadata=detail,
                actor_id=resolved_actor,
                target_id=target,
            )
    except Exception:
        logger.warning("audit insert failed for event=%s", event, exc_info=True)
