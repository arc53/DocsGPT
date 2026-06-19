"""Role resolution and authorization helpers (admin/user RBAC).

Roles are resolved per-request from the database plus computed overlays and are
NEVER read from the inbound JWT: ``simple_jwt``/``session_jwt`` tokens are
self-mintable, so trusting a ``roles`` claim would be a trivial privilege
escalation. ``resolve_roles`` always rebuilds the set from scratch.

Policy (see ``rbac-spec.md``):
- Persisted RBAC (``user_roles``) applies only under ``AUTH_TYPE=oidc``.
- ``AUTH_TYPE=None`` (no-auth self-host) grants admin only when
  ``LOCAL_MODE_ADMIN`` is enabled (default off).
- ``simple_jwt`` / ``session_jwt`` can never be admin (shared/throwaway ``sub``).
- ``/v1`` agent keys, device tokens, and pre-auth requests are role-less.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import jsonify, make_response, request

from application.core.settings import settings
from application.storage.db.repositories.user_roles import UserRolesRepository
from application.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

ROLE_USER = "user"
ROLE_ADMIN = "admin"


def resolve_roles(token: dict | None) -> list[str]:
    """Compute the sorted role set for a request principal.

    Fails open to less privilege: a DB error while reading grants demotes
    DB-backed admins to ``user`` rather than raising (which would turn a roles
    outage into a total-auth outage on the universal before-request path).
    """
    if not token:
        return [ROLE_USER]
    roles = {ROLE_USER}
    sub = token.get("sub")
    if settings.AUTH_TYPE == "oidc":
        if sub:
            try:
                with db_readonly() as conn:
                    roles.update(UserRolesRepository(conn).role_names_for(sub))
            except Exception:
                logger.error(
                    "resolve_roles: user_roles read failed for sub=%s", sub, exc_info=True
                )
    elif settings.AUTH_TYPE is None and settings.LOCAL_MODE_ADMIN:
        roles.add(ROLE_ADMIN)
    # simple_jwt / session_jwt: never admin.
    return sorted(roles)


def has_role(token: dict | None, name: str) -> bool:
    """True if the principal holds ``name``.

    ``user`` is implicit and always true. Tolerates a ``None`` token or a token
    that never went through ``resolve_roles`` (e.g. async/SSE or /v1 paths) —
    those are treated as role-less and only satisfy the implicit ``user`` role.
    """
    if name == ROLE_USER:
        return True
    roles = (token or {}).get("roles") or []
    return name in roles


def require_role(name: str):
    """Decorator factory: 401 when unauthenticated, 403 when lacking ``name``.

    Fails closed — a missing/None token or absent ``roles`` key never raises and
    never passes through. The frontend route guard is cosmetic; this is the
    security boundary.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            token = getattr(request, "decoded_token", None)
            if not token:
                return make_response(
                    jsonify({"success": False, "message": "Authentication required"}), 401
                )
            if not has_role(token, name):
                return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
            return func(*args, **kwargs)

        return wrapper

    return decorator


admin_required = require_role(ROLE_ADMIN)
