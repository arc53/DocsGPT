"""
PoC / regression test for CWE-862: Missing authentication on /api/delete_by_ids.

The DeleteByIds endpoint at /api/delete_by_ids does not check request.decoded_token,
allowing any unauthenticated user to delete vector-store indexes belonging to any user.

This test verifies that:
1. An unauthenticated request (no token) to /api/delete_by_ids returns 401.
2. An authenticated request is allowed to proceed (returns 200 or 400 depending
   on whether the IDs exist — but NOT 401).
"""

import os
import sys

import pytest

# Ensure the application root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture()
def app(monkeypatch):
    """Create a minimal Flask app with the sources blueprint registered."""
    # Patch settings BEFORE importing app machinery
    from application.core.settings import settings

    monkeypatch.setattr(settings, "AUTH_TYPE", "simple_jwt")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-secret-key")

    # Use mongomock so we don't need a real MongoDB
    import mongomock

    mock_client = mongomock.MongoClient()
    mock_db = mock_client[settings.MONGO_DB_NAME]

    monkeypatch.setattr(
        "application.api.user.base.sources_collection", mock_db["sources"]
    )

    from application.app import app as flask_app

    flask_app.config["TESTING"] = True
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_header(app):
    """Return a valid Authorization header."""
    from jose import jwt
    from application.core.settings import settings

    token = jwt.encode({"sub": "test-user"}, settings.JWT_SECRET_KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


class TestDeleteByIdsAuth:
    """Verify that /api/delete_by_ids requires authentication."""

    def test_unauthenticated_request_returns_401(self, client):
        """An unauthenticated request MUST be rejected with 401."""
        resp = client.get("/api/delete_by_ids?path=some-id-1,some-id-2")
        assert resp.status_code == 401, (
            f"Expected 401 for unauthenticated /api/delete_by_ids, got {resp.status_code}. "
            "Endpoint is missing authentication check (CWE-862)."
        )

    def test_authenticated_request_is_allowed(self, client, auth_header):
        """An authenticated request should NOT get 401 (may get 400 if IDs don't exist)."""
        resp = client.get(
            "/api/delete_by_ids?path=nonexistent-id", headers=auth_header
        )
        # 200 or 400 are acceptable — the point is it should NOT be 401
        assert resp.status_code != 401, (
            f"Authenticated request got 401; auth check may be broken."
        )

    def test_missing_path_param_returns_400(self, client, auth_header):
        """Missing 'path' parameter should return 400, not allow operation."""
        resp = client.get("/api/delete_by_ids", headers=auth_header)
        assert resp.status_code == 400
