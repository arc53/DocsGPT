"""Integration tests for the end-to-end snapshot+tail handoff.

Exercises the publisher → journal → reconnect-reader round-trip without
mocking the journal layer, so a regression in any of:
- complete_stream's _emit closure
- record_event's commit-per-call contract
- the shared snapshot read (``event_replay.read_snapshot_lines``)
- the reconnect route's ownership SQL (``async_sse._user_owns_message``)
- message_events repo SQL
would surface here as a failed integration assertion.

The live tail itself (pub/sub) and the full async HTTP route are covered by
``scripts/e2e_async_sse.py`` against a real Redis + uvicorn. These tests pin
the DB-backed halves against a transactional ``pg_conn`` fixture.
"""

from __future__ import annotations

import uuid as _uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text as sql_text


@contextmanager
def _patch_journal_session(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.streaming.message_journal.db_session", _yield
    ), patch(
        "application.streaming.event_replay.db_readonly", _yield
    ):
        yield


def _seed_message(conn, user_id: str | None = None):
    user_id = user_id or f"u-{_uuid.uuid4().hex[:6]}"
    conv_id = _uuid.uuid4()
    msg_id = _uuid.uuid4()
    conn.execute(sql_text("INSERT INTO users (user_id) VALUES (:u)"), {"u": user_id})
    conn.execute(
        sql_text(
            "INSERT INTO conversations (id, user_id, name) VALUES (:id, :u, 't')"
        ),
        {"id": conv_id, "u": user_id},
    )
    conn.execute(
        sql_text(
            "INSERT INTO conversation_messages (id, conversation_id, user_id, position) "
            "VALUES (:id, :c, :u, 0)"
        ),
        {"id": msg_id, "c": conv_id, "u": user_id},
    )
    return user_id, str(msg_id)


def _emitted_ids(lines: list[str]) -> list[int]:
    """Extract the ``id:`` sequence numbers from formatted SSE frames."""
    return sorted(
        int(line.split("\n", 1)[0].split(": ", 1)[1])
        for line in lines
        if line.startswith("id: ")
    )


@pytest.mark.integration
class TestSnapshotPlusTailRoundTrip:
    def test_record_event_then_snapshot_returns_what_was_journaled(
        self, pg_conn,
    ):
        """End-to-end of the journal half: ``record_event`` writes through a
        real ``MessageEventsRepository``, ``read_snapshot_lines`` reads the
        snapshot back via the same repo and formats it for the wire — the
        exact primitive the async reader replays through.
        """
        from application.streaming.event_replay import read_snapshot_lines
        from application.streaming.message_journal import record_event

        _, message_id = _seed_message(pg_conn)

        with _patch_journal_session(pg_conn):
            record_event(message_id, 0, "answer", {"type": "answer", "answer": "A"})
            record_event(message_id, 1, "answer", {"type": "answer", "answer": "B"})
            record_event(message_id, 2, "end", {"type": "end"})

            lines, max_seq, terminal = read_snapshot_lines(message_id, None)

        assert len(lines) == 3
        assert "id: 0" in lines[0] and '"answer": "A"' in lines[0]
        assert "id: 1" in lines[1] and '"answer": "B"' in lines[1]
        assert "id: 2" in lines[2] and '"type": "end"' in lines[2]
        assert max_seq == 2
        # A terminal event in the snapshot tells the reader to close.
        assert terminal is True

    def test_snapshot_resumes_past_last_event_id(self, pg_conn):
        from application.streaming.event_replay import read_snapshot_lines
        from application.streaming.message_journal import record_event

        _, message_id = _seed_message(pg_conn)

        with _patch_journal_session(pg_conn):
            for seq in range(5):
                record_event(
                    message_id, seq, "answer", {"type": "answer", "answer": str(seq)}
                )

            # Client says it has seen up through seq=2; expect 3 + 4.
            lines, max_seq, terminal = read_snapshot_lines(message_id, 2)

        assert _emitted_ids(lines) == [3, 4]
        assert max_seq == 4
        assert terminal is False

    def test_ownership_sql_accepts_owner_and_rejects_others(self, pg_conn):
        """The async route's ownership gate runs real SQL against
        ``conversation_messages`` — the owner passes, everyone else 404s.
        """
        from application.api import async_sse

        user_id, message_id = _seed_message(pg_conn)

        @contextmanager
        def _yield():
            yield pg_conn

        with patch("application.api.async_sse.db_readonly", _yield):
            assert async_sse._user_owns_message(message_id, user_id) is True
            assert async_sse._user_owns_message(message_id, "different-user") is False
            # A well-formed but unknown id is also not owned.
            assert async_sse._user_owns_message(str(_uuid.uuid4()), user_id) is False

    def test_snapshot_read_is_user_scoped(self, pg_conn):
        """``read_snapshot_lines(..., user_id=)`` re-asserts ownership at the
        data layer: the owner gets the journal rows, a non-owner gets none.
        """
        from application.streaming.event_replay import read_snapshot_lines
        from application.streaming.message_journal import record_event

        user_id, message_id = _seed_message(pg_conn)

        with _patch_journal_session(pg_conn):
            record_event(message_id, 0, "answer", {"type": "answer", "answer": "x"})
            record_event(message_id, 1, "end", {"type": "end"})

            owner_lines, _, owner_terminal = read_snapshot_lines(
                message_id, None, user_id
            )
            other_lines, _, other_terminal = read_snapshot_lines(
                message_id, None, "different-user"
            )
            # Unscoped (user_id=None) still returns everything.
            unscoped_lines, _, _ = read_snapshot_lines(message_id, None)

        assert _emitted_ids(owner_lines) == [0, 1] and owner_terminal is True
        assert other_lines == [] and other_terminal is False
        assert _emitted_ids(unscoped_lines) == [0, 1]

    def test_watchdog_is_user_scoped(self, pg_conn):
        """``_check_producer_liveness(..., user_id)`` only sees the caller's
        own row; a non-owner reads as missing (terminal), not as the row's
        real status.
        """
        from application.streaming.event_replay import _check_producer_liveness

        # Seed a row and flip it to a terminal status the watchdog reports.
        user_id, message_id = _seed_message(pg_conn)
        pg_conn.execute(
            sql_text(
                "UPDATE conversation_messages SET status='complete' WHERE id = :id"
            ),
            {"id": message_id},
        )

        @contextmanager
        def _yield():
            yield pg_conn

        with patch("application.streaming.event_replay.db_readonly", _yield):
            owner = _check_producer_liveness(message_id, user_id, 90.0)
            other = _check_producer_liveness(message_id, "different-user", 90.0)

        # Owner sees the real terminal state; non-owner sees "missing".
        assert owner == {"type": "end"}
        assert other is not None and other.get("code") == "message_missing"
