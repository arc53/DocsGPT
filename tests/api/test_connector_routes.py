"""Tests for application/api/connector/routes.py"""

import base64
import json
from unittest.mock import MagicMock, patch

import mongomock
import pytest


@pytest.fixture
def app():
    with patch("application.app.handle_auth", return_value={"sub": "test_user"}):
        from application.app import app as flask_app
        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_sessions(monkeypatch):
    mock_client = mongomock.MongoClient()
    mock_db = mock_client["docsgpt"]
    sessions = mock_db["connector_sessions"]
    sources = mock_db["sources"]
    monkeypatch.setattr("application.api.connector.routes.sessions_collection", sessions)
    monkeypatch.setattr("application.api.connector.routes.sources_collection", sources)
    return {"sessions": sessions, "sources": sources}


class TestConnectorAuth:

    @pytest.mark.unit
    def test_missing_provider(self, client):
        resp = client.get("/api/connectors/auth")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_unsupported_provider(self, client):
        resp = client.get("/api/connectors/auth?provider=dropbox")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_unauthorized(self, client, app):
        with patch("application.app.handle_auth", return_value=None):
            resp = client.get("/api/connectors/auth?provider=google_drive")
            data = json.loads(resp.data)
            # decoded_token is None -> 401
            assert resp.status_code == 401 or data.get("error") == "Unauthorized"

    @pytest.mark.unit
    def test_success(self, client, mock_sessions):
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.is_supported.return_value = True
            mock_auth = MagicMock()
            mock_auth.get_authorization_url.return_value = "https://oauth.example.com/auth"
            MockCC.create_auth.return_value = mock_auth

            resp = client.get("/api/connectors/auth?provider=google_drive")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["success"] is True
            assert "authorization_url" in data

    @pytest.mark.unit
    def test_exception_returns_500(self, client, mock_sessions):
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.is_supported.return_value = True
            MockCC.create_auth.side_effect = Exception("oauth fail")
            resp = client.get("/api/connectors/auth?provider=google_drive")
            assert resp.status_code == 500


