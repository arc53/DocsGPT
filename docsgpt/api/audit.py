"""Shared audit-trail helper and the event → category map.

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
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import has_request_context, request

from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository

logger = logging.getLogger(__name__)


# Coarse grouping for the admin activity feed's facet filter. Keyed by exact
# event name or by a ``prefix.`` namespace; see :func:`category_for`.
EVENT_CATEGORIES: dict[str, str] = {
    # Who you are: authentication, provisioning, personal credentials.
    "oidc_login": "identity",
    "oidc_login_denied": "identity",
    "oidc_refresh": "identity",
    "backchannel_logout": "identity",
    "scim_created": "identity",
    "scim_deactivated": "identity",
    "scim_reactivated": "identity",
    "pat_created": "identity",
    "pat_revoked": "identity",
    "pat_regenerated": "identity",
    # What you may do: roles, account state, team membership and sharing.
    "role_granted": "access",
    "role_revoked": "access",
    "admin_user_activated": "access",
    "admin_user_deactivated": "access",
    "admin_sessions_revoked": "access",
    "team.": "access",
    # How the instance is configured.
    "quota_policy_set": "config",
    "quota_policy_deleted": "config",
    # What the data looks like.
    "source.": "data",
    "agent.": "data",
    "conversation.": "data",
    # Everything an older release wrote that this one does not know about.
    "other": "other",
}


def category_for(event: str) -> str:
    """Return the activity category for ``event``.

    Args:
        event: The audit event name.

    Returns:
        One of ``identity``, ``access``, ``config``, ``data``, or ``other``
        for names this release does not recognise.
    """
    exact = EVENT_CATEGORIES.get(event)
    if exact is not None and not event.endswith("."):
        return exact
    namespace, dot, _ = event.partition(".")
    if dot:
        return EVENT_CATEGORIES.get(f"{namespace}.", "other")
    return "other"


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
