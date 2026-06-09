"""OIDC provider client: discovery, JWKS, code exchange, ID-token validation."""

from __future__ import annotations

import logging
import threading
import time

import requests
from jose import jwt

from application.core.settings import settings

logger = logging.getLogger(__name__)

DISCOVERY_TTL_SECONDS = 3600
LEEWAY_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
# Asymmetric algorithms only: a symmetric alg here would let an attacker
# forge ID tokens signed with the (public) JWKS material.
ALLOWED_ID_TOKEN_ALGS = [
    "RS256", "RS384", "RS512",
    "ES256", "ES384", "ES512",
    "PS256", "PS384", "PS512",
]

_lock = threading.Lock()
_cache: dict = {"discovery": None, "discovery_at": 0.0, "jwks": None, "jwks_at": 0.0}


class OIDCError(Exception):
    """Raised when an OIDC flow step fails."""


def reset_cache() -> None:
    """Clear the cached discovery document and JWKS (used by tests)."""
    with _lock:
        _cache.update({"discovery": None, "discovery_at": 0.0, "jwks": None, "jwks_at": 0.0})


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
        if (
            not force
            and _cache["jwks"] is not None
            and time.time() - _cache["jwks_at"] < DISCOVERY_TTL_SECONDS
        ):
            return _cache["jwks"]
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


def validate_id_token(id_token: str, nonce: str) -> dict:
    """Verify the ID token's signature, iss, aud, exp, and nonce; return claims."""
    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as exc:
        raise OIDCError(f"Malformed id_token: {exc}") from exc
    if header.get("alg") not in ALLOWED_ID_TOKEN_ALGS:
        raise OIDCError(f"Disallowed id_token alg: {header.get('alg')}")

    key = _find_key(header.get("kid"))
    if key is None:
        get_jwks(force=True)
        key = _find_key(header.get("kid"))
    if key is None:
        raise OIDCError("No matching key in IdP JWKS")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=ALLOWED_ID_TOKEN_ALGS,
            audience=settings.OIDC_CLIENT_ID,
            # Compare against the discovery document's own issuer value —
            # some IdPs (Authentik) use a trailing slash the operator may
            # not have typed into OIDC_ISSUER.
            issuer=get_discovery()["issuer"],
            options={
                "verify_at_hash": False,
                "leeway": LEEWAY_SECONDS,
                "require_iss": True,
                "require_aud": True,
                "require_exp": True,
                "require_sub": True,
            },
        )
    except Exception as exc:
        raise OIDCError(f"id_token validation failed: {exc}") from exc
    if claims.get("nonce") != nonce:
        raise OIDCError("nonce mismatch")
    return claims


def exchange_code(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Exchange the authorization code at the IdP token endpoint."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.OIDC_CLIENT_ID,
        "code_verifier": code_verifier,
    }
    if settings.OIDC_CLIENT_SECRET:
        data["client_secret"] = settings.OIDC_CLIENT_SECRET
    try:
        response = requests.post(
            get_discovery()["token_endpoint"], data=data, timeout=HTTP_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise OIDCError(f"Token exchange request failed: {exc}") from exc
    if response.status_code != 200:
        logger.error(
            "OIDC token exchange failed (%s): %s", response.status_code, response.text[:500]
        )
        raise OIDCError(f"Token exchange returned {response.status_code}")
    return response.json()
