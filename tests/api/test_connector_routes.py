"""Tests for application/api/connector/routes.py"""

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
