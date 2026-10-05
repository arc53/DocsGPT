"""Tests for docsgpt/app.py route handlers."""

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def app():
    """Import the Flask app with auth mocked to avoid JWT setup issues."""
    with patch("docsgpt.app.handle_auth", return_value={"sub": "test_user"}):
        from docsgpt.app import app as flask_app
        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHomeRoute:

    @pytest.mark.unit
    def test_root_redirects_to_the_swagger_ui(self, client):
        """On the bare API, root sends the caller to the Swagger UI."""
        response = client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/api/docs")


class TestSwaggerDocs:

    @pytest.mark.unit
    def test_swagger_ui_lives_under_the_api_prefix(self, client):
        response = client.get("/api/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["Content-Type"]
        assert b"swagger.json" in response.data

    @pytest.mark.unit
    def test_spec_stays_at_swagger_json(self, client):
        response = client.get("/swagger.json")
        assert response.status_code == 200
        assert json.loads(response.data)["info"]["title"] == "DocsGPT API"

    @pytest.mark.unit
    def test_swagger_ui_survives_the_bundled_web_ui(self, app, tmp_path):
        """With the web UI served at /, the Swagger UI is still reachable."""
        from a2wsgi import WSGIMiddleware
        from starlette.testclient import TestClient

        from docsgpt.ui import StaticUI

        (tmp_path / "index.html").write_text("<html><body>web ui</body></html>")
        wrapped = StaticUI.wrap(WSGIMiddleware(app), app.url_map, static_dir=tmp_path)
        assert isinstance(wrapped, StaticUI)
        with TestClient(wrapped) as ui_client:
            assert "web ui" in ui_client.get("/").text
            docs = ui_client.get("/api/docs")
            assert docs.status_code == 200
            assert "swagger.json" in docs.text and "web ui" not in docs.text
            assert ui_client.get("/swagger.json").status_code == 200


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
        with patch("docsgpt.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = None
            response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "auth_type" in data
        assert "requires_auth" in data
        assert "oidc" not in data

    @pytest.mark.unit
    def test_exposes_graphrag_available(self, client):
        with patch("docsgpt.app.settings") as mock_settings, patch(
            "docsgpt.graphrag.graphrag_available", return_value=True
        ):
            mock_settings.AUTH_TYPE = None
            response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["graphrag_available"] is True

    @pytest.mark.unit
    def test_graphrag_unavailable_when_flag_off(self, client):
        with patch("docsgpt.app.settings") as mock_settings, patch(
            "docsgpt.graphrag.graphrag_available", return_value=False
        ):
            mock_settings.AUTH_TYPE = None
            response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["graphrag_available"] is False

    @pytest.mark.unit
    def test_hybrid_available_when_pgvector(self, client):
        with patch("docsgpt.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = None
            mock_settings.VECTOR_STORE = "pgvector"
            response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["hybrid_available"] is True

    @pytest.mark.unit
    def test_hybrid_unavailable_when_not_pgvector(self, client):
        with patch("docsgpt.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = None
            mock_settings.VECTOR_STORE = "faiss"
            response = client.get("/api/config")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["hybrid_available"] is False

    @pytest.mark.unit
    def test_speech_features_available_by_default(self, client):
        with patch("docsgpt.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = None
            mock_settings.TTS_PROVIDER = "google_tts"
            mock_settings.STT_PROVIDER = "openai"
            response = client.get("/api/config")
        data = json.loads(response.data)
        assert data["tts_available"] is True
        assert data["stt_available"] is True

    @pytest.mark.unit
    def test_speech_features_unavailable_when_disabled(self, client):
        with patch("docsgpt.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = None
            mock_settings.TTS_PROVIDER = "none"
            mock_settings.STT_PROVIDER = "none"
            response = client.get("/api/config")
        data = json.loads(response.data)
        assert data["tts_available"] is False
        assert data["stt_available"] is False

    @pytest.mark.unit
    def test_exposes_attachment_budget_share(self, client):
        with patch("docsgpt.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = None
            mock_settings.ATTACHMENT_BUDGET_SHARE = 0.4
            response = client.get("/api/config")
        data = json.loads(response.data)
        assert data["attachment_budget_share"] == 0.4

    @pytest.mark.unit
    def test_oidc_config_exposes_login_paths(self, client):
        with patch("docsgpt.app.settings") as mock_settings:
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
        with patch("docsgpt.app.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "session_jwt"
            mock_settings.JWT_SECRET_KEY = "test_secret"
            response = client.get("/api/generate_token")
            assert response.status_code == 200
            data = json.loads(response.data)
            assert "token" in data

    @pytest.mark.unit
    def test_non_session_jwt_returns_error(self, client, app):
        with patch("docsgpt.app.settings") as mock_settings:
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
        with patch("docsgpt.app.should_reject_stt_request", return_value=True), \
             patch("docsgpt.app.build_stt_file_size_limit_message", return_value="Too large"):
            response = client.post("/api/stt/upload", data=b"x" * 100)
            assert response.status_code == 413


class TestDocumentUploadRequestSizeLimits:

    @pytest.mark.unit
    def test_oversized_upload_rejected_before_multipart_parsing(self, client):
        with patch(
            "docsgpt.app.settings.UPLOAD_MAX_REQUEST_BYTES",
            32,
        ):
            response = client.post(
                "/api/upload",
                data=b"x" * 100,
                content_type="multipart/form-data",
            )

        assert response.status_code == 413
        assert response.get_json() == {
            "success": False,
            "message": "Request exceeds the 32-byte upload limit",
        }

    @pytest.mark.unit
    def test_internal_worker_upload_is_not_subject_to_user_limit(self, client):
        with patch(
            "docsgpt.app.settings.UPLOAD_MAX_REQUEST_BYTES",
            32,
        ):
            response = client.post(
                "/api/upload_index",
                data=b"x" * 100,
                content_type="application/octet-stream",
            )

        assert response.status_code != 413

    @pytest.mark.unit
    def test_json_spec_uses_dedicated_request_limit(self, client):
        with patch(
            "docsgpt.app.settings.PARSE_SPEC_MAX_BYTES",
            32,
        ):
            response = client.post(
                "/api/parse_spec",
                json={"spec_content": "x" * 100},
            )

        assert response.status_code == 413
        assert response.get_json() == {
            "success": False,
            "message": "Request exceeds the 32-byte upload limit",
        }


class TestAuthenticateRequest:

    @pytest.mark.unit
    def test_options_returns_200(self, client):
        response = client.options("/api/health")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_auth_error_returns_401(self, client, app):
        with patch("docsgpt.app.handle_auth", return_value={"error": "Invalid token"}):
            response = client.get("/api/health")
            assert response.status_code == 401

    @pytest.mark.unit
    def test_no_token_sets_none(self, client, app):
        with patch("docsgpt.app.handle_auth", return_value=None):
            response = client.get("/api/health")
            assert response.status_code == 200

    @pytest.mark.unit
    def test_oidc_auth_paths_exempt_from_jwt_check(self, client, app):
        # A stale/expired Bearer header must never 401 the oidc login
        # endpoints — they are the only path back to a fresh session. The oidc
        # routes are only live under AUTH_TYPE=oidc, so pin it here.
        from docsgpt.core.settings import settings as _settings

        with patch(
            "docsgpt.app.handle_auth", return_value={"error": "invalid_token"}
        ), patch(
            "docsgpt.api.oidc.routes.get_redis_instance", return_value=None
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


class TestDefaultEncryptionKeyWarning:
    """The startup warning must say what the public default key actually blocks."""

    def _warning(self, monkeypatch, caplog, auth_type):
        import logging

        from docsgpt import app as app_module
        from docsgpt.security import encryption

        monkeypatch.setattr(app_module.settings, "AUTH_TYPE", auth_type)
        monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", encryption.DEFAULT_ENCRYPTION_KEY)
        with caplog.at_level(logging.WARNING):
            app_module._warn_default_encryption_key()
        return " ".join(r.getMessage() for r in caplog.records)

    def test_with_auth_it_names_the_refused_connections_and_the_rotation(self, monkeypatch, caplog):
        message = self._warning(monkeypatch, caplog, "oidc")
        assert "new connections are refused" in message
        assert "ENCRYPTION_SECRET_KEY_PREVIOUS" in message
        assert "docsgpt connectors reencrypt" in message

    def test_without_auth_it_names_the_rotation(self, monkeypatch, caplog):
        message = self._warning(monkeypatch, caplog, None)
        assert "ENCRYPTION_SECRET_KEY_PREVIOUS" in message
