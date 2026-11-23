"""Team-scoped authorization — the SECOND authz plane beside global RBAC.

Mirrors ``docsgpt/api/user/authz.py`` (the global admin/user plane) but for
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

Team roles rank Viewer < Editor < Admin (``docsgpt.workspaces.roles``); a
route asks for the weakest stored role it needs; ``team_viewer`` means "any
member". This plane guards team management (members, team settings, grants
lists); access to a team's *items* never comes from here, and the instance
admin short-circuit does not reach them (``resource_access.resolve``).
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import jsonify, make_response, request

from docsgpt.api.user.authz import ROLE_ADMIN, has_role
from docsgpt.storage.db.repositories.team_members import (
    ROLE_TEAM_ADMIN,
    ROLE_TEAM_EDITOR,
    ROLE_TEAM_VIEWER,
    TeamMembersRepository,
)
from docsgpt.storage.db.session import db_readonly
from docsgpt.workspaces.roles import from_stored_role, role_at_least

logger = logging.getLogger(__name__)


def team_role_for(token: dict | None, team_id: str | None) -> str | None:
    """Strongest stored team role the caller holds in ``team_id``, or None.

    ``team_admin``, ``team_editor`` or ``team_viewer``; the team owner holds an
    admin row, so they answer ``team_admin`` here.

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
    """True if the caller holds ``name`` or a stronger role in ``team_id``.

    A global ``admin`` satisfies any team role for team management
    (superuser over all teams' membership, not over their items).
    The stored names rank ``team_viewer`` < ``team_editor`` < ``team_admin``,
    so ``team_viewer`` asks for any membership (the legacy ``team_member`` reads
    as a viewer). An unknown ``name``
    or stored role never passes.

    Args:
        token: The decoded request token.
        team_id: The team, from the URL path.
        name: The weakest stored role the route needs.

    Returns:
        bool: Whether the caller may go on.
    """
    if has_role(token, ROLE_ADMIN):
        return True
    held = from_stored_role(team_role_for(token, team_id))
    if held is None:
        return False
    needed = from_stored_role(name)
    return needed is not None and role_at_least(held, needed)


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
team_editor_required = require_team_role(ROLE_TEAM_EDITOR)
team_member_required = require_team_role(ROLE_TEAM_VIEWER)
