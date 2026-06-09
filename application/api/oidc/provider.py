"""OIDC provider client: discovery, JWKS, token grants, ID/logout-token validation."""

from __future__ import annotations

import logging
import threading
import time

import requests
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

from application.core.settings import settings

logger = logging.getLogger(__name__)

DISCOVERY_TTL_SECONDS = 3600
FORCE_REFETCH_COOLDOWN_SECONDS = 10
LEEWAY_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"
# Asymmetric algorithms only: a symmetric alg here would let an attacker
# forge ID tokens signed with the (public) JWKS material.
ALLOWED_ID_TOKEN_ALGS = [
    "RS256", "RS384", "RS512",
    "ES256", "ES384", "ES512",
    "PS256", "PS384", "PS512",
]

_lock = threading.Lock()
_cache: dict = {
    "discovery": None,
    "discovery_at": 0.0,
    "jwks": None,
    "jwks_at": 0.0,
    "jwks_force_at": 0.0,
}


class OIDCError(Exception):
    """Raised when an OIDC flow step fails."""


def reset_cache() -> None:
    """Clear the cached discovery document and JWKS (used by tests)."""
    with _lock:
        _cache.update(
            {"discovery": None, "discovery_at": 0.0, "jwks": None, "jwks_at": 0.0, "jwks_force_at": 0.0}
        )


def _fetch_json(url: str) -> dict:
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise OIDCError(f"OIDC request to {url} failed: {exc}") from exc
    if response.status_code != 200:
        raise OIDCError(f"OIDC request to {url} returned {response.status_code}")
    return response.json()


def get_discovery() -> dict:
    """Return the IdP discovery document, fetching/caching it per process."""
    with _lock:
        if _cache["discovery"] is not None and time.time() - _cache["discovery_at"] < DISCOVERY_TTL_SECONDS:
            return _cache["discovery"]
    url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    document = _fetch_json(url)
    with _lock:
        _cache["discovery"] = document
        _cache["discovery_at"] = time.time()
    return document


def get_jwks(force: bool = False) -> dict:
    """Return the IdP JWKS; ``force=True`` bypasses the cache (key rotation)."""
    with _lock:
        fresh = (
            _cache["jwks"] is not None
            and time.time() - _cache["jwks_at"] < DISCOVERY_TTL_SECONDS
        )
        if not force and fresh:
            return _cache["jwks"]
        if force and fresh:
            # Rate-limit forced refetches: unauthenticated callers (back-channel
            # logout) must not be able to hammer the IdP through us.
            if time.time() - _cache["jwks_force_at"] < FORCE_REFETCH_COOLDOWN_SECONDS:
                return _cache["jwks"]
            _cache["jwks_force_at"] = time.time()
    jwks = _fetch_json(get_discovery()["jwks_uri"])
    with _lock:
        _cache["jwks"] = jwks
        _cache["jwks_at"] = time.time()
    return jwks


def _find_key(kid: str | None) -> dict | None:
    keys = get_jwks().get("keys", [])
    if kid is None:
        return keys[0] if len(keys) == 1 else None
    return next((key for key in keys if key.get("kid") == kid), None)


def _resolve_signing_key(token: str) -> dict:
    """Return the JWKS key matching the token header, refetching once on unknown kid."""
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise OIDCError(f"Malformed token: {exc}") from exc
    if header.get("alg") not in ALLOWED_ID_TOKEN_ALGS:
        raise OIDCError(f"Disallowed token alg: {header.get('alg')}")

    key = _find_key(header.get("kid"))
    if key is None:
        get_jwks(force=True)
        key = _find_key(header.get("kid"))
    if key is None:
        raise OIDCError("No matching key in IdP JWKS")
    return key


