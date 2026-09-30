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
            "docsgpt.api.user.teams.routes.db_readonly",
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


def _team(conn, slug="q-team", member=None, name=None):
    team_id = str(
        conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES (:n, :s, 'o') RETURNING id"),
            {"n": name or slug, "s": slug},
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

            one_bucket = _body(client.delete("/api/admin/quotas/instance?bucket=agent"))
            the_rest = _body(client.delete("/api/admin/quotas/instance"))
            remaining = _body(client.get("/api/admin/quotas"))["instance"]
        assert (one_bucket["deleted"], the_rest["deleted"], remaining) == (1, 1, [])

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
            {"token_limit": 10**400},
            {"cost_limit_usd": 10**400},
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
            resp = client.delete("/api/admin/quotas/instance?bucket=nope")
        assert resp.status_code == 400

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
        assert overall["tokens"] == {"limit": 900, "used": 40, "source": "team", "source_id": big}
        assert isinstance(overall["tokens"]["limit"], int)
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


def _seed_listing(conn):
    """Three teams with allowances (one per two buckets) and three user overrides."""
    repo = QuotaPoliciesRepository(conn)
    teams = {
        slug: _team(conn, slug, name=name)
        for slug, name in (("q-eng", "Engineering"), ("q-ops", "Operations"), ("q-sales", "Sales Team"))
    }
    for team_id in teams.values():
        repo.upsert(scope="team", subject_id=team_id, token_limit=100)
    repo.upsert(scope="team", subject_id=teams["q-eng"], bucket="agent", token_limit=50)
    users = UsersRepository(conn)
    users.upsert("alice-sub", email="Alice@Example.com")
    users.upsert("bob-sub", email="bob@corp.io")
    users.upsert("carol-sub")
    for sub in ("alice-sub", "bob-sub", "carol-sub"):
        repo.upsert(scope="user", subject_id=sub, token_limit=10)
    return teams


class TestQuotaListing:
    def test_defaults_return_every_row_plus_totals(self, client, db):
        _seed_listing(db)
        with _admin():
            body = _body(client.get("/api/admin/quotas"))
        assert set(body) == {
            "success", "period", "period_start", "resets_at", "instance", "teams", "users",
            "unpriced_models", "teams_total", "users_total",
        }
        assert (len(body["teams"]), body["teams_total"]) == (4, 4)
        assert (len(body["users"]), body["users_total"]) == (3, 3)
        assert [u["subject_id"] for u in body["users"]] == ["alice-sub", "bob-sub", "carol-sub"]
        assert "email" not in body["users"][0]

    def test_teams_q_matches_name_or_slug_case_insensitively(self, client, db):
        _seed_listing(db)
        with _admin():
            by_name = _body(client.get("/api/admin/quotas?teams_q=sales team"))
            by_slug = _body(client.get("/api/admin/quotas?teams_q=Q-ENG"))
            none = _body(client.get("/api/admin/quotas?teams_q=%25"))
        assert [t["team_slug"] for t in by_name["teams"]] == ["q-sales"]
        assert by_name["teams_total"] == 1
        assert {t["team_slug"] for t in by_slug["teams"]} == {"q-eng"}
        assert (by_slug["teams_total"], [t["bucket"] for t in by_slug["teams"]]) == (2, ["all", "agent"])
        # A literal ``%`` is not a wildcard; users are left unfiltered.
        assert (none["teams"], none["teams_total"], none["users_total"]) == ([], 0, 3)

    def test_users_q_matches_subject_or_email(self, client, db):
        _seed_listing(db)
        with _admin():
            by_email = _body(client.get("/api/admin/quotas?users_q=example.COM"))
            by_sub = _body(client.get("/api/admin/quotas?users_q=carol"))
            both = _body(client.get("/api/admin/quotas?users_q=-sub"))
        assert [u["subject_id"] for u in by_email["users"]] == ["alice-sub"]
        assert (by_email["users_total"], by_email["teams_total"]) == (1, 4)
        assert [u["subject_id"] for u in by_sub["users"]] == ["carol-sub"]
        assert both["users_total"] == 3

    def test_pages_only_the_list_whose_page_is_given(self, client, db):
        _seed_listing(db)
        with _admin():
            first = _body(client.get("/api/admin/quotas?users_page=1&page_size=2"))
            second = _body(client.get("/api/admin/quotas?users_page=2&page_size=2"))
            beyond = _body(client.get("/api/admin/quotas?users_page=9&page_size=2"))
            teams = _body(client.get("/api/admin/quotas?teams_page=2&page_size=3"))
        assert [u["subject_id"] for u in first["users"]] == ["alice-sub", "bob-sub"]
        assert [u["subject_id"] for u in second["users"]] == ["carol-sub"]
        assert (beyond["users"], beyond["users_total"]) == ([], 3)
        assert (first["users_total"], len(first["teams"]), first["teams_total"]) == (3, 4, 4)
        assert (len(teams["teams"]), teams["teams_total"], len(teams["users"])) == (1, 4, 3)

    def test_paging_is_deterministic_and_combines_with_the_filter(self, client, db):
        _seed_listing(db)
        with _admin():
            everything = _body(client.get("/api/admin/quotas"))["teams"]
            pages = [
                _body(client.get(f"/api/admin/quotas?teams_page={n}&page_size=1"))["teams"] for n in (1, 2, 3, 4)
            ]
            filtered = _body(client.get("/api/admin/quotas?teams_q=q-&teams_page=2&page_size=2"))
        assert [p[0] for p in pages] == everything
        assert (filtered["teams"], filtered["teams_total"]) == (everything[2:], 4)

    @pytest.mark.parametrize(
        "query, expected",
        [
            ("users_page=1&page_size=0", 1),
            ("users_page=1&page_size=500", 3),
            ("users_page=0&page_size=2", 2),
            ("users_page=abc&page_size=1", 1),
            ("users_page=1&page_size=abc", 3),
        ],
    )
    def test_page_params_are_clamped(self, client, db, query, expected):
        _seed_listing(db)
        with _admin():
            body = _body(client.get(f"/api/admin/quotas?{query}"))
        assert (len(body["users"]), body["users_total"]) == (expected, 3)


class TestAdminTeamsSearch:
    def test_no_params_lists_every_team(self, client, db):
        teams = _seed_listing(db)
        bare = _team(db, "q-bare", name="Bare")
        with _admin():
            body = _body(client.get("/api/admin/teams"))
        assert {t["id"] for t in body["teams"]} == {*teams.values(), bare}

    def test_without_quota_matches_the_all_bucket_rule(self, client, db):
        teams = _seed_listing(db)
        bare = _team(db, "q-bare", name="Bare")
        agent_only = _team(db, "q-agent", name="Agent Only")
        disabled = _team(db, "q-off", name="Disabled")
        repo = QuotaPoliciesRepository(db)
        # Only an ``all``-bucket row covers a team; a disabled one still does.
        repo.upsert(scope="team", subject_id=agent_only, bucket="agent", token_limit=5)
        repo.upsert(scope="team", subject_id=disabled, token_limit=5, enabled=False)
        # A user override whose subject happens to equal a team id is not a team allowance.
        repo.upsert(scope="user", subject_id=bare, token_limit=5)
        with _admin():
            body = _body(client.get("/api/admin/teams?without_quota=1"))
        ids = [t["id"] for t in body["teams"]]
        assert set(ids) == {bare, agent_only}
        assert not set(ids) & {*teams.values(), disabled}
        assert body["teams"][0]["member_count"] == 0

    def test_q_filters_name_or_slug(self, client, db):
        _seed_listing(db)
        _team(db, "q-bare", name="Bare Metal")
        with _admin():
            by_name = _body(client.get("/api/admin/teams?q=METAL"))
            by_slug = _body(client.get("/api/admin/teams?q=q-sa"))
            combined = _body(client.get("/api/admin/teams?q=q-&without_quota=1"))
            literal = _body(client.get("/api/admin/teams?q=_"))
        assert [t["slug"] for t in by_name["teams"]] == ["q-bare"]
        assert [t["slug"] for t in by_slug["teams"]] == ["q-sales"]
        assert [t["slug"] for t in combined["teams"]] == ["q-bare"]
        assert literal["teams"] == []

    @pytest.mark.parametrize("limit, expected", [("2", 2), ("0", 1), ("1000", 5), ("abc", 5), (None, 5)])
    def test_limit_is_clamped(self, client, db, limit, expected):
        _seed_listing(db)
        _team(db, "q-bare")
        _team(db, "q-more")
        query = "q=q-" + (f"&limit={limit}" if limit is not None else "")
        with _admin():
            body = _body(client.get(f"/api/admin/teams?{query}"))
        assert len(body["teams"]) == expected

    def test_default_limit_is_twenty(self, client, db):
        for n in range(25):
            _team(db, f"q-many-{n:02d}")
        with _admin():
            assert len(_body(client.get("/api/admin/teams?without_quota=1"))["teams"]) == 20
            assert len(_body(client.get("/api/admin/teams"))["teams"]) == 25

    def test_search_stays_admin_only(self, client, db):
        with _as("u1"):
            assert client.get("/api/admin/teams?without_quota=1").status_code == 403


class TestUnpricedModels:
    def test_lists_models_recorded_at_zero_for_want_of_a_price(self, client, db):
        usage = TokenUsageRepository(db)
        usage.insert(user_id="u1", prompt_tokens=10, model_id="local-llama")
        # Priced when called; its provider may be disabled by now.
        usage.insert(user_id="u1", prompt_tokens=5, model_id="retired-priced-model", cost=0.1)
        usage.insert(user_id="u1", prompt_tokens=3, model_id="free-model")
        usage.insert(user_id="u1", prompt_tokens=7, model_id="7d0c1a52-2f5e-4c53-9a0e-111111111111")
        with _admin(), patch("docsgpt.api.admin.quotas.is_priced", lambda m: m == "free-model"):
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
        assert bucket["tokens"] == {"limit": 100, "used": 30}
        assert bucket["cost"] == {"limit": None, "used": 0.0}
        assert "source" not in json.dumps(body) and "secret" not in json.dumps(body)

    def test_a_user_only_sees_their_own_quota(self, client, db):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u1", token_limit=100)
        with _as("u2"):
            assert _body(client.get("/api/user/quota"))["buckets"] == []

    def test_unauthenticated(self, client):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/user/quota").status_code == 401
