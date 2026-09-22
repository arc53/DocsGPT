"""Repository tests for ``auth_events`` (actor/target attribution + feed filters)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository


pytestmark = pytest.mark.integration


@pytest.fixture()
def repo(pg_conn):
    return AuthEventsRepository(pg_conn)


class TestInsertAttribution:
    def test_self_service_event_is_its_own_actor(self, repo):
        row = repo.insert("u1", "oidc_login")
        assert row["actor_id"] == "u1"
        assert row["target_id"] == "u1"
        assert row["user_id"] == "u1"

    def test_admin_action_separates_actor_from_target(self, repo):
        row = repo.insert(
            "victim", "admin_user_deactivated", actor_id="admin-1", target_id="victim"
        )
        assert row["actor_id"] == "admin-1"
        assert row["target_id"] == "victim"
        # ``user_id`` stays the subject, so the per-user feed is unchanged.
        assert row["user_id"] == "victim"

    def test_actor_only_event_has_no_target(self, repo):
        row = repo.insert("admin-1", "team.create", actor_id="admin-1", target_id=None)
        assert row["actor_id"] == "admin-1"
        assert row["target_id"] is None

    def test_positional_user_id_still_supported(self, repo):
        """Existing call sites pass only ``user_id``; it must keep working."""
        row = repo.insert("u2", "pat_created", metadata={"token_id": "t"})
        assert (row["actor_id"], row["target_id"]) == ("u2", "u2")


class TestFeedFilters:
    def _seed(self, repo):
        repo.insert("a", "oidc_login")
        repo.insert("b", "oidc_login_denied")
        repo.insert("b", "admin_user_deactivated", actor_id="admin-9", target_id="b")

    def test_filter_by_actor(self, repo):
        self._seed(repo)
        rows = repo.list_all(actor_id="admin-9")
        assert [r["event"] for r in rows] == ["admin_user_deactivated"]
        assert repo.count_all(actor_id="admin-9") == 1

    def test_filter_by_multiple_events(self, repo):
        self._seed(repo)
        rows = repo.list_all(events=["oidc_login", "oidc_login_denied"])
        assert {r["event"] for r in rows} == {"oidc_login", "oidc_login_denied"}
        assert repo.count_all(events=["oidc_login", "oidc_login_denied"]) == 2

    def test_single_event_filter_still_supported(self, repo):
        self._seed(repo)
        assert repo.count_all(event="oidc_login") == 1

    def test_filter_by_until(self, repo):
        self._seed(repo)
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert repo.count_all(until=past) == 0
        assert repo.count_all(until=datetime.now(timezone.utc) + timedelta(days=1)) == 3

    def test_search_matches_user_actor_and_metadata(self, repo):
        repo.insert("someone", "pat_created", metadata={"name": "ci-deploy-key"})
        assert repo.count_all(search="ci-deploy") == 1
        assert repo.count_all(search="someone") == 1
        assert repo.count_all(search="nothing-here") == 0

    def test_event_names_catalogue(self, repo):
        self._seed(repo)
        names = repo.event_names()
        assert names == sorted(names)
        assert "oidc_login" in names and "admin_user_deactivated" in names
