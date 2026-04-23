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
        response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "auth_type" in data
        assert "requires_auth" in data


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


class TestFlaskCors:

    @pytest.mark.unit
    def test_cors_headers_on_flask_route(self, client):
        response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert response.headers["Access-Control-Allow-Headers"] == "Content-Type, Authorization"
        assert response.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT, DELETE, OPTIONS"

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
        assert response.headers["Access-Control-Allow-Headers"] == "Content-Type, Authorization"
        assert response.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT, DELETE, OPTIONS"
