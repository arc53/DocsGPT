"""A team principal is never a person: nobody signs in, gets a token or is administered as one (plan WP2, R1).

The principal (``users.kind = 'team'``, ``user_id = '__team__' || team_id``)
owns a team's items, so an identity that resolves to it would own every one of
them. Each test here fails if its guard is removed.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from sqlalchemy import text
from starlette.requests import Request

from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.admin_stats import AdminStatsRepository
from docsgpt.storage.db.repositories.personal_access_tokens import PersonalAccessTokensRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_roles import UserRolesRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

SECRET = "wp2-test-secret-of-at-least-32-bytes"
FORGED = principal_id(uuid.uuid4())


def _team(conn, owner: str = "alice", name: str = "Ops") -> dict:
    return TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner_id=owner)


def _token(sub: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "iat": now, "exp": now + 600}, SECRET, algorithm="HS256")


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SECRET)

    def _set(auth_type: str) -> None:
        monkeypatch.setattr(settings, "AUTH_TYPE", auth_type)

    _set("simple_jwt")
    return _set


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


# ----------------------------------------------------------------------
# Token and session identity
# ----------------------------------------------------------------------
class TestSignedTokens:
    @pytest.mark.parametrize("auth_type", ["simple_jwt", "session_jwt", "oidc"])
    def test_the_decoder_refuses_a_principal_sub(self, jwt_mode, auth_type):
        from docsgpt.auth import handle_auth

        jwt_mode(auth_type)
        request = SimpleNamespace(headers={"Authorization": f"Bearer {_token(FORGED)}"})
        decoded = handle_auth(request)
        assert decoded["error"] == "invalid_token"
        assert "sub" not in decoded

    def test_the_decoder_still_accepts_a_person(self, jwt_mode):
        from docsgpt.auth import handle_auth

        request = SimpleNamespace(headers={"Authorization": f"Bearer {_token('alice')}"})
        assert handle_auth(request)["sub"] == "alice"

    def test_flask_answers_401_to_a_forged_principal_token(self, jwt_mode, client):
        refused = client.get("/api/health", headers={"Authorization": f"Bearer {_token(FORGED)}"})
        allowed = client.get("/api/health", headers={"Authorization": f"Bearer {_token('alice')}"})
        assert refused.status_code == 401
        assert refused.get_json()["error"] == "invalid_token"
        assert allowed.status_code == 200

    @pytest.mark.parametrize(
        "claims",
        [{"sub": FORGED}, {"sub": FORGED, "auth_method": "pat", "pat_id": "x", "scopes": [], "resource_filter": {}}],
    )
    def test_flask_refuses_principal_claims_whatever_decoded_them(self, client, claims):
        # The hook checks again, so a future decoder (or a PAT row) can't hand the app a principal.
        with patch("docsgpt.app.handle_auth", return_value=dict(claims)):
            response = client.get("/api/health")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_asgi_answers_401_to_a_forged_principal_token(self, jwt_mode):
        from docsgpt.api import asgi_auth

        decoded, error = await asgi_auth.authenticate(_starlette_request(_token(FORGED)))
        assert decoded is None
        assert error.status_code == 401
        assert json.loads(error.body)["error"] == "invalid_token"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "claims",
        [{"sub": FORGED}, {"sub": FORGED, "auth_method": "pat", "pat_id": "x", "scopes": ["agents:read"]}],
    )
    async def test_asgi_refuses_principal_claims_whatever_decoded_them(self, claims):
        from docsgpt.api import asgi_auth

        with patch.object(asgi_auth, "handle_auth", return_value=dict(claims)):
            decoded, error = await asgi_auth.authenticate(_starlette_request("x"), pat_scope="agents:read")
        assert decoded is None
        assert error.status_code == 401


def _starlette_request(token: str) -> Request:
    headers = [(b"authorization", f"Bearer {token}".encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""})


# ----------------------------------------------------------------------
# SCIM: the repository reads it uses
# ----------------------------------------------------------------------
class TestScimReads:
    def test_list_never_returns_a_principal_or_the_system_row(self, pg_conn):
        team = _team(pg_conn)
        principal = principal_id(team["id"])
        UsersRepository(pg_conn).upsert("alice")
        total, rows = UsersRepository(pg_conn).list_paginated(None, 0, 500)
        ids = {r["user_id"] for r in rows}
        assert principal not in ids and "__system__" not in ids
        assert "alice" in ids
        assert total == int(pg_conn.execute(text("SELECT count(*) FROM users WHERE kind = 'user'")).scalar())

    def test_a_username_filter_naming_a_principal_finds_nothing(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        assert UsersRepository(pg_conn).list_paginated(principal.upper(), 0, 10) == (0, [])

    def test_get_by_pk_and_set_active_skip_a_principal(self, pg_conn):
        principal = UsersRepository(pg_conn).team_principal(_team(pg_conn)["id"])
        repo = UsersRepository(pg_conn)
        assert repo.get_by_pk(str(principal["id"])) is None
        assert repo.set_active(str(principal["id"]), False) is None
        assert repo.get(principal["user_id"])["active"] is True


# ----------------------------------------------------------------------
# Personal access tokens
# ----------------------------------------------------------------------
class TestPersonalAccessTokens:
    def _insert(self, conn, user_id: str, token_hash: str) -> None:
        conn.execute(
            text(
                "INSERT INTO personal_access_tokens (user_id, name, token_hash, token_prefix, scopes) "
                "VALUES (:u, 'ci', :h, 'dgpt_ab', ARRAY['agents:read'])"
            ),
            {"u": user_id, "h": token_hash},
        )

    def test_a_token_owned_by_a_principal_never_resolves(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        self._insert(pg_conn, principal, "hash-principal")
        UsersRepository(pg_conn).upsert("bob")
        self._insert(pg_conn, "bob", "hash-bob")
        repo = PersonalAccessTokensRepository(pg_conn)
        assert repo.find_active_by_hash("hash-principal") is None
        assert repo.find_active_by_hash("hash-bob")["user_id"] == "bob"

    def test_the_repository_refuses_to_create_one_for_a_principal(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        with pytest.raises(ValueError):
            PersonalAccessTokensRepository(pg_conn).create(
                principal, "ci", token_hash="h", token_prefix="dgpt_ab", scopes=["agents:read"]
            )


# ----------------------------------------------------------------------
# Admin surfaces
# ----------------------------------------------------------------------
class TestAdminStats:
    def test_overview_counts_people_only(self, pg_conn):
        team = _team(pg_conn)
        principal = principal_id(team["id"])
        pg_conn.execute(
            text("INSERT INTO token_usage (user_id, prompt_tokens, generated_tokens) VALUES (:u, 5, 5)"),
            {"u": principal},
        )
        people = int(pg_conn.execute(text("SELECT count(*) FROM users WHERE kind = 'user'")).scalar())
        everyone = int(pg_conn.execute(text("SELECT count(*) FROM users")).scalar())
        assert everyone > people
        stats = AdminStatsRepository(pg_conn).overview()
        assert stats["users"]["total"] == people
        assert stats["new_users_7d"] <= people
        assert stats["active_users_30d"] == 0

    def test_user_list_and_search_leave_out_principals(self, pg_conn):
        _team(pg_conn)
        repo = AdminStatsRepository(pg_conn)
        total, rows = repo.list_users(None, 0, 500)
        assert all(not r["user_id"].startswith("__") for r in rows)
        assert total == len(rows)
        assert repo.list_users("__team__", 0, 50) == (0, [])
        assert repo.list_users("__system__", 0, 50) == (0, [])

    def test_top_spenders_leave_out_principals(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        UsersRepository(pg_conn).upsert("bob")
        for user_id in (principal, "bob"):
            pg_conn.execute(
                text("INSERT INTO token_usage (user_id, prompt_tokens, generated_tokens) VALUES (:u, 5, 5)"),
                {"u": user_id},
            )
        top = AdminStatsRepository(pg_conn).top_token_users(since=_long_ago())
        assert [r["user_id"] for r in top] == ["bob"]

    def test_the_admin_count_leaves_out_a_principal_grant(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        # A grant written before the guard existed, straight into the table.
        pg_conn.execute(
            text("INSERT INTO user_roles (user_id, role, source) VALUES (:u, 'admin', 'manual')"), {"u": principal}
        )
        admins = int(
            pg_conn.execute(text("SELECT count(DISTINCT user_id) FROM user_roles WHERE role = 'admin'")).scalar()
        )
        assert AdminStatsRepository(pg_conn).overview()["admins"] == admins - 1


def _long_ago():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) - timedelta(days=1)


class TestRoleGrants:
    def test_the_repository_refuses_an_admin_grant_to_a_principal(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        with pytest.raises(ValueError):
            UserRolesRepository(pg_conn).grant(principal, "admin")
        assert UserRolesRepository(pg_conn).role_names_for(principal) == []


@pytest.fixture
def admin_db(pg_conn):
    """Point the admin, quota and token routes at the test transaction."""

    @contextmanager
    def _yield():
        yield pg_conn

    with ExitStack() as stack:
        for target in (
            "docsgpt.api.admin.routes.db_readonly",
            "docsgpt.api.admin.routes.db_session",
            "docsgpt.api.admin.quotas.db_readonly",
            "docsgpt.api.admin.quotas.db_session",
            "docsgpt.api.pat.routes.db_readonly",
            "docsgpt.api.pat.routes.db_session",
        ):
            stack.enter_context(patch(target, _yield))
        stack.enter_context(patch("docsgpt.app.handle_auth", return_value={"sub": "admin1"}))
        stack.enter_context(patch("docsgpt.app.resolve_roles", return_value=["admin", "user"]))
        yield pg_conn


class TestAdminRoutes:
    @pytest.mark.parametrize(
        "method, path, body",
        [
            ("patch", "/api/admin/users/{id}", {"active": False}),
            ("post", "/api/admin/users/{id}/role", None),
            ("post", "/api/admin/users/{id}/revoke-sessions", None),
            ("get", "/api/admin/quotas/users/{id}", None),
            ("put", "/api/admin/quotas/users/{id}", {"token_limit": 10}),
        ],
    )
    def test_a_principal_cannot_be_administered(self, client, admin_db, method, path, body):
        principal = principal_id(_team(admin_db)["id"])
        with patch("docsgpt.api.admin.routes.denylist") as deny:
            response = getattr(client, method)(path.format(id=principal), json=body)
        assert response.status_code == 409
        assert response.get_json()["error"] == "not_a_person"
        assert not deny.deny_user.called
        row = UsersRepository(admin_db).get(principal)
        assert row["active"] is True
        assert UserRolesRepository(admin_db).role_names_for(principal) == []
        policies = admin_db.execute(
            text("SELECT count(*) FROM quota_policies WHERE subject_id = :p"), {"p": principal}
        ).scalar()
        assert policies == 0

    def test_the_system_row_cannot_be_deactivated_either(self, client, admin_db):
        response = client.patch("/api/admin/users/__system__", json={"active": False})
        assert response.status_code == 409
        assert UsersRepository(admin_db).get("__system__")["active"] is True

    def test_a_person_is_still_administered(self, client, admin_db):
        UsersRepository(admin_db).upsert("bob")
        assert client.patch("/api/admin/users/bob", json={"active": False}).status_code == 200
        assert client.post("/api/admin/users/bob/role").status_code == 200

    def test_the_drill_down_labels_a_principal_as_its_team(self, client, admin_db):
        team = _team(admin_db, name="Platform")
        response = client.get(f"/api/admin/users/{principal_id(team['id'])}")
        assert response.status_code == 200
        user = response.get_json()["user"]
        assert user["kind"] == "team"
        assert user["label"] == "Team Platform"
        assert user["team_id"] == str(team["id"])

    def test_a_principal_has_no_token_list(self, client, admin_db):
        principal = principal_id(_team(admin_db)["id"])
        assert client.get(f"/api/admin/users/{principal}/tokens").status_code == 404


class TestActivityLabels:
    def test_feed_rows_name_a_principal_by_its_team(self, pg_conn):
        from docsgpt.api.admin.activity import _with_emails

        team = _team(pg_conn, name="Platform")
        principal = principal_id(team["id"])
        UsersRepository(pg_conn).upsert("bob", email="bob@example.com")
        rows = _with_emails([{"actor_id": "bob", "target_id": principal}], pg_conn)
        assert rows[0]["actor_email"] == "bob@example.com"
        assert rows[0]["target_email"] is None
        assert rows[0]["actor_label"] == "bob@example.com"
        assert rows[0]["target_label"] == "Team Platform"
