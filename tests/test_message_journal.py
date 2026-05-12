"""Unit tests for ``application/streaming/message_journal.py``.

The journal hook is best-effort by contract — its failure modes are
the most important thing to lock down so a streaming hiccup never
crashes ``complete_stream``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from application.streaming.message_journal import record_event


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
