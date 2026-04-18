"""Tests for application/api/connector/routes.py.

Directly instantiates Resource classes via ``test_request_context`` instead
of registering the blueprint (the flask_restx ``api`` is a module-level
singleton that can only be init_app'd once, which breaks per-test fixtures).
"""

import base64
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.connector.routes.db_session", _yield
    ), patch(
        "application.api.connector.routes.db_readonly", _yield
    ):
        yield


def _encode_state(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


class TestBuildCallbackRedirect:
    def test_builds_safe_url_with_params(self):
        from application.api.connector.routes import build_callback_redirect

        got = build_callback_redirect({"status": "success", "provider": "x"})
        assert got.startswith("/api/connectors/callback-status?")
        assert "status=success" in got
        assert "provider=x" in got


class TestConnectorAuth:
    def test_returns_400_missing_provider(self, app):
        from application.api.connector.routes import ConnectorAuth

        with app.test_request_context("/api/connectors/auth"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorAuth().get()
        assert r.status_code == 400

    def test_returns_400_unsupported_provider(self, app):
        from application.api.connector.routes import ConnectorAuth

        with patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=False,
        ), app.test_request_context("/api/connectors/auth?provider=nope"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorAuth().get()
        assert r.status_code == 400

    def test_returns_401_unauthenticated(self, app):
        from application.api.connector.routes import ConnectorAuth

        with patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=True,
        ), app.test_request_context(
            "/api/connectors/auth?provider=google_drive"
        ):
            from flask import request
            request.decoded_token = None
            r = ConnectorAuth().get()
        assert r.status_code == 401

    def test_generates_authorization_url(self, app, pg_conn):
        from application.api.connector.routes import ConnectorAuth

        fake_auth = MagicMock()
        fake_auth.get_authorization_url.return_value = "https://ex/auth?state=x"

        with _patch_db(pg_conn), patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=True,
        ), patch(
            "application.api.connector.routes.ConnectorCreator.create_auth",
            return_value=fake_auth,
        ), app.test_request_context(
            "/api/connectors/auth?provider=google_drive"
        ):
            from flask import request
            request.decoded_token = {"sub": "u-auth"}
            r = ConnectorAuth().get()
        assert r.status_code == 200
        assert r.json["success"] is True
        assert r.json["authorization_url"] == "https://ex/auth?state=x"


class TestConnectorsCallback:
    def test_invalid_provider_redirects_to_error(self, app):
        from application.api.connector.routes import ConnectorsCallback

        state = _encode_state({"provider": "bogus", "object_id": "x"})
        with patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=False,
        ), app.test_request_context(f"/api/connectors/callback?state={state}"):
            r = ConnectorsCallback().get()
        assert r.status_code == 302
        assert "callback-status" in r.location

    def test_access_denied_redirects_cancelled(self, app):
        from application.api.connector.routes import ConnectorsCallback

        state = _encode_state({"provider": "google_drive", "object_id": "x"})
        with patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=True,
        ), app.test_request_context(
            f"/api/connectors/callback?state={state}&error=access_denied"
        ):
            r = ConnectorsCallback().get()
        assert r.status_code == 302
        assert "cancelled" in r.location

    def test_error_redirects_error(self, app):
        from application.api.connector.routes import ConnectorsCallback

        state = _encode_state({"provider": "google_drive", "object_id": "x"})
        with patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=True,
        ), app.test_request_context(
            f"/api/connectors/callback?state={state}&error=other"
        ):
            r = ConnectorsCallback().get()
        assert r.status_code == 302
        assert "status=error" in r.location

    def test_missing_code_redirects_error(self, app):
        from application.api.connector.routes import ConnectorsCallback

        state = _encode_state({"provider": "google_drive", "object_id": "x"})
        with patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=True,
        ), app.test_request_context(
            f"/api/connectors/callback?state={state}"
        ):
            r = ConnectorsCallback().get()
        assert r.status_code == 302
        assert "status=error" in r.location

    def test_successful_callback_updates_session(self, app, pg_conn):
        from application.api.connector.routes import ConnectorsCallback
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        session = ConnectorSessionsRepository(pg_conn).upsert(
            "u-callback", "google_drive", status="pending",
        )
        state = _encode_state({
            "provider": "google_drive",
            "object_id": str(session["id"]),
        })

        fake_auth = MagicMock()
        fake_auth.exchange_code_for_tokens.return_value = {
            "access_token": "at", "refresh_token": "rt",
            "user_info": {"email": "someone@example.com"},
        }
        fake_auth.sanitize_token_info.return_value = {"access_token": "at"}
        # Force the google_drive user-info branch to fail so we fall back
        # to the string "Connected User" rather than returning a MagicMock
        # that can't be adapted to JSONB by psycopg.
        fake_auth.create_credentials_from_token_info.side_effect = (
            RuntimeError("no creds")
        )

        with _patch_db(pg_conn), patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=True,
        ), patch(
            "application.api.connector.routes.ConnectorCreator.create_auth",
            return_value=fake_auth,
        ), app.test_request_context(
            f"/api/connectors/callback?state={state}&code=auth-code"
        ):
            r = ConnectorsCallback().get()
        assert r.status_code == 302
        assert "status=success" in r.location

    def test_token_exchange_failure_redirects_error(self, app, pg_conn):
        from application.api.connector.routes import ConnectorsCallback

        state = _encode_state({"provider": "google_drive", "object_id": ""})
        fake_auth = MagicMock()
        fake_auth.exchange_code_for_tokens.side_effect = RuntimeError("fail")

        with _patch_db(pg_conn), patch(
            "application.api.connector.routes.ConnectorCreator.is_supported",
            return_value=True,
        ), patch(
            "application.api.connector.routes.ConnectorCreator.create_auth",
            return_value=fake_auth,
        ), app.test_request_context(
            f"/api/connectors/callback?state={state}&code=auth-code"
        ):
            r = ConnectorsCallback().get()
        assert r.status_code == 302


