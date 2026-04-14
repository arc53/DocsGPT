"""Tests for UsersRepository against a real Postgres instance.

Every test runs inside a rolled-back transaction (see ``pg_conn`` fixture
in the parent conftest) so no data leaks between tests.
"""

from __future__ import annotations

import pytest

from application.storage.db.repositories.users import UsersRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _repo(conn) -> UsersRepository:
    return UsersRepository(conn)


# ------------------------------------------------------------------
# upsert / get
# ------------------------------------------------------------------

class TestUpsert:
    def test_creates_new_user_with_defaults(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.upsert("user-new")
        assert doc["user_id"] == "user-new"
        assert doc["agent_preferences"] == {"pinned": [], "shared_with_me": []}
        assert "id" in doc
        assert doc["_id"] == doc["id"]

    def test_upsert_is_idempotent(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.upsert("user-idem")
        second = repo.upsert("user-idem")
        assert first["id"] == second["id"]
        assert first["agent_preferences"] == second["agent_preferences"]

    def test_upsert_preserves_existing_preferences(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-prefs")
        repo.add_pinned("user-prefs", "agent-1")
        doc = repo.upsert("user-prefs")
        assert "agent-1" in doc["agent_preferences"]["pinned"]


class TestGet:
    def test_returns_none_for_missing_user(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("nonexistent") is None

    def test_returns_user_after_upsert(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-get")
        doc = repo.get("user-get")
        assert doc is not None
        assert doc["user_id"] == "user-get"


# ------------------------------------------------------------------
# pinned agents
# ------------------------------------------------------------------

class TestPinned:
    def test_add_pinned(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-pin")
        repo.add_pinned("user-pin", "a1")
        doc = repo.get("user-pin")
        assert doc["agent_preferences"]["pinned"] == ["a1"]

    def test_add_pinned_is_idempotent(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-pin2")
        repo.add_pinned("user-pin2", "a1")
        repo.add_pinned("user-pin2", "a1")
        doc = repo.get("user-pin2")
        assert doc["agent_preferences"]["pinned"] == ["a1"]

    def test_add_multiple_pinned(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-pin3")
        repo.add_pinned("user-pin3", "a1")
        repo.add_pinned("user-pin3", "a2")
        doc = repo.get("user-pin3")
        assert set(doc["agent_preferences"]["pinned"]) == {"a1", "a2"}

    def test_remove_pinned(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-unpin")
        repo.add_pinned("user-unpin", "a1")
        repo.add_pinned("user-unpin", "a2")
        repo.remove_pinned("user-unpin", "a1")
        doc = repo.get("user-unpin")
        assert doc["agent_preferences"]["pinned"] == ["a2"]

    def test_remove_pinned_nonexistent_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-unpin2")
        repo.add_pinned("user-unpin2", "a1")
        repo.remove_pinned("user-unpin2", "zzz")
        doc = repo.get("user-unpin2")
        assert doc["agent_preferences"]["pinned"] == ["a1"]

    def test_remove_pinned_bulk(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-bulk")
        repo.add_pinned("user-bulk", "a1")
        repo.add_pinned("user-bulk", "a2")
        repo.add_pinned("user-bulk", "a3")
        repo.remove_pinned_bulk("user-bulk", ["a1", "a3"])
        doc = repo.get("user-bulk")
        assert doc["agent_preferences"]["pinned"] == ["a2"]

    def test_remove_pinned_bulk_empty_list_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-bulk2")
        repo.add_pinned("user-bulk2", "a1")
        repo.remove_pinned_bulk("user-bulk2", [])
        doc = repo.get("user-bulk2")
        assert doc["agent_preferences"]["pinned"] == ["a1"]


# ------------------------------------------------------------------
# shared_with_me
# ------------------------------------------------------------------

class TestShared:
    def test_add_shared(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-share")
        repo.add_shared("user-share", "s1")
        doc = repo.get("user-share")
        assert doc["agent_preferences"]["shared_with_me"] == ["s1"]

    def test_add_shared_is_idempotent(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-share2")
        repo.add_shared("user-share2", "s1")
        repo.add_shared("user-share2", "s1")
        doc = repo.get("user-share2")
        assert doc["agent_preferences"]["shared_with_me"] == ["s1"]

    def test_remove_shared_bulk(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-rshare")
        repo.add_shared("user-rshare", "s1")
        repo.add_shared("user-rshare", "s2")
        repo.remove_shared_bulk("user-rshare", ["s1"])
        doc = repo.get("user-rshare")
        assert doc["agent_preferences"]["shared_with_me"] == ["s2"]


# ------------------------------------------------------------------
# remove_agent_from_all (cascade on agent delete)
# ------------------------------------------------------------------

class TestRemoveAgentFromAll:
    def test_removes_from_both_arrays(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-cascade")
        repo.add_pinned("user-cascade", "agent-x")
        repo.add_shared("user-cascade", "agent-x")
        repo.remove_agent_from_all("user-cascade", "agent-x")
        doc = repo.get("user-cascade")
        assert "agent-x" not in doc["agent_preferences"]["pinned"]
        assert "agent-x" not in doc["agent_preferences"]["shared_with_me"]

    def test_leaves_other_agents_untouched(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-cascade2")
        repo.add_pinned("user-cascade2", "keep")
        repo.add_pinned("user-cascade2", "remove")
        repo.add_shared("user-cascade2", "keep")
        repo.add_shared("user-cascade2", "remove")
        repo.remove_agent_from_all("user-cascade2", "remove")
        doc = repo.get("user-cascade2")
        assert doc["agent_preferences"]["pinned"] == ["keep"]
        assert doc["agent_preferences"]["shared_with_me"] == ["keep"]

    def test_noop_when_agent_not_present(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("user-cascade3")
        repo.add_pinned("user-cascade3", "a1")
        repo.remove_agent_from_all("user-cascade3", "nonexistent")
        doc = repo.get("user-cascade3")
        assert doc["agent_preferences"]["pinned"] == ["a1"]


# ------------------------------------------------------------------
# tenant isolation
# ------------------------------------------------------------------

class TestTenantIsolation:
    def test_get_cannot_see_other_users(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("alice")
        repo.upsert("bob")
        repo.add_pinned("alice", "a-private")
        bob_doc = repo.get("bob")
        assert "a-private" not in bob_doc["agent_preferences"]["pinned"]

    def test_mutations_on_one_user_dont_affect_another(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("alice")
        repo.upsert("bob")
        repo.add_pinned("alice", "a1")
        repo.add_shared("bob", "s1")
        alice = repo.get("alice")
        bob = repo.get("bob")
        assert alice["agent_preferences"]["pinned"] == ["a1"]
        assert alice["agent_preferences"]["shared_with_me"] == []
        assert bob["agent_preferences"]["pinned"] == []
        assert bob["agent_preferences"]["shared_with_me"] == ["s1"]


# ------------------------------------------------------------------
# Agent prefs remediation (ObjectId → UUID post-cutover)
# ------------------------------------------------------------------

class TestAgentPrefsRemediation:
    def _insert_agent(self, pg_conn, user_id: str, legacy_mongo_id: str) -> str:
        """Insert a minimal agents row with ``legacy_mongo_id`` and return its UUID."""
        from sqlalchemy import text

        row = pg_conn.execute(
            text(
                "INSERT INTO agents (user_id, name, status, legacy_mongo_id) "
                "VALUES (:u, 'test', 'draft', :lid) RETURNING id"
            ),
            {"u": user_id, "lid": legacy_mongo_id},
        ).fetchone()
        return str(row._mapping["id"])

    def test_remediates_object_ids_to_uuids(self, pg_conn):
        # Import lazily so collection doesn't fail if scripts/ isn't importable.
        import sys
        from pathlib import Path

        sys.path.insert(
            0, str(Path(__file__).resolve().parents[4])
        )
        from scripts.db.backfill import _remediate_user_agent_prefs

        # Create an agent with a known legacy_mongo_id
        legacy_id = "507f1f77bcf86cd799439011"
        agent_uuid = self._insert_agent(pg_conn, "owner-u", legacy_id)

        # Create a user whose pinned list has the ObjectId, an already-UUID,
        # and an unresolvable ObjectId (simulating a pre-migration delete).
        repo = _repo(pg_conn)
        repo.upsert("u-remediate")
        existing_uuid = "11111111-2222-3333-4444-555555555555"
        unresolvable_oid = "deadbeefdeadbeefdeadbeef"
        from sqlalchemy import text
        pg_conn.execute(
            text(
                "UPDATE users SET agent_preferences = CAST(:p AS jsonb) "
                "WHERE user_id = :u"
            ),
            {
                "u": "u-remediate",
                "p": (
                    '{"pinned": ["' + legacy_id + '", "' + existing_uuid + '", '
                    '"' + unresolvable_oid + '"], "shared_with_me": ["' + legacy_id + '"]}'
                ),
            },
        )

        stats = _remediate_user_agent_prefs(conn=pg_conn, dry_run=False)

        doc = repo.get("u-remediate")
        pinned = doc["agent_preferences"]["pinned"]
        shared = doc["agent_preferences"]["shared_with_me"]

        assert agent_uuid in pinned, "legacy ObjectId should be remapped"
        assert existing_uuid in pinned, "pre-existing UUID should be preserved"
        assert unresolvable_oid not in pinned, "unresolvable OID should be dropped"
        assert pinned.count(agent_uuid) == 1
        assert shared == [agent_uuid]
        assert stats["updated"] >= 1
        assert stats["entries_remapped"] >= 2
        assert stats["entries_dropped"] >= 1

    def test_remediation_is_idempotent(self, pg_conn):
        import sys
        from pathlib import Path

        sys.path.insert(
            0, str(Path(__file__).resolve().parents[4])
        )
        from scripts.db.backfill import _remediate_user_agent_prefs

        repo = _repo(pg_conn)
        repo.upsert("u-idem")
        repo.add_pinned("u-idem", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        stats1 = _remediate_user_agent_prefs(conn=pg_conn, dry_run=False)
        before = repo.get("u-idem")["agent_preferences"]
        stats2 = _remediate_user_agent_prefs(conn=pg_conn, dry_run=False)
        after = repo.get("u-idem")["agent_preferences"]
        assert before == after
        # No further updates in the second pass.
        assert stats2["updated"] == 0 or stats2["updated"] <= stats1["updated"]
