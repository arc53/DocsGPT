"""Login, callback, session-token, logout, and refresh endpoints for AUTH_TYPE=oidc.

Flow: the backend redirects the browser to the IdP (Authorization Code +
PKCE), validates the ID token at the callback, mints a local HS256 session
JWT, and hands it to the SPA via a short-lived single-use code in the URL
fragment. Browser redirects only ever target the configured
``OIDC_FRONTEND_URL`` or IdP endpoints taken from discovery.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from urllib.parse import quote, urlencode

from flask import Blueprint, Response, jsonify, make_response, redirect, request
from jose import jwt

from application.api.oidc import denylist, provider
from application.auth import handle_auth
from application.cache import get_redis_instance
from application.core.settings import settings
from application.storage.db.repositories.auth_events import AuthEventsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 600
HANDOFF_TTL_SECONDS = 60
LOGOUT_JTI_TTL_SECONDS = 600
MAX_PICTURE_CLAIM_CHARS = 2048
# Browser-bound CSRF guard for the login flow: the callback requires this
# cookie to echo the ``state`` it received. Scoped to the oidc paths so it is
# only ever sent on the callback.
STATE_COOKIE_NAME = "oidc_state"
STATE_COOKIE_PATH = "/api/auth/oidc/"


def _state_key(state: str) -> str:
    return f"oidc:state:{state}"


def _handoff_key(code: str) -> str:
    return f"oidc:handoff:{code}"


def _refresh_key(jti: str) -> str:
    return f"oidc:refresh:{jti}"


def _logout_jti_key(jti: str) -> str:
    return f"oidc:bcl:jti:{jti}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _redirect_uri() -> str:
    return settings.OIDC_REDIRECT_URI or request.host_url.rstrip("/") + "/api/auth/oidc/callback"


def _frontend_url() -> str:
    return (settings.OIDC_FRONTEND_URL or "").rstrip("/") or "/"


def _state_cookie_secure() -> bool:
    """Mark the state cookie ``Secure`` when the app is served over HTTPS."""
    return (settings.OIDC_FRONTEND_URL or "").lower().startswith("https")


def _frontend_redirect(fragment: str):
    base = (settings.OIDC_FRONTEND_URL or "").rstrip("/")
    return redirect(f"{base}/#{fragment}", code=302)


def _no_store(payload, status: int = 200) -> Response:
    """Build a response marked non-cacheable (back-channel logout requirement)."""
    response = make_response(payload, status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _allowed_groups() -> list[str]:
    """Parse the comma-separated group allowlist; empty/unset means everyone."""
    raw = settings.OIDC_ALLOWED_GROUPS or ""
    return [group.strip() for group in raw.split(",") if group.strip()]


def _claim_groups(claims: dict) -> list[str]:
    """Read the groups claim as a list of strings; missing means no groups."""
    value = claims.get(settings.OIDC_GROUPS_CLAIM)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(member) for member in value]
    return [str(value)]


def _effective_claims(tokens: dict, claims: dict) -> dict:
    """Merge userinfo into the id_token claims when required claims are missing."""
    effective = dict(claims)
    need_user_id = not effective.get(settings.OIDC_USER_ID_CLAIM)
    need_groups = bool(_allowed_groups()) and settings.OIDC_GROUPS_CLAIM not in effective
    if not (need_user_id or need_groups) or not tokens.get("access_token"):
        return effective
    try:
        userinfo = provider.fetch_userinfo(tokens["access_token"])
    except provider.OIDCError:
        logger.warning("OIDC userinfo fetch failed; continuing with id_token claims", exc_info=True)
        return effective
    if userinfo.get("sub") != claims.get("sub"):
        raise provider.OIDCError("userinfo sub does not match id_token sub")
    for key, value in userinfo.items():
        effective.setdefault(key, value)
    return effective


def _mint_session_token(identity: dict) -> tuple[str, str]:
    """Mint the local HS256 session JWT for ``identity``; returns (token, jti)."""
    now = int(time.time())
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(identity["sub"]),
        "jti": jti,
        "iat": now,
        "exp": now + settings.OIDC_SESSION_LIFETIME_SECONDS,
    }
    if identity.get("oidc_sub"):
        payload["oidc_sub"] = str(identity["oidc_sub"])
    if identity.get("oidc_sid"):
        payload["oidc_sid"] = str(identity["oidc_sid"])
    for claim in ("email", "name"):
        if identity.get(claim):
            payload[claim] = identity[claim]
    picture = identity.get("picture")
    if picture and isinstance(picture, str) and len(picture) < MAX_PICTURE_CLAIM_CHARS:
        payload["picture"] = picture
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256"), jti


def _record_login_denied(user_id: str, metadata: dict) -> None:
    """Best-effort audit of a denied login; never raises."""
    try:
        with db_session() as conn:
            AuthEventsRepository(conn).insert(
                user_id,
                "oidc_login_denied",
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
                metadata=metadata,
            )
    except Exception:
        logger.warning("Failed to record oidc_login_denied for %s", user_id, exc_info=True)


def _gate_and_audit_login(user_id: str, effective: dict, groups: list[str]) -> bool:
    """Reject disabled users, provision new ones, audit the login.

    Returns False only when the user row was readable and marked inactive;
    a DB outage logs an error and lets the login proceed.
    """
    disabled = False
    try:
        with db_session() as conn:
            users = UsersRepository(conn)
            row = users.get(user_id)
            if row is not None and row.get("active") is False:
                disabled = True
                AuthEventsRepository(conn).insert(
                    user_id,
                    "oidc_login_denied",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata={"reason": "account_disabled"},
                )
            else:
                if row is None:
                    users.upsert(user_id)
                AuthEventsRepository(conn).insert(
                    user_id,
                    "oidc_login",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata={"email": effective.get("email"), "groups": groups or None},
                )
    except Exception:
        logger.error(
            "OIDC provisioning/audit failed for %s%s",
            user_id,
            "" if disabled else "; continuing login",
            exc_info=True,
        )
    return not disabled


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
    response = redirect(f"{authorization_endpoint}?{urlencode(params)}", code=302)
    # Bind this login to the browser: the callback rejects any state that
    # isn't echoed by this cookie, so a code+state captured from another
    # browser (login CSRF / session fixation) can't complete the flow.
    response.set_cookie(
        STATE_COOKIE_NAME,
        state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=_state_cookie_secure(),
        samesite="Lax",
        path=STATE_COOKIE_PATH,
    )
    return response


def oidc_callback():
    """Validate the IdP response, mint a session JWT, redirect with a handoff code."""
    if request.args.get("error"):
        return _frontend_redirect("oidc_error=" + quote(request.args["error"]))
    state = request.args.get("state")
    code = request.args.get("code")
    if not state or not code:
        return _frontend_redirect("oidc_error=invalid_state")

    # Browser binding: the state must match the cookie set at login. Without
    # this, an attacker could feed a victim a code+state from the attacker's
    # own login and silently sign the victim into the attacker's account.
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    if not cookie_state or not hmac.compare_digest(cookie_state, state):
        logger.warning("OIDC callback rejected: state cookie missing or mismatched")
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
        effective = _effective_claims(tokens, claims)
    except (provider.OIDCError, KeyError):
        logger.error("OIDC callback failed", exc_info=True)
        return _frontend_redirect("oidc_error=auth_failed")

    user_id = effective.get(settings.OIDC_USER_ID_CLAIM)
    if not user_id:
        logger.error("OIDC id_token missing user id claim %r", settings.OIDC_USER_ID_CLAIM)
        return _frontend_redirect("oidc_error=missing_claim")
    user_id = str(user_id)

    allowed = _allowed_groups()
    groups = _claim_groups(effective)
    if allowed and not set(groups) & set(allowed):
        logger.info("OIDC login denied for %s: groups %s not in allowlist", user_id, groups)
        _record_login_denied(user_id, {"reason": "not_authorized", "groups": groups})
        return _frontend_redirect("oidc_error=not_authorized")

    if not _gate_and_audit_login(user_id, effective, groups):
        return _frontend_redirect("oidc_error=account_disabled")

    # No need to lift prior revocations here: the denylist keys on a revocation
    # timestamp and the session minted below carries a newer ``iat``, so it is
    # allowed automatically while still-live sessions revoked on other devices
    # stay denied.
    session_token, jti = _mint_session_token(
        {
            "sub": user_id,
            "email": effective.get("email"),
            "name": effective.get("name"),
            "picture": effective.get("picture"),
            "oidc_sub": claims["sub"],
            "oidc_sid": claims.get("sid"),
        }
    )

    refresh_token = tokens.get("refresh_token")
    if refresh_token:
        try:
            redis.set(_refresh_key(jti), refresh_token, ex=settings.OIDC_SESSION_LIFETIME_SECONDS)
        except Exception:
            logger.warning("Failed to store OIDC refresh token", exc_info=True)

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


def _is_account_disabled(user_id: str) -> bool:
    """True only when a readable user row is marked inactive (DB outage fails open)."""
    try:
        with db_readonly() as conn:
            row = UsersRepository(conn).get(user_id)
    except Exception:
        logger.error("User lookup failed during OIDC refresh", exc_info=True)
        return False
    return bool(row is not None and row.get("active") is False)


def oidc_refresh():
    """Rotate the stored IdP refresh token and mint a fresh session JWT."""
    decoded = handle_auth(request)
    if (
        not isinstance(decoded, dict)
        or "error" in decoded
        or not decoded.get("sub")
        or not decoded.get("jti")
    ):
        error = "invalid_token"
        if isinstance(decoded, dict) and decoded.get("error") == "token_expired":
            error = "token_expired"
        return make_response(jsonify({"error": error}), 401)

    if denylist.is_denied(decoded):
        return make_response(jsonify({"error": "token_revoked"}), 401)

    # Gate the current session identity before spending the refresh token.
    if _is_account_disabled(str(decoded["sub"])):
        return make_response(jsonify({"error": "account_disabled"}), 401)

    redis = get_redis_instance()
    if redis is None:
        return make_response(jsonify({"error": "redis_unavailable"}), 503)
    raw = redis.getdel(_refresh_key(str(decoded["jti"])))
    if raw is None:
        return make_response(jsonify({"error": "no_refresh_token"}), 404)
    refresh_token = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    try:
        tokens = provider.refresh_grant(refresh_token)
    except provider.OIDCTransientError:
        # IdP unreachable / 5xx — the refresh token is still valid. Put it back
        # and tell the client to retry instead of killing a live session over a
        # transient blip (the frontend reschedules a renewal on 503).
        try:
            redis.set(
                _refresh_key(str(decoded["jti"])),
                refresh_token,
                ex=settings.OIDC_SESSION_LIFETIME_SECONDS,
            )
        except Exception:
            logger.warning("Failed to restore refresh token after transient error", exc_info=True)
        logger.warning("OIDC refresh grant failed transiently", exc_info=True)
        return make_response(jsonify({"error": "refresh_unavailable"}), 503)
    except provider.OIDCError:
        # invalid_grant / 4xx — the refresh token is spent or revoked; leave it
        # consumed so the client falls back to a fresh login.
        logger.warning("OIDC refresh grant rejected", exc_info=True)
        return make_response(jsonify({"error": "refresh_failed"}), 401)

    identity = {
        "sub": str(decoded["sub"]),
        "email": decoded.get("email"),
        "name": decoded.get("name"),
        "picture": decoded.get("picture"),
        "oidc_sub": decoded.get("oidc_sub"),
        "oidc_sid": decoded.get("oidc_sid"),
    }
    id_token = tokens.get("id_token")
    if id_token:
        try:
            claims = provider.validate_id_token(id_token, nonce=None)
            effective = _effective_claims(tokens, claims)
        except provider.OIDCError:
            logger.warning("Refresh-issued id_token failed validation", exc_info=True)
            return make_response(jsonify({"error": "refresh_failed"}), 401)
        # Re-gate group membership on every renewal that carries fresh
        # claims — otherwise removal from the allowlist would never bite
        # while silent renewal keeps extending the session.
        allowed = _allowed_groups()
        groups = _claim_groups(effective)
        if allowed and not (set(groups) & set(allowed)):
            denied_user = str(effective.get(settings.OIDC_USER_ID_CLAIM) or decoded["sub"])
            logger.info("OIDC refresh denied for %s: groups %s not allowed", denied_user, groups)
            _record_login_denied(
                denied_user,
                {"reason": "not_authorized", "via": "refresh", "groups": groups},
            )
            return make_response(jsonify({"error": "not_authorized"}), 401)
        user_id = effective.get(settings.OIDC_USER_ID_CLAIM)
        if user_id:
            user_id = str(user_id)
            # The pre-grant gate only saw the old sub. If the refreshed identity
            # maps to a different user id, re-check that account is enabled
            # before minting a session for it.
            if user_id != str(decoded["sub"]) and _is_account_disabled(user_id):
                return make_response(jsonify({"error": "account_disabled"}), 401)
            identity["sub"] = user_id
        for claim in ("email", "name", "picture"):
            if effective.get(claim):
                identity[claim] = effective[claim]
        identity["oidc_sub"] = effective.get("sub") or identity["oidc_sub"]
        if effective.get("sid"):
            identity["oidc_sid"] = effective["sid"]

    # Re-check revocation right before minting, against the (possibly remapped)
    # identity but with the ORIGINAL session's iat: a back-channel logout or
    # SCIM deny that landed during the IdP grant — or one targeting the
    # refreshed sub/sid — sets a watermark newer than this iat and must block
    # renewal. The renewed token's own (fresh) iat would post-date the
    # watermark and slip past the per-request check, so anchor on the old iat.
    if denylist.is_denied(
        {
            "sub": identity["sub"],
            "oidc_sub": identity.get("oidc_sub"),
            "oidc_sid": identity.get("oidc_sid"),
            "iat": decoded.get("iat"),
        }
    ):
        return make_response(jsonify({"error": "token_revoked"}), 401)

    new_token, new_jti = _mint_session_token(identity)
    new_refresh = tokens.get("refresh_token") or refresh_token
    try:
        redis.set(_refresh_key(new_jti), new_refresh, ex=settings.OIDC_SESSION_LIFETIME_SECONDS)
    except Exception:
        logger.warning("Failed to store rotated OIDC refresh token", exc_info=True)

    try:
        with db_session() as conn:
            AuthEventsRepository(conn).insert(
                identity["sub"],
                "oidc_refresh",
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
    except Exception:
        logger.warning("Failed to record oidc_refresh for %s", identity["sub"], exc_info=True)

    return jsonify({"token": new_token})


def oidc_backchannel_logout():
    """Revoke sessions named by a signed IdP back-channel logout token."""
    logout_token = request.form.get("logout_token")
    if not logout_token:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            logout_token = body.get("logout_token")
    if not logout_token or not isinstance(logout_token, str):
        return _no_store(jsonify({"error": "missing_logout_token"}), 400)

    try:
        claims = provider.validate_logout_token(logout_token)
    except provider.OIDCError:
        logger.warning("Rejected OIDC back-channel logout token", exc_info=True)
        return _no_store(jsonify({"error": "invalid_logout_token"}), 400)

    # Reject stale tokens: past the jti replay-cache window we can no longer
    # detect replays by jti, so bound acceptance to that window (logout tokens
    # are short-lived). Combined with the always-on jti check below, a captured
    # token can be replayed neither within the window (jti dedupe) nor after it
    # (iat too old).
    now = int(time.time())
    iat = claims.get("iat")
    if not isinstance(iat, (int, float)) or now - iat > LOGOUT_JTI_TTL_SECONDS:
        logger.warning("Rejected stale OIDC back-channel logout token")
        return _no_store(jsonify({"error": "invalid_logout_token"}), 400)

    jti = claims.get("jti")
    redis = get_redis_instance()
    if redis is not None and jti:
        try:
            fresh = redis.set(_logout_jti_key(str(jti)), "1", ex=LOGOUT_JTI_TTL_SECONDS, nx=True)
        except Exception:
            logger.warning("Logout-token jti replay check failed; accepting token", exc_info=True)
            fresh = True
        if not fresh:
            return _no_store(jsonify({"error": "invalid_logout_token"}), 400)

    sub = claims.get("sub")
    sid = claims.get("sid")
    revoked = True
    if sub:
        revoked = bool(denylist.deny_idp_sub(str(sub))) and revoked
    if sid:
        revoked = bool(denylist.deny_sid(str(sid))) and revoked
    if not revoked:
        # The denylist write failed (Redis down). Report failure so the IdP
        # retries rather than recording a logout that never took effect.
        logger.error("Back-channel logout could not persist the revocation")
        return _no_store(jsonify({"error": "revocation_unavailable"}), 502)

    user_id = str(sub) if sub else f"sid:{sid}"
    try:
        with db_session() as conn:
            AuthEventsRepository(conn).insert(
                user_id,
                "backchannel_logout",
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
                metadata={"sid": str(sid)} if sid else None,
            )
    except Exception:
        logger.warning("Failed to record backchannel_logout for %s", user_id, exc_info=True)

    return _no_store("", 200)


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


def _require_oidc_enabled() -> Response | None:
    """404 every oidc route unless OIDC is the active auth mode.

    Registration is unconditional (so the import-time auth mode doesn't matter),
    but the endpoints only work under ``AUTH_TYPE=oidc`` — otherwise OIDC_ISSUER
    is unset and ``get_discovery`` would dereference ``None`` and 500. Mirrors
    SCIM's ``SCIM_ENABLED`` gate.
    """
    if settings.AUTH_TYPE != "oidc":
        return make_response(jsonify({"error": "oidc_not_enabled"}), 404)
    return None


def register(bp: Blueprint) -> None:
    """Attach the oidc auth routes to ``bp``."""
    bp.before_request(_require_oidc_enabled)
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
        "/api/auth/oidc/refresh", view_func=oidc_refresh, methods=["POST"], endpoint="refresh"
    )
    bp.add_url_rule(
        "/api/auth/oidc/backchannel-logout",
        view_func=oidc_backchannel_logout,
        methods=["POST"],
        endpoint="backchannel_logout",
    )
    bp.add_url_rule(
        "/api/auth/oidc/logout", view_func=oidc_logout, methods=["GET"], endpoint="logout"
    )
