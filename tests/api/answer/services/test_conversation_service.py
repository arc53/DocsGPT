"""Tests for application/api/answer/services/conversation_service.py."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.answer.services.conversation_service.db_session",
        _yield,
    ), patch(
        "application.api.answer.services.conversation_service.db_readonly",
        _yield,
    ):
        yield


class TestConversationServiceGet:
    def test_returns_none_when_no_conversation_id(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        assert ConversationService().get_conversation("", "u") is None

    def test_returns_none_when_no_user_id(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        assert (
            ConversationService().get_conversation(
                "00000000-0000-0000-0000-000000000001", ""
            )
            is None
        )

    def test_returns_none_when_not_found(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with _patch_db(pg_conn):
            got = ConversationService().get_conversation(
                "00000000-0000-0000-0000-000000000000", "u",
            )
        assert got is None

    def test_returns_conversation_with_messages(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-get"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="hi")
        conv_id = str(conv["id"])
        repo.append_message(
            conv_id, {"prompt": "q1", "response": "r1"}
        )

        with _patch_db(pg_conn):
            got = ConversationService().get_conversation(conv_id, user)
        assert got is not None
        assert got["_id"] == conv_id
        assert len(got["queries"]) == 1

    def test_handles_exception_returns_none(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.answer.services.conversation_service.db_readonly",
            _broken,
        ):
            got = ConversationService().get_conversation("abc", "u")
        assert got is None


class TestConversationServiceSave:
    def test_raises_for_none_token(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with pytest.raises(ValueError):
            ConversationService().save_conversation(
                conversation_id=None,
                question="q", response="r", thought="", sources=[],
                tool_calls=[], llm=MagicMock(), model_id="gpt",
                decoded_token=None,
            )

    def test_raises_when_no_user_in_token(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with pytest.raises(ValueError):
            ConversationService().save_conversation(
                conversation_id=None,
                question="q", response="r", thought="", sources=[],
                tool_calls=[], llm=MagicMock(), model_id="gpt",
                decoded_token={},
            )

    def test_creates_new_conversation(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-save-new"
        mock_llm = MagicMock()
        mock_llm.gen.return_value = "Title"

        with _patch_db(pg_conn):
            conv_id = ConversationService().save_conversation(
                conversation_id=None,
                question="q1", response="r1", thought="",
                sources=[{"text": "x" * 2000}], tool_calls=[],
                llm=mock_llm, model_id="gpt-4",
                decoded_token={"sub": user},
            )
        got = ConversationsRepository(pg_conn).get_any(conv_id, user)
        assert got is not None
        assert got["name"] == "Title"

    def test_appends_message_to_existing(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-append"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="existing")
        conv_id = str(conv["id"])

        with _patch_db(pg_conn):
            got = ConversationService().save_conversation(
                conversation_id=conv_id,
                question="q-new", response="r-new", thought="",
                sources=[], tool_calls=[],
                llm=MagicMock(), model_id="gpt-4",
                decoded_token={"sub": user},
            )
        assert got == conv_id
        messages = repo.get_messages(conv_id)
        assert any(m["prompt"] == "q-new" for m in messages)

    def test_updates_message_at_index(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-update-at"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="edit")
        conv_id = str(conv["id"])
        repo.append_message(conv_id, {"prompt": "old", "response": "old"})

        with _patch_db(pg_conn):
            got = ConversationService().save_conversation(
                conversation_id=conv_id,
                question="updated", response="reply", thought="",
                sources=[], tool_calls=[],
                llm=MagicMock(), model_id="gpt-4",
                decoded_token={"sub": user},
                index=0,
            )
        assert got == conv_id
        messages = repo.get_messages(conv_id)
        assert messages[0]["prompt"] == "updated"

    def test_raises_when_conversation_missing(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with _patch_db(pg_conn), pytest.raises(ValueError):
            ConversationService().save_conversation(
                conversation_id="00000000-0000-0000-0000-000000000000",
                question="q", response="r", thought="",
                sources=[], tool_calls=[],
                llm=MagicMock(), model_id="gpt",
                decoded_token={"sub": "u"},
            )

    def test_save_with_empty_llm_title_falls_back(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-empty-title"
        mock_llm = MagicMock()
        mock_llm.gen.return_value = ""

        with _patch_db(pg_conn):
            conv_id = ConversationService().save_conversation(
                conversation_id=None,
                question="q-fallback", response="r", thought="",
                sources=[], tool_calls=[],
                llm=mock_llm, model_id="gpt-4",
                decoded_token={"sub": user},
            )
        got = ConversationsRepository(pg_conn).get_any(conv_id, user)
        assert got["name"] == "q-fallback"


class TestCompressionMetadata:
    def test_update_compression_metadata(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-compress"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="c")
        conv_id = str(conv["id"])

        with _patch_db(pg_conn):
            ConversationService().update_compression_metadata(
                conv_id,
                {
                    "timestamp": datetime.now(timezone.utc),
                    "compressed_summary": "summary",
                    "model_used": "gpt",
                },
            )

    def test_update_compression_raises_on_error(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.answer.services.conversation_service.db_session",
            _broken,
        ), pytest.raises(RuntimeError):
            ConversationService().update_compression_metadata("abc", {})

    def test_append_compression_message_skips_empty_summary(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        with _patch_db(pg_conn):
            ConversationService().append_compression_message(
                "any-id", {"compressed_summary": ""}
            )

    def test_append_compression_message_appends_summary(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-append-cs"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="c")
        conv_id = str(conv["id"])

        with _patch_db(pg_conn):
            ConversationService().append_compression_message(
                conv_id,
                {
                    "compressed_summary": "A summary",
                    "timestamp": datetime.now(timezone.utc),
                    "model_used": "gpt-4",
                },
            )

        messages = repo.get_messages(conv_id)
        assert any(m["response"] == "A summary" for m in messages)

    def test_append_compression_message_swallows_error(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.answer.services.conversation_service.db_session",
            _broken,
        ):
            ConversationService().append_compression_message(
                "abc", {"compressed_summary": "x"}
            )

    def test_get_compression_metadata_returns_none_for_missing(
        self, pg_conn,
    ):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with _patch_db(pg_conn):
            got = ConversationService().get_compression_metadata(
                "00000000-0000-0000-0000-000000000000"
            )
        assert got is None

    def test_get_compression_metadata_non_uuid_does_not_raise(
        self, pg_conn, caplog,
    ):
        """Non-UUID ids (legacy Mongo ObjectIds with no legacy_mongo_id row)
        must return None without hitting ``CAST(:id AS uuid)`` — which
        would raise and pollute logs with a stack trace every call."""
        import logging

        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        with caplog.at_level(logging.ERROR):
            with _patch_db(pg_conn):
                got = ConversationService().get_compression_metadata(
                    "507f1f77bcf86cd799439011"
                )
        assert got is None
        assert not any(
            "Error getting compression metadata" in r.message for r in caplog.records
        )

    def test_get_compression_metadata_handles_exception(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.answer.services.conversation_service.db_readonly",
            _broken,
        ):
            got = ConversationService().get_compression_metadata("abc")
        assert got is None
