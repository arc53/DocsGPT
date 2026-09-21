"""Tests for QuotaPoliciesRepository against a real Postgres instance."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository


def _repo(conn) -> QuotaPoliciesRepository:
    return QuotaPoliciesRepository(conn)


def _team(conn, slug: str) -> str:
    return str(
        conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES (:n, :s, 'owner') RETURNING id"),
            {"n": slug, "s": slug},
        ).scalar()
    )


def _member(conn, team_id: str, user_id: str, role: str = "team_member", source: str = "manual") -> None:
    conn.execute(
        text(
            "INSERT INTO team_members (team_id, user_id, role, source) "
            "VALUES (CAST(:t AS uuid), :u, :r, :s)"
        ),
        {"t": team_id, "u": user_id, "r": role, "s": source},
    )


class TestUpsert:
    def test_creates_then_replaces(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.upsert(scope="user", subject_id="u1", token_limit=100, note="trial", actor="admin1")
        assert created["token_limit"] == 100
        assert created["created_by"] == created["updated_by"] == "admin1"

        replaced = repo.upsert(scope="user", subject_id="u1", cost_limit_usd=2.5, actor="admin2")
        assert replaced["id"] == created["id"]
        assert replaced["token_limit"] is None
        assert float(replaced["cost_limit_usd"]) == 2.5
        assert replaced["note"] is None
        assert (replaced["created_by"], replaced["updated_by"]) == ("admin1", "admin2")

    def test_instance_row_is_a_singleton_per_bucket(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert(scope="instance", subject_id=None, token_limit=1)
        repo.upsert(scope="instance", subject_id=None, token_limit=2)
        repo.upsert(scope="instance", subject_id=None, bucket="agent", token_limit=3)
        rows = repo.list_by_scope("instance")
        assert [(r["bucket"], r["token_limit"]) for r in rows] == [("all", 2), ("agent", 3)]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"scope": "org", "subject_id": "x"},
            {"scope": "user", "subject_id": None},
            {"scope": "instance", "subject_id": "x"},
            {"scope": "user", "subject_id": "u", "bucket": "nope"},
            {"scope": "user", "subject_id": "u", "token_limit": 1, "token_unlimited": True},
            {"scope": "user", "subject_id": "u", "cost_limit_usd": 1, "cost_unlimited": True},
            {"scope": "user", "subject_id": "u", "token_limit": -1},
            {"scope": "user", "subject_id": "u", "cost_limit_usd": -0.5},
        ],
    )
    def test_rejects_invalid_policies(self, pg_conn, kwargs):
        with pytest.raises(ValueError):
            _repo(pg_conn).upsert(**kwargs)


class TestReads:
    def test_get_and_list_for_subject(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert(scope="user", subject_id="u1", bucket="agent", token_limit=5)
        repo.upsert(scope="user", subject_id="u1", token_limit=9)
        assert repo.get("user", "u1")["token_limit"] == 9
        assert repo.get("user", "u1", "direct") is None
        assert [r["bucket"] for r in repo.list_for_subject("user", "u1")] == ["all", "agent"]
        assert repo.list_for_subject("user", "nobody") == []

    def test_list_by_scope_rejects_unknown_scope(self, pg_conn):
        with pytest.raises(ValueError):
            _repo(pg_conn).list_by_scope("org")


class TestPoliciesForUser:
    def test_collects_instance_user_and_team_rows(self, pg_conn):
        repo = _repo(pg_conn)
        mine, other = _team(pg_conn, "qp-mine"), _team(pg_conn, "qp-other")
        _member(pg_conn, mine, "u1")
        repo.upsert(scope="instance", subject_id=None, token_limit=1)
        repo.upsert(scope="team", subject_id=mine, token_limit=2)
        repo.upsert(scope="team", subject_id=other, token_limit=3)
        repo.upsert(scope="user", subject_id="u1", token_limit=4)
        repo.upsert(scope="user", subject_id="u2", token_limit=5)

        limits = sorted(r["token_limit"] for r in repo.policies_for_user("u1"))
        assert limits == [1, 2, 4]

    def test_a_team_counts_once_however_many_memberships(self, pg_conn):
        repo = _repo(pg_conn)
        team = _team(pg_conn, "qp-multi")
        _member(pg_conn, team, "u1", "team_member", "manual")
        _member(pg_conn, team, "u1", "team_admin", "manual")
        _member(pg_conn, team, "u1", "team_member", "oidc_group")
        repo.upsert(scope="team", subject_id=team, token_limit=7)
        assert [r["token_limit"] for r in repo.policies_for_user("u1")] == [7]

    def test_every_team_of_the_user_is_included(self, pg_conn):
        repo = _repo(pg_conn)
        for slug, limit in (("qp-a", 10), ("qp-b", 20), ("qp-c", 30)):
            team = _team(pg_conn, slug)
            _member(pg_conn, team, "u1")
            repo.upsert(scope="team", subject_id=team, token_limit=limit)
        assert sorted(r["token_limit"] for r in repo.policies_for_user("u1")) == [10, 20, 30]

    def test_disabled_rows_are_left_out(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert(scope="user", subject_id="u1", token_limit=4, enabled=False)
        assert repo.policies_for_user("u1") == []

    def test_leaving_a_team_drops_its_allowance(self, pg_conn):
        repo = _repo(pg_conn)
        team = _team(pg_conn, "qp-leave")
        _member(pg_conn, team, "u1")
        repo.upsert(scope="team", subject_id=team, token_limit=7)
        pg_conn.execute(text("DELETE FROM team_members WHERE user_id = 'u1'"))
        assert repo.policies_for_user("u1") == []


class TestDelete:
    def test_delete_one_bucket_or_all(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert(scope="user", subject_id="u1", token_limit=1)
        repo.upsert(scope="user", subject_id="u1", bucket="agent", token_limit=2)
        repo.upsert(scope="user", subject_id="u2", token_limit=3)
        first = repo.delete("user", "u1", "agent")
        again = repo.delete("user", "u1", "agent")
        rest = repo.delete("user", "u1")
        assert (first, again, rest) == (1, 0, 1)
        assert repo.get("user", "u2") is not None
