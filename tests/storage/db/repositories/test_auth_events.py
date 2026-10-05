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
    """``/api/admin/audit`` is the single-journal feed; the merged one has its
    own repository, so the filter set here stays deliberately small."""

    def _seed(self, repo):
        repo.insert("a", "oidc_login")
        repo.insert("b", "oidc_login_denied")
        repo.insert("b", "admin_user_deactivated", actor_id="admin-9", target_id="b")

    def test_filter_by_event(self, repo):
        self._seed(repo)
        rows = repo.list_all(event="oidc_login")
        assert [r["event"] for r in rows] == ["oidc_login"]
        assert repo.count_all(event="oidc_login") == 1

    def test_filter_by_user_matches_subject_or_target(self, repo):
        self._seed(repo)
        assert repo.count_all(user_id="b") == 2

    def test_filter_by_since(self, repo):
        self._seed(repo)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        assert repo.count_all(since=future) == 0
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert repo.count_all(since=past) == 3

    def test_pagination(self, repo):
        self._seed(repo)
        assert len(repo.list_all(limit=2)) == 2
        assert len(repo.list_all(limit=2, offset=2)) == 1


class TestPerUserPanel:
    """The admin user drill-down is a security panel, not an activity log."""

    def test_data_plane_events_can_be_excluded(self, repo):
        repo.insert("u1", "oidc_login_denied")
        for _ in range(5):
            repo.insert("u1", "conversation.deleted", target_id=None, actor_id="u1")
        rows = repo.list_recent(
            "u1", limit=3, exclude_events_like=("source.", "agent.", "conversation.")
        )
        # Without the exclusion the five deletes would fill the window and
        # push the denied login out of it.
        assert [r["event"] for r in rows] == ["oidc_login_denied"]

    def test_without_exclusions_everything_is_returned(self, repo):
        repo.insert("u1", "oidc_login")
        repo.insert("u1", "conversation.deleted", target_id=None, actor_id="u1")
        assert len(repo.list_recent("u1")) == 2
