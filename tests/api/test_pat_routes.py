"""Endpoint tests for personal access token management (/api/user/tokens, admin)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.pat import routes as pat_routes
from docsgpt.api.pat import tokens as pat_tokens

AGENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def client():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(autouse=True)
def _policy(monkeypatch):
    monkeypatch.setattr(pat_tokens.settings, "AUTH_TYPE", "oidc")
    monkeypatch.setattr(pat_tokens.settings, "PAT_ENABLED", True)
    monkeypatch.setattr(pat_tokens.settings, "PAT_DEFAULT_LIFETIME_DAYS", 90)
    monkeypatch.setattr(pat_tokens.settings, "PAT_MAX_LIFETIME_DAYS", 365)
    monkeypatch.setattr(pat_tokens.settings, "PAT_ALLOW_NON_EXPIRING", False)
    monkeypatch.setattr(pat_tokens.settings, "PAT_MAX_PER_USER", 25)


@pytest.fixture
def db(pg_conn):
    """Route every session the token code opens onto the test's rolled-back connection."""

    @contextmanager
    def _yield_conn():
        yield pg_conn

    with patch.object(pat_routes, "db_session", _yield_conn), patch.object(
        pat_routes, "db_readonly", _yield_conn
    ), patch.object(pat_tokens, "db_session", _yield_conn), patch.object(
        pat_tokens, "db_readonly", _yield_conn
    ):
        yield pg_conn


@contextmanager
def _session(sub="alice", roles=("user",)):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=list(roles)
    ), patch("docsgpt.app.oidc_session_denied", return_value=False):
        yield


def _create(client, **body):
    body.setdefault("name", "ci")
    body.setdefault("scopes", ["agents:write"])
    with _session():
        return client.post("/api/user/tokens", json=body)


class TestCreate:
    def test_returns_the_secret_once_and_stores_only_its_hash(self, client, db):
        response = _create(client)
        assert response.status_code == 201
        body = json.loads(response.data)
        token = body["token"]
        assert token.startswith("dgpt_pat_")
        public = body["personal_access_token"]
        assert public["token_prefix"] == token[:15]
        assert "token" not in public and "token_hash" not in public
        stored = db.execute(text("SELECT token_hash FROM personal_access_tokens")).scalar_one()
        assert stored == pat_tokens.hash_token(token)
        assert token not in stored

        with _session():
            listed = json.loads(client.get("/api/user/tokens").data)
        assert [t["name"] for t in listed["tokens"]] == ["ci"]
        assert token not in json.dumps(listed)

    def test_default_expiry_applies(self, client, db):
        body = json.loads(_create(client).data)
        assert body["personal_access_token"]["expires_at"] is not None

    def test_non_expiring_needs_operator_opt_in(self, client, db, monkeypatch):
        assert _create(client, expires_in_days=0).status_code == 400
        monkeypatch.setattr(pat_tokens.settings, "PAT_ALLOW_NON_EXPIRING", True)
        response = _create(client, expires_in_days=0)
        assert response.status_code == 201
        assert json.loads(response.data)["personal_access_token"]["expires_at"] is None

    def test_lifetime_cap(self, client, db):
        assert _create(client, expires_in_days=366).status_code == 400

    def test_resource_filter_is_stored(self, client, db):
        response = _create(client, resource_filter={"agents": [AGENT_A]})
        assert json.loads(response.data)["personal_access_token"]["resource_filter"] == {
            "agents": [AGENT_A]
        }

    @pytest.mark.parametrize(
        "body",
        [
            {"name": ""},
            {"name": "x" * 101},
            {"scopes": []},
            {"scopes": ["admin:all"]},
            {"resource_filter": {"agents": ["nope"]}},
            {"resource_filter": {"sources": [AGENT_A]}},
            {"expires_in_days": "soon"},
        ],
    )
    def test_validation(self, client, db, body):
        assert _create(client, **body).status_code == 400

    def test_duplicate_name_conflicts(self, client, db):
        assert _create(client).status_code == 201
        assert _create(client).status_code == 409

    def test_per_user_cap(self, client, db, monkeypatch):
        monkeypatch.setattr(pat_tokens.settings, "PAT_MAX_PER_USER", 1)
        assert _create(client, name="one").status_code == 201
        assert _create(client, name="two").status_code == 409

    @pytest.mark.parametrize("auth_type", ["simple_jwt", "session_jwt"])
    def test_unavailable_without_a_stable_identity(self, client, db, monkeypatch, auth_type):
        monkeypatch.setattr(pat_tokens.settings, "AUTH_TYPE", auth_type)
        assert _create(client).status_code == 403

    def test_disabled_by_operator(self, client, db, monkeypatch):
        monkeypatch.setattr(pat_tokens.settings, "PAT_ENABLED", False)
        assert _create(client).status_code == 403
        with _session():
            assert json.loads(client.get("/api/user/tokens").data)["policy"]["enabled"] is False

    def test_requires_a_session(self, client, db):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.post("/api/user/tokens", json={"name": "x", "scopes": ["agents:read"]}).status_code == 401

    def test_audited(self, client, db):
        _create(client)
        event, metadata = db.execute(
            text("SELECT event, metadata FROM auth_events WHERE user_id = 'alice'")
        ).one()
        assert event == "pat_created"
        assert metadata["scopes"] == ["agents:write"]
        assert "dgpt_pat_" not in json.dumps(metadata)


