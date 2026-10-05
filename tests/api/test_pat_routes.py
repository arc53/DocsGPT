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

    @pytest.mark.parametrize("body", [[1], "text", 5])
    def test_non_object_body_is_a_client_error(self, client, db, body):
        with _session():
            assert client.post("/api/user/tokens", json=body).status_code == 400

    def test_duplicate_name_conflicts(self, client, db):
        assert _create(client).status_code == 201
        assert _create(client).status_code == 409

    def test_expired_token_does_not_reserve_its_name(self, client, db):
        assert _create(client).status_code == 201
        db.execute(text("UPDATE personal_access_tokens SET expires_at = now() - interval '1 day'"))
        assert _create(client).status_code == 201
        rows = db.execute(
            text("SELECT status, revoke_reason FROM personal_access_tokens ORDER BY created_at")
        ).all()
        assert [tuple(r) for r in rows] == [("revoked", "expired"), ("active", None)]

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


class TestExpiredStatus:
    def test_expired_token_is_reported_as_expired_not_active(self, client, db):
        _create(client)
        with _session():
            assert json.loads(client.get("/api/user/tokens").data)["tokens"][0]["status"] == "active"
        db.execute(text("UPDATE personal_access_tokens SET expires_at = now() - interval '1 day'"))
        with _session():
            assert json.loads(client.get("/api/user/tokens").data)["tokens"][0]["status"] == "expired"


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


