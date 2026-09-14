"""Connector OAuth hardening: popup message origin, token exposure, session ownership."""

import base64
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn, module="docsgpt.api.connector.routes"):
    @contextmanager
    def _yield():
        yield conn

    with patch(f"{module}.db_session", _yield), patch(f"{module}.db_readonly", _yield):
        yield


def _encode_state(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _seed_session(pg_conn, user, token, provider="google_drive"):
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    repo = ConnectorSessionsRepository(pg_conn)
    row = repo.upsert(user, provider, status="authorized")
    repo.update(str(row["id"]), {"session_token": token})
    return repo


class TestConnectorAllowedOrigins:
    def test_collects_configured_origins(self):
        from docsgpt.api.connector.routes import connector_allowed_origins
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", "https://app.example.com/, https://b.example.com/x"), \
                patch.object(settings, "OIDC_FRONTEND_URL", "https://sso.example.com/home"), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback"):
            origins = connector_allowed_origins("https://api.example.com/")

        assert set(origins) == {
            "https://app.example.com",
            "https://b.example.com",
            "https://sso.example.com",
            "https://api.example.com",
        }

    def test_rejects_wildcards_and_non_http_values(self):
        from docsgpt.api.connector.routes import connector_allowed_origins
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", "*, javascript:alert(1), null, not a url"), \
                patch.object(settings, "OIDC_FRONTEND_URL", None), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback"):
            origins = connector_allowed_origins("https://api.example.com/")

        assert origins == ["https://api.example.com"]

    def test_loopback_dev_frontend_allowed_only_for_loopback_callback(self):
        from docsgpt.api.connector.routes import connector_allowed_origins
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", None), \
                patch.object(settings, "OIDC_FRONTEND_URL", None), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "http://127.0.0.1:7091/api/connectors/callback"):
            local = connector_allowed_origins("http://127.0.0.1:7091/")
        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", None), \
                patch.object(settings, "OIDC_FRONTEND_URL", None), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback"):
            public = connector_allowed_origins("http://localhost:7091/")

        assert "http://localhost:5173" in local
        assert "http://127.0.0.1:5173" in local
        assert "http://localhost:5173" not in public


class TestCallbackStatusPage:
    def test_never_posts_to_wildcard_origin(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=success&provider=google_drive"
        ):
            r = ConnectorCallbackStatus().get()
        body = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "'*'" not in body
        assert '"*"' not in body

    def test_ignores_session_token_query_param(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=success&provider=google_drive"
            "&session_token=attacker-supplied&user_email=evil@example.com"
        ):
            r = ConnectorCallbackStatus().get()
        body = r.get_data(as_text=True)
        assert "attacker-supplied" not in body
        assert "evil@example.com" not in body


class TestCallbackDeliversTokenSafely:
    def test_success_renders_page_without_redirecting_token(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorsCallback
        from docsgpt.core.settings import settings
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        user = "u-cb-origin"
        repo = ConnectorSessionsRepository(pg_conn)
        pending = repo.upsert(user, "google_drive", status="pending")
        state = _encode_state({"provider": "google_drive", "object_id": str(pending["id"])})

        fake_auth = MagicMock()
        fake_auth.exchange_code_for_tokens.return_value = {"access_token": "at"}
        fake_auth.sanitize_token_info.return_value = {"access_token": "at"}
        fake_auth.create_credentials_from_token_info.side_effect = RuntimeError("no creds")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.is_supported", return_value=True,
        ), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=fake_auth,
        ), patch.object(
            settings, "CONNECTOR_ALLOWED_ORIGINS", "https://app.example.com",
        ), app.test_request_context(
            f"/api/connectors/callback?state={state}&code=auth-code",
            base_url="https://api.example.com",
        ):
            r = ConnectorsCallback().get()

        token = repo.get_by_user_provider(user, "google_drive")["session_token"]
        body = r.get_data(as_text=True)
        assert token
        assert r.status_code == 200
        assert "Location" not in r.headers
        assert token in body
        assert '"https://app.example.com"' in body
        assert "'*'" not in body
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["Referrer-Policy"] == "no-referrer"