class TestList:
    def test_includes_scope_catalog_and_policy(self, client, db):
        with _session():
            body = json.loads(client.get("/api/user/tokens").data)
        assert {s["name"] for s in body["scopes"]} == set(pat_tokens.SCOPES)
        assert body["policy"] == {
            "enabled": True,
            "default_lifetime_days": 90,
            "max_lifetime_days": 365,
            "allow_non_expiring": False,
            "max_per_user": 25,
            "filterable_families": list(pat_tokens.FILTERABLE_FAMILIES),
        }

    def test_is_owner_scoped(self, client, db):
        _create(client)
        with _session(sub="bob"):
            assert json.loads(client.get("/api/user/tokens").data)["tokens"] == []


class TestEndToEnd:
    def test_created_token_authenticates_and_revocation_is_immediate(self, client, db):
        created = json.loads(_create(client, scopes=["prompts:read"]).data)
        headers = {"Authorization": f"Bearer {created['token']}"}

        me = client.get("/api/user/me", headers=headers)
        assert me.status_code == 200
        body = json.loads(me.data)
        assert body["user_id"] == "alice"
        assert body["token"]["scopes"] == ["prompts:read"]

        # Scoped: cannot list agents, cannot manage tokens.
        assert client.get("/api/get_agents", headers=headers).status_code == 403
        assert client.get("/api/user/tokens", headers=headers).status_code == 403
        assert client.post("/api/user/tokens", headers=headers, json={}).status_code == 403

        with _session():
            token_id = created["personal_access_token"]["id"]
            assert client.delete(f"/api/user/tokens/{token_id}").status_code == 200
        assert client.get("/api/user/me", headers=headers).status_code == 401

    def test_tampered_token_is_rejected(self, client, db):
        token = json.loads(_create(client).data)["token"]
        response = client.get("/api/user/me", headers={"Authorization": f"Bearer {token}x"})
        assert response.status_code == 401


class TestRevoke:
    def test_cannot_revoke_someone_elses_token(self, client, db):
        token_id = json.loads(_create(client).data)["personal_access_token"]["id"]
        with _session(sub="bob"):
            assert client.delete(f"/api/user/tokens/{token_id}").status_code == 404

    def test_unknown_and_malformed_ids(self, client, db):
        with _session():
            assert client.delete(f"/api/user/tokens/{AGENT_A}").status_code == 404
            assert client.delete("/api/user/tokens/not-a-uuid").status_code == 404


class TestAdmin:
    def test_requires_admin(self, client, db):
        with _session():
            assert client.get("/api/admin/users/alice/tokens").status_code == 403
            assert client.delete(f"/api/admin/tokens/{AGENT_A}").status_code == 403

    def test_admin_can_list_and_revoke_any_token(self, client, db):
        created = json.loads(_create(client).data)
        token_id = created["personal_access_token"]["id"]
        with _session(sub="root", roles=("admin", "user")):
            listed = json.loads(client.get("/api/admin/users/alice/tokens").data)
            assert [t["id"] for t in listed["tokens"]] == [token_id]
            assert client.delete(f"/api/admin/tokens/{token_id}").status_code == 200
            assert client.delete(f"/api/admin/tokens/{token_id}").status_code == 404
        headers = {"Authorization": f"Bearer {created['token']}"}
        assert client.get("/api/user/me", headers=headers).status_code == 401

    def test_revoke_sessions_also_revokes_tokens(self, client, db):
        from docsgpt.api.admin import routes as admin_routes

        @contextmanager
        def _yield_conn():
            yield db

        created = json.loads(_create(client).data)
        with _session(sub="root", roles=("admin", "user")), patch.object(
            admin_routes, "db_session", _yield_conn
        ), patch.object(admin_routes.denylist, "deny_user", return_value=True):
            assert client.post("/api/admin/users/alice/revoke-sessions").status_code == 200
        headers = {"Authorization": f"Bearer {created['token']}"}
        assert client.get("/api/user/me", headers=headers).status_code == 401
