"""Unit tests for ``application/streaming/message_journal.py``.

The journal hook is best-effort by contract — its failure modes are
the most important thing to lock down so a streaming hiccup never
crashes ``complete_stream``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from application.streaming.message_journal import (
    BatchedJournalWriter,
    record_event,
)


@pytest.mark.unit
class TestRecordEvent:
    def test_invalid_args_return_false(self):
        assert record_event("", 0, "answer") is False
        assert record_event("msg-1", 0, "") is False

    def test_happy_path_writes_and_publishes(self):
        with patch(
            "application.streaming.message_journal.db_session"
        ) as mock_session, patch(
            "application.streaming.message_journal.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.message_journal.Topic"
        ) as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            result = record_event(
                "msg-1", 5, "answer", {"type": "answer", "answer": "ok"}
            )

            assert result is True
            mock_repo.record.assert_called_once_with(
                "msg-1", 5, "answer", {"type": "answer", "answer": "ok"}
            )
            mock_topic_cls.assert_called_once_with("channel:msg-1")
            mock_topic.publish.assert_called_once()
            wire = mock_topic.publish.call_args[0][0]
            envelope = json.loads(wire)
            assert envelope["sequence_no"] == 5
            assert envelope["event_type"] == "answer"
            assert envelope["payload"] == {"type": "answer", "answer": "ok"}

    def test_publish_attempted_even_when_journal_fails(self):
        """A DB hiccup must not stop the live tail — currently-attached
        subscribers should still receive the live event so their UI is
        live even if a future reconnect's snapshot is missing this row.
        """
        with patch(
            "application.streaming.message_journal.db_session"
        ) as mock_session, patch(
            "application.streaming.message_journal.MessageEventsRepository"
        ), patch(
            "application.streaming.message_journal.Topic"
        ) as mock_topic_cls:
            mock_session.return_value.__enter__.side_effect = RuntimeError("pg down")
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            result = record_event(
                "msg-1", 1, "answer", {"type": "answer", "answer": "x"}
            )

            assert result is False
            mock_topic.publish.assert_called_once()

    def test_publish_failure_does_not_raise(self):
        with patch(
            "application.streaming.message_journal.db_session"
        ) as mock_session, patch(
            "application.streaming.message_journal.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.message_journal.Topic"
        ) as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.record = MagicMock()
            mock_topic = MagicMock()
            mock_topic.publish.side_effect = RuntimeError("redis down")
            mock_topic_cls.return_value = mock_topic

            # Must not raise.
            result = record_event("msg-1", 0, "answer", {"answer": "y"})
            assert result is True  # Journal still committed.

    def test_payload_none_treated_as_empty_dict(self):
        with patch(
            "application.streaming.message_journal.db_session"
        ) as mock_session, patch(
            "application.streaming.message_journal.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.message_journal.Topic"
        ) as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_topic_cls.return_value = MagicMock()

            record_event("msg-1", 0, "end", None)
            mock_repo.record.assert_called_once_with("msg-1", 0, "end", {})

    def test_payload_non_dict_rejected_at_gate(self):
        """Contract: payload must be a dict (or None). Lists, strings,
        ints, and other shapes are rejected without writing or
        publishing.

        Background: the live path (``base.py::_emit``) and the replay
        path (``event_replay``) previously reconstructed non-dicts
        differently — ``{"value": payload}`` live vs.
        ``{"type": event_type}`` on replay — so a reconnecting client
        would receive a different envelope than the one originally
        streamed. Rejecting at this gate keeps the two paths
        byte-identical.
        """
        with patch(
            "application.streaming.message_journal.db_session"
        ) as mock_session, patch(
            "application.streaming.message_journal.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.message_journal.Topic"
        ) as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            result = record_event("msg-1", 0, "end", ["unexpected", "list"])

            assert result is False
            mock_repo.record.assert_not_called()
            mock_topic.publish.assert_not_called()

    def test_integrity_error_retries_with_seq_plus_one(self):
        """Composite-PK collision on (message_id, sequence_no) is
        recovered by one retry against ``latest_sequence_no + 1`` —
        the most likely cause is a stale seq seed on a continuation
        retry, where the route read MAX(seq) from a separate
        connection before another writer committed past it.

        On success the live pubsub publish uses the retried seq so
        the journal row and the live frame agree, even though the
        caller's original POST stream still carries the pre-retry id.
        """
        from sqlalchemy.exc import IntegrityError

        # Two repo instances: one per ``with db_session()`` block.
        # repo_first.record raises IntegrityError; the readonly
        # session returns latest=7; repo_retry.record succeeds at 8.
        repo_first = MagicMock(name="repo_first")
        repo_first.record.side_effect = IntegrityError("stmt", {}, Exception())
        repo_readonly = MagicMock(name="repo_readonly")
        repo_readonly.latest_sequence_no.return_value = 7
        repo_retry = MagicMock(name="repo_retry")

        repo_instances = iter([repo_first, repo_readonly, repo_retry])

        with patch(
            "application.streaming.message_journal.db_session"
        ) as mock_session, patch(
            "application.streaming.message_journal.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.message_journal.MessageEventsRepository",
            side_effect=lambda conn: next(repo_instances),
        ), patch(
            "application.streaming.message_journal.Topic"
        ) as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            result = record_event("msg-1", 3, "answer", {"text": "hi"})

            assert result is True
            # First INSERT attempted at the caller's seq=3.
            repo_first.record.assert_called_once_with(
                "msg-1", 3, "answer", {"text": "hi"}
            )
            # Latest probed for the retry seed.
            repo_readonly.latest_sequence_no.assert_called_once_with("msg-1")
            # Retry INSERT at latest+1 = 8.
            repo_retry.record.assert_called_once_with(
                "msg-1", 8, "answer", {"text": "hi"}
            )
            # Live publish uses the materialised seq so the wire and
            # the journal row stay in lockstep on the retry path.
            mock_topic.publish.assert_called_once()
            wire = json.loads(mock_topic.publish.call_args[0][0])
            assert wire["sequence_no"] == 8

    def test_integrity_error_retry_failure_drops_silently(self):
        """If the retry collides again (truly concurrent writers in
        lockstep) the journal write is dropped but the function still
        returns ``False`` without raising — the streaming loop must
        not be killed by a journal hiccup.
        """
        from sqlalchemy.exc import IntegrityError

        repo_first = MagicMock(name="repo_first")
        repo_first.record.side_effect = IntegrityError("stmt", {}, Exception())
        repo_readonly = MagicMock(name="repo_readonly")
        repo_readonly.latest_sequence_no.return_value = 3
        repo_retry = MagicMock(name="repo_retry")
        repo_retry.record.side_effect = IntegrityError("stmt", {}, Exception())

        repo_instances = iter([repo_first, repo_readonly, repo_retry])

        with patch(
            "application.streaming.message_journal.db_session"
        ) as mock_session, patch(
            "application.streaming.message_journal.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.message_journal.MessageEventsRepository",
            side_effect=lambda conn: next(repo_instances),
        ), patch(
            "application.streaming.message_journal.Topic"
        ) as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            result = record_event("msg-1", 0, "answer", {"text": "hi"})

            assert result is False
            # Both INSERT attempts fired; the second raised too.
            assert repo_first.record.call_count == 1
            assert repo_retry.record.call_count == 1
            # Live publish still fires on the materialised seq path —
            # subscribers downgrade to keepalives if they were waiting
            # on this event, which is correct since the journal can't
            # serve it on a future reconnect anyway.
            mock_topic.publish.assert_called_once()


@pytest.mark.unit
class TestBatchedJournalWriter:
    """``BatchedJournalWriter`` amortizes per-emit PG commits.

    Tests cover the four flush triggers (size, time, lifecycle,
    explicit), the bulk→per-row IntegrityError fallback, and the
    live-publish-stays-synchronous invariant.
    """

    def _patch_io(self):
        """Standard patch set: stub PG sessions and Redis pubsub.

        Returns a tuple ``(session_cm, readonly_cm, repo_factory, topic)``.
        The repo_factory is a list — each ``MessageEventsRepository(...)``
        call inside the writer pops one element off the front. Tests
        push fakes onto it before triggering the path that needs them.
        """
        from unittest.mock import patch as _patch

        session_cm = _patch("application.streaming.message_journal.db_session")
        readonly_cm = _patch(
            "application.streaming.message_journal.db_readonly"
        )
        repo_cls = _patch(
            "application.streaming.message_journal.MessageEventsRepository"
        )
        topic_cls = _patch("application.streaming.message_journal.Topic")
        return session_cm, readonly_cm, repo_cls, topic_cls

    def test_size_trigger_flushes_at_batch_size(self):
        """Buffer reaches ``batch_size`` → one bulk_record call covers
        all rows; live pubsub publishes fire per ``record()`` so the
        subscriber count matches the row count.
        """
        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            writer = BatchedJournalWriter(
                "msg-1", batch_size=3, batch_interval_ms=10_000
            )
            # First two records: buffered, no bulk_record yet.
            writer.record(0, "answer", {"text": "a"})
            writer.record(1, "answer", {"text": "b"})
            mock_repo.bulk_record.assert_not_called()
            # Third record: triggers a size-based flush.
            writer.record(2, "answer", {"text": "c"})
            mock_repo.bulk_record.assert_called_once()
            args = mock_repo.bulk_record.call_args
            assert args.args[0] == "msg-1"
            buffered = args.args[1]
            assert len(buffered) == 3
            assert [seq for seq, _, _ in buffered] == [0, 1, 2]
            # Live publish fires per ``record()``, not per flush.
            assert mock_topic.publish.call_count == 3

    def test_time_trigger_flushes_after_interval(self):
        """When the elapsed time since the last flush exceeds
        ``batch_interval_ms``, the next ``record()`` flushes — even if
        the buffer is well below ``batch_size``. Drives reconnect
        visibility for slow producers.
        """
        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls, patch(
            "application.streaming.message_journal.time.monotonic"
        ) as mock_mono:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_topic_cls.return_value = MagicMock()

            # First call from __init__ at t=0; subsequent calls drive
            # the time-trigger check inside ``_should_flush``.
            #   t=0.000  → __init__ snapshots last_flush
            #   t=0.001  → record(0) — 1ms elapsed → no flush
            #   t=0.001  → after record, last_flush snapshot when flush called (n/a)
            #   t=0.200  → record(1) — 200ms elapsed → flush
            #   t=0.200  → flush updates last_flush
            mock_mono.side_effect = iter([0.000, 0.001, 0.200, 0.200])

            writer = BatchedJournalWriter(
                "msg-1", batch_size=100, batch_interval_ms=100
            )
            writer.record(0, "answer", {"text": "a"})
            mock_repo.bulk_record.assert_not_called()
            writer.record(1, "answer", {"text": "b"})
            mock_repo.bulk_record.assert_called_once()

    def test_close_drains_remaining_buffer(self):
        """``close()`` is the lifecycle flush — at end of stream every
        buffered event must commit before the writer goes silent.
        Idempotent so it's safe in multiple finally clauses.
        """
        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_topic_cls.return_value = MagicMock()

            writer = BatchedJournalWriter(
                "msg-1", batch_size=100, batch_interval_ms=100_000
            )
            writer.record(0, "answer", {"text": "a"})
            writer.record(1, "end", {"type": "end"})
            mock_repo.bulk_record.assert_not_called()

            writer.close()
            mock_repo.bulk_record.assert_called_once()
            assert len(mock_repo.bulk_record.call_args.args[1]) == 2

            # Second close is a no-op.
            writer.close()
            assert mock_repo.bulk_record.call_count == 1

    def test_record_after_close_returns_false(self):
        """Writing past ``close()`` must not silently land in a stale
        buffer — return False so the caller's flow surfaces the bug.
        """
        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value = MagicMock()
            mock_topic_cls.return_value = MagicMock()

            writer = BatchedJournalWriter("msg-1", batch_size=100)
            writer.close()
            assert writer.record(0, "answer", {"text": "a"}) is False

    def test_record_rejects_non_dict_payload(self):
        """Same contract as ``record_event``: non-dict payloads are
        rejected to keep live and replay paths byte-identical.
        """
        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value = MagicMock()
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            writer = BatchedJournalWriter("msg-1")
            assert writer.record(0, "answer", ["bad", "list"]) is False
            # Nothing publishes either — the gate fires before the wire.
            mock_topic.publish.assert_not_called()

    def test_bulk_collision_falls_back_to_per_row(self):
        """Bulk INSERT fails with IntegrityError → writer retries each
        row individually via the legacy ``record_event`` retry path,
        so a single colliding seq doesn't drop the whole batch.
        """
        from sqlalchemy.exc import IntegrityError

        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm as mock_readonly, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_readonly.return_value.__enter__.return_value = MagicMock()

            # First call: bulk_record raises. Subsequent calls: per-row
            # record succeeds. Use a single fake whose first
            # ``bulk_record`` call raises and whose ``record`` succeeds.
            bulk_repo = MagicMock(name="bulk_repo")
            bulk_repo.bulk_record.side_effect = IntegrityError(
                "stmt", {}, Exception()
            )
            per_row_repo = MagicMock(name="per_row_repo")
            # MessageEventsRepository(conn) is called once per session
            # opened. Bulk path = 1; per-row fallback = 2 rows × 1 each.
            mock_repo_cls.side_effect = [bulk_repo, per_row_repo, per_row_repo]

            mock_topic_cls.return_value = MagicMock()

            writer = BatchedJournalWriter("msg-1", batch_size=2)
            writer.record(0, "answer", {"text": "a"})
            writer.record(1, "answer", {"text": "b"})

            bulk_repo.bulk_record.assert_called_once()
            # Per-row fallback wrote each row in its own session.
            assert per_row_repo.record.call_count == 2
            assert per_row_repo.record.call_args_list[0].args[1] == 0
            assert per_row_repo.record.call_args_list[1].args[1] == 1

    def test_flush_clears_buffer_even_on_total_failure(self):
        """A flush that fails with a non-IntegrityError exception must
        still clear the buffer — leaving rows would grow memory
        unbounded across the remainder of the stream. Degraded UX
        (missing snapshot rows) beats runaway memory.
        """
        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo = MagicMock()
            mock_repo.bulk_record.side_effect = RuntimeError("PG gone")
            mock_repo_cls.return_value = mock_repo
            mock_topic_cls.return_value = MagicMock()

            writer = BatchedJournalWriter("msg-1", batch_size=2)
            writer.record(0, "answer", {"text": "a"})
            writer.record(1, "answer", {"text": "b"})
            # Bulk failed, but the buffer is cleared so a subsequent
            # close() is a no-op and memory stays bounded.
            assert writer._buffer == []
            writer.close()
            # Only the one flush we forced — no double-attempt on
            # close after the buffer was already drained.
            assert mock_repo.bulk_record.call_count == 1

    def test_live_publish_fires_per_record_not_per_flush(self):
        """Subscribers must see events in real time, not in batches —
        the journal write is the only thing being amortized.
        """
        session_cm, readonly_cm, repo_cls_p, topic_cls_p = self._patch_io()
        with session_cm as mock_session, readonly_cm, repo_cls_p as mock_repo_cls, topic_cls_p as mock_topic_cls:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value = MagicMock()
            mock_topic = MagicMock()
            mock_topic_cls.return_value = mock_topic

            writer = BatchedJournalWriter("msg-1", batch_size=100)
            for i in range(5):
                writer.record(i, "answer", {"text": str(i)})
            # All five fire live immediately, even though only 0 flushes
            # have happened (size threshold not met).
            assert mock_topic.publish.call_count == 5
            # Each publish carries its own monotonic sequence_no.
            published_seqs = [
                json.loads(call.args[0])["sequence_no"]
                for call in mock_topic.publish.call_args_list
            ]
            assert published_seqs == [0, 1, 2, 3, 4]