class TestRegenerate:
    def _regen(self, client, token_id, **body):
        with _session():
            return client.post(f"/api/user/tokens/{token_id}/regenerate", json=body)

    def test_new_secret_works_old_one_stops_and_the_rest_is_kept(self, client, db):
        created = json.loads(
            _create(client, scopes=["prompts:read"], resource_filter={"prompts": [AGENT_A]}).data
        )
        old, token_id = created["token"], created["personal_access_token"]["id"]
        response = self._regen(client, token_id)
        assert response.status_code == 200
        body = json.loads(response.data)
        new, public = body["token"], body["personal_access_token"]
        assert new.startswith("dgpt_pat_") and new != old
        assert public["id"] == token_id and public["name"] == "ci"
        assert public["scopes"] == ["prompts:read"]
        assert public["resource_filter"] == {"prompts": [AGENT_A]}
        assert public["token_prefix"] == new[:15]
        assert public["regenerated_at"] is not None
        assert public["last_used_at"] is None

        assert client.get("/api/user/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
        me = client.get("/api/user/me", headers={"Authorization": f"Bearer {new}"})
        assert me.status_code == 200
        assert json.loads(me.data)["token"]["id"] == token_id
        stored = db.execute(text("SELECT token_hash FROM personal_access_tokens")).scalar_one()
        assert stored == pat_tokens.hash_token(new)

    def test_expiry_is_reset_to_the_original_lifetime(self, client, db):
        token_id = json.loads(_create(client, expires_in_days=30).data)["personal_access_token"]["id"]
        # 20 days in: 10 days left.
        db.execute(
            text(
                "UPDATE personal_access_tokens SET created_at = now() - interval '20 days', "
                "expires_at = now() + interval '10 days'"
            )
        )
        self._regen(client, token_id)
        days_left = db.execute(
            text("SELECT extract(epoch FROM expires_at - now()) / 86400 FROM personal_access_tokens")
        ).scalar_one()
        assert 29.9 < float(days_left) < 30.1

    def test_explicit_lifetime_is_honoured_and_capped(self, client, db):
        token_id = json.loads(_create(client).data)["personal_access_token"]["id"]
        assert self._regen(client, token_id, expires_in_days=7).status_code == 200
        days_left = db.execute(
            text("SELECT extract(epoch FROM expires_at - now()) / 86400 FROM personal_access_tokens")
        ).scalar_one()
        assert 6.9 < float(days_left) < 7.1
        assert self._regen(client, token_id, expires_in_days=366).status_code == 400
        assert self._regen(client, token_id, expires_in_days=0).status_code == 400

    def test_an_expired_token_can_be_renewed(self, client, db):
        created = json.loads(_create(client, expires_in_days=30).data)
        db.execute(
            text(
                "UPDATE personal_access_tokens SET created_at = now() - interval '31 days', "
                "expires_at = now() - interval '1 day'"
            )
        )
        old_headers = {"Authorization": f"Bearer {created['token']}"}
        assert client.get("/api/user/me", headers=old_headers).status_code == 401
        body = json.loads(self._regen(client, created["personal_access_token"]["id"]).data)
        assert body["personal_access_token"]["status"] == "active"
        headers = {"Authorization": f"Bearer {body['token']}"}
        assert client.get("/api/user/me", headers=headers).status_code == 200

    def test_non_expiring_token_stays_non_expiring_only_while_the_operator_allows_it(
        self, client, db, monkeypatch
    ):
        monkeypatch.setattr(pat_tokens.settings, "PAT_ALLOW_NON_EXPIRING", True)
        token_id = json.loads(_create(client, expires_in_days=0).data)["personal_access_token"]["id"]
        assert json.loads(self._regen(client, token_id).data)["personal_access_token"]["expires_at"] is None
        monkeypatch.setattr(pat_tokens.settings, "PAT_ALLOW_NON_EXPIRING", False)
        renewed = json.loads(self._regen(client, token_id).data)["personal_access_token"]
        assert renewed["expires_at"] is not None  # falls back to the default lifetime

    def test_revoked_foreign_unknown_and_malformed_tokens_are_not_found(self, client, db):
        token_id = json.loads(_create(client).data)["personal_access_token"]["id"]
        with _session(sub="bob"):
            assert client.post(f"/api/user/tokens/{token_id}/regenerate").status_code == 404
        with _session():
            client.delete(f"/api/user/tokens/{token_id}")
        assert self._regen(client, token_id).status_code == 404
        assert self._regen(client, AGENT_A).status_code == 404
        assert self._regen(client, f"urn:uuid:{AGENT_A}").status_code == 404

    def test_a_token_cannot_regenerate_itself_or_others(self, client, db):
        created = json.loads(_create(client, scopes=list(pat_tokens.SCOPES)).data)
        headers = {"Authorization": f"Bearer {created['token']}"}
        token_id = created["personal_access_token"]["id"]
        response = client.post(f"/api/user/tokens/{token_id}/regenerate", headers=headers)
        assert response.status_code == 403
        assert json.loads(response.data)["error"] == "not_available_to_tokens"

    def test_requires_a_session_and_an_object_body(self, client, db):
        token_id = json.loads(_create(client).data)["personal_access_token"]["id"]
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.post(f"/api/user/tokens/{token_id}/regenerate").status_code == 401
        with _session():
            assert client.post(f"/api/user/tokens/{token_id}/regenerate", json=[1]).status_code == 400

    def test_audited_without_the_secret(self, client, db):
        token_id = json.loads(_create(client).data)["personal_access_token"]["id"]
        self._regen(client, token_id)
        metadata = db.execute(
            text("SELECT metadata FROM auth_events WHERE event = 'pat_regenerated'")
        ).scalar_one()
        assert metadata["token_id"] == token_id
        assert "dgpt_pat_" not in json.dumps(metadata)


class TestRevoke:
    def test_cannot_revoke_someone_elses_token(self, client, db):
        token_id = json.loads(_create(client).data)["personal_access_token"]["id"]
        with _session(sub="bob"):
            assert client.delete(f"/api/user/tokens/{token_id}").status_code == 404

    @pytest.mark.parametrize(
        "token_id",
        [AGENT_A, "not-a-uuid", f"urn:uuid:{AGENT_A}", "{" + AGENT_A + "}", AGENT_A.replace("-", "")],
    )
    def test_unknown_and_malformed_ids(self, client, db, token_id):
        # uuid.UUID() accepts urn:/braced/bare-hex spellings that Postgres rejects; none may reach the cast.
        with _session():
            assert client.delete(f"/api/user/tokens/{token_id}").status_code == 404
        with _session(sub="root", roles=("admin", "user")):
            assert client.delete(f"/api/admin/tokens/{token_id}").status_code == 404


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
        events = db.execute(
            text("SELECT metadata FROM auth_events WHERE user_id = 'alice' AND event = 'pat_revoked'")
        ).all()
        assert [e[0]["token_id"] for e in events] == [created["personal_access_token"]["id"]]
        assert events[0][0]["via"] == "admin_sessions_revoked"
