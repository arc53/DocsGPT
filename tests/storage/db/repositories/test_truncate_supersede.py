"""``truncate_after`` must not silently orphan a still-running stream.

Reconstructed from production: on 2026-08-09 a paused message row was
deleted by the user's edit at the same position, and 9 minutes later the
original stream resumed and wrote 342 FK-violating journal events before
finalizing into nothing. A second victim the same day was deleted 235 ms
after a concurrent retry started, mid-emit.
"""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.conversations import (
    ConversationsRepository,
    MessageUpdateOutcome,
)


def _seed(conn, conv_id: str, position: int, status: str, user_id="u") -> str:
    row = conn.execute(
        text(
            """
            INSERT INTO conversation_messages (
                conversation_id, position, prompt, response, status, user_id,
                timestamp, message_metadata
            )
            VALUES (CAST(:cid AS uuid), :pos, 'p', '', :st, :uid,
                    clock_timestamp(), '{}'::jsonb)
            RETURNING id
            """
        ),
        {"cid": conv_id, "pos": position, "st": status, "uid": user_id},
    ).fetchone()
    return str(row[0])


def _row(conn, message_id: str):
    return conn.execute(
        text(
            "SELECT status, message_metadata FROM conversation_messages "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": message_id},
    ).fetchone()


class TestTruncateAfterSupersede:
    def test_in_flight_row_is_superseded_before_deletion(self, pg_conn):
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "supersede test")
        _seed(pg_conn, conv["id"], 0, "complete")
        live = _seed(pg_conn, conv["id"], 1, "streaming")

        # The user edits the turn at position 1.
        deleted = repo.truncate_after(conv["id"], keep_up_to=0)

        assert deleted == 1
        # The row is gone, as the user asked.
        assert _row(pg_conn, live) is None

    def test_late_finalize_reports_not_found_and_is_countable(self, pg_conn):
        """The owning stream's late write must be distinguishable.

        ``NOT_FOUND`` is what the route now turns into an
        ``answer_persist_failed`` alert, rather than discarding silently.
        """
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "late finalize")
        live = _seed(pg_conn, conv["id"], 0, "streaming")

        repo.truncate_after(conv["id"], keep_up_to=-1)

        outcome = repo.update_message_by_id(
            live,
            {"response": "3115 chars of answer", "status": "complete"},
            only_if_non_terminal=True,
            reclaim_reconciler_failed=True,
        )

        assert outcome is MessageUpdateOutcome.NOT_FOUND

    def test_terminal_rows_are_not_restamped(self, pg_conn):
        """Only in-flight rows get the supersede stamp."""
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "terminal")
        done = _seed(pg_conn, conv["id"], 0, "complete")

        # keep_up_to=-1 targets everything, but nothing is in flight.
        repo.truncate_after(conv["id"], keep_up_to=-1)

        assert _row(pg_conn, done) is None

    def test_pending_row_is_superseded(self, pg_conn):
        """A paused row (client-side tool) counts as in flight.

        This is the exact shape of the 2026-08-09 victim: reserved, paused
        awaiting a client tool result, deleted by an edit at the same
        position, resumed minutes later.
        """
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "paused")
        _seed(pg_conn, conv["id"], 0, "complete")
        paused = _seed(pg_conn, conv["id"], 1, "pending")

        repo.truncate_after(conv["id"], keep_up_to=0)

        assert _row(pg_conn, paused) is None

    def test_nothing_to_truncate_is_a_noop(self, pg_conn):
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "noop")
        kept = _seed(pg_conn, conv["id"], 0, "complete")

        assert repo.truncate_after(conv["id"], keep_up_to=5) == 0
        assert _row(pg_conn, kept) is not None

    def test_invalid_conversation_id_is_rejected(self, pg_conn):
        repo = ConversationsRepository(pg_conn)
        assert repo.truncate_after("not-a-uuid", keep_up_to=0) == 0


class TestSupersedeTombstone:
    """``NOT_FOUND`` alone cannot tell a replaced turn from a lost answer.

    The cancel flag is a ``threading.Event`` in the superseding request's own
    process, so a stream in another worker never sees it and runs to
    completion. Its late finalize then hits a row that is gone — routine on the
    retry/edit path, and previously logged as an ERROR indistinguishable from a
    genuinely orphaned answer.
    """

    def test_truncate_tombstones_every_row_it_deletes(self, pg_conn):
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "tombstone")
        live = _seed(pg_conn, conv["id"], 0, "streaming")
        done = _seed(pg_conn, conv["id"], 1, "complete")

        repo.truncate_after(conv["id"], keep_up_to=-1)

        # Both, not just the in-flight one: the UPDATE's status filter is
        # narrower than the DELETE's, so the stamp alone would miss `done`.
        assert repo.was_superseded(live) is True
        assert repo.was_superseded(done) is True

    def test_tombstone_survives_the_delete_that_created_it(self, pg_conn):
        """No FK to conversation_messages, or the CASCADE would take it."""
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "cascade")
        live = _seed(pg_conn, conv["id"], 0, "streaming")

        repo.truncate_after(conv["id"], keep_up_to=-1)

        assert _row(pg_conn, live) is None
        assert repo.was_superseded(live) is True

    def test_an_untouched_message_has_no_tombstone(self, pg_conn):
        """A genuinely orphaned answer must still reach the ERROR path."""
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "kept")
        kept = _seed(pg_conn, conv["id"], 0, "streaming")
        dropped = _seed(pg_conn, conv["id"], 1, "streaming")

        repo.truncate_after(conv["id"], keep_up_to=0)

        assert repo.was_superseded(kept) is False
        assert repo.was_superseded(dropped) is True

    def test_was_superseded_shrugs_off_a_non_uuid(self, pg_conn):
        """Shape-gate: a legacy ObjectId must not poison the transaction."""
        repo = ConversationsRepository(pg_conn)
        assert repo.was_superseded("507f1f77bcf86cd799439011") is False
        assert repo.was_superseded("") is False

    def test_truncate_is_repeatable(self, pg_conn):
        """A second truncate over the same range must not raise on the PK."""
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "twice")
        first = _seed(pg_conn, conv["id"], 0, "streaming")
        repo.truncate_after(conv["id"], keep_up_to=-1)
        _seed(pg_conn, conv["id"], 0, "streaming")
        repo.truncate_after(conv["id"], keep_up_to=-1)
        assert repo.was_superseded(first) is True

    def test_cleanup_sweeps_old_tombstones_only(self, pg_conn):
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u", "sweep")
        recent = _seed(pg_conn, conv["id"], 0, "streaming")
        repo.truncate_after(conv["id"], keep_up_to=-1)
        stale = _seed(pg_conn, conv["id"], 0, "streaming")
        repo.truncate_after(conv["id"], keep_up_to=-1)
        pg_conn.execute(
            text(
                "UPDATE superseded_messages "
                "SET superseded_at = clock_timestamp() - make_interval(days => 30) "
                "WHERE message_id = CAST(:mid AS uuid)"
            ),
            {"mid": stale},
        )

        assert repo.cleanup_superseded_older_than(14) == 1
        assert repo.was_superseded(stale) is False
        assert repo.was_superseded(recent) is True