def _decode_verified(token: str, options: dict) -> dict:
    """Decode ``token`` against the JWKS, retrying once if the IdP re-keyed.

    A signature failure can mean the IdP replaced its signing key while
    reusing the same kid — the kid-miss refetch never triggers then, so
    retry once against a freshly fetched JWKS (rate-limited in get_jwks).
    """
    key = _resolve_signing_key(token)
    decode_kwargs = {
        "algorithms": ALLOWED_ID_TOKEN_ALGS,
        "audience": settings.OIDC_CLIENT_ID,
        # Compare against the discovery document's own issuer value —
        # some IdPs (Authentik) use a trailing slash the operator may
        # not have typed into OIDC_ISSUER.
        "issuer": get_discovery()["issuer"],
        "options": options,
    }
    try:
        return jwt.decode(token, key, **decode_kwargs)
    except (ExpiredSignatureError, JWTClaimsError) as exc:
        raise OIDCError(f"token validation failed: {exc}") from exc
    except Exception:
        get_jwks(force=True)
        key = _find_key(jwt.get_unverified_header(token).get("kid"))
        if key is None:
            raise OIDCError("No matching key in IdP JWKS")
        try:
            return jwt.decode(token, key, **decode_kwargs)
        except Exception as exc:
            raise OIDCError(f"token validation failed: {exc}") from exc


def validate_id_token(id_token: str, nonce: str | None = None) -> dict:
    """Verify the ID token's signature, iss, aud, exp, and (when given) nonce; return claims."""
    claims = _decode_verified(
        id_token,
        options={
            "verify_at_hash": False,
            "leeway": LEEWAY_SECONDS,
            "require_iss": True,
            "require_aud": True,
            "require_exp": True,
            "require_sub": True,
        },
    )
    # Refresh-issued id_tokens carry no nonce; callers pass None to skip the check.
    if nonce is not None and claims.get("nonce") != nonce:
        raise OIDCError("nonce mismatch")
    return claims


def validate_logout_token(logout_token: str) -> dict:
    """Verify a back-channel logout token per OIDC Back-Channel Logout 1.0; return claims."""
    claims = _decode_verified(
        logout_token,
        options={
            "verify_at_hash": False,
            "leeway": LEEWAY_SECONDS,
            "require_iss": True,
            "require_aud": True,
            "require_iat": True,
            "require_exp": False,
        },
    )
    events = claims.get("events")
    if not isinstance(events, dict) or BACKCHANNEL_LOGOUT_EVENT not in events:
        raise OIDCError("logout_token missing the backchannel-logout event")
    if "nonce" in claims:
        raise OIDCError("logout_token must not contain a nonce")
    if not claims.get("sub") and not claims.get("sid"):
        raise OIDCError("logout_token must contain sub or sid")
    return claims


def _token_request(data: dict) -> dict:
    """POST to the token endpoint using the discovery-advertised client auth method."""
    discovery = get_discovery()
    data = {**data, "client_id": settings.OIDC_CLIENT_ID}
    post_kwargs: dict = {"data": data, "timeout": HTTP_TIMEOUT_SECONDS}
    if settings.OIDC_CLIENT_SECRET:
        # Absent metadata means the RFC 8414 default, client_secret_basic.
        methods = discovery.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        if "client_secret_post" in methods:
            data["client_secret"] = settings.OIDC_CLIENT_SECRET
        else:
            post_kwargs["auth"] = (settings.OIDC_CLIENT_ID, settings.OIDC_CLIENT_SECRET)
    try:
        response = requests.post(discovery["token_endpoint"], **post_kwargs)
    except requests.RequestException as exc:
        raise OIDCError(f"Token request failed: {exc}") from exc
    if response.status_code != 200:
        logger.error(
            "OIDC token request failed (%s): %s", response.status_code, response.text[:500]
        )
        raise OIDCError(f"Token endpoint returned {response.status_code}")
    return response.json()


def exchange_code(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Exchange the authorization code at the IdP token endpoint."""
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    )


def refresh_grant(refresh_token: str) -> dict:
    """Redeem a refresh token at the IdP token endpoint."""
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


def fetch_userinfo(access_token: str) -> dict:
    """Fetch claims from the IdP userinfo endpoint with a Bearer access token."""
    endpoint = get_discovery().get("userinfo_endpoint")
    if not endpoint:
        raise OIDCError("No userinfo_endpoint in discovery document")
    try:
        response = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise OIDCError(f"userinfo request failed: {exc}") from exc
    if response.status_code != 200:
        raise OIDCError(f"userinfo endpoint returned {response.status_code}")
    return response.json()
