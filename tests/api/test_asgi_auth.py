"""Tests for ``docsgpt/api/asgi_auth.py`` — auth shared by the Starlette routes.

The helper must gate a native-async route exactly like ``authenticate_request``
gates a Flask one: same decoder, same 401 payloads, same OIDC revocation check.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from jose import jwt
from starlette.requests import Request

from docsgpt.api import asgi_auth
from docsgpt.core import log_context


def _request(headers: dict | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": raw, "query_string": b""}
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuthenticate:
    async def test_local_mode_resolves_local_user(self, monkeypatch):
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", None)
        decoded, error = await asgi_auth.authenticate(_request())
        assert error is None
        assert decoded == {"sub": "local"}

    async def test_missing_token_is_anonymous_not_rejected(self, monkeypatch):
        # Flask leaves ``decoded_token`` None here and lets the route decide
        # (a share token can still authorize an artifact download).
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", "simple_jwt")
        decoded, error = await asgi_auth.authenticate(_request())
        assert decoded is None
        assert error is None

    async def test_invalid_token_rejected_with_decoder_payload(self, monkeypatch):
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", "simple_jwt")
        monkeypatch.setattr(asgi_auth.settings, "JWT_SECRET_KEY", "test-secret")
        decoded, error = await asgi_auth.authenticate(
            _request({"Authorization": "Bearer not-a-jwt"})
        )
        assert decoded is None
        assert error.status_code == 401
        assert json.loads(error.body) == {
            "message": "Authentication error: invalid token",
            "error": "invalid_token",
        }

    async def test_valid_token_decoded(self, monkeypatch):
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", "simple_jwt")
        monkeypatch.setattr(asgi_auth.settings, "JWT_SECRET_KEY", "test-secret")
        token = jwt.encode({"sub": "alice"}, "test-secret", algorithm="HS256")
        decoded, error = await asgi_auth.authenticate(
            _request({"Authorization": f"Bearer {token}"})
        )
        assert error is None
        assert decoded["sub"] == "alice"

    async def test_revoked_oidc_session_rejected(self, monkeypatch):
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", "oidc")
        claims = {"sub": "alice", "iat": 1}
        with patch.object(asgi_auth, "handle_auth", return_value=claims), patch.object(
            asgi_auth, "oidc_session_denied", return_value=True
        ) as denied:
            decoded, error = await asgi_auth.authenticate(_request())
        assert decoded is None
        assert error.status_code == 401
        assert json.loads(error.body) == {
            "message": "Authentication error: session revoked",
            "error": "token_revoked",
        }
        denied.assert_called_once_with(claims)

    async def test_live_oidc_session_passes(self, monkeypatch):
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", "oidc")
        with patch.object(
            asgi_auth, "handle_auth", return_value={"sub": "alice", "iat": 1}
        ), patch.object(asgi_auth, "oidc_session_denied", return_value=False):
            decoded, error = await asgi_auth.authenticate(_request())
        assert error is None
        assert decoded["sub"] == "alice"

    async def test_denylist_only_consulted_for_oidc(self, monkeypatch):
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", "simple_jwt")
        with patch.object(
            asgi_auth, "handle_auth", return_value={"sub": "alice"}
        ), patch.object(asgi_auth, "oidc_session_denied") as denied:
            await asgi_auth.authenticate(_request())
        denied.assert_not_called()


@pytest.mark.unit
def test_bind_log_context_stamps_request_keys():
    token = asgi_auth.bind_log_context("event_stream", "alice")
    try:
        snap = log_context.snapshot()
        assert snap["endpoint"] == "event_stream"
        assert snap["user_id"] == "alice"
        assert snap["activity_id"]
    finally:
        log_context.reset(token)


@pytest.mark.unit
def test_json_error_shape():
    response = asgi_auth.json_error("Forbidden", 403)
    assert response.status_code == 403
    assert json.loads(response.body) == {"success": False, "message": "Forbidden"}


_PAT_CLAIMS = {
    "sub": "alice",
    "auth_method": "pat",
    "pat_id": "t1",
    "scopes": ["chat:run"],
    "resource_filter": {},
}


@pytest.mark.unit
@pytest.mark.asyncio
class TestPersonalAccessTokens:
    async def test_routes_reject_tokens_unless_they_name_a_scope(self):
        with patch.object(asgi_auth, "handle_auth", return_value=dict(_PAT_CLAIMS)):
            decoded, error = await asgi_auth.authenticate(_request())
        assert decoded is None
        assert error.status_code == 403
        assert json.loads(error.body)["error"] == "insufficient_scope"

    async def test_token_with_the_route_scope_passes(self):
        with patch.object(asgi_auth, "handle_auth", return_value=dict(_PAT_CLAIMS)):
            decoded, error = await asgi_auth.authenticate(_request(), pat_scope="chat:run")
        assert error is None
        assert decoded["sub"] == "alice"

    async def test_token_without_the_route_scope_is_refused(self):
        claims = dict(_PAT_CLAIMS, scopes=["agents:read"])
        with patch.object(asgi_auth, "handle_auth", return_value=claims):
            decoded, error = await asgi_auth.authenticate(_request(), pat_scope="chat:run")
        assert decoded is None
        assert error.status_code == 403

    async def test_session_denylist_is_not_consulted_for_tokens(self, monkeypatch):
        monkeypatch.setattr(asgi_auth.settings, "AUTH_TYPE", "oidc")
        with patch.object(asgi_auth, "handle_auth", return_value=dict(_PAT_CLAIMS)), patch.object(
            asgi_auth, "oidc_session_denied", return_value=True
        ) as denied:
            decoded, error = await asgi_auth.authenticate(_request(), pat_scope="chat:run")
        denied.assert_not_called()
        assert error is None and decoded is not None

    async def test_restricted_token_is_refused_even_with_the_scope(self):
        claims = dict(_PAT_CLAIMS, resource_filter={"agents": ["a1"]})
        with patch.object(asgi_auth, "handle_auth", return_value=claims):
            decoded, error = await asgi_auth.authenticate(_request(), pat_scope="chat:run")
        assert decoded is None
        assert error.status_code == 403
        assert json.loads(error.body)["error"] == "resource_not_allowed"
