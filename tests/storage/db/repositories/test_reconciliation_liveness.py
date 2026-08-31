"""Liveness fixes for the reconciler's stuck-message sweep.

Production evidence behind these: two healthy streams were force-failed
mid-flight and shown to users as "Response was terminated prior to
completion", one of which went on to finish successfully 20 minutes later
with 1,866 completion tokens. Both were heavy tool loops, whose silent
windows the chunk-gated heartbeat could not cover.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from application.storage.db.repositories.conversations import (
    ConversationsRepository,
    MessageUpdateOutcome,
)
from application.storage.db.repositories.reconciliation import (
    ReconciliationRepository,
)

RECONCILER_ERROR = (
    "reconciler: stuck in pending/streaming for >5 min after 3 attempts"
)


def _seed_message(
    conn,
    *,
    status: str = "pending",
    age_minutes: int = 6,
    user_id: str = "u",
    metadata: dict | None = None,
) -> dict:
    conv = ConversationsRepository(conn).create(user_id, "liveness test")
    row = conn.execute(
        text(
            """
            INSERT INTO conversation_messages (
                conversation_id, position, prompt, response, status, user_id,
                timestamp, message_metadata
            )
            VALUES (
                CAST(:cid AS uuid), 0, 'p', '', :status, :uid,
                clock_timestamp() - make_interval(mins => :age),
                CAST(:meta AS jsonb)
            )
            RETURNING id
            """
        ),
        {
            "cid": conv["id"],
            "status": status,
            "uid": user_id,
            "age": age_minutes,
            "meta": json.dumps(metadata or {}),
        },
    ).fetchone()
    return {"id": str(row[0]), "conversation_id": conv["id"], "user_id": user_id}


def _seed_tool_call_for(
    conn, message_id: str, *, status: str, age_minutes: int, call_id: str,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO tool_call_attempts (
                call_id, tool_name, action_name, arguments, status, message_id
            )
            VALUES (:cid, 'googlesearch', 'search', '{}'::jsonb, :st,
                    CAST(:mid AS uuid))
            """
        ),
        {"cid": call_id, "st": status, "mid": message_id},
    )
    # The BEFORE-UPDATE trigger resets updated_at; disable it so the
    # backdate lands as written.
    conn.execute(text("ALTER TABLE tool_call_attempts DISABLE TRIGGER USER"))
    try:
        conn.execute(
            text(
                """
                UPDATE tool_call_attempts
                SET attempted_at = clock_timestamp() - make_interval(mins => :age),
                    updated_at = clock_timestamp() - make_interval(mins => :age)
                WHERE call_id = :cid
                """
            ),
            {"cid": call_id, "age": age_minutes},
        )
    finally:
        conn.execute(text("ALTER TABLE tool_call_attempts ENABLE TRIGGER USER"))


