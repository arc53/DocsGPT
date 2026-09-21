"""Current-principal endpoint.

``GET /api/user/me`` returns the caller's user id and resolved roles, sourced
only from ``request.decoded_token`` (already populated and role-resolved by the
auth chokepoint in ``app.py``). Auth-mode-agnostic. ``email``/``name``/
``picture`` are OIDC-only and optional — they are echoed from the token and are
never present for ``simple_jwt``/``session_jwt``/no-auth modes.
"""

from __future__ import annotations

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api.pat.tokens import is_pat

me_ns = Namespace("me", description="Current user identity and roles", path="/api")


@me_ns.route("/user/me")
class MeResource(Resource):
    def get(self):
        """Return ``{user_id, roles, email?, name?, picture?}`` for the caller."""
        decoded_token = getattr(request, "decoded_token", None)
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        body = {
            "success": True,
            "user_id": decoded_token.get("sub"),
            "roles": decoded_token.get("roles") or ["user"],
        }
        for field in ("email", "name", "picture"):
            value = decoded_token.get(field)
            if value:
                body[field] = value
        if is_pat(decoded_token):
            # Lets a CLI or pipeline confirm what its token is allowed to do.
            body["auth_method"] = "pat"
            body["token"] = {
                "id": decoded_token.get("pat_id"),
                "name": decoded_token.get("pat_name"),
                "scopes": decoded_token.get("scopes") or [],
                "resource_filter": decoded_token.get("resource_filter") or {},
            }
        return make_response(jsonify(body), 200)
