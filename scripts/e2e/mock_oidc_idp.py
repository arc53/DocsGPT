"""Mock OpenID Connect provider for the DocsGPT e2e suite and local dev.

Speaks the minimum OIDC surface the backend's ``AUTH_TYPE=oidc`` flow needs:

* ``GET /.well-known/openid-configuration`` (discovery)
* ``GET /authorize`` (auto-approves and redirects back with a code)
* ``POST /token`` (single-use code + PKCE S256 check, RS256 ``id_token``)
* ``GET /jwks`` (public key for ID-token verification)
* ``GET /end-session`` (honors ``post_logout_redirect_uri``)
* ``GET /healthz`` (liveness probe)

There is no login form: every ``/authorize`` request is approved as the user
configured via ``MOCK_OIDC_SUB`` / ``MOCK_OIDC_EMAIL`` (overridable per
request with ``?sub=``/``?email=`` for multi-user tests).

Run standalone (does NOT import anything from ``application/``). Dependencies
(flask, python-jose, cryptography) are all in ``application/requirements.txt``.

Usage::

    python scripts/e2e/mock_oidc_idp.py

Defaults to ``127.0.0.1:7999`` to match ``scripts/e2e/env.sh``'s
``OIDC_ISSUER`` default for ``AUTH_TYPE=oidc`` runs.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import time
from urllib.parse import urlencode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask, Response, jsonify, redirect, request
from jose import jwk
from jose import jwt as jose_jwt

HOST = os.environ.get("MOCK_OIDC_HOST", "127.0.0.1")
PORT = int(os.environ.get("MOCK_OIDC_PORT", "7999"))
ISSUER = f"http://{HOST}:{PORT}"
DEFAULT_SUB = os.environ.get("MOCK_OIDC_SUB", "mock-oidc-user")
DEFAULT_EMAIL = os.environ.get("MOCK_OIDC_EMAIL", "mock-oidc-user@example.com")
DEFAULT_NAME = os.environ.get("MOCK_OIDC_NAME", "Mock OIDC User")
ID_TOKEN_TTL_SECONDS = 300
KID = "mock-oidc-key-1"

app = Flask(__name__)

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("ascii")
PUBLIC_JWK = {
    **jwk.construct(PRIVATE_PEM, algorithm="RS256").public_key().to_dict(),
    "kid": KID,
    "use": "sig",
}

# code -> {client_id, redirect_uri, code_challenge, nonce, sub, email, name}
_codes: dict[str, dict] = {}


def _log(message: str) -> None:
    sys.stderr.write(f"[mock-oidc] {message}\n")
    sys.stderr.flush()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@app.get("/.well-known/openid-configuration")
def discovery() -> Response:
    return jsonify(
        {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "jwks_uri": f"{ISSUER}/jwks",
            "end_session_endpoint": f"{ISSUER}/end-session",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["openid", "profile", "email"],
        }
    )


@app.get("/jwks")
def jwks() -> Response:
    return jsonify({"keys": [PUBLIC_JWK]})


@app.get("/authorize")
def authorize() -> Response:
    args = request.args
    missing = [
        name
        for name in ("client_id", "redirect_uri", "code_challenge", "state")
        if not args.get(name)
    ]
    if missing:
        return Response(f"missing params: {', '.join(missing)}", status=400)
    if args.get("response_type") != "code":
        return Response("unsupported response_type", status=400)
    if args.get("code_challenge_method") != "S256":
        return Response("unsupported code_challenge_method", status=400)

    code = secrets.token_urlsafe(24)
    _codes[code] = {
        "client_id": args["client_id"],
        "redirect_uri": args["redirect_uri"],
        "code_challenge": args["code_challenge"],
        "nonce": args.get("nonce"),
        "sub": args.get("sub") or DEFAULT_SUB,
        "email": args.get("email") or DEFAULT_EMAIL,
        "name": DEFAULT_NAME,
    }
    _log(f"authorize: auto-approved sub={_codes[code]['sub']}")
    separator = "&" if "?" in args["redirect_uri"] else "?"
    query = urlencode({"code": code, "state": args["state"]})
    return redirect(f"{args['redirect_uri']}{separator}{query}", code=302)


@app.post("/token")
def token() -> Response:
    form = request.form
    if form.get("grant_type") != "authorization_code":
        return jsonify({"error": "unsupported_grant_type"}), 400
    record = _codes.pop(form.get("code", ""), None)  # single-use
    if record is None:
        _log("token: unknown or replayed code")
        return jsonify({"error": "invalid_grant"}), 400
    if form.get("redirect_uri") != record["redirect_uri"]:
        return jsonify({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}), 400
    if form.get("client_id") != record["client_id"]:
        return jsonify({"error": "invalid_client"}), 400
    verifier = form.get("code_verifier", "")
    if not verifier or _pkce_challenge(verifier) != record["code_challenge"]:
        _log("token: PKCE verification failed")
        return jsonify({"error": "invalid_grant", "error_description": "PKCE failed"}), 400

    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": record["client_id"],
        "sub": record["sub"],
        "email": record["email"],
        "name": record["name"],
        "iat": now,
        "exp": now + ID_TOKEN_TTL_SECONDS,
    }
    if record["nonce"]:
        claims["nonce"] = record["nonce"]
    id_token = jose_jwt.encode(claims, PRIVATE_PEM, algorithm="RS256", headers={"kid": KID})
    _log(f"token: issued id_token for sub={record['sub']}")
    return jsonify(
        {
            "access_token": secrets.token_urlsafe(24),
            "token_type": "Bearer",
            "expires_in": ID_TOKEN_TTL_SECONDS,
            "id_token": id_token,
        }
    )


@app.get("/end-session")
def end_session() -> Response:
    target = request.args.get("post_logout_redirect_uri")
    _log(f"end-session: redirect={target or '<none>'}")
    if target:
        return redirect(target, code=302)
    return Response("Signed out of mock IdP.", status=200, mimetype="text/plain")


@app.get("/healthz")
def healthz() -> Response:
    return jsonify({"ok": True})


def main() -> None:
    _log(f"listening on {ISSUER} (sub={DEFAULT_SUB})")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
