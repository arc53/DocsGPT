"""Audit event taxonomy: the categories the admin activity feed filters on.

Lives at the top level (like ``docsgpt/pricing.py``) because both the API
layer — which records events — and the storage layer — which has to filter a
merged feed in SQL — need the same map, and neither should import the other.

Two representations of one table:

* :func:`category_for` classifies a single event name in Python.
* :func:`category_case_sql` emits the equivalent ``CASE`` expression so a
  category filter can be pushed into the query instead of enumerating every
  event name a release might have written.
"""

from __future__ import annotations

# Categories in the order the UI shows them. ``other`` catches event names an
# older release wrote that this one does not know about — the feed must never
# hide a row just because its name is unfamiliar.
ACTIVITY_CATEGORIES = ("identity", "access", "config", "data", "device", "safety", "other")

# Exact event names.
_EXACT: dict[str, str] = {
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
    # What you may do: roles, account state.
    "role_granted": "access",
    "role_revoked": "access",
    "admin_user_activated": "access",
    "admin_user_deactivated": "access",
    "admin_sessions_revoked": "access",
    # How the instance is configured.
    "quota_policy_set": "config",
    "quota_policy_deleted": "config",
}

# Dotted namespaces, matched on the part before the first ``.``.
_NAMESPACES: dict[str, str] = {
    "team": "access",
    "source": "data",
    "agent": "data",
    "conversation": "data",
    "device": "device",
    "guardrail": "safety",
}


def category_for(event: str) -> str:
    """Return the activity category for ``event``.

    Args:
        event: The audit event name (``oidc_login``, ``source.deleted``).

    Returns:
        One of :data:`ACTIVITY_CATEGORIES`; ``"other"`` for names this release
        does not recognise.
    """
    namespace, dot, _ = event.partition(".")
    if dot:
        return _NAMESPACES.get(namespace, "other")
    return _EXACT.get(event, "other")


def category_case_sql(column: str) -> str:
    """Build the SQL ``CASE`` that classifies ``column`` the way :func:`category_for` does.

    Uses ``split_part`` rather than ``LIKE`` so the expression carries no ``%``
    — which a pyformat DBAPI would otherwise read as a parameter marker.

    Args:
        column: The SQL expression holding an event name.

    Returns:
        A parenthesised ``CASE`` expression. Every literal in it comes from the
        maps above, never from user input, so it is safe to interpolate.
    """
    namespace_branches = " ".join(
        f"WHEN '{namespace}' THEN '{category}'"
        for namespace, category in _NAMESPACES.items()
    )
    by_category: dict[str, list[str]] = {}
    for event, category in _EXACT.items():
        by_category.setdefault(category, []).append(event)
    exact_branches = " ".join(
        f"WHEN {column} IN ({', '.join(repr(event) for event in sorted(events))}) "
        f"THEN '{category}'"
        for category, events in sorted(by_category.items())
    )
    return (
        "(CASE "
        f"WHEN position('.' in {column}) > 0 "
        f"THEN (CASE split_part({column}, '.', 1) {namespace_branches} ELSE 'other' END) "
        f"{exact_branches} "
        "ELSE 'other' END)"
    )