class TestAuthUrlReportsCallbackOrigin:
    def test_includes_callback_origin(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorAuth
        from docsgpt.core.settings import settings

        fake_auth = MagicMock()
        fake_auth.get_authorization_url.return_value = "https://ex/auth?state=x"

        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.is_supported", return_value=True,
        ), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=fake_auth,
        ), patch.object(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback",
        ), app.test_request_context("/api/connectors/auth?provider=google_drive"):
            from flask import request
            request.decoded_token = {"sub": "u-auth-origin"}
            r = ConnectorAuth().get()

        assert r.status_code == 200
        assert r.json["callback_origin"] == "https://api.example.com"


class TestDisconnectOwnership:
    def test_requires_authentication(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorDisconnect

        repo = _seed_session(pg_conn, "u-owner", "st-noauth")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/disconnect", method="POST",
            json={"provider": "google_drive", "session_token": "st-noauth"},
        ):
            from flask import request
            request.decoded_token = None
            r = ConnectorDisconnect().post()

        assert r.status_code == 401
        assert repo.get_by_session_token("st-noauth") is not None

    def test_cannot_delete_another_users_session(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorDisconnect

        repo = _seed_session(pg_conn, "u-victim", "st-victim")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/disconnect", method="POST",
            json={"provider": "google_drive", "session_token": "st-victim"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-attacker"}
            ConnectorDisconnect().post()

        assert repo.get_by_session_token("st-victim") is not None

    def test_owner_can_delete_own_session(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorDisconnect

        repo = _seed_session(pg_conn, "u-self", "st-self")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/disconnect", method="POST",
            json={"provider": "google_drive", "session_token": "st-self"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-self"}
            r = ConnectorDisconnect().post()

        assert r.status_code == 200
        assert repo.get_by_session_token("st-self") is None


class TestSyncSessionOwnership:
    def test_rejects_foreign_session_token(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorSync
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        _seed_session(pg_conn, "u-victim-sync", "st-victim-sync")
        attacker = "u-attacker-sync"
        src = SourcesRepository(pg_conn).create(
            "drive-src", user_id=attacker,
            remote_data={"provider": "google_drive", "file_ids": ["f"], "folder_ids": []},
        )

        delay = MagicMock()
        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ingest_connector_task.delay", delay,
        ), app.test_request_context(
            "/api/connectors/sync", method="POST",
            json={"source_id": str(src["id"]), "session_token": "st-victim-sync"},
        ):
            from flask import request
            request.decoded_token = {"sub": attacker}
            r = ConnectorSync().post()

        assert r.status_code == 401
        delay.assert_not_called()


class TestRemoteUploadSessionOwnership:
    def _post(self, app, pg_conn, user, token, apply_mock):
        from docsgpt.api.user.sources.upload import UploadRemote

        with _patch_db(pg_conn, "docsgpt.api.user.sources.upload"), patch(
            "docsgpt.api.user.sources.upload.ingest_connector_task.apply_async", apply_mock,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": user, "source": "google_drive", "name": "g",
                "data": json.dumps({"session_token": token, "file_ids": ["f1"]}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return UploadRemote().post()

    def test_rejects_foreign_session_token(self, app, pg_conn):
        _seed_session(pg_conn, "u-victim-up", "st-victim-up")
        apply_mock = MagicMock(return_value=MagicMock(id="t"))

        r = self._post(app, pg_conn, "u-attacker-up", "st-victim-up", apply_mock)

        assert r.status_code == 401
        apply_mock.assert_not_called()

    def test_accepts_own_session_token(self, app, pg_conn):
        _seed_session(pg_conn, "u-owner-up", "st-owner-up")
        apply_mock = MagicMock(return_value=MagicMock(id="t"))

        r = self._post(app, pg_conn, "u-owner-up", "st-owner-up", apply_mock)

        assert r.status_code == 200
        apply_mock.assert_called_once()