class TestConnectorFiles:

    @pytest.mark.unit
    def test_missing_params(self, client):
        resp = client.post("/api/connectors/files", json={"provider": "google_drive"})
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_invalid_session(self, client, mock_sessions):
        resp = client.post("/api/connectors/files", json={
            "provider": "google_drive",
            "session_token": "bad_token",
        })
        assert resp.status_code == 401

    @pytest.mark.unit
    def test_success(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one({
            "session_token": "valid_tok",
            "user": "test_user",
            "provider": "google_drive",
        })

        mock_doc = MagicMock()
        mock_doc.doc_id = "f1"
        mock_doc.extra_info = {
            "file_name": "test.pdf",
            "mime_type": "application/pdf",
            "size": 1024,
            "modified_time": "2025-01-01T12:00:00.000Z",
            "is_folder": False,
        }
        mock_loader = MagicMock()
        mock_loader.load_data.return_value = [mock_doc]
        mock_loader.next_page_token = None

        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.create_connector.return_value = mock_loader
            resp = client.post("/api/connectors/files", json={
                "provider": "google_drive",
                "session_token": "valid_tok",
            })
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert len(data["files"]) == 1

    @pytest.mark.unit
    def test_no_modified_time(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one({
            "session_token": "tok2",
            "user": "test_user",
            "provider": "google_drive",
        })
        mock_doc = MagicMock()
        mock_doc.doc_id = "f1"
        mock_doc.extra_info = {"file_name": "test.pdf", "mime_type": "application/pdf"}
        mock_loader = MagicMock()
        mock_loader.load_data.return_value = [mock_doc]
        mock_loader.next_page_token = None

        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.create_connector.return_value = mock_loader
            resp = client.post("/api/connectors/files", json={
                "provider": "google_drive", "session_token": "tok2",
            })
        assert resp.status_code == 200


class TestConnectorValidateSession:

    @pytest.mark.unit
    def test_missing_params(self, client):
        resp = client.post("/api/connectors/validate-session", json={"provider": "google_drive"})
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_invalid_session(self, client, mock_sessions):
        resp = client.post("/api/connectors/validate-session", json={
            "provider": "google_drive", "session_token": "bad",
        })
        assert resp.status_code == 401

    @pytest.mark.unit
    def test_valid_non_expired(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one({
            "session_token": "valid",
            "user": "test_user",
            "provider": "google_drive",
            "token_info": {"access_token": "at", "refresh_token": "rt", "expiry": None},
            "user_email": "user@example.com",
        })
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            mock_auth = MagicMock()
            mock_auth.is_token_expired.return_value = False
            MockCC.create_auth.return_value = mock_auth
            resp = client.post("/api/connectors/validate-session", json={
                "provider": "google_drive", "session_token": "valid",
            })
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert data["expired"] is False

    @pytest.mark.unit
    def test_expired_with_refresh(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one({
            "session_token": "expired_tok",
            "user": "test_user",
            "provider": "google_drive",
            "token_info": {"access_token": "old_at", "refresh_token": "rt", "expiry": 100},
        })
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            mock_auth = MagicMock()
            mock_auth.is_token_expired.return_value = True
            mock_auth.refresh_access_token.return_value = {"access_token": "new_at", "refresh_token": "rt"}
            mock_auth.sanitize_token_info.return_value = {"access_token": "new_at", "refresh_token": "rt"}
            MockCC.create_auth.return_value = mock_auth
            resp = client.post("/api/connectors/validate-session", json={
                "provider": "google_drive", "session_token": "expired_tok",
            })
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_expired_no_refresh(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one({
            "session_token": "exp_no_ref",
            "user": "test_user",
            "token_info": {"access_token": "at", "expiry": 100},
        })
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            mock_auth = MagicMock()
            mock_auth.is_token_expired.return_value = True
            MockCC.create_auth.return_value = mock_auth
            resp = client.post("/api/connectors/validate-session", json={
                "provider": "google_drive", "session_token": "exp_no_ref",
            })
        assert resp.status_code == 401


class TestConnectorDisconnect:

    @pytest.mark.unit
    def test_missing_provider(self, client):
        resp = client.post("/api/connectors/disconnect", json={})
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_success_with_session(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one({"session_token": "del_me", "provider": "google_drive"})
        resp = client.post("/api/connectors/disconnect", json={
            "provider": "google_drive", "session_token": "del_me",
        })
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True

    @pytest.mark.unit
    def test_success_without_session(self, client, mock_sessions):
        resp = client.post("/api/connectors/disconnect", json={"provider": "google_drive"})
        assert resp.status_code == 200


class TestConnectorSync:

    @pytest.mark.unit
    def test_missing_params(self, client, mock_sessions):
        resp = client.post("/api/connectors/sync", json={"source_id": "abc"})
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_source_not_found(self, client, mock_sessions):
        from bson.objectid import ObjectId
        resp = client.post("/api/connectors/sync", json={
            "source_id": str(ObjectId()), "session_token": "tok",
        })
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_unauthorized_source(self, client, mock_sessions):
        sid = mock_sessions["sources"].insert_one({"user": "other_user", "name": "src"}).inserted_id
        resp = client.post("/api/connectors/sync", json={
            "source_id": str(sid), "session_token": "tok",
        })
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_missing_provider_in_remote_data(self, client, mock_sessions):
        sid = mock_sessions["sources"].insert_one({
            "user": "test_user", "name": "src", "remote_data": json.dumps({}),
        }).inserted_id
        resp = client.post("/api/connectors/sync", json={
            "source_id": str(sid), "session_token": "tok",
        })
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_success(self, client, mock_sessions):
        sid = mock_sessions["sources"].insert_one({
            "user": "test_user",
            "name": "src",
            "remote_data": json.dumps({"provider": "google_drive", "file_ids": ["f1"]}),
        }).inserted_id
        mock_task = MagicMock()
        mock_task.id = "task_123"
        with patch("application.api.connector.routes.ingest_connector_task") as mock_ingest:
            mock_ingest.delay.return_value = mock_task
            resp = client.post("/api/connectors/sync", json={
                "source_id": str(sid), "session_token": "tok",
            })
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["task_id"] == "task_123"


class TestConnectorCallbackStatus:

    @pytest.mark.unit
    def test_success_status(self, client):
        resp = client.get("/api/connectors/callback-status?status=success&message=OK&provider=google_drive&session_token=tok&user_email=u@e.com")
        assert resp.status_code == 200
        assert b"success" in resp.data

    @pytest.mark.unit
    def test_error_status(self, client):
        resp = client.get("/api/connectors/callback-status?status=error&message=Failed")
        assert resp.status_code == 200
        assert b"error" in resp.data

    @pytest.mark.unit
    def test_cancelled_status(self, client):
        resp = client.get("/api/connectors/callback-status?status=cancelled&message=Cancelled&provider=google_drive")
        assert resp.status_code == 200
        assert b"cancelled" in resp.data

    @pytest.mark.unit
    def test_unknown_status_defaults_to_error(self, client):
        resp = client.get("/api/connectors/callback-status?status=badvalue")
        assert resp.status_code == 200
        assert b"error" in resp.data

    @pytest.mark.unit
    def test_html_escaping(self, client):
        resp = client.get('/api/connectors/callback-status?status=error&message=<script>alert(1)</script>')
        assert resp.status_code == 200
        # The raw <script> tag should be escaped (not executable)
        assert b"<script>alert(1)</script>" not in resp.data


class TestBuildCallbackRedirect:

    @pytest.mark.unit
    def test_builds_url(self):
        from application.api.connector.routes import build_callback_redirect
        url = build_callback_redirect({"status": "success", "message": "OK"})
        assert url.startswith("/api/connectors/callback-status?")
        assert "status=success" in url


@pytest.mark.unit
class TestConnectorsCallback:
    """Tests for the ConnectorsCallback OAuth callback route."""

    def _encode_state(self, state_dict):
        return base64.urlsafe_b64encode(json.dumps(state_dict).encode()).decode()

    def _patch_connector_creator(self):
        """Patch ConnectorCreator at both module-level and local-import locations."""
        return patch(
            "application.parser.connectors.connector_creator.ConnectorCreator",
        )

    def test_callback_invalid_provider_redirects_error(self, client, mock_sessions):
        state = self._encode_state({"provider": "dropbox", "object_id": "abc123"})
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = False
            resp = client.get(
                f"/api/connectors/callback?code=auth_code&state={state}"
            )
        assert resp.status_code == 302
        assert "error" in resp.headers.get("Location", "")

    def test_callback_access_denied_redirects_cancelled(self, client, mock_sessions):
        state = self._encode_state(
            {"provider": "google_drive", "object_id": "abc123"}
        )
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = True
            resp = client.get(
                f"/api/connectors/callback?error=access_denied&state={state}"
            )
        assert resp.status_code == 302
        assert "cancelled" in resp.headers.get("Location", "")

    def test_callback_other_error_redirects_error(self, client, mock_sessions):
        state = self._encode_state(
            {"provider": "google_drive", "object_id": "abc123"}
        )
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = True
            resp = client.get(
                f"/api/connectors/callback?error=server_error&state={state}"
            )
        assert resp.status_code == 302
        assert "error" in resp.headers.get("Location", "")

    def test_callback_missing_code_redirects_error(self, client, mock_sessions):
        state = self._encode_state(
            {"provider": "google_drive", "object_id": "abc123"}
        )
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = True
            resp = client.get(f"/api/connectors/callback?state={state}")
        assert resp.status_code == 302
        assert "error" in resp.headers.get("Location", "")

    def test_callback_success_google_drive(self, client, mock_sessions):
        oid = mock_sessions["sessions"].insert_one(
            {
                "provider": "google_drive",
                "user": "test_user",
                "status": "pending",
            }
        ).inserted_id
        state = self._encode_state(
            {"provider": "google_drive", "object_id": str(oid)}
        )
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = True
            mock_auth = MagicMock()
            mock_auth.exchange_code_for_tokens.return_value = {
                "access_token": "at",
                "refresh_token": "rt",
            }
            mock_creds = MagicMock()
            mock_auth.create_credentials_from_token_info.return_value = mock_creds
            mock_service = MagicMock()
            mock_service.about.return_value.get.return_value.execute.return_value = {
                "user": {"emailAddress": "user@example.com"}
            }
            mock_auth.build_drive_service.return_value = mock_service
            mock_auth.sanitize_token_info.return_value = {
                "access_token": "at",
                "refresh_token": "rt",
            }
            MockCC.create_auth.return_value = mock_auth

            resp = client.get(
                f"/api/connectors/callback?code=auth_code&state={state}"
            )
        assert resp.status_code == 302
        assert "success" in resp.headers.get("Location", "")

    def test_callback_success_non_google_provider(self, client, mock_sessions):
        oid = mock_sessions["sessions"].insert_one(
            {
                "provider": "other_provider",
                "user": "test_user",
                "status": "pending",
            }
        ).inserted_id
        state = self._encode_state(
            {"provider": "other_provider", "object_id": str(oid)}
        )
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = True
            mock_auth = MagicMock()
            mock_auth.exchange_code_for_tokens.return_value = {
                "access_token": "at",
                "user_info": {"email": "other@example.com"},
            }
            mock_auth.sanitize_token_info.return_value = {"access_token": "at"}
            MockCC.create_auth.return_value = mock_auth

            resp = client.get(
                f"/api/connectors/callback?code=auth_code&state={state}"
            )
        assert resp.status_code == 302
        assert "success" in resp.headers.get("Location", "")

    def test_callback_exchange_tokens_fails(self, client, mock_sessions):
        oid = mock_sessions["sessions"].insert_one(
            {
                "provider": "google_drive",
                "user": "test_user",
                "status": "pending",
            }
        ).inserted_id
        state = self._encode_state(
            {"provider": "google_drive", "object_id": str(oid)}
        )
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = True
            mock_auth = MagicMock()
            mock_auth.exchange_code_for_tokens.side_effect = Exception("token error")
            MockCC.create_auth.return_value = mock_auth

            resp = client.get(
                f"/api/connectors/callback?code=auth_code&state={state}"
            )
        assert resp.status_code == 302
        assert "error" in resp.headers.get("Location", "")

    def test_callback_bad_state_returns_error(self, client, mock_sessions):
        resp = client.get("/api/connectors/callback?code=auth_code&state=badbase64!!!")
        assert resp.status_code == 302
        assert "error" in resp.headers.get("Location", "")

    def test_callback_user_info_fails_gracefully(self, client, mock_sessions):
        oid = mock_sessions["sessions"].insert_one(
            {
                "provider": "google_drive",
                "user": "test_user",
                "status": "pending",
            }
        ).inserted_id
        state = self._encode_state(
            {"provider": "google_drive", "object_id": str(oid)}
        )
        with self._patch_connector_creator() as MockCC:
            MockCC.is_supported.return_value = True
            mock_auth = MagicMock()
            mock_auth.exchange_code_for_tokens.return_value = {
                "access_token": "at",
                "refresh_token": "rt",
            }
            mock_auth.create_credentials_from_token_info.side_effect = Exception(
                "cred error"
            )
            mock_auth.sanitize_token_info.return_value = {
                "access_token": "at",
            }
            MockCC.create_auth.return_value = mock_auth

            resp = client.get(
                f"/api/connectors/callback?code=auth_code&state={state}"
            )
        assert resp.status_code == 302
        assert "success" in resp.headers.get("Location", "")


@pytest.mark.unit
class TestConnectorFilesAdditional:
    """Additional tests for ConnectorFiles."""

    def test_unauthorized_user(self, client, mock_sessions):
        with patch("application.app.handle_auth", return_value=None):
            resp = client.post(
                "/api/connectors/files",
                json={
                    "provider": "google_drive",
                    "session_token": "tok",
                },
            )
        assert resp.status_code == 401

    def test_files_with_pagination(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one(
            {
                "session_token": "pag_tok",
                "user": "test_user",
                "provider": "google_drive",
            }
        )

        mock_doc = MagicMock()
        mock_doc.doc_id = "f1"
        mock_doc.extra_info = {
            "file_name": "test.pdf",
            "mime_type": "application/pdf",
            "size": 1024,
            "modified_time": "2025-01-01T12:00:00.000Z",
            "is_folder": False,
        }
        mock_loader = MagicMock()
        mock_loader.load_data.return_value = [mock_doc]
        mock_loader.next_page_token = "next_token_123"

        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.create_connector.return_value = mock_loader
            resp = client.post(
                "/api/connectors/files",
                json={
                    "provider": "google_drive",
                    "session_token": "pag_tok",
                    "page_token": "prev_token",
                },
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["has_more"] is True
        assert data["next_page_token"] == "next_token_123"

    def test_files_exception_returns_500(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one(
            {
                "session_token": "err_tok",
                "user": "test_user",
                "provider": "google_drive",
            }
        )

        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.create_connector.side_effect = Exception("connector error")
            resp = client.post(
                "/api/connectors/files",
                json={
                    "provider": "google_drive",
                    "session_token": "err_tok",
                },
            )
        assert resp.status_code == 500


@pytest.mark.unit
class TestConnectorFilesSearchQuery:
    """Test ConnectorFiles with search_query parameter."""

    def test_files_with_search_query(self, client, mock_sessions):
        mock_sessions["sessions"].insert_one(
            {
                "session_token": "search_tok",
                "user": "test_user",
                "provider": "google_drive",
            }
        )

        mock_doc = MagicMock()
        mock_doc.doc_id = "f1"
        mock_doc.extra_info = {
            "file_name": "result.pdf",
            "mime_type": "application/pdf",
            "size": 512,
            "is_folder": False,
        }
        mock_loader = MagicMock()
        mock_loader.load_data.return_value = [mock_doc]
        mock_loader.next_page_token = None

        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.create_connector.return_value = mock_loader
            resp = client.post(
                "/api/connectors/files",
                json={
                    "provider": "google_drive",
                    "session_token": "search_tok",
                    "search_query": "test search",
                },
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        # Verify search_query was passed in input_config
        call_args = mock_loader.load_data.call_args[0][0]
        assert call_args.get("search_query") == "test search"


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectorValidateSessionAdditional:
    """Cover uncovered branches in ConnectorValidateSession."""

    def test_unauthorized_returns_401(self, client, mock_sessions):
        """Line 288: decoded_token is None -> 401."""
        with patch("application.app.handle_auth", return_value=None):
            resp = client.post(
                "/api/connectors/validate-session",
                json={
                    "provider": "google_drive",
                    "session_token": "tok",
                },
            )
        assert resp.status_code == 401

    def test_refresh_token_failure_still_expired(self, client, mock_sessions):
        """Lines 299-310: refresh attempt fails, token stays expired."""
        mock_sessions["sessions"].insert_one({
            "session_token": "rf_fail_tok",
            "user": "test_user",
            "provider": "google_drive",
            "token_info": {
                "access_token": "old_at",
                "refresh_token": "rt",
                "expiry": 100,
            },
        })
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            mock_auth = MagicMock()
            mock_auth.is_token_expired.return_value = True
            mock_auth.refresh_access_token.side_effect = Exception("refresh failed")
            MockCC.create_auth.return_value = mock_auth
            resp = client.post(
                "/api/connectors/validate-session",
                json={
                    "provider": "google_drive",
                    "session_token": "rf_fail_tok",
                },
            )
        assert resp.status_code == 401
        data = json.loads(resp.data)
        assert data["expired"] is True

    def test_provider_extras_in_response(self, client, mock_sessions):
        """Lines 319-327: provider_extras are included in response."""
        mock_sessions["sessions"].insert_one({
            "session_token": "extras_tok",
            "user": "test_user",
            "provider": "google_drive",
            "token_info": {
                "access_token": "at",
                "refresh_token": "rt",
                "token_uri": "uri",
                "expiry": None,
                "custom_field": "custom_value",
            },
            "user_email": "user@test.com",
        })
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            mock_auth = MagicMock()
            mock_auth.is_token_expired.return_value = False
            MockCC.create_auth.return_value = mock_auth
            resp = client.post(
                "/api/connectors/validate-session",
                json={
                    "provider": "google_drive",
                    "session_token": "extras_tok",
                },
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert data["custom_field"] == "custom_value"
        assert data["user_email"] == "user@test.com"

    def test_exception_returns_500(self, client, mock_sessions):
        """Lines 331-333: general exception -> 500."""
        with patch("application.api.connector.routes.ConnectorCreator") as MockCC:
            MockCC.create_auth.side_effect = Exception("total failure")
            mock_sessions["sessions"].insert_one({
                "session_token": "err_tok",
                "user": "test_user",
                "provider": "google_drive",
                "token_info": {"access_token": "at"},
            })
            resp = client.post(
                "/api/connectors/validate-session",
                json={
                    "provider": "google_drive",
                    "session_token": "err_tok",
                },
            )
        assert resp.status_code == 500


@pytest.mark.unit
class TestConnectorDisconnectAdditional:
    """Cover uncovered branches in ConnectorDisconnect."""

    def test_exception_returns_500(self, client, mock_sessions):
        """Lines 353-355: exception in disconnect -> 500."""
        with patch(
            "application.api.connector.routes.sessions_collection"
        ) as mock_col:
            mock_col.delete_one.side_effect = Exception("db down")
            resp = client.post(
                "/api/connectors/disconnect",
                json={
                    "provider": "google_drive",
                    "session_token": "tok",
                },
            )
        assert resp.status_code == 500

    def test_unauthorized_still_works(self, client, mock_sessions):
        """ConnectorDisconnect doesn't check decoded_token, just data parsing.
        No auth check branch to cover, but confirm basic flow."""
        resp = client.post(
            "/api/connectors/disconnect",
            json={"provider": "google_drive"},
        )
        assert resp.status_code == 200


@pytest.mark.unit
class TestConnectorSyncAdditional:
    """Cover uncovered branches in ConnectorSync."""

    def test_unauthorized_returns_401(self, client, mock_sessions):
        """Line 373: decoded_token is None -> 401."""
        from bson.objectid import ObjectId as ObjId

        with patch("application.app.handle_auth", return_value=None):
            resp = client.post(
                "/api/connectors/sync",
                json={
                    "source_id": str(ObjId()),
                    "session_token": "tok",
                },
            )
        assert resp.status_code == 401

    def test_exception_returns_400(self, client, mock_sessions):
        """Lines 453-464: general exception returns 400."""
        sid = mock_sessions["sources"].insert_one({
            "user": "test_user",
            "name": "src",
            "remote_data": json.dumps({
                "provider": "google_drive",
                "file_ids": ["f1"],
            }),
        }).inserted_id
        with patch(
            "application.api.connector.routes.ingest_connector_task"
        ) as mock_ingest:
            mock_ingest.delay.side_effect = Exception("task error")
            resp = client.post(
                "/api/connectors/sync",
                json={
                    "source_id": str(sid),
                    "session_token": "tok",
                },
            )
        assert resp.status_code == 400

    def test_invalid_remote_data_json(self, client, mock_sessions):
        """Line 411-413: invalid remote_data JSON."""
        sid = mock_sessions["sources"].insert_one({
            "user": "test_user",
            "name": "src",
            "remote_data": "not-valid-json{",
        }).inserted_id
        resp = client.post(
            "/api/connectors/sync",
            json={
                "source_id": str(sid),
                "session_token": "tok",
            },
        )
        # remote_data parsing fails, remote_data = {}, no provider -> 400
        assert resp.status_code == 400
