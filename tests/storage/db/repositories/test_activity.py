"""Repository tests for the merged admin activity feed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.activity import (
    ACTIVITY_COLUMNS,
    ActivityRepository,
)
from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository


pytestmark = pytest.mark.integration


@pytest.fixture()
def seeded(pg_conn):
    """One row in each journal, oldest to newest: guardrail, device, auth."""
    now = datetime.now(timezone.utc)
    pg_conn.execute(
        text(
            "INSERT INTO guardrail_events "
            "(user_id, api_key, stage, check_name, detector_type, action, "
            " outcome, matched_value, created_at) VALUES "
            "('u-guard', 'sk-secret', 'input', 'pii', 'regex', 'block', "
            " 'blocked', 'alex@example.com', :ts)"
        ),
        {"ts": now - timedelta(minutes=10)},
    )
    pg_conn.execute(
        text(
            "INSERT INTO devices "
            "(id, user_id, name, machine_pubkey_fingerprint, token_hash, status) "
            "VALUES ('dev-1', 'u-dev', 'laptop', 'fp-1', 'hash-1', 'active')"
        )
    )
    pg_conn.execute(
        text(
            "INSERT INTO device_audit_log "
            "(device_id, user_id, invocation_id, action, command, "
            " approval_mode, decision, issued_at, created_at) VALUES "
            "('dev-1', 'u-dev', 'inv-1', 'run_command', 'ls -la', "
            " 'ask', 'allowed', :ts, :ts)"
        ),
        {"ts": now - timedelta(minutes=5)},
    )
    AuthEventsRepository(pg_conn).insert(
        "victim", "admin_user_deactivated", ip="203.0.113.9",
        actor_id="admin-1", target_id="victim",
    )
    return pg_conn


@pytest.fixture()
def repo(seeded):
    return ActivityRepository(seeded)


class TestMergedFeed:
    def test_spans_all_three_journals_newest_first(self, repo):
        rows = repo.list()
        assert [row["feed"] for row in rows] == ["auth", "device", "guardrail"]
        assert repo.count() == 3

    def test_every_row_has_the_common_shape(self, repo):
        for row in repo.list():
            assert set(row) == set(ACTIVITY_COLUMNS)

    def test_side_journals_get_namespaced_event_names(self, repo):
        events = {row["feed"]: row["event"] for row in repo.list()}
        assert events["device"] == "device.run_command"
        assert events["guardrail"] == "guardrail.input"

    def test_categories_are_derived(self, repo):
        rows = {row["feed"]: row["category"] for row in repo.list()}
        assert rows == {
            "auth": "access",
            "device": "device",
            "guardrail": "safety",
        }

    def test_outcome_carries_the_side_journal_verdict(self, repo):
        rows = {row["feed"]: row["outcome"] for row in repo.list()}
        assert rows["device"] == "allowed"
        assert rows["guardrail"] == "blocked"
        assert rows["auth"] is None


class TestSecretExclusion:
    def test_guardrail_secrets_never_reach_the_feed(self, repo):
        """``api_key`` is a raw agent key and ``matched_value`` is source text."""
        row = next(r for r in repo.list() if r["feed"] == "guardrail")
        serialized = str(row)
        assert "sk-secret" not in serialized
        assert "alex@example.com" not in serialized


class TestFilters:
    def test_by_feed(self, repo):
        assert [r["feed"] for r in repo.list(feeds=["device"])] == ["device"]

    def test_by_category(self, repo):
        rows = repo.list(categories=["safety"])
        assert [r["feed"] for r in rows] == ["guardrail"]
        assert repo.count(categories=["safety"]) == 1

    def test_by_category_spanning_auth_and_a_side_journal(self, repo):
        rows = repo.list(categories=["access", "device"])
        assert {r["feed"] for r in rows} == {"auth", "device"}

    def test_by_actor(self, repo):
        assert [r["actor_id"] for r in repo.list(actor_id="admin-1")] == ["admin-1"]

    def test_by_user_matches_actor_or_target(self, repo):
        assert repo.count(user_id="victim") == 1
        assert repo.count(user_id="admin-1") == 1

    def test_by_event(self, repo):
        assert repo.count(events=["device.run_command"]) == 1

    def test_by_time_window(self, repo):
        now = datetime.now(timezone.utc)
        assert repo.count(since=now - timedelta(minutes=7)) == 2
        assert repo.count(until=now - timedelta(minutes=7)) == 1

    def test_search_spans_detail(self, repo):
        assert repo.count(search="ls -la") == 1
        assert repo.count(search="203.0.113") == 1
        assert repo.count(search="nope") == 0

    def test_unknown_feed_yields_nothing(self, repo):
        assert repo.list(feeds=["made-up"]) == []
        assert repo.count(feeds=["made-up"]) == 0

    def test_category_no_journal_can_produce(self, repo):
        assert repo.count(feeds=["device"], categories=["data"]) == 0


class TestPagination:
    def test_limit_and_offset(self, repo):
        assert len(repo.list(limit=2)) == 2
        assert [r["feed"] for r in repo.list(limit=2, offset=2)] == ["guardrail"]


class TestExportStream:
    def test_iter_all_walks_every_row(self, repo):
        assert len(list(repo.iter_all(chunk_size=1))) == 3

    def test_iter_all_honours_max_rows(self, repo):
        assert len(list(repo.iter_all(chunk_size=1, max_rows=2))) == 2

    def test_iter_all_applies_filters(self, repo):
        rows = list(repo.iter_all(chunk_size=1, feeds=["auth"]))
        assert [r["feed"] for r in rows] == ["auth"]


class TestCatalogue:
    def test_event_names_are_paired_with_categories(self, repo):
        catalogue = repo.event_names()
        assert {"event": "device.run_command", "category": "device"} in catalogue
        assert {"event": "admin_user_deactivated", "category": "access"} in catalogue
