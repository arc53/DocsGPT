"""Round-trip tests for ``MessageEventsRepository`` against a real
ephemeral Postgres (via the project's ``pg_engine`` fixture).

Phase 2A coverage: insert ordering, read_after cursor semantics, the
composite PK rejecting duplicate (message_id, sequence_no), cascade on
parent delete.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from application.storage.db.repositories.message_events import (
    MessageEventsRepository,
)


def _seed_message(conn) -> str:
    """Create a parent conversation + message and return the message_id."""
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    conv_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    conn.execute(
        text("INSERT INTO users (user_id) VALUES (:u)"),
        {"u": user_id},
    )
    conn.execute(
        text(
            "INSERT INTO conversations (id, user_id, name) "
            "VALUES (:id, :u, 'test')"
        ),
        {"id": conv_id, "u": user_id},
    )
    conn.execute(
        text(
            "INSERT INTO conversation_messages (id, conversation_id, user_id, position) "
            "VALUES (:id, :c, :u, 0)"
        ),
        {"id": msg_id, "c": conv_id, "u": user_id},
    )
    return str(msg_id)


@pytest.mark.integration
class TestMessageEventsRepository:
    def test_record_and_read_after_in_order(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)

        repo.record(message_id, 0, "answer", {"chunk": "Hello"})
        repo.record(message_id, 1, "answer", {"chunk": " world"})
        repo.record(message_id, 2, "end", {})

        rows = list(repo.read_after(message_id))
        assert [r["sequence_no"] for r in rows] == [0, 1, 2]
        assert rows[0]["event_type"] == "answer"
        assert rows[0]["payload"] == {"chunk": "Hello"}
        assert rows[2]["event_type"] == "end"

    def test_read_after_filters_by_cursor(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)

        for n in range(5):
            repo.record(message_id, n, "answer", {"chunk": f"#{n}"})

        # Cursor at 1 returns sequence_no in [2, 3, 4].
        rows = list(repo.read_after(message_id, last_sequence_no=1))
        assert [r["sequence_no"] for r in rows] == [2, 3, 4]

        # Cursor None replays the whole backlog.
        rows = list(repo.read_after(message_id, last_sequence_no=None))
        assert [r["sequence_no"] for r in rows] == [0, 1, 2, 3, 4]

        # Cursor past the end returns empty.
        rows = list(repo.read_after(message_id, last_sequence_no=99))
        assert rows == []

    def test_duplicate_sequence_no_raises(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)

        repo.record(message_id, 0, "answer", {"chunk": "first"})
        with pytest.raises(IntegrityError):
            repo.record(message_id, 0, "answer", {"chunk": "second"})

    def test_latest_sequence_no(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)
        # Empty journal returns None.
        assert repo.latest_sequence_no(message_id) is None
        repo.record(message_id, 0, "answer", {"chunk": "a"})
        repo.record(message_id, 7, "answer", {"chunk": "b"})
        assert repo.latest_sequence_no(message_id) == 7

    def test_cascade_on_message_delete(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)

        repo.record(message_id, 0, "answer", {"chunk": "x"})
        pg_conn.execute(
            text("DELETE FROM conversation_messages WHERE id = CAST(:id AS uuid)"),
            {"id": message_id},
        )
        assert list(repo.read_after(message_id)) == []

    def test_payload_default_empty_jsonb(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)
        repo.record(message_id, 0, "end")  # no payload
        rows = list(repo.read_after(message_id))
        assert rows[0]["payload"] == {}

    def test_record_with_list_payload_preserves_shape(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)
        repo.record(message_id, 0, "sources", [{"url": "a"}, {"url": "b"}])
        rows = repo.read_after(message_id)
        assert rows[0]["payload"] == [{"url": "a"}, {"url": "b"}]

    def test_record_empty_event_type_raises(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)
        with pytest.raises(ValueError):
            repo.record(message_id, 0, "")

    def test_record_failure_isolated_via_savepoint(self, pg_conn):
        """The shared-connection caller must use ``begin_nested`` so a
        single integrity error doesn't poison the whole transaction.
        """
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)

        repo.record(message_id, 0, "answer", {"chunk": "first"})
        # Duplicate sequence_no — must not abort the outer transaction
        # when wrapped in a SAVEPOINT.
        try:
            with pg_conn.begin_nested():
                repo.record(message_id, 0, "answer", {"chunk": "duplicate"})
        except IntegrityError:
            pass
        # Subsequent record on the same outer transaction still works.
        repo.record(message_id, 1, "answer", {"chunk": "after"})
        rows = repo.read_after(message_id)
        assert [r["sequence_no"] for r in rows] == [0, 1]

    def test_cleanup_older_than_deletes_only_aged_rows(self, pg_conn):
        message_id = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)

        repo.record(message_id, 0, "answer", {"chunk": "stale"})
        repo.record(message_id, 1, "answer", {"chunk": "fresh"})
        # Backdate row 0 past the retention window so the janitor catches
        # it; row 1 stays at "now" and must survive.
        pg_conn.execute(
            text(
                "UPDATE message_events SET created_at = now() - interval '20 days' "
                "WHERE message_id = CAST(:id AS uuid) AND sequence_no = 0"
            ),
            {"id": message_id},
        )

        deleted = repo.cleanup_older_than(ttl_days=14)
        assert deleted == 1
        rows = list(repo.read_after(message_id))
        assert [r["sequence_no"] for r in rows] == [1]

    def test_cleanup_older_than_rejects_non_positive(self, pg_conn):
        repo = MessageEventsRepository(pg_conn)
        with pytest.raises(ValueError):
            repo.cleanup_older_than(ttl_days=0)
        with pytest.raises(ValueError):
            repo.cleanup_older_than(ttl_days=-1)

    def test_message_id_isolation(self, pg_conn):
        m1 = _seed_message(pg_conn)
        m2 = _seed_message(pg_conn)
        repo = MessageEventsRepository(pg_conn)

        repo.record(m1, 0, "answer", {"chunk": "msg1"})
        repo.record(m2, 0, "answer", {"chunk": "msg2"})

        rows1 = list(repo.read_after(m1))
        rows2 = list(repo.read_after(m2))
        assert len(rows1) == 1 and rows1[0]["payload"] == {"chunk": "msg1"}
        assert len(rows2) == 1 and rows2[0]["payload"] == {"chunk": "msg2"}