class TestConnectorFiles:
    def test_returns_400_missing_fields(self, app):
        from application.api.connector.routes import ConnectorFiles

        with app.test_request_context(
            "/api/connectors/files",
            method="POST",
            json={"provider": "google_drive"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorFiles().post()
        assert r.status_code == 400

    def test_returns_401_unauthenticated(self, app):
        from application.api.connector.routes import ConnectorFiles

        with app.test_request_context(
            "/api/connectors/files",
            method="POST",
            json={"provider": "google_drive", "session_token": "st"},
        ):
            from flask import request
            request.decoded_token = None
            r = ConnectorFiles().post()
        assert r.status_code == 401

    def test_returns_401_invalid_session(self, app, pg_conn):
        from application.api.connector.routes import ConnectorFiles

        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/files",
            method="POST",
            json={"provider": "google_drive", "session_token": "bad"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorFiles().post()
        assert r.status_code == 401

    def test_lists_files_successfully(self, app, pg_conn):
        from application.api.connector.routes import ConnectorFiles
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        user = "u-files"
        session = ConnectorSessionsRepository(pg_conn).upsert(
            user, "google_drive", status="authorized",
        )
        ConnectorSessionsRepository(pg_conn).update(
            str(session["id"]),
            {"session_token": "st-files", "status": "authorized"},
        )

        fake_doc = SimpleNamespace(
            doc_id="file-1",
            extra_info={
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "size": 1024,
                "modified_time": "2024-01-01T12:00:00.000Z",
                "is_folder": False,
            },
        )
        fake_loader = MagicMock()
        fake_loader.load_data.return_value = [fake_doc]
        fake_loader.next_page_token = None

        with _patch_db(pg_conn), patch(
            "application.api.connector.routes.ConnectorCreator.create_connector",
            return_value=fake_loader,
        ), app.test_request_context(
            "/api/connectors/files",
            method="POST",
            json={"provider": "google_drive", "session_token": "st-files"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            r = ConnectorFiles().post()
        assert r.status_code == 200
        assert r.json["files"][0]["name"] == "report.pdf"


class TestConnectorValidateSession:
    def test_returns_400_missing_fields(self, app):
        from application.api.connector.routes import ConnectorValidateSession

        with app.test_request_context(
            "/api/connectors/validate-session",
            method="POST",
            json={"provider": "google_drive"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorValidateSession().post()
        assert r.status_code == 400

    def test_returns_401_unauthenticated(self, app):
        from application.api.connector.routes import ConnectorValidateSession

        with app.test_request_context(
            "/api/connectors/validate-session",
            method="POST",
            json={"provider": "google_drive", "session_token": "x"},
        ):
            from flask import request
            request.decoded_token = None
            r = ConnectorValidateSession().post()
        assert r.status_code == 401

    def test_returns_401_invalid_session(self, app, pg_conn):
        from application.api.connector.routes import ConnectorValidateSession

        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/validate-session",
            method="POST",
            json={"provider": "google_drive", "session_token": "bad"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorValidateSession().post()
        assert r.status_code == 401

    def test_valid_session_returns_tokens(self, app, pg_conn):
        from application.api.connector.routes import ConnectorValidateSession
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        user = "u-valid-sess"
        repo = ConnectorSessionsRepository(pg_conn)
        session = repo.upsert(user, "google_drive", status="authorized")
        repo.update(
            str(session["id"]),
            {
                "session_token": "st-valid",
                "token_info": {"access_token": "at", "refresh_token": "rt"},
                "user_email": "user@example.com",
            },
        )

        fake_auth = MagicMock()
        fake_auth.is_token_expired.return_value = False

        with _patch_db(pg_conn), patch(
            "application.api.connector.routes.ConnectorCreator.create_auth",
            return_value=fake_auth,
        ), app.test_request_context(
            "/api/connectors/validate-session",
            method="POST",
            json={"provider": "google_drive", "session_token": "st-valid"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            r = ConnectorValidateSession().post()
        assert r.status_code == 200
        assert r.json["access_token"] == "at"

    def test_expired_token_refreshes(self, app, pg_conn):
        from application.api.connector.routes import ConnectorValidateSession
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        user = "u-refresh"
        repo = ConnectorSessionsRepository(pg_conn)
        session = repo.upsert(user, "google_drive", status="authorized")
        repo.update(
            str(session["id"]),
            {
                "session_token": "st-refresh",
                "token_info": {"access_token": "old", "refresh_token": "rt"},
            },
        )

        fake_auth = MagicMock()
        fake_auth.is_token_expired.return_value = True
        fake_auth.refresh_access_token.return_value = {"access_token": "new-at"}
        fake_auth.sanitize_token_info.return_value = {"access_token": "new-at"}

        with _patch_db(pg_conn), patch(
            "application.api.connector.routes.ConnectorCreator.create_auth",
            return_value=fake_auth,
        ), app.test_request_context(
            "/api/connectors/validate-session",
            method="POST",
            json={"provider": "google_drive", "session_token": "st-refresh"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            r = ConnectorValidateSession().post()
        assert r.status_code == 200
        assert r.json["access_token"] == "new-at"


class TestConnectorDisconnect:
    def test_returns_400_missing_provider(self, app):
        from application.api.connector.routes import ConnectorDisconnect

        with app.test_request_context(
            "/api/connectors/disconnect", method="POST", json={}
        ):
            r = ConnectorDisconnect().post()
        assert r.status_code == 400

    def test_disconnects_session(self, app, pg_conn):
        from application.api.connector.routes import ConnectorDisconnect
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        user = "u-disc"
        repo = ConnectorSessionsRepository(pg_conn)
        session = repo.upsert(user, "google_drive", status="authorized")
        repo.update(str(session["id"]), {"session_token": "st-disc"})

        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/disconnect",
            method="POST",
            json={"provider": "google_drive", "session_token": "st-disc"},
        ):
            r = ConnectorDisconnect().post()
        assert r.status_code == 200
        assert r.json["success"] is True

    def test_disconnect_without_session_token_succeeds(self, app):
        from application.api.connector.routes import ConnectorDisconnect

        with app.test_request_context(
            "/api/connectors/disconnect",
            method="POST",
            json={"provider": "google_drive"},
        ):
            r = ConnectorDisconnect().post()
        assert r.status_code == 200


class TestConnectorSync:
    def test_returns_401_unauthenticated(self, app):
        from application.api.connector.routes import ConnectorSync

        with app.test_request_context(
            "/api/connectors/sync",
            method="POST",
            json={"source_id": "x", "session_token": "y"},
        ):
            from flask import request
            request.decoded_token = None
            r = ConnectorSync().post()
        assert r.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.connector.routes import ConnectorSync

        with app.test_request_context(
            "/api/connectors/sync", method="POST", json={"source_id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorSync().post()
        assert r.status_code == 400

    def test_returns_404_source_not_found(self, app, pg_conn):
        from application.api.connector.routes import ConnectorSync

        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/sync",
            method="POST",
            json={
                "source_id": "00000000-0000-0000-0000-000000000000",
                "session_token": "y",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            r = ConnectorSync().post()
        assert r.status_code == 404

    def test_returns_400_missing_provider(self, app, pg_conn):
        from application.api.connector.routes import ConnectorSync
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-noprov"
        src = SourcesRepository(pg_conn).create(
            "s", user_id=user, remote_data={"no_provider": True}
        )

        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/sync",
            method="POST",
            json={"source_id": str(src["id"]), "session_token": "y"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            r = ConnectorSync().post()
        assert r.status_code == 400

    def test_triggers_sync_task(self, app, pg_conn):
        from application.api.connector.routes import ConnectorSync
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-sync-trigger"
        src = SourcesRepository(pg_conn).create(
            "github-src", user_id=user,
            remote_data={"provider": "github", "file_ids": [], "folder_ids": []},
        )

        fake_task = MagicMock(id="task-abc")
        with _patch_db(pg_conn), patch(
            "application.api.connector.routes.ingest_connector_task.delay",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/connectors/sync",
            method="POST",
            json={"source_id": str(src["id"]), "session_token": "st"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            r = ConnectorSync().post()
        assert r.status_code == 200
        assert r.json["task_id"] == "task-abc"


class TestConnectorCallbackStatus:
    def test_returns_html_for_success(self, app):
        from application.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?"
            "status=success&provider=google_drive&message=hello&user_email=a@b.com"
        ):
            r = ConnectorCallbackStatus().get()
        assert r.status_code == 200
        assert r.mimetype == "text/html"
        assert b"Google Drive" in r.data
        assert b"hello" in r.data

    def test_returns_html_for_error(self, app):
        from application.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=error&message=oops"
        ):
            r = ConnectorCallbackStatus().get()
        assert r.status_code == 200
        assert b"oops" in r.data

    def test_unknown_status_coerces_to_error(self, app):
        from application.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=weird"
        ):
            r = ConnectorCallbackStatus().get()
        assert r.status_code == 200
