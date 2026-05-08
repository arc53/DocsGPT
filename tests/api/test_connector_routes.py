"""Tests for application/api/connector/routes.py"""

import base64
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


def _make_oid():
    """Return a unique 24-hex string usable as a document _id."""
    return uuid.uuid4().hex[:24]


class _InMemoryCollection:
    """Minimal dict-backed Mongo collection for connector route tests."""

    def __init__(self):
        self._docs = []

    def _matches(self, doc, query):
        for k, v in query.items():
            dv = doc.get(k)
            # Normalize ObjectId vs string comparison
            if str(dv) != str(v):
                return False
        return True

    def insert_one(self, doc):
        new_doc = dict(doc)
        if "_id" not in new_doc:
            new_doc["_id"] = _make_oid()
        self._docs.append(new_doc)
        result = MagicMock()
        result.inserted_id = new_doc["_id"]
        return result

    def find_one(self, query):
        import copy
        for doc in self._docs:
            if self._matches(doc, query):
                return copy.deepcopy(doc)
        return None

    def find(self, query=None):
        import copy
        query = query or {}
        return [copy.deepcopy(d) for d in self._docs if self._matches(d, query)]

    def delete_one(self, query):
        for i, doc in enumerate(self._docs):
            if self._matches(doc, query):
                self._docs.pop(i)
                result = MagicMock()
                result.deleted_count = 1
                return result
        result = MagicMock()
        result.deleted_count = 0
        return result

    def update_one(self, query, update, upsert=False):
        result = MagicMock()
        result.modified_count = 0
        for doc in self._docs:
            if self._matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                result.modified_count = 1
                return result
        result.modified_count = 0
        return result

    def find_one_and_update(self, query, update, upsert=False, return_document=False):
        import copy
        for doc in self._docs:
            if self._matches(doc, query):
                before = copy.deepcopy(doc)
                if "$set" in update:
                    doc.update(update["$set"])
                return before
        if upsert:
            new_doc = dict(query)
            if "$set" in update:
                new_doc.update(update["$set"])
            self._docs.append(new_doc)
        return None


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
    sessions = _InMemoryCollection()
    sources = _InMemoryCollection()
    monkeypatch.setattr("application.api.connector.routes.sessions_collection", sessions)
    monkeypatch.setattr("application.api.connector.routes.sources_collection", sources)
    return {"sessions": sessions, "sources": sources}


class TestConnectorAuth:
    pass

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




class TestConnectorFiles:
    pass

    @pytest.mark.unit
    def test_missing_params(self, client):
        resp = client.post("/api/connectors/files", json={"provider": "google_drive"})
        assert resp.status_code == 400





class TestConnectorValidateSession:
    pass

    @pytest.mark.unit
    def test_missing_params(self, client):
        resp = client.post("/api/connectors/validate-session", json={"provider": "google_drive"})
        assert resp.status_code == 400






class TestConnectorDisconnect:
    pass

    @pytest.mark.unit
    def test_missing_provider(self, client):
        resp = client.post("/api/connectors/disconnect", json={})
        assert resp.status_code == 400




class TestConnectorSync:
    pass

class TestConnectorCallbackStatus:
    pass

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
    pass

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











@pytest.mark.unit
class TestConnectorFilesAdditional:
    """Additional tests for ConnectorFiles."""





@pytest.mark.unit
class TestConnectorFilesSearchQuery:
    """Test ConnectorFiles with search_query parameter."""



# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectorValidateSessionAdditional:
    """Cover uncovered branches in ConnectorValidateSession."""






@pytest.mark.unit
class TestConnectorDisconnectAdditional:
    """Cover uncovered branches in ConnectorDisconnect."""




@pytest.mark.unit
class TestConnectorSyncAdditional:
    """Cover uncovered branches in ConnectorSync."""



