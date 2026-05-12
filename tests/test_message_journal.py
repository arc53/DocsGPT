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

    def test_payload_non_dict_normalised_to_empty(self):
        """Defensive: callers should pass dicts. Non-dicts (lists,
        strings, ints) collapse to ``{}`` rather than raising.
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
            mock_topic_cls.return_value = MagicMock()

            record_event("msg-1", 0, "end", ["unexpected", "list"])
            mock_repo.record.assert_called_once_with("msg-1", 0, "end", {})
