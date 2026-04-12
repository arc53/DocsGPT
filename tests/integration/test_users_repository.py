"""Integration tests for ``UsersRepository`` against a live Postgres.

These tests need:

* A running Postgres reachable via ``POSTGRES_URI``
* Alembic migration ``0001_initial`` applied

They are skipped automatically by the default ``pytest`` run because
``pytest.ini`` has ``--ignore=tests/integration`` in ``addopts``. They
are additionally marked ``@pytest.mark.integration`` so they can be
selected/excluded explicitly. Run them locally with::

    .venv/bin/python -m pytest tests/integration/test_users_repository.py \\
        --override-ini="addopts=" --no-cov

Covers every operation the legacy Mongo code performs on
``users_collection``: upsert + get + add/remove on the pinned and
shared_with_me JSONB arrays, plus explicit tenant-isolation checks
(a user's operations must never touch another user's data).
"""

from __future__ import annotations

import pytest

from application.storage.db.repositories.users import UsersRepository


@pytest.fixture
def repo(pg_clean_users):
    return UsersRepository(pg_clean_users)


@pytest.mark.integration
class TestUpsert:
    def test_upsert_creates_new_user_with_default_preferences(self, repo):
        doc = repo.upsert("alice@example.com")
        assert doc["user_id"] == "alice@example.com"
        assert doc["agent_preferences"] == {"pinned": [], "shared_with_me": []}
        assert "id" in doc
        assert "_id" in doc  # Mongo-compat alias

    def test_upsert_is_idempotent(self, repo):
        first = repo.upsert("alice@example.com")
        second = repo.upsert("alice@example.com")
        assert first["id"] == second["id"]
        assert first["agent_preferences"] == second["agent_preferences"]

    def test_upsert_preserves_existing_preferences(self, repo):
        repo.upsert("alice@example.com")
        repo.add_pinned("alice@example.com", "agent-1")
        doc = repo.upsert("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-1"]


@pytest.mark.integration
class TestGet:
    def test_get_returns_none_for_missing_user(self, repo):
        assert repo.get("nobody@example.com") is None

    def test_get_returns_dict_for_existing_user(self, repo):
        repo.upsert("alice@example.com")
        doc = repo.get("alice@example.com")
        assert doc is not None
        assert doc["user_id"] == "alice@example.com"
        assert doc["agent_preferences"] == {"pinned": [], "shared_with_me": []}


@pytest.mark.integration
class TestAddPinned:
    def test_add_pinned_to_new_user_creates_user(self, repo):
        repo.upsert("alice@example.com")
        repo.add_pinned("alice@example.com", "agent-1")
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-1"]

    def test_add_pinned_is_idempotent(self, repo):
        repo.upsert("alice@example.com")
        repo.add_pinned("alice@example.com", "agent-1")
        repo.add_pinned("alice@example.com", "agent-1")
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-1"]

    def test_add_pinned_preserves_order(self, repo):
        repo.upsert("alice@example.com")
        repo.add_pinned("alice@example.com", "agent-1")
        repo.add_pinned("alice@example.com", "agent-2")
        repo.add_pinned("alice@example.com", "agent-3")
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-1", "agent-2", "agent-3"]


@pytest.mark.integration
class TestRemovePinned:
    def test_remove_pinned_single(self, repo):
        repo.upsert("alice@example.com")
        repo.add_pinned("alice@example.com", "agent-1")
        repo.add_pinned("alice@example.com", "agent-2")
        repo.remove_pinned("alice@example.com", "agent-1")
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-2"]

    def test_remove_pinned_missing_is_noop(self, repo):
        repo.upsert("alice@example.com")
        repo.add_pinned("alice@example.com", "agent-1")
        repo.remove_pinned("alice@example.com", "agent-999")
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-1"]

    def test_remove_pinned_bulk(self, repo):
        repo.upsert("alice@example.com")
        for i in range(5):
            repo.add_pinned("alice@example.com", f"agent-{i}")
        repo.remove_pinned_bulk("alice@example.com", ["agent-1", "agent-3", "agent-999"])
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-0", "agent-2", "agent-4"]


@pytest.mark.integration
class TestSharedWithMe:
    def test_add_shared_is_idempotent(self, repo):
        repo.upsert("alice@example.com")
        repo.add_shared("alice@example.com", "agent-x")
        repo.add_shared("alice@example.com", "agent-x")
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["shared_with_me"] == ["agent-x"]

    def test_remove_shared_bulk(self, repo):
        repo.upsert("alice@example.com")
        for i in range(3):
            repo.add_shared("alice@example.com", f"shared-{i}")
        repo.remove_shared_bulk("alice@example.com", ["shared-0", "shared-2"])
        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["shared_with_me"] == ["shared-1"]


@pytest.mark.integration
class TestRemoveAgentFromAll:
    def test_removes_from_both_pinned_and_shared(self, repo):
        repo.upsert("alice@example.com")
        repo.add_pinned("alice@example.com", "agent-X")
        repo.add_pinned("alice@example.com", "agent-keep")
        repo.add_shared("alice@example.com", "agent-X")
        repo.add_shared("alice@example.com", "agent-keep-2")

        repo.remove_agent_from_all("alice@example.com", "agent-X")

        doc = repo.get("alice@example.com")
        assert doc["agent_preferences"]["pinned"] == ["agent-keep"]
        assert doc["agent_preferences"]["shared_with_me"] == ["agent-keep-2"]


@pytest.mark.integration
class TestTenantIsolation:
    """Security-critical: operations on one user must never touch another's data."""

    def test_add_pinned_does_not_leak_across_users(self, repo):
        repo.upsert("alice@example.com")
        repo.upsert("bob@example.com")
        repo.add_pinned("alice@example.com", "agent-a")
        repo.add_pinned("bob@example.com", "agent-b")

        alice = repo.get("alice@example.com")
        bob = repo.get("bob@example.com")
        assert alice["agent_preferences"]["pinned"] == ["agent-a"]
        assert bob["agent_preferences"]["pinned"] == ["agent-b"]

    def test_remove_does_not_leak_across_users(self, repo):
        repo.upsert("alice@example.com")
        repo.upsert("bob@example.com")
        repo.add_pinned("alice@example.com", "shared-agent-id")
        repo.add_pinned("bob@example.com", "shared-agent-id")

        repo.remove_pinned("alice@example.com", "shared-agent-id")

        assert repo.get("alice@example.com")["agent_preferences"]["pinned"] == []
        assert repo.get("bob@example.com")["agent_preferences"]["pinned"] == [
            "shared-agent-id"
        ]
