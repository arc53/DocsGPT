"""Tests for PendingToolStateRepository against a real Postgres instance."""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.pending_tool_state import PendingToolStateRepository


def _conv(conn) -> dict:
    return ConversationsRepository(conn).create("user-1", "test conv")


def _repo(conn) -> PendingToolStateRepository:
    return PendingToolStateRepository(conn)


def _sample_state() -> dict:
    return {
        "messages": [{"role": "user", "content": "hello"}],
        "pending_tool_calls": [{"id": "tc-1", "name": "search"}],
        "tools_dict": {"search": {"type": "function"}},
        "tool_schemas": [{"name": "search"}],
        "agent_config": {"model_id": "gpt-4", "llm_name": "openai"},
    }


class TestSaveState:
    def test_creates_state(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        state = _sample_state()
        doc = repo.save_state(conv["id"], "user-1", **state)
        assert doc["user_id"] == "user-1"
        assert doc["messages"] == state["messages"]
        assert doc["pending_tool_calls"] == state["pending_tool_calls"]
        assert doc["expires_at"] is not None

    def test_upsert_replaces_existing(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        state = _sample_state()
        repo.save_state(conv["id"], "user-1", **state)
        state["messages"] = [{"role": "user", "content": "updated"}]
        doc2 = repo.save_state(conv["id"], "user-1", **state)
        # Same row, updated content
        assert doc2["messages"] == [{"role": "user", "content": "updated"}]

    def test_save_with_client_tools(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        state = _sample_state()
        state["client_tools"] = [{"name": "browser"}]
        doc = repo.save_state(conv["id"], "user-1", **state)
        assert doc["client_tools"] == [{"name": "browser"}]


class TestLoadState:
    def test_loads_existing(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        loaded = repo.load_state(conv["id"], "user-1")
        assert loaded is not None
        assert loaded["agent_config"]["model_id"] == "gpt-4"

    def test_load_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.load_state("00000000-0000-0000-0000-000000000000", "u") is None


class TestDeleteState:
    def test_deletes(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        assert repo.delete_state(conv["id"], "user-1") is True
        assert repo.load_state(conv["id"], "user-1") is None

    def test_delete_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.delete_state("00000000-0000-0000-0000-000000000000", "u") is False


class TestCleanupExpired:
    def test_cleanup_removes_expired(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        # Create a state with TTL of 0 seconds (already expired)
        repo.save_state(conv["id"], "user-1", **_sample_state(), ttl_seconds=0)
        deleted = repo.cleanup_expired()
        assert len(deleted) >= 1
        # Deleted rows carry the keys needed to revoke a stale approval toast.
        assert any(
            str(row["conversation_id"]) == conv["id"]
            and row["user_id"] == "user-1"
            for row in deleted
        )
        assert repo.load_state(conv["id"], "user-1") is None


class TestMarkResuming:
    def test_flips_pending_to_resuming(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())

        flipped = repo.mark_resuming(conv["id"], "user-1")
        assert flipped is True

        loaded = repo.load_state_any(conv["id"], "user-1")
        assert loaded["status"] == "resuming"
        assert loaded["resumed_at"] is not None

    def test_noop_when_already_resuming(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        assert repo.mark_resuming(conv["id"], "user-1") is True
        # Second call should not flip again — row is no longer 'pending'.
        assert repo.mark_resuming(conv["id"], "user-1") is False

    def test_noop_when_no_row(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.mark_resuming(
            "00000000-0000-0000-0000-000000000000", "u"
        ) is False

    def test_save_state_resets_resuming_back_to_pending(self, pg_conn):
        # A second tool pause re-saves the row; status must drop back to
        # 'pending' so a future mark_resuming can claim it.
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.mark_resuming(conv["id"], "user-1")

        repo.save_state(conv["id"], "user-1", **_sample_state())
        loaded = repo.load_state(conv["id"], "user-1")
        assert loaded["status"] == "pending"
        assert loaded["resumed_at"] is None


class TestRevertStaleResuming:
    @staticmethod
    def _backdate_resumed(conn, conv_id: str, user_id: str, secs_ago: int) -> None:
        conn.execute(
            text(
                "UPDATE pending_tool_state "
                "SET resumed_at = clock_timestamp() "
                "             - make_interval(secs => :secs) "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "AND user_id = :user_id"
            ),
            {"secs": secs_ago, "conv_id": conv_id, "user_id": user_id},
        )

    def test_reverts_stale_rows(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.mark_resuming(conv["id"], "user-1")
        # 11 minutes ago — past 10 minute grace.
        self._backdate_resumed(pg_conn, conv["id"], "user-1", 660)

        reverted = repo.revert_stale_resuming(grace_seconds=600)
        assert reverted == 1

        loaded = repo.load_state(conv["id"], "user-1")
        assert loaded["status"] == "pending"
        assert loaded["resumed_at"] is None

    def test_leaves_fresh_resuming_alone(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.mark_resuming(conv["id"], "user-1")
        # Within grace.
        self._backdate_resumed(pg_conn, conv["id"], "user-1", 30)

        reverted = repo.revert_stale_resuming(grace_seconds=600)
        assert reverted == 0

        loaded = repo.load_state_any(conv["id"], "user-1")
        assert loaded["status"] == "resuming"

    def test_leaves_pending_alone(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        # Never marked resuming — should not be touched.
        reverted = repo.revert_stale_resuming(grace_seconds=600)
        assert reverted == 0

        loaded = repo.load_state(conv["id"], "user-1")
        assert loaded["status"] == "pending"

    def test_bumps_expires_at_to_protect_from_ttl_sweep(self, pg_conn):
        # A row reverted just past its original TTL would be wiped by
        # cleanup_expired in the same tick — bump expires_at on revert
        # so the user gets a fresh window to retry.
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.mark_resuming(conv["id"], "user-1")
        self._backdate_resumed(pg_conn, conv["id"], "user-1", 660)
        pg_conn.execute(
            text(
                "UPDATE pending_tool_state "
                "SET expires_at = clock_timestamp() - interval '1 second' "
                "WHERE conversation_id = CAST(:conv_id AS uuid)"
            ),
            {"conv_id": conv["id"]},
        )

        repo.revert_stale_resuming(grace_seconds=600)
        # Same tick: the original expires_at was set to "now" (ttl=0)
        # and is well past — without the bump, cleanup_expired would
        # delete the just-reverted row.
        deleted = repo.cleanup_expired()
        assert deleted == []
        loaded = repo.load_state(conv["id"], "user-1")
        assert loaded is not None
        assert loaded["status"] == "pending"


class TestReleaseClaim:
    def test_returns_a_claimed_row_to_pending(self, pg_conn):
        """A failed resume must hand the claim back immediately.

        Without this the only way back is ``revert_stale_resuming``'s 600 s
        grace, and ``load_state`` ignores ``resuming`` rows — so the paused
        turn stays resumable but invisible and the user is locked out of their
        own conversation for ten minutes.
        """
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        assert repo.claim_state(conv["id"], "user-1") is not None
        assert repo.load_state(conv["id"], "user-1") is None

        assert repo.release_claim(conv["id"], "user-1") is True

        reclaimed = repo.load_state(conv["id"], "user-1")
        assert reclaimed is not None
        assert reclaimed["status"] == "pending"
        assert reclaimed["resumed_at"] is None
        # ...and the next resume attempt can take it straight away.
        assert repo.claim_state(conv["id"], "user-1") is not None

    def test_bumps_expires_at_to_protect_from_the_ttl_sweep(self, pg_conn):
        """A claim released after a long resume must not come back expired.

        ``claim_state``/``mark_resuming`` gate on ``expires_at``, and flipping
        to ``pending`` also hides the row from ``revert_stale_resuming``, which
        matches ``resuming`` only. Without the bump, releasing a claim on a row
        whose TTL lapsed mid-resume DELETES the user's rescue instead of
        speeding it up — the turn is reported retryable but can never be
        re-claimed. This is the sibling of
        ``TestRevertStaleResuming::test_bumps_expires_at_to_protect_from_ttl_sweep``.
        """
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.claim_state(conv["id"], "user-1")
        # The resume outlived the row's TTL before it failed.
        pg_conn.execute(
            text(
                """
                UPDATE pending_tool_state
                SET expires_at = clock_timestamp() - interval '1 minute'
                WHERE conversation_id = CAST(:conv_id AS uuid)
                """
            ),
            {"conv_id": conv["id"]},
        )

        assert repo.release_claim(conv["id"], "user-1") is True

        reclaimed = repo.load_state(conv["id"], "user-1")
        assert reclaimed is not None, "released claim came back already expired"
        assert repo.claim_state(conv["id"], "user-1") is not None
        assert repo.cleanup_expired() == []

    def test_does_not_shorten_a_healthy_ttl(self, pg_conn):
        """A failed resume must never cut short a row with time left."""
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.claim_state(conv["id"], "user-1")
        before = repo.load_state_any(conv["id"], "user-1")["expires_at"]

        repo.release_claim(conv["id"], "user-1", ttl_extension_seconds=1)

        after = repo.load_state_any(conv["id"], "user-1")["expires_at"]
        assert after == before

    def test_noop_on_a_pending_row(self, pg_conn):
        """Only a claim can be released; a live pending row is left alone."""
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        assert repo.release_claim(conv["id"], "user-1") is False
        assert repo.load_state(conv["id"], "user-1")["status"] == "pending"

    def test_noop_when_the_row_is_gone(self, pg_conn):
        """Must not resurrect a row another request deleted."""
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.claim_state(conv["id"], "user-1")
        repo.delete_state(conv["id"], "user-1")

        assert repo.release_claim(conv["id"], "user-1") is False
        assert repo.load_state_any(conv["id"], "user-1") is None

    def test_scoped_to_the_owning_user(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        repo.claim_state(conv["id"], "user-1")

        assert repo.release_claim(conv["id"], "someone-else") is False
        assert repo.load_state_any(conv["id"], "user-1")["status"] == "resuming"
