"""Tests for ConversationWakesRepository."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.storage.db.repositories.conversation_wakes import ConversationWakesRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


def _conversation(conn, user_id: str = "u1") -> str:
    return str(ConversationsRepository(conn).create(user_id, "chat")["id"])


def _wake(repo, conversation_id, key, **overrides):
    fields = {
        "user_id": "u1",
        "conversation_id": conversation_id,
        "source": "job",
        "ref_id": "j1",
        "title": "run_code finished",
        "body": "done",
        "dedupe_key": key,
    }
    fields.update(overrides)
    return repo.enqueue(**fields)


class TestEnqueue:
    def test_a_key_is_queued_once(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        first = _wake(repo, conversation_id, "job:1:final", payload={"a": 1})
        assert first["status"] == "pending"
        assert first["payload"] == {"a": 1}
        assert _wake(repo, conversation_id, "job:1:final") is None

    def test_strips_nul_bytes(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        row = _wake(repo, _conversation(pg_conn), "k", body="a\x00b", payload={"x": "c\x00d"})
        assert row["body"] == "ab"
        assert row["payload"] == {"x": "cd"}


class TestClaim:
    def test_claims_a_batch_oldest_first_up_to_the_limit(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        keys = [f"k{i}" for i in range(4)]
        for i, key in enumerate(keys):
            row = _wake(repo, conversation_id, key)
            pg_conn.execute(
                text(
                    "UPDATE conversation_wakes SET created_at = now() - make_interval(secs => :s) "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"s": 100 - i, "id": row["id"]},
            )
        _wake(repo, _conversation(pg_conn), "elsewhere")
        claimed = repo.claim_batch(conversation_id, limit=3)
        assert [r["dedupe_key"] for r in claimed] == ["k0", "k1", "k2"]
        assert all(r["status"] == "claimed" and r["attempts"] == 1 for r in claimed)
        assert [r["dedupe_key"] for r in repo.claim_batch(conversation_id, limit=3)] == ["k3"]
        assert repo.claim_batch(conversation_id) == []

    def test_release_puts_claims_back(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        _wake(repo, conversation_id, "k")
        claimed = repo.claim_batch(conversation_id)
        assert repo.release([r["id"] for r in claimed]) == 1
        again = repo.claim_batch(conversation_id)
        assert again[0]["attempts"] == 2

    def test_mark_delivered_records_the_message(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        _wake(repo, conversation_id, "k")
        claimed = repo.claim_batch(conversation_id)
        message = ConversationsRepository(pg_conn).append_message(conversation_id, {"prompt": "p", "response": "r"})
        assert repo.mark([claimed[0]["id"]], "delivered", message_id=str(message["id"])) == 1
        row = repo.get(claimed[0]["id"])
        assert row["status"] == "delivered"
        assert row["message_id"] == str(message["id"])
        assert row["delivered_at"] is not None


class TestFoldAndSupersede:
    def test_fold_takes_every_pending_wake(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        _wake(repo, conversation_id, "a", source="monitor")
        _wake(repo, conversation_id, "b")
        repo.claim_batch(conversation_id, limit=1)
        folded = repo.fold_pending(conversation_id, "u1")
        assert [r["dedupe_key"] for r in folded] == ["b"]
        assert repo.fold_pending(conversation_id, "u1") == []

    def test_fold_can_skip_job_wakes(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        _wake(repo, conversation_id, "a", source="monitor")
        _wake(repo, conversation_id, "b", source="job")
        folded = repo.fold_pending(conversation_id, "u1", exclude_sources=("job",))
        assert [r["dedupe_key"] for r in folded] == ["a"]

    def test_supersede_for_ref(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        _wake(repo, conversation_id, "a", ref_id="j1")
        _wake(repo, conversation_id, "b", ref_id="j2")
        assert repo.supersede_for_ref("job", "j1") == 1
        assert [r["dedupe_key"] for r in repo.claim_batch(conversation_id)] == ["b"]


class TestSweeps:
    def test_pending_conversations_and_stale_claims(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        row = _wake(repo, conversation_id, "a")
        pg_conn.execute(
            text(
                "UPDATE conversation_wakes SET created_at = now() - interval '10 minutes' "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row["id"]},
        )
        assert repo.pending_conversations(older_than_seconds=120) == [(conversation_id, "u1")]
        repo.claim_batch(conversation_id)
        assert repo.pending_conversations(older_than_seconds=120) == []
        pg_conn.execute(
            text("UPDATE conversation_wakes SET claimed_at = now() - interval '2 hours' WHERE id = CAST(:id AS uuid)"),
            {"id": row["id"]},
        )
        assert repo.release_stale_claims(older_than_seconds=3600) == 1
        assert repo.get(row["id"])["status"] == "pending"

    def test_cleanup_removes_old_finished_wakes(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        old = _wake(repo, conversation_id, "old")
        repo.claim_batch(conversation_id)
        pending = _wake(repo, conversation_id, "pending")
        assert repo.mark([old["id"]], "delivered") == 1
        pg_conn.execute(
            text(
                "UPDATE conversation_wakes SET created_at = now() - interval '30 days' "
                "WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"
            ),
            {"a": old["id"], "b": pending["id"]},
        )
        assert repo.cleanup_older_than(7) == 1
        assert repo.get(pending["id"]) is not None


class TestMarkIsConditional:
    def test_only_claimed_wakes_settle(self, pg_conn):
        repo = ConversationWakesRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        row = _wake(repo, conversation_id, "k")
        assert repo.mark([row["id"]], "delivered") == 0
        repo.claim_batch(conversation_id)
        repo.release([row["id"]])
        folded = repo.fold_pending(conversation_id, "u1")
        assert [r["id"] for r in folded] == [row["id"]]
        # A continuation whose claim was handed back can't overwrite the fold.
        assert repo.mark([row["id"]], "delivered") == 0
        assert repo.get(row["id"])["status"] == "folded"
