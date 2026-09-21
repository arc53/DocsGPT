"""Endpoint tests for the admin quota API and ``GET /api/user/quota``.

Driven through the real app.py chokepoint against an ephemeral Postgres; only
``handle_auth`` / ``resolve_roles`` are patched.
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.repositories.users import UsersRepository


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with ExitStack() as stack:
        for target in (
            "docsgpt.api.admin.quotas.db_readonly",
            "docsgpt.api.admin.quotas.db_session",
            "docsgpt.quotas.service.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        yield pg_conn


@contextmanager
def _as(sub, *roles):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=list(roles) or ["user"]
    ):
        yield


def _admin():
    return _as("admin1", "admin", "user")


def _body(resp):
    return json.loads(resp.data)


def _team(conn, slug="q-team", member=None):
    team_id = str(
        conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES (:n, :s, 'o') RETURNING id"),
            {"n": slug, "s": slug},
        ).scalar()
    )
    if member:
        conn.execute(
            text("INSERT INTO team_members (team_id, user_id, role) VALUES (CAST(:t AS uuid), :u, 'team_member')"),
            {"t": team_id, "u": member},
        )
    return team_id


ADMIN_ROUTES = [
    ("get", "/api/admin/quotas"),
    ("put", "/api/admin/quotas/instance"),
    ("delete", "/api/admin/quotas/instance"),
    ("get", "/api/admin/quotas/users/u1"),
    ("put", "/api/admin/quotas/users/u1"),
    ("delete", "/api/admin/quotas/users/u1"),
    ("get", "/api/admin/quotas/teams/00000000-0000-0000-0000-000000000000"),
    ("put", "/api/admin/quotas/teams/00000000-0000-0000-0000-000000000000"),
    ("delete", "/api/admin/quotas/teams/00000000-0000-0000-0000-000000000000"),
]


class TestGuard:
    @pytest.mark.parametrize("method, path", ADMIN_ROUTES)
    def test_non_admin_forbidden(self, client, db, method, path):
        with _as("u1"):
            assert getattr(client, method)(path, json={"token_limit": 1}).status_code == 403

    @pytest.mark.parametrize("method, path", ADMIN_ROUTES)
    def test_unauthenticated(self, client, method, path):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert getattr(client, method)(path, json={"token_limit": 1}).status_code == 401

    def test_team_admin_cannot_set_their_teams_allowance(self, client, db):
        team_id = _team(db)
        db.execute(
            text("INSERT INTO team_members (team_id, user_id, role) VALUES (CAST(:t AS uuid), 'lead', 'team_admin')"),
            {"t": team_id},
        )
        with _as("lead"):
            resp = client.put(f"/api/admin/quotas/teams/{team_id}", json={"token_unlimited": True})
        assert resp.status_code == 403
        assert QuotaPoliciesRepository(db).get("team", team_id) is None


class TestInstancePolicy:
    def test_set_read_delete(self, client, db):
        with _admin():
            put = client.put("/api/admin/quotas/instance", json={"token_limit": 1000, "note": " default "})
            assert put.status_code == 200
            policy = _body(put)["policy"]
            assert (policy["token_limit"], policy["note"], policy["updated_by"]) == (1000, "default", "admin1")

            client.put("/api/admin/quotas/instance", json={"bucket": "agent", "cost_limit_usd": 2.5})
            overview = _body(client.get("/api/admin/quotas"))
            assert [(p["bucket"], p["token_limit"], p["cost_limit_usd"]) for p in overview["instance"]] == [
                ("all", 1000, None),
                ("agent", None, 2.5),
            ]
            assert overview["period"] == "month"

            assert _body(client.delete("/api/admin/quotas/instance?bucket=agent"))["deleted"] == 1
            assert _body(client.delete("/api/admin/quotas/instance"))["deleted"] == 1
            assert _body(client.get("/api/admin/quotas"))["instance"] == []

    def test_writes_are_audited(self, client, db):
        with _admin():
            client.put("/api/admin/quotas/instance", json={"token_limit": 5})
            client.delete("/api/admin/quotas/instance")
            client.delete("/api/admin/quotas/instance")
        events = db.execute(
            text("SELECT user_id, event, metadata FROM auth_events WHERE event LIKE 'quota_policy_%'")
        ).fetchall()
        by_event = {e[1]: e for e in events}
        # The second delete removed nothing, so it left no event.
        assert sorted((e[0], e[1]) for e in events) == [
            ("admin1", "quota_policy_deleted"),
            ("admin1", "quota_policy_set"),
        ]
        metadata = by_event["quota_policy_set"][2]
        assert metadata["token_limit"] == 5 and metadata["by"] == "admin1"

    @pytest.mark.parametrize(
        "body",
        [
            None,
            [],
            {},
            {"note": "only a note"},
            {"token_limit": -1},
            {"token_limit": 1.5},
            {"token_limit": True},
            {"token_limit": "10"},
            {"token_limit": 2**63},
            {"cost_limit_usd": -0.01},
            {"cost_limit_usd": "5"},
            {"cost_limit_usd": float("inf")},
            {"cost_limit_usd": 1e12},
            {"token_limit": 1, "token_unlimited": True},
            {"cost_limit_usd": 1, "cost_unlimited": True},
            {"token_unlimited": "yes"},
            {"token_limit": 1, "enabled": "no"},
            {"token_limit": 1, "bucket": "everything"},
            {"token_limit": 1, "note": 7},
        ],
    )
    def test_invalid_bodies_rejected(self, client, db, body):
        with _admin():
            resp = client.put("/api/admin/quotas/instance", json=body)
        assert resp.status_code == 400
        assert QuotaPoliciesRepository(db).list_by_scope("instance") == []

    def test_unknown_bucket_on_delete(self, client, db):
        with _admin():
            assert client.delete("/api/admin/quotas/instance?bucket=nope").status_code == 400

    def test_zero_is_accepted_as_a_block(self, client, db):
        with _admin():
            resp = client.put("/api/admin/quotas/instance", json={"token_limit": 0, "cost_limit_usd": 0})
        assert resp.status_code == 200
        assert _body(resp)["policy"]["token_limit"] == 0


class TestTeamPolicy:
    def test_set_and_list_with_team_details(self, client, db):
        team_id = _team(db, "q-eng", member="u1")
        with _admin():
            assert client.put(f"/api/admin/quotas/teams/{team_id}", json={"token_limit": 500}).status_code == 200
            (row,) = _body(client.get("/api/admin/quotas"))["teams"]
            assert (row["team_slug"], row["token_limit"], row["member_count"]) == ("q-eng", 500, 1)
            assert _body(client.get(f"/api/admin/quotas/teams/{team_id}"))["policies"][0]["token_limit"] == 500

    @pytest.mark.parametrize("team_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
    def test_unknown_team(self, client, db, team_id):
        with _admin():
            assert client.put(f"/api/admin/quotas/teams/{team_id}", json={"token_limit": 1}).status_code == 404
            assert client.get(f"/api/admin/quotas/teams/{team_id}").status_code == 404


class TestUserPolicy:
    def test_unknown_user(self, client, db):
        with _admin():
            assert client.put("/api/admin/quotas/users/ghost", json={"token_limit": 1}).status_code == 404
            assert client.get("/api/admin/quotas/users/ghost").status_code == 404

    def test_effective_limits_name_their_source(self, client, db):
        UsersRepository(db).upsert("u1")
        small, big = _team(db, "q-small", member="u1"), _team(db, "q-big", member="u1")
        repo = QuotaPoliciesRepository(db)
        repo.upsert(scope="instance", subject_id=None, token_limit=10, cost_limit_usd=1)
        repo.upsert(scope="team", subject_id=small, token_limit=100)
        repo.upsert(scope="team", subject_id=big, token_limit=900)
        TokenUsageRepository(db).insert(user_id="u1", prompt_tokens=40, cost=0.25)

        with _admin():
            body = _body(client.get("/api/admin/quotas/users/u1"))
        overall = body["effective"][0]
        assert overall["bucket"] == "all"
        assert overall["tokens"] == {"limit": 900.0, "used": 40, "source": "team", "source_id": big}
        assert overall["cost"] == {"limit": 1.0, "used": 0.25, "source": "instance", "source_id": None}
        assert body["policies"] == []

        with _admin():
            client.put("/api/admin/quotas/users/u1", json={"token_limit": 50})
            body = _body(client.get("/api/admin/quotas/users/u1"))
        assert body["effective"][0]["tokens"]["source"] == "user"
        assert body["policies"][0]["token_limit"] == 50

    def test_user_policy_audit_is_filed_under_the_user(self, client, db):
        UsersRepository(db).upsert("u1")
        with _admin():
            client.put("/api/admin/quotas/users/u1", json={"cost_unlimited": True})
        row = db.execute(
            text("SELECT user_id, metadata FROM auth_events WHERE event = 'quota_policy_set'")
        ).one()
        assert row[0] == "u1" and row[1]["by"] == "admin1" and row[1]["scope"] == "user"


class TestUnpricedModels:
    def test_lists_used_catalog_models_without_a_price(self, client, db):
        usage = TokenUsageRepository(db)
        usage.insert(user_id="u1", prompt_tokens=10, model_id="local-llama")
        usage.insert(user_id="u1", prompt_tokens=5, model_id="claude-haiku-4-5", cost=0.1)
        usage.insert(user_id="u1", prompt_tokens=7, model_id="7d0c1a52-2f5e-4c53-9a0e-111111111111")
        with _admin(), patch("docsgpt.api.admin.quotas.is_priced", lambda m: m == "claude-haiku-4-5"):
            unpriced = _body(client.get("/api/admin/quotas"))["unpriced_models"]
        assert unpriced == [{"model_id": "local-llama", "tokens": 10, "cost": 0.0}]


class TestMyQuota:
    def test_unlimited_user_sees_no_buckets(self, client, db):
        with _as("u1"):
            body = _body(client.get("/api/user/quota"))
        assert body == {"success": True, "period": "month", "buckets": []}

    def test_limited_user_sees_usage_without_policy_internals(self, client, db):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u1", token_limit=100, note="secret note")
        TokenUsageRepository(db).insert(user_id="u1", prompt_tokens=30)
        with _as("u1"):
            body = _body(client.get("/api/user/quota"))
        (bucket,) = body["buckets"]
        assert bucket["bucket"] == "all"
        assert bucket["tokens"] == {"limit": 100.0, "used": 30}
        assert bucket["cost"] == {"limit": None, "used": 0.0}
        assert "source" not in json.dumps(body) and "secret" not in json.dumps(body)

    def test_a_user_only_sees_their_own_quota(self, client, db):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u1", token_limit=100)
        with _as("u2"):
            assert _body(client.get("/api/user/quota"))["buckets"] == []

    def test_unauthenticated(self, client):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/user/quota").status_code == 401
