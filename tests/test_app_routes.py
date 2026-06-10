"""Tests for application/app.py route handlers."""

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def app():
    """Import the Flask app with auth mocked to avoid JWT setup issues."""
    with patch("application.app.handle_auth", return_value={"sub": "test_user"}):
        from application.app import app as flask_app
        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHomeRoute:

    @pytest.mark.unit
    def test_root_returns_200(self, client):
        """Root serves Swagger UI via Flask-RESTX."""
        response = client.get("/")
        assert response.status_code == 200


class TestHealthRoute:

    @pytest.mark.unit
    def test_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "ok"


class TestConfigRoute:

    @pytest.mark.unit
    def test_returns_auth_config(self, client):
        # Pin AUTH_TYPE so the assertion doesn't depend on the dev .env.
        with patch("application.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = None
            response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "auth_type" in data
        assert "requires_auth" in data
        assert "oidc" not in data

    @pytest.mark.unit
    def test_oidc_config_exposes_login_paths(self, client):
        with patch("application.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.OIDC_PROVIDER_NAME = "Test SSO"
            response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["auth_type"] == "oidc"
        assert data["requires_auth"] is True
        assert data["oidc"] == {
            "login_path": "/api/auth/oidc/login",
            "logout_path": "/api/auth/oidc/logout",
            "provider_name": "Test SSO",
        }


class TestGenerateTokenRoute:

    @pytest.mark.unit
    def test_session_jwt_generates_token(self, client, app):
        with patch("application.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "session_jwt"
            mock_settings.JWT_SECRET_KEY = "test_secret"
            response = client.get("/api/generate_token")
            assert response.status_code == 200
            data = json.loads(response.data)
            assert "token" in data

    @pytest.mark.unit
    def test_non_session_jwt_returns_error(self, client, app):
        with patch("application.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "none"
            response = client.get("/api/generate_token")
            assert response.status_code == 400


class TestSttRequestSizeLimits:

    @pytest.mark.unit
    def test_non_stt_request_passes(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_oversized_stt_request_rejected(self, client):
        with patch("application.app.should_reject_stt_request", return_value=True), \
             patch("application.app.build_stt_file_size_limit_message", return_value="Too large"):
            response = client.post("/api/stt/upload", data=b"x" * 100)
            assert response.status_code == 413


class TestAuthenticateRequest:

    @pytest.mark.unit
    def test_options_returns_200(self, client):
        response = client.options("/api/health")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_auth_error_returns_401(self, client, app):
        with patch("application.app.handle_auth", return_value={"error": "Invalid token"}):
            response = client.get("/api/health")
            assert response.status_code == 401

    @pytest.mark.unit
    def test_no_token_sets_none(self, client, app):
        with patch("application.app.handle_auth", return_value=None):
            response = client.get("/api/health")
            assert response.status_code == 200

    @pytest.mark.unit
    def test_oidc_auth_paths_exempt_from_jwt_check(self, client, app):
        # A stale/expired Bearer header must never 401 the oidc login
        # endpoints — they are the only path back to a fresh session. The oidc
        # routes are only live under AUTH_TYPE=oidc, so pin it here.
        from application.core.settings import settings as _settings

        with patch(
            "application.app.handle_auth", return_value={"error": "invalid_token"}
        ), patch(
            "application.api.oidc.routes.get_redis_instance", return_value=None
        ), patch.object(_settings, "AUTH_TYPE", "oidc"):
            response = client.get(
                "/api/auth/oidc/login", headers={"Authorization": "Bearer garbage"}
            )
        assert response.status_code == 503  # redis guard, not a 401


class TestFlaskCors:

    @pytest.mark.unit
    def test_cors_headers_on_flask_route(self, client):
        response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert response.headers["Access-Control-Allow-Headers"] == (
            "Content-Type, Authorization, Idempotency-Key"
        )
        assert response.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT, PATCH, DELETE, OPTIONS"

    @pytest.mark.unit
    def test_cors_headers_on_flask_preflight(self, client):
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert response.headers["Access-Control-Allow-Headers"] == (
            "Content-Type, Authorization, Idempotency-Key"
        )
        assert response.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT, PATCH, DELETE, OPTIONS"
