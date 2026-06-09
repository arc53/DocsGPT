"""Login, callback, and session-token endpoints for AUTH_TYPE=oidc.

Flow: the backend redirects the browser to the IdP (Authorization Code +
PKCE), validates the ID token at the callback, mints a local HS256 session
JWT, and hands it to the SPA via a short-lived single-use code in the URL
fragment. Browser redirects only ever target the configured
``OIDC_FRONTEND_URL`` or IdP endpoints taken from discovery.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import quote, urlencode

from flask import Blueprint, jsonify, make_response, redirect, request
from jose import jwt

from application.api.oidc import provider
from application.cache import get_redis_instance
from application.core.settings import settings

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 600
HANDOFF_TTL_SECONDS = 60


def _state_key(state: str) -> str:
    return f"oidc:state:{state}"


def _handoff_key(code: str) -> str:
    return f"oidc:handoff:{code}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _redirect_uri() -> str:
    return settings.OIDC_REDIRECT_URI or request.host_url.rstrip("/") + "/api/auth/oidc/callback"


def _frontend_url() -> str:
    return (settings.OIDC_FRONTEND_URL or "").rstrip("/") or "/"


def _frontend_redirect(fragment: str):
    base = (settings.OIDC_FRONTEND_URL or "").rstrip("/")
    return redirect(f"{base}/#{fragment}", code=302)


def oidc_login():
    """Start the Authorization Code + PKCE flow with a 302 to the IdP."""
    redis = get_redis_instance()
    if redis is None:
        return make_response(jsonify({"error": "redis_unavailable"}), 503)
    try:
        authorization_endpoint = provider.get_discovery()["authorization_endpoint"]
    except (provider.OIDCError, KeyError):
        logger.error("OIDC discovery failed during login", exc_info=True)
        return make_response(jsonify({"error": "idp_unavailable"}), 503)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    redis.set(
        _state_key(state),
        json.dumps({"code_verifier": code_verifier, "nonce": nonce}),
        ex=STATE_TTL_SECONDS,
        nx=True,
    )
    params = {
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "scope": settings.OIDC_SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return redirect(f"{authorization_endpoint}?{urlencode(params)}", code=302)


def oidc_callback():
    """Validate the IdP response, mint a session JWT, redirect with a handoff code."""
    if request.args.get("error"):
        return _frontend_redirect("oidc_error=" + quote(request.args["error"]))
    state = request.args.get("state")
    code = request.args.get("code")
    if not state or not code:
        return _frontend_redirect("oidc_error=invalid_state")

    redis = get_redis_instance()
    if redis is None:
        logger.error("Redis unavailable during OIDC callback")
        return _frontend_redirect("oidc_error=auth_failed")
    raw_state = redis.getdel(_state_key(state))
    if raw_state is None:
        return _frontend_redirect("oidc_error=invalid_state")
    stored = json.loads(raw_state)

    try:
        tokens = provider.exchange_code(code, stored["code_verifier"], _redirect_uri())
        claims = provider.validate_id_token(tokens["id_token"], stored["nonce"])
    except (provider.OIDCError, KeyError):
        logger.error("OIDC callback failed", exc_info=True)
        return _frontend_redirect("oidc_error=auth_failed")

    user_id = claims.get(settings.OIDC_USER_ID_CLAIM)
    if not user_id:
        logger.error("OIDC id_token missing user id claim %r", settings.OIDC_USER_ID_CLAIM)
        return _frontend_redirect("oidc_error=missing_claim")

    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + settings.OIDC_SESSION_LIFETIME_SECONDS,
    }
    for claim in ("email", "name"):
        if claims.get(claim):
            payload[claim] = claims[claim]
    session_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")

    handoff = secrets.token_urlsafe(32)
    redis.set(_handoff_key(handoff), session_token, ex=HANDOFF_TTL_SECONDS, nx=True)
    return _frontend_redirect("oidc_code=" + handoff)


def oidc_token():
    """Redeem a single-use handoff code for the minted session JWT."""
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    if not code or not isinstance(code, str):
        return make_response(jsonify({"error": "invalid_code"}), 401)
    redis = get_redis_instance()
    if redis is None:
        return make_response(jsonify({"error": "redis_unavailable"}), 503)
    raw = redis.getdel(_handoff_key(code))
    if raw is None:
        return make_response(jsonify({"error": "invalid_code"}), 401)
    token = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return jsonify({"token": token})


def oidc_logout():
    """Redirect to the IdP end-session endpoint, falling back to the frontend."""
    frontend = _frontend_url()
    try:
        end_session = provider.get_discovery().get("end_session_endpoint")
    except provider.OIDCError:
        end_session = None
    if not end_session:
        return redirect(frontend, code=302)
    params = {
        "post_logout_redirect_uri": frontend,
        "client_id": settings.OIDC_CLIENT_ID,
    }
    return redirect(f"{end_session}?{urlencode(params)}", code=302)


def register(bp: Blueprint) -> None:
    """Attach the oidc auth routes to ``bp``."""
    bp.add_url_rule(
        "/api/auth/oidc/login", view_func=oidc_login, methods=["GET"], endpoint="login"
    )
    bp.add_url_rule(
        "/api/auth/oidc/callback", view_func=oidc_callback, methods=["GET"], endpoint="callback"
    )
    bp.add_url_rule(
        "/api/auth/oidc/token", view_func=oidc_token, methods=["POST"], endpoint="token"
    )
    bp.add_url_rule(
        "/api/auth/oidc/logout", view_func=oidc_logout, methods=["GET"], endpoint="logout"
    )
