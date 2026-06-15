"""Real-SQL tests for the admin dashboard aggregates.

The migrated schema seeds a ``'__system__'`` user (0001_initial), so global
counts carry a baseline — these tests assert deltas / user-scoped filters rather
than absolute totals.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.storage.db.repositories.admin_stats import AdminStatsRepository
from application.storage.db.repositories.auth_events import AuthEventsRepository
from application.storage.db.repositories.token_usage import TokenUsageRepository
from application.storage.db.repositories.user_roles import UserRolesRepository
from application.storage.db.repositories.users import UsersRepository


class TestOverview:
    def test_count_deltas_reflect_seeded_data(self, pg_conn):
        repo = AdminStatsRepository(pg_conn)
        before = repo.overview()

        UsersRepository(pg_conn).upsert("ov_alice")
        UsersRepository(pg_conn).upsert("ov_bob")
        UserRolesRepository(pg_conn).grant("ov_alice", "admin", source="manual")
        TokenUsageRepository(pg_conn).insert(
            user_id="ov_alice", prompt_tokens=10, generated_tokens=5
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="ov_bob", prompt_tokens=3, generated_tokens=2
        )
        AuthEventsRepository(pg_conn).insert("ov_bob", "oidc_login_denied")

        after = repo.overview()
        assert after["users"]["total"] - before["users"]["total"] == 2
        assert after["users"]["active"] - before["users"]["active"] == 2
        assert after["admins"] - before["admins"] == 1
        assert after["new_users_7d"] - before["new_users_7d"] == 2
        assert after["active_users_30d"] - before["active_users_30d"] == 2
        assert after["failed_logins_7d"] - before["failed_logins_7d"] == 1
        assert after["tokens_30d"] - before["tokens_30d"] == 20

    def test_inactive_user_counted(self, pg_conn):
        repo = AdminStatsRepository(pg_conn)
        before = repo.overview()
        UsersRepository(pg_conn).upsert("ov_inact")
        row = UsersRepository(pg_conn).get("ov_inact")
        UsersRepository(pg_conn).set_active(str(row["id"]), False)
        after = repo.overview()
        assert after["users"]["total"] - before["users"]["total"] == 1
        assert after["users"]["active"] - before["users"]["active"] == 0
        assert after["users"]["inactive"] - before["users"]["inactive"] == 1

    def test_overview_shape(self, pg_conn):
        ov = AdminStatsRepository(pg_conn).overview()
        assert set(ov["users"]) == {"total", "active", "inactive"}
        for key in (
            "admins",
            "agents",
            "sources",
            "conversations",
            "new_users_7d",
            "active_users_30d",
            "failed_logins_7d",
            "tokens_30d",
        ):
            assert isinstance(ov[key], int)


class TestListUsers:
    def test_last_seen_and_recent_first_ordering(self, pg_conn):
        UsersRepository(pg_conn).upsert("lu_dormant")
        UsersRepository(pg_conn).upsert("lu_recent")
        AuthEventsRepository(pg_conn).insert("lu_recent", "oidc_login")

        total, rows = AdminStatsRepository(pg_conn).list_users(None, 0, 200)
        by_user = {r["user_id"]: r for r in rows}
        assert total >= 2
        assert by_user["lu_recent"]["last_seen"] is not None
        assert by_user["lu_dormant"]["last_seen"] is None
        ids = [r["user_id"] for r in rows]
        # the user with auth activity sorts ahead of the dormant one
        assert ids.index("lu_recent") < ids.index("lu_dormant")

    def test_exact_filter(self, pg_conn):
        UsersRepository(pg_conn).upsert("lu_a")
        UsersRepository(pg_conn).upsert("lu_b")
        total, rows = AdminStatsRepository(pg_conn).list_users("lu_a", 0, 200)
        assert total == 1
        assert [r["user_id"] for r in rows] == ["lu_a"]


class TestTopTokenUsers:
    def test_ordered_by_spend_desc(self, pg_conn):
        since = datetime.now(timezone.utc) - timedelta(days=30)
        TokenUsageRepository(pg_conn).insert(
            user_id="tt_big", prompt_tokens=100000, generated_tokens=0
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="tt_small", prompt_tokens=1, generated_tokens=0
        )
        top = AdminStatsRepository(pg_conn).top_token_users(since=since, limit=100)
        by_user = {t["user_id"]: t["tokens"] for t in top}
        assert by_user["tt_big"] == 100000
        assert by_user["tt_small"] == 1
        ids = [t["user_id"] for t in top]
        assert ids.index("tt_big") < ids.index("tt_small")


class TestUserCounts:
    def test_tokens_and_zero_resources(self, pg_conn):
        TokenUsageRepository(pg_conn).insert(
            user_id="uc_alice", prompt_tokens=7, generated_tokens=3
        )
        counts = AdminStatsRepository(pg_conn).user_counts("uc_alice")
        assert counts["tokens_30d"] == 10
        assert counts["agents"] == 0
        assert counts["sources"] == 0
        assert counts["conversations"] == 0


class TestAuthEventsGlobalFeed:
    def test_filter_count_and_paginate(self, pg_conn):
        repo = AuthEventsRepository(pg_conn)
        repo.insert("ae_alice", "oidc_login")
        repo.insert("ae_alice", "oidc_login_denied")
        repo.insert("ae_bob", "oidc_login")

        assert repo.count_all(user_id="ae_alice") == 2
        assert repo.count_all(user_id="ae_bob") == 1
        assert repo.count_all(user_id="ae_alice", event="oidc_login") == 1

        denied = repo.list_all(user_id="ae_alice", event="oidc_login_denied")
        assert len(denied) == 1 and denied[0]["user_id"] == "ae_alice"

        assert len(repo.list_all(user_id="ae_alice", limit=1, offset=0)) == 1
        assert len(repo.list_all(user_id="ae_alice", limit=5, offset=2)) == 0

    def test_since_excludes_older(self, pg_conn):
        repo = AuthEventsRepository(pg_conn)
        repo.insert("ae_since", "oidc_login")
        future = datetime.now(timezone.utc) + timedelta(days=1)
        assert repo.count_all(user_id="ae_since", since=future) == 0
        assert repo.list_all(user_id="ae_since", since=future) == []
