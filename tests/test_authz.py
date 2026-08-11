"""Unit tests for role resolution and the authorization decorator."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from flask import Flask, request

from application.api.user import authz


@contextmanager
def _fake_conn():
    yield Mock()


def _patch_oidc(role_names=None, raise_db=False):
    """Patch authz for OIDC mode with a stubbed UserRolesRepository."""
    repo = Mock()
    repo.role_names_for.return_value = role_names or []
    settings_patch = patch.object(authz, "settings")
    db_patch = patch.object(authz, "db_readonly", _fake_conn)
    if raise_db:
        repo_patch = patch.object(authz, "UserRolesRepository", side_effect=RuntimeError("db down"))
    else:
        repo_patch = patch.object(authz, "UserRolesRepository", return_value=repo)
    return settings_patch, db_patch, repo_patch, repo


@pytest.mark.unit
class TestResolveRoles:
    def test_no_token_is_user_only(self):
        assert authz.resolve_roles(None) == ["user"]

    def test_simple_jwt_never_admin(self):
        with patch.object(authz, "settings") as s:
            s.AUTH_TYPE = "simple_jwt"
            assert authz.resolve_roles({"sub": "local"}) == ["user"]

    def test_session_jwt_never_admin(self):
        with patch.object(authz, "settings") as s:
            s.AUTH_TYPE = "session_jwt"
            assert authz.resolve_roles({"sub": "abc-uuid"}) == ["user"]

    def test_none_mode_local_admin_disabled(self):
        with patch.object(authz, "settings") as s:
            s.AUTH_TYPE = None
            s.LOCAL_MODE_ADMIN = False
            assert authz.resolve_roles({"sub": "local"}) == ["user"]

    def test_none_mode_local_admin_enabled(self):
        with patch.object(authz, "settings") as s:
            s.AUTH_TYPE = None
            s.LOCAL_MODE_ADMIN = True
            assert authz.resolve_roles({"sub": "local"}) == ["admin", "user"]

    def test_oidc_db_grant_makes_admin(self):
        sp, dp, rp, repo = _patch_oidc(role_names=["admin"])
        with sp as s, dp, rp:
            s.AUTH_TYPE = "oidc"
            assert authz.resolve_roles({"sub": "alice"}) == ["admin", "user"]
            repo.role_names_for.assert_called_once_with("alice")

    def test_oidc_no_grant_is_user(self):
        sp, dp, rp, _ = _patch_oidc(role_names=[])
        with sp as s, dp, rp:
            s.AUTH_TYPE = "oidc"
            assert authz.resolve_roles({"sub": "bob"}) == ["user"]

    def test_oidc_ignores_forged_roles_claim(self):
        sp, dp, rp, _ = _patch_oidc(role_names=[])
        with sp as s, dp, rp:
            s.AUTH_TYPE = "oidc"
            # A self-minted token asserting admin must NOT be trusted.
            assert authz.resolve_roles({"sub": "bob", "roles": ["admin"]}) == ["user"]

    def test_oidc_db_error_fails_open_to_user(self):
        sp, dp, rp, _ = _patch_oidc(raise_db=True)
        with sp as s, dp, rp:
            s.AUTH_TYPE = "oidc"
            assert authz.resolve_roles({"sub": "bob"}) == ["user"]


@pytest.mark.unit
class TestHasRole:
    def test_user_role_always_true(self):
        assert authz.has_role(None, "user")
        assert authz.has_role({}, "user")
        assert authz.has_role({"roles": []}, "user")

    def test_admin_requires_grant(self):
        assert authz.has_role({"roles": ["admin"]}, "admin")
        assert not authz.has_role({"roles": ["user"]}, "admin")

    def test_missing_roles_key_is_not_admin(self):
        assert not authz.has_role({"sub": "x"}, "admin")
        assert not authz.has_role(None, "admin")


@pytest.mark.unit
class TestRequireRole:
    def _invoke(self, token):
        app = Flask(__name__)

        @authz.require_role("admin")
        def view():
            return "ok"

        with app.test_request_context("/"):
            request.decoded_token = token
            return view()

    def test_no_token_returns_401(self):
        resp = self._invoke(None)
        assert resp.status_code == 401

    def test_non_admin_returns_403(self):
        resp = self._invoke({"sub": "x", "roles": ["user"]})
        assert resp.status_code == 403

    def test_missing_roles_key_returns_403_without_raising(self):
        resp = self._invoke({"sub": "x"})
        assert resp.status_code == 403

    def test_admin_passes_through(self):
        assert self._invoke({"sub": "x", "roles": ["admin"]}) == "ok"
