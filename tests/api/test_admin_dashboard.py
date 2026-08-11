"""Endpoint tests for the admin dashboard (Phase 0 + Phase 1).

Repos are mocked at the route layer (the real SQL is covered by
tests/storage/db/repositories/test_admin_stats.py); these pin the route wiring,
the @admin_required boundary, the audited mutations, and the safety guards.
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def client():
    from application.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _fake_conn():
    yield Mock()


@contextmanager
def _admin(**route_patches):
    """Authenticate as admin and patch application.api.admin.routes.* members."""
    with ExitStack() as stack:
        stack.enter_context(
            patch("application.app.handle_auth", return_value={"sub": "admin1"})
        )
        stack.enter_context(
            patch("application.app.resolve_roles", return_value=["admin", "user"])
        )
        stack.enter_context(patch("application.api.admin.routes.db_readonly", _fake_conn))
        stack.enter_context(patch("application.api.admin.routes.db_session", _fake_conn))
        for name, value in route_patches.items():
            stack.enter_context(patch(f"application.api.admin.routes.{name}", value))
        yield


def _body(resp):
    return json.loads(resp.data)


@pytest.mark.unit
class TestGuard:
    def test_non_admin_forbidden(self, client):
        with patch("application.app.handle_auth", return_value={"sub": "u"}), patch(
            "application.app.resolve_roles", return_value=["user"]
        ):
            assert client.get("/api/admin/overview").status_code == 403

    def test_unauthenticated(self, client):
        with patch("application.app.handle_auth", return_value=None):
            assert client.get("/api/admin/overview").status_code == 401


@pytest.mark.unit
class TestOverview:
    def test_ok(self, client):
        stats = Mock()
        stats.overview.return_value = {
            "users": {"total": 3, "active": 3, "inactive": 0},
            "admins": 1,
            "agents": 0,
            "sources": 0,
            "conversations": 0,
            "new_users_7d": 1,
            "active_users_30d": 2,
            "failed_logins_7d": 0,
            "tokens_30d": 42,
        }
        with _admin(AdminStatsRepository=Mock(return_value=stats)):
            resp = client.get("/api/admin/overview")
        assert resp.status_code == 200
        data = _body(resp)
        assert data["users"]["total"] == 3
        assert data["tokens_30d"] == 42


@pytest.mark.unit
class TestAdminsAndRoles:
    def test_list_admins(self, client):
        roles = Mock()
        roles.list_admins.return_value = [
            {"user_id": "a", "granted_at": None, "sources": ["manual"]}
        ]
        with _admin(UserRolesRepository=Mock(return_value=roles)):
            resp = client.get("/api/admin/admins")
        assert resp.status_code == 200
        assert _body(resp)["admins"][0]["user_id"] == "a"

    def test_grant_admin_audited(self, client):
        roles = Mock()
        roles.grant.return_value = True
        events = Mock()
        with _admin(
            UserRolesRepository=Mock(return_value=roles),
            AuthEventsRepository=Mock(return_value=events),
        ):
            resp = client.post("/api/admin/users/alice/role")
        assert resp.status_code == 200
        assert _body(resp)["granted"] is True
        roles.grant.assert_called_once()
        # audited as role_granted
        assert events.insert.call_args.args[1] == "role_granted"

    def test_revoke_blocks_last_admin(self, client):
        roles = Mock()
        roles.list_admins.return_value = [{"user_id": "alice"}]
        with _admin(
            UserRolesRepository=Mock(return_value=roles),
            AuthEventsRepository=Mock(return_value=Mock()),
        ):
            resp = client.delete("/api/admin/users/alice/role")
        assert resp.status_code == 409
        roles.revoke.assert_not_called()

    def test_revoke_ok_when_other_admins_exist(self, client):
        roles = Mock()
        roles.list_admins.return_value = [{"user_id": "alice"}, {"user_id": "bob"}]
        roles.revoke.return_value = True
        events = Mock()
        with _admin(
            UserRolesRepository=Mock(return_value=roles),
            AuthEventsRepository=Mock(return_value=events),
        ):
            resp = client.delete("/api/admin/users/alice/role")
        assert resp.status_code == 200
        roles.revoke.assert_called_once()
        assert events.insert.call_args.args[1] == "role_revoked"


@pytest.mark.unit
class TestUserLifecycle:
    def test_self_deactivation_blocked(self, client):
        with _admin(UsersRepository=Mock()):
            resp = client.patch("/api/admin/users/admin1", json={"active": False})
        assert resp.status_code == 409

    def test_bad_body(self, client):
        with _admin(UsersRepository=Mock()):
            resp = client.patch("/api/admin/users/bob", json={})
        assert resp.status_code == 400

    def test_user_not_found(self, client):
        users = Mock()
        users.get.return_value = None
        with _admin(
            UsersRepository=Mock(return_value=users),
            AuthEventsRepository=Mock(return_value=Mock()),
        ):
            resp = client.patch("/api/admin/users/ghost", json={"active": True})
        assert resp.status_code == 404

    def test_deactivate_revokes_sessions_and_audits(self, client):
        users = Mock()
        users.get.return_value = {
            "id": "00000000-0000-0000-0000-000000000001",
            "user_id": "bob",
        }
        users.set_active.return_value = {"active": False}
        events = Mock()
        with _admin(
            UsersRepository=Mock(return_value=users),
            AuthEventsRepository=Mock(return_value=events),
        ), patch("application.api.admin.routes.denylist") as dl:
            resp = client.patch("/api/admin/users/bob", json={"active": False})
        assert resp.status_code == 200
        dl.deny_user.assert_called_once_with("bob")
        assert events.insert.call_args.args[1] == "admin_user_deactivated"

    def test_force_logout(self, client):
        events = Mock()
        with _admin(AuthEventsRepository=Mock(return_value=events)), patch(
            "application.api.admin.routes.denylist"
        ) as dl:
            dl.deny_user.return_value = True
            resp = client.post("/api/admin/users/bob/revoke-sessions")
        assert resp.status_code == 200
        dl.deny_user.assert_called_once_with("bob")

    def test_user_detail(self, client):
        users = Mock()
        users.get.return_value = {
            "user_id": "bob",
            "active": True,
            "created_at": None,
            "updated_at": None,
        }
        roles = Mock()
        roles.role_names_for.return_value = ["admin"]
        roles.list_for.return_value = []
        events = Mock()
        events.list_recent.return_value = []
        stats = Mock()
        stats.user_counts.return_value = {
            "agents": 0,
            "sources": 0,
            "conversations": 0,
            "tokens_30d": 0,
        }
        with _admin(
            UsersRepository=Mock(return_value=users),
            UserRolesRepository=Mock(return_value=roles),
            AuthEventsRepository=Mock(return_value=events),
            AdminStatsRepository=Mock(return_value=stats),
        ):
            resp = client.get("/api/admin/users/bob")
        assert resp.status_code == 200
        data = _body(resp)
        assert data["user"]["user_id"] == "bob"
        assert "admin" in data["roles"] and "user" in data["roles"]


@pytest.mark.unit
class TestUsageAndAudit:
    def test_usage(self, client):
        usage = Mock()
        usage.bucketed_totals.return_value = [
            {"bucket": "2026-06-14", "prompt_tokens": 5, "generated_tokens": 3}
        ]
        usage.sum_tokens_in_range.return_value = 8
        stats = Mock()
        stats.top_token_users.return_value = [{"user_id": "a", "tokens": 8}]
        with _admin(
            TokenUsageRepository=Mock(return_value=usage),
            AdminStatsRepository=Mock(return_value=stats),
        ):
            resp = client.get("/api/admin/usage?days=7&bucket=day")
        assert resp.status_code == 200
        data = _body(resp)
        assert data["total_tokens"] == 8
        assert len(data["series"]) == 1
        assert data["top_users"][0]["user_id"] == "a"

    def test_usage_invalid_bucket(self, client):
        with _admin():
            resp = client.get("/api/admin/usage?bucket=year")
        assert resp.status_code == 400

    def test_audit_feed(self, client):
        repo = Mock()
        repo.count_all.return_value = 1
        repo.list_all.return_value = [{"user_id": "a", "event": "oidc_login"}]
        with _admin(AuthEventsRepository=Mock(return_value=repo)):
            resp = client.get("/api/admin/audit?event=oidc_login&page=1&page_size=10")
        assert resp.status_code == 200
        data = _body(resp)
        assert data["total"] == 1
        assert data["events"][0]["event"] == "oidc_login"
        repo.list_all.assert_called_once()

    def test_device_audit_feed(self, client):
        repo = Mock()
        repo.count_global.return_value = 0
        repo.list_global.return_value = []
        with _admin(DeviceAuditLogRepository=Mock(return_value=repo)):
            resp = client.get("/api/admin/devices/audit?decision=denied")
        assert resp.status_code == 200
        assert _body(resp)["invocations"] == []
