"""Personal access token management.

``/api/user/tokens`` lets a signed-in user list, create and revoke their own
tokens; ``/api/admin/...`` lets an admin inspect and revoke anyone's. None of
these routes accept a PAT (see ``docsgpt/api/pat/rules.py``), so a leaked
token can neither mint a replacement nor widen itself.
"""

from __future__ import annotations

import uuid

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError

from docsgpt.api.pat.tokens import (
    FILTERABLE_FAMILIES,
    SCOPES,
    auth_type_supports_pats,
    generate_token,
    is_pat,
    normalize_resource_filter,
    normalize_scopes,
    resolve_expiry,
)
from docsgpt.api.user.authz import admin_required
from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository
from docsgpt.storage.db.repositories.personal_access_tokens import (
    PersonalAccessTokensRepository,
)
from docsgpt.storage.db.session import db_readonly, db_session

pat_ns = Namespace("tokens", description="Personal access tokens", path="/api")

_MAX_NAME_LENGTH = 100


def _error(message: str, status: int):
    return make_response(jsonify({"success": False, "message": message}), status)


def _session_user_id():
    """The caller's id, or ``None`` for anonymous and PAT callers alike."""
    decoded = getattr(request, "decoded_token", None)
    if not decoded or is_pat(decoded):
        return None
    return decoded.get("sub")


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def serialize_token(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "token_prefix": row["token_prefix"],
        "scopes": list(row.get("scopes") or []),
        "resource_filter": row.get("resource_filter") or {},
        "status": row["status"],
        "expires_at": row.get("expires_at"),
        "last_used_at": row.get("last_used_at"),
        "last_used_ip": row.get("last_used_ip"),
        "created_at": row.get("created_at"),
        "revoked_at": row.get("revoked_at"),
    }


def _policy() -> dict:
    return {
        "enabled": auth_type_supports_pats(),
        "default_lifetime_days": settings.PAT_DEFAULT_LIFETIME_DAYS,
        "max_lifetime_days": settings.PAT_MAX_LIFETIME_DAYS,
        "allow_non_expiring": settings.PAT_ALLOW_NON_EXPIRING,
        "max_per_user": settings.PAT_MAX_PER_USER,
        "filterable_families": list(FILTERABLE_FAMILIES),
    }


@pat_ns.route("/user/tokens")
class PersonalAccessTokens(Resource):
    def get(self):
        """List the caller's tokens with the scope catalog and the server's token policy."""
        user_id = _session_user_id()
        if not user_id:
            return _error("Authentication required", 401)
        with db_readonly() as conn:
            rows = PersonalAccessTokensRepository(conn).list_for_user(user_id)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "tokens": [serialize_token(r) for r in rows],
                    "scopes": [{"name": k, "description": v} for k, v in SCOPES.items()],
                    "policy": _policy(),
                }
            ),
            200,
        )

    def post(self):
        """Create a token. The plaintext ``token`` is returned here and never again."""
        user_id = _session_user_id()
        if not user_id:
            return _error("Authentication required", 401)
        if not auth_type_supports_pats():
            return _error("Personal access tokens are not available on this server", 403)

        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return _error("Request body must be a JSON object", 400)
        name = body.get("name")
        if not isinstance(name, str) or not name.strip():
            return _error("name is required", 400)
        name = name.strip()
        if len(name) > _MAX_NAME_LENGTH:
            return _error(f"name must be at most {_MAX_NAME_LENGTH} characters", 400)
        try:
            scopes = normalize_scopes(body.get("scopes"))
            resource_filter = normalize_resource_filter(body.get("resource_filter"), scopes)
            expires_at = resolve_expiry(body.get("expires_in_days"))
        except ValueError as exc:
            return _error(str(exc), 400)

        token, token_hash, token_prefix = generate_token()
        try:
            with db_session() as conn:
                repo = PersonalAccessTokensRepository(conn)
                if repo.count_active(user_id) >= settings.PAT_MAX_PER_USER:
                    return _error(
                        f"Token limit reached ({settings.PAT_MAX_PER_USER}); revoke one first", 409
                    )
                repo.retire_expired_name(user_id, name)
                if repo.name_in_use(user_id, name):
                    return _error("A token with this name already exists", 409)
                row = repo.create(
                    user_id,
                    name,
                    token_hash=token_hash,
                    token_prefix=token_prefix,
                    scopes=scopes,
                    resource_filter=resource_filter,
                    expires_at=expires_at,
                )
                AuthEventsRepository(conn).insert(
                    user_id,
                    "pat_created",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata={
                        "token_id": str(row["id"]),
                        "name": name,
                        "scopes": scopes,
                        "resource_filter": resource_filter,
                        "expires_at": row.get("expires_at"),
                    },
                )
        except IntegrityError:
            # Lost a race against a concurrent create with the same name.
            return _error("A token with this name already exists", 409)
        return make_response(
            jsonify({"success": True, "token": token, "personal_access_token": serialize_token(row)}),
            201,
        )


@pat_ns.route("/user/tokens/<string:token_id>")
class PersonalAccessToken(Resource):
    def delete(self, token_id):
        """Revoke one of the caller's tokens. Takes effect on the next request."""
        user_id = _session_user_id()
        if not user_id:
            return _error("Authentication required", 401)
        if not _valid_uuid(token_id):
            return _error("Token not found", 404)
        with db_session() as conn:
            revoked = PersonalAccessTokensRepository(conn).revoke(token_id, user_id)
            if revoked:
                AuthEventsRepository(conn).insert(
                    user_id,
                    "pat_revoked",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata={"token_id": token_id, "by": user_id},
                )
        if not revoked:
            return _error("Token not found", 404)
        return make_response(jsonify({"success": True}), 200)


@pat_ns.route("/admin/users/<string:user_id>/tokens")
class AdminUserTokens(Resource):
    @admin_required
    def get(self, user_id):
        """List a user's tokens, revoked ones included."""
        with db_readonly() as conn:
            rows = PersonalAccessTokensRepository(conn).list_for_user(user_id, include_revoked=True)
        return make_response(
            jsonify({"success": True, "tokens": [serialize_token(r) for r in rows]}), 200
        )


@pat_ns.route("/admin/tokens/<string:token_id>")
class AdminToken(Resource):
    @admin_required
    def delete(self, token_id):
        """Revoke any user's token."""
        if not _valid_uuid(token_id):
            return _error("Token not found", 404)
        actor = (getattr(request, "decoded_token", None) or {}).get("sub")
        with db_session() as conn:
            repo = PersonalAccessTokensRepository(conn)
            row = repo.get(token_id)
            revoked = bool(row) and repo.revoke(token_id, reason="admin_revoked")
            if revoked:
                AuthEventsRepository(conn).insert(
                    row["user_id"],
                    "pat_revoked",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata={"token_id": token_id, "by": actor, "via": "admin_api"},
                )
        if not revoked:
            return _error("Token not found", 404)
        return make_response(jsonify({"success": True}), 200)
