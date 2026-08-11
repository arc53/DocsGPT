"""Endpoint tests for GET /api/user/me and GET /api/admin/users."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def client():
    from application.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _fake_readonly():
    yield Mock()


@pytest.mark.unit
class TestMeEndpoint:
    def test_returns_user_id_and_roles(self, client):
        with patch("application.app.handle_auth", return_value={"sub": "u1"}), patch(
            "application.app.resolve_roles", return_value=["user"]
        ):
            resp = client.get("/api/user/me")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["user_id"] == "u1"
        assert data["roles"] == ["user"]

    def test_echoes_admin_role(self, client):
        with patch("application.app.handle_auth", return_value={"sub": "a1"}), patch(
            "application.app.resolve_roles", return_value=["admin", "user"]
        ):
            resp = client.get("/api/user/me")
        data = json.loads(resp.data)
        assert data["roles"] == ["admin", "user"]

    def test_unauthenticated_returns_401(self, client):
        with patch("application.app.handle_auth", return_value=None):
            resp = client.get("/api/user/me")
        assert resp.status_code == 401


@pytest.mark.unit
class TestAdminUsersEndpoint:
    def test_non_admin_forbidden(self, client):
        with patch("application.app.handle_auth", return_value={"sub": "u1"}), patch(
            "application.app.resolve_roles", return_value=["user"]
        ):
            resp = client.get("/api/admin/users")
        assert resp.status_code == 403

    def test_unauthenticated_401(self, client):
        with patch("application.app.handle_auth", return_value=None):
            resp = client.get("/api/admin/users")
        assert resp.status_code == 401

    @staticmethod
    def _admin_get(client, repo, query=""):
        # The list endpoint resolves users (with last_seen) via AdminStatsRepository.
        with patch("application.app.handle_auth", return_value={"sub": "a1"}), patch(
            "application.app.resolve_roles", return_value=["admin", "user"]
        ), patch("application.api.admin.routes.db_readonly", _fake_readonly), patch(
            "application.api.admin.routes.AdminStatsRepository", return_value=repo
        ):
            return client.get(f"/api/admin/users{query}")

    @staticmethod
    def _rows(n):
        return [
            {
                "user_id": f"u{i}",
                "active": True,
                "created_at": "2026-01-01",
                "last_seen": "2026-02-01",
            }
            for i in range(n)
        ]

    def test_admin_gets_user_list(self, client):
        repo = Mock()
        repo.list_users.return_value = (1, self._rows(1))
        resp = self._admin_get(client, repo)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert data["total"] == 1
        assert data["users"][0] == {
            "user_id": "u0",
            "active": True,
            "created_at": "2026-01-01",
            "last_seen": "2026-02-01",
        }
        repo.list_users.assert_called_once_with(None, 0, 25)

    def test_page_size_clamped_and_offset_computed(self, client):
        repo = Mock()
        repo.list_users.return_value = (0, [])
        self._admin_get(client, repo, "?page=2&page_size=999")
        # page_size clamps to _MAX_PAGE_SIZE=100, offset=(2-1)*100
        repo.list_users.assert_called_once_with(None, 100, 100)

    def test_non_int_params_fall_back_to_defaults(self, client):
        repo = Mock()
        repo.list_users.return_value = (0, [])
        self._admin_get(client, repo, "?page=abc&page_size=xyz")
        repo.list_users.assert_called_once_with(None, 0, 25)

    def test_user_id_filter_passed_first_positional(self, client):
        repo = Mock()
        repo.list_users.return_value = (0, [])
        self._admin_get(client, repo, "?user_id=foo")
        repo.list_users.assert_called_once_with("foo", 0, 25)

    def test_has_more_true_when_more_pages_remain(self, client):
        repo = Mock()
        repo.list_users.return_value = (5, self._rows(3))
        resp = self._admin_get(client, repo, "?page=1&page_size=3")
        assert json.loads(resp.data)["has_more"] is True

    def test_has_more_false_at_last_page(self, client):
        repo = Mock()
        repo.list_users.return_value = (3, self._rows(3))
        resp = self._admin_get(client, repo, "?page=1&page_size=3")
        assert json.loads(resp.data)["has_more"] is False


@pytest.mark.unit
class TestChokepointOverwritesForgedRoles:
    """The real resolver must overwrite any inbound 'roles' claim end-to-end.

    These drive a forged admin token through the actual app.py chokepoint (only
    handle_auth is patched; resolve_roles runs for real), so a regression that
    trusted the JWT's roles claim would be caught.
    """

    def test_forged_admin_ignored_in_session_jwt_mode(self, client):
        from application.api.user import authz

        forged = lambda *a, **k: {"sub": "attacker", "roles": ["admin"]}  # noqa: E731
        with patch("application.app.handle_auth", side_effect=forged), patch.object(
            authz.settings, "AUTH_TYPE", "session_jwt"
        ):
            admin_resp = client.get("/api/admin/users")
            me_resp = client.get("/api/user/me")
        assert admin_resp.status_code == 403
        assert json.loads(me_resp.data)["roles"] == ["user"]

    def test_forged_admin_ignored_in_no_auth_with_local_admin_off(self, client):
        from application.api.user import authz

        forged = lambda *a, **k: {"sub": "local", "roles": ["admin"]}  # noqa: E731
        with patch("application.app.handle_auth", side_effect=forged), patch.object(
            authz.settings, "AUTH_TYPE", None
        ), patch.object(authz.settings, "LOCAL_MODE_ADMIN", False):
            admin_resp = client.get("/api/admin/users")
            me_resp = client.get("/api/user/me")
        assert admin_resp.status_code == 403
        assert json.loads(me_resp.data)["roles"] == ["user"]

    def test_forged_admin_ignored_in_oidc_mode_without_grant(self, client):
        # OIDC is the only privilege-bearing mode: drive a forged admin claim
        # through the real chokepoint with NO DB grant — must resolve to user.
        from application.api.user import authz

        repo = Mock()
        repo.role_names_for.return_value = []  # no persisted grant
        forged = lambda *a, **k: {"sub": "attacker", "roles": ["admin"]}  # noqa: E731
        with patch("application.app.handle_auth", side_effect=forged), patch(
            "application.app.oidc_session_denied", return_value=False
        ), patch.object(authz.settings, "AUTH_TYPE", "oidc"), patch.object(
            authz, "db_readonly", _fake_readonly
        ), patch.object(authz, "UserRolesRepository", return_value=repo):
            admin_resp = client.get("/api/admin/users")
            me_resp = client.get("/api/user/me")
        assert admin_resp.status_code == 403
        assert json.loads(me_resp.data)["roles"] == ["user"]
        # Proves the chokepoint fired and resolved from the DB, not the claim.
        repo.role_names_for.assert_called_with("attacker")

    def test_oidc_db_grant_yields_admin_end_to_end(self, client):
        # The DB grant (not any claim) is the source of admin, end-to-end.
        from application.api.user import authz

        authz_repo = Mock()
        authz_repo.role_names_for.return_value = ["admin"]
        admin_repo = Mock()
        admin_repo.list_users.return_value = (0, [])
        with patch(
            "application.app.handle_auth", return_value={"sub": "alice"}
        ), patch("application.app.oidc_session_denied", return_value=False), patch.object(
            authz.settings, "AUTH_TYPE", "oidc"
        ), patch.object(authz, "db_readonly", _fake_readonly), patch.object(
            authz, "UserRolesRepository", return_value=authz_repo
        ), patch("application.api.admin.routes.db_readonly", _fake_readonly), patch(
            "application.api.admin.routes.AdminStatsRepository", return_value=admin_repo
        ):
            admin_resp = client.get("/api/admin/users")
            me_resp = client.get("/api/user/me")
        assert admin_resp.status_code == 200
        assert json.loads(me_resp.data)["roles"] == ["admin", "user"]
