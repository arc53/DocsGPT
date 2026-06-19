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
        return make_response(jsonify(body), 200)
