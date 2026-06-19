"""Team-scoped authorization — the SECOND authz plane beside global RBAC.

Mirrors ``application/api/user/authz.py`` (the global admin/user plane) but for
per-team roles. The two planes never mix: a global ``admin`` is a superuser over
all teams (short-circuit below), but a ``team_admin`` is NOT a global admin.

Key differences from the global resolver, all deliberate:
- Team roles are resolved PER ROUTE (lazy), not eagerly in the app.py chokepoint
  — most requests never touch a team route, so we don't pay a team query on the
  universal path.
- Team roles are NEVER read from the JWT (same reason as global RBAC: simple_jwt
  / session_jwt are self-mintable).
- ``team_id`` is read ONLY from ``request.view_args`` (the URL path), NEVER the
  request body — a body-supplied team_id would be a trivial escalation vector.
- Resolution FAILS CLOSED: a DB error while reading membership denies access
  (the inverse of the global resolver, which fails open — here, failing open
  would grant team access during an outage).
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import jsonify, make_response, request

from application.api.user.authz import ROLE_ADMIN, has_role
from application.storage.db.repositories.team_members import (
    ROLE_TEAM_ADMIN,
    ROLE_TEAM_MEMBER,
    TeamMembersRepository,
)
from application.storage.db.session import db_readonly

logger = logging.getLogger(__name__)


def team_role_for(token: dict | None, team_id: str | None) -> str | None:
    """Strongest team role the principal holds in ``team_id``, or None.

    Fails closed to None on a DB error so a membership-read outage denies team
    access rather than granting it.
    """
    if not token or not team_id:
        return None
    sub = token.get("sub")
    if not sub:
        return None
    try:
        with db_readonly() as conn:
            return TeamMembersRepository(conn).role_for(sub, team_id)
    except Exception:
        logger.error(
            "team_role_for: team_members read failed for sub=%s team=%s",
            sub,
            team_id,
            exc_info=True,
        )
        return None


def has_team_role(token: dict | None, team_id: str | None, name: str) -> bool:
    """True if the principal satisfies ``name`` for ``team_id``.

    A global ``admin`` satisfies any team role (superuser over all teams).
    Otherwise ``team_admin`` implies ``team_member`` (admin ⊇ member).
    """
    if has_role(token, ROLE_ADMIN):
        return True
    role = team_role_for(token, team_id)
    if role is None:
        return False
    if name == ROLE_TEAM_MEMBER:
        return True
    return role == name


def require_team_role(name: str):
    """Decorator factory: 401 when unauthenticated, 403 when lacking ``name``.

    Reads ``team_id`` from the route kwargs (URL path) ONLY — never the body.
    Fails closed: a missing token, missing team_id, or membership-read error
    never passes through.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            token = getattr(request, "decoded_token", None)
            if not token:
                return make_response(
                    jsonify({"success": False, "message": "Authentication required"}), 401
                )
            team_id = kwargs.get("team_id")
            if not team_id:
                return make_response(
                    jsonify({"success": False, "message": "Team not specified"}), 400
                )
            if not has_team_role(token, team_id, name):
                return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
            return func(*args, **kwargs)

        return wrapper

    return decorator


team_admin_required = require_team_role(ROLE_TEAM_ADMIN)
team_member_required = require_team_role(ROLE_TEAM_MEMBER)