def _meta(conn, message_id: str) -> dict:
    row = conn.execute(
        text(
            "SELECT message_metadata FROM conversation_messages "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": message_id},
    ).fetchone()
    return row[0] or {}


def _status(conn, message_id: str) -> str:
    return conn.execute(
        text(
            "SELECT status FROM conversation_messages WHERE id = CAST(:id AS uuid)"
        ),
        {"id": message_id},
    ).fetchone()[0]


class TestServerToolLivenessExemption:
    """Fix D — server-executed tools leave no ``pending_tool_state`` row."""

    def test_recent_executed_tool_call_exempts_message(self, pg_conn):
        msg = _seed_message(pg_conn, age_minutes=10)
        _seed_tool_call_for(
            pg_conn, msg["id"], status="executed", age_minutes=1, call_id="c1",
        )

        rows = ReconciliationRepository(pg_conn).find_and_lock_stuck_messages()

        assert not any(str(r["id"]) == msg["id"] for r in rows)

    def test_recent_proposed_tool_call_exempts_message(self, pg_conn):
        msg = _seed_message(pg_conn, age_minutes=10)
        _seed_tool_call_for(
            pg_conn, msg["id"], status="proposed", age_minutes=2, call_id="c2",
        )

        rows = ReconciliationRepository(pg_conn).find_and_lock_stuck_messages()

        assert not any(str(r["id"]) == msg["id"] for r in rows)

    def test_stale_tool_call_does_not_exempt(self, pg_conn):
        """The exemption expires, so a genuinely dead stream is still swept."""
        msg = _seed_message(pg_conn, age_minutes=30)
        _seed_tool_call_for(
            pg_conn, msg["id"], status="executed", age_minutes=20, call_id="c3",
        )

        rows = ReconciliationRepository(pg_conn).find_and_lock_stuck_messages()

        assert any(str(r["id"]) == msg["id"] for r in rows)

    def test_terminal_tool_call_does_not_exempt(self, pg_conn):
        """Confirmed/failed rows are not in-flight."""
        msg = _seed_message(pg_conn, age_minutes=10)
        _seed_tool_call_for(
            pg_conn, msg["id"], status="confirmed", age_minutes=1, call_id="c4",
        )

        rows = ReconciliationRepository(pg_conn).find_and_lock_stuck_messages()

        assert any(str(r["id"]) == msg["id"] for r in rows)


class TestConsecutiveAttemptCounter:
    """Fix F — the counter means consecutive stale ticks, not a lifetime total."""

    def test_counter_accumulates_while_heartbeat_is_unchanged(self, pg_conn):
        msg = _seed_message(
            pg_conn, metadata={"last_heartbeat_at": "2026-08-10T10:00:00+00:00"},
        )
        repo = ReconciliationRepository(pg_conn)

        assert repo.increment_message_reconcile_attempts(msg["id"]) == 1
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 2
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 3

    def test_counter_resets_when_heartbeat_advanced(self, pg_conn):
        """A stream that proved life between ticks starts over."""
        msg = _seed_message(
            pg_conn, metadata={"last_heartbeat_at": "2026-08-10T10:00:00+00:00"},
        )
        repo = ReconciliationRepository(pg_conn)

        assert repo.increment_message_reconcile_attempts(msg["id"]) == 1
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 2

        pg_conn.execute(
            text(
                """
                UPDATE conversation_messages
                SET message_metadata = jsonb_set(
                    message_metadata, '{last_heartbeat_at}',
                    to_jsonb('2026-08-10T10:05:00+00:00'::text)
                )
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": msg["id"]},
        )

        assert repo.increment_message_reconcile_attempts(msg["id"]) == 1

    def test_missing_heartbeat_still_accumulates(self, pg_conn):
        """A row that never heartbeats must still escalate."""
        msg = _seed_message(pg_conn, metadata={})
        repo = ReconciliationRepository(pg_conn)

        assert repo.increment_message_reconcile_attempts(msg["id"]) == 1
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 2
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 3


class TestFinalizeReclaim:
    """Fix C — a late, successful finalize may reclaim a stale-swept row."""

    def test_reclaims_reconciler_failed_row(self, pg_conn):
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={"error": RECONCILER_ERROR, "reconcile_attempts": 3},
        )
        repo = ConversationsRepository(pg_conn)

        outcome = repo.update_message_by_id(
            msg["id"],
            {"response": "the real answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        assert outcome is MessageUpdateOutcome.UPDATED
        assert _status(pg_conn, msg["id"]) == "complete"

    def test_reclaim_strips_reconciler_bookkeeping(self, pg_conn):
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={
                "error": RECONCILER_ERROR,
                "reconcile_attempts": 3,
                "last_reconcile_seen_heartbeat": "2026-08-10T10:00:00+00:00",
                "keep_me": "yes",
            },
        )
        repo = ConversationsRepository(pg_conn)

        repo.update_message_by_id(
            msg["id"],
            {"response": "answer", "status": "complete", "metadata": {"m": 1}},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        meta = _meta(pg_conn, msg["id"])
        assert "error" not in meta
        assert "reconcile_attempts" not in meta
        assert "last_reconcile_seen_heartbeat" not in meta
        assert meta["keep_me"] == "yes"
        assert meta["m"] == 1

    def test_reclaim_strips_even_without_metadata_field(self, pg_conn):
        """A finalize with no query metadata must still clear the keys."""
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={"error": RECONCILER_ERROR, "reconcile_attempts": 3},
        )
        repo = ConversationsRepository(pg_conn)

        repo.update_message_by_id(
            msg["id"],
            {"response": "answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        meta = _meta(pg_conn, msg["id"])
        assert "error" not in meta
        assert "reconcile_attempts" not in meta

    def test_reclaims_a_resume_that_released_its_claim(self, pg_conn):
        """A failed resume that handed the turn back must not block the retry.

        The stream handler releases the continuation claim and stamps
        ``resume_retryable`` in the same breath. The retry reuses this very row
        (the reserved id lives in the persisted ``agent_config``), so without
        the second reclaim hole its successful finalize lands ALREADY_FAILED
        and the user's answer is discarded after they watched it stream in.
        """
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={"error": "KeyError: 'name'", "resume_retryable": True},
        )
        repo = ConversationsRepository(pg_conn)

        outcome = repo.update_message_by_id(
            msg["id"],
            {"response": "the retry's answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        assert outcome is MessageUpdateOutcome.UPDATED
        assert _status(pg_conn, msg["id"]) == "complete"
        # The marker must not survive onto the finished row, or the API
        # response carries a stale failure alongside a complete answer.
        meta = _meta(pg_conn, msg["id"])
        assert "resume_retryable" not in meta
        assert "error" not in meta

    def test_does_not_reclaim_a_failure_that_kept_its_claim(self, pg_conn):
        """No marker means no release happened, so the row stays terminal."""
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={"error": "KeyError: 'name'"},
        )
        repo = ConversationsRepository(pg_conn)

        outcome = repo.update_message_by_id(
            msg["id"],
            {"response": "late answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        assert outcome is MessageUpdateOutcome.ALREADY_FAILED
        assert _status(pg_conn, msg["id"]) == "failed"

    def test_does_not_reclaim_genuine_failure(self, pg_conn):
        """Client disconnect, provider errors etc. stay terminal."""
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={"error": "ConnectionError: client disconnected"},
        )
        repo = ConversationsRepository(pg_conn)

        outcome = repo.update_message_by_id(
            msg["id"],
            {"response": "late answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        assert outcome is MessageUpdateOutcome.ALREADY_FAILED
        assert _status(pg_conn, msg["id"]) == "failed"

    def test_does_not_reclaim_when_approval_was_revoked(self, pg_conn):
        """The UI was already told the approval was cleared; don't contradict it."""
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={
                "error": RECONCILER_ERROR,
                "reconciler_cleared_approval": True,
            },
        )
        repo = ConversationsRepository(pg_conn)

        outcome = repo.update_message_by_id(
            msg["id"],
            {"response": "late answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        assert outcome is MessageUpdateOutcome.ALREADY_FAILED
        assert _status(pg_conn, msg["id"]) == "failed"

    def test_does_not_reclaim_a_completed_row(self, pg_conn):
        msg = _seed_message(pg_conn, status="complete")
        repo = ConversationsRepository(pg_conn)

        outcome = repo.update_message_by_id(
            msg["id"],
            {"response": "second answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        assert outcome is MessageUpdateOutcome.ALREADY_COMPLETE

    def test_without_reclaim_flag_reconciler_row_stays_failed(self, pg_conn):
        """The old behaviour is unchanged when the flag is off."""
        msg = _seed_message(
            pg_conn,
            status="failed",
            metadata={"error": RECONCILER_ERROR},
        )
        repo = ConversationsRepository(pg_conn)

        outcome = repo.update_message_by_id(
            msg["id"],
            {"response": "answer", "status": "complete"},
            only_if_non_terminal=True,
        )

        assert outcome is MessageUpdateOutcome.ALREADY_FAILED


class TestApprovalClearedStamp:
    def test_marks_metadata_flag(self, pg_conn):
        msg = _seed_message(pg_conn, status="failed")
        repo = ReconciliationRepository(pg_conn)

        assert repo.mark_message_approval_cleared(msg["id"]) is True
        assert _meta(pg_conn, msg["id"])["reconciler_cleared_approval"] is True
