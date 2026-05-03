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


class TestSaveUserQuestion:
    def test_creates_conversation_and_reserves_message(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
            TERMINATED_RESPONSE_PLACEHOLDER,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-wal-new"
        with _patch_db(pg_conn):
            result = ConversationService().save_user_question(
                conversation_id=None,
                question="what is python?",
                decoded_token={"sub": user},
            )
        assert result["conversation_id"]
        assert result["message_id"]
        assert result["request_id"]

        repo = ConversationsRepository(pg_conn)
        conv = repo.get_any(result["conversation_id"], user)
        assert conv is not None
        messages = repo.get_messages(result["conversation_id"])
        assert len(messages) == 1
        assert messages[0]["status"] == "pending"
        assert messages[0]["prompt"] == "what is python?"
        assert messages[0]["response"] == TERMINATED_RESPONSE_PLACEHOLDER
        assert messages[0]["request_id"] == result["request_id"]

    def test_appends_to_existing_conversation(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-wal-existing"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="hi")
        conv_id = str(conv["id"])

        with _patch_db(pg_conn):
            result = ConversationService().save_user_question(
                conversation_id=conv_id,
                question="follow-up",
                decoded_token={"sub": user},
            )
        assert result["conversation_id"] == conv_id
        msgs = repo.get_messages(conv_id)
        assert len(msgs) == 1
        assert msgs[0]["prompt"] == "follow-up"

    def test_raises_when_token_missing(self):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with pytest.raises(ValueError):
            ConversationService().save_user_question(
                conversation_id=None,
                question="q",
                decoded_token=None,
            )

    def test_regenerate_at_index_replaces_old_message(self, pg_conn):
        """Regenerate at ``index`` truncates the old message *and
        everything after* before reserving the placeholder, so the new
        WAL row lands at ``position=index`` rather than appending at
        the end. Pre-fix the WAL path appended unconditionally and the
        old answer survived alongside the regenerated one.
        """
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-wal-regen"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="regen-test")
        conv_id = str(conv["id"])

        # Seed five completed messages at positions 0..4.
        for i in range(5):
            repo.append_message(
                conv_id,
                {
                    "prompt": f"q{i}",
                    "response": f"a{i}",
                    "thought": "",
                    "sources": [],
                    "tool_calls": [],
                    "metadata": {},
                },
            )
        seeded = repo.get_messages(conv_id)
        assert len(seeded) == 5
        assert [m["position"] for m in seeded] == [0, 1, 2, 3, 4]

        with _patch_db(pg_conn):
            result = ConversationService().save_user_question(
                conversation_id=conv_id,
                question="q3-regen",
                decoded_token={"sub": user},
                index=3,
            )

        msgs = repo.get_messages(conv_id)
        # Positions 0,1,2 from the seed plus the new placeholder at 3.
        assert [m["position"] for m in msgs] == [0, 1, 2, 3]
        # The placeholder carries the regenerated prompt.
        regen = next(m for m in msgs if m["position"] == 3)
        assert regen["prompt"] == "q3-regen"
        assert regen["status"] == "pending"
        assert str(regen["id"]) == result["message_id"]
        # The old answer at index 3 is gone.
        assert not any(m["response"] == "a3" for m in msgs)
        # And anything after index 3 was truncated.
        assert not any(m["prompt"] == "q4" for m in msgs)

    def test_regenerate_at_index_zero_truncates_everything(self, pg_conn):
        """``index=0`` is a valid edge: it should drop every prior
        message and reseat the placeholder at position 0.
        """
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-wal-regen-zero"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="regen-zero")
        conv_id = str(conv["id"])
        for i in range(3):
            repo.append_message(
                conv_id,
                {
                    "prompt": f"old-{i}",
                    "response": f"old-a-{i}",
                    "thought": "",
                    "sources": [],
                    "tool_calls": [],
                    "metadata": {},
                },
            )

        with _patch_db(pg_conn):
            ConversationService().save_user_question(
                conversation_id=conv_id,
                question="fresh-from-start",
                decoded_token={"sub": user},
                index=0,
            )

        msgs = repo.get_messages(conv_id)
        assert len(msgs) == 1
        assert msgs[0]["position"] == 0
        assert msgs[0]["prompt"] == "fresh-from-start"

    def test_regenerate_index_ignored_without_conversation_id(self, pg_conn):
        """``index`` only makes sense against an existing conversation;
        the create-then-reserve path silently treats it as a no-op
        rather than truncating a freshly-created conversation.
        """
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-wal-regen-no-conv"
        with _patch_db(pg_conn):
            result = ConversationService().save_user_question(
                conversation_id=None,
                question="brand new q",
                decoded_token={"sub": user},
                index=2,
            )

        repo = ConversationsRepository(pg_conn)
        msgs = repo.get_messages(result["conversation_id"])
        assert len(msgs) == 1
        assert msgs[0]["position"] == 0
        assert msgs[0]["prompt"] == "brand new q"

    def test_raises_when_conversation_unauthorized(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with _patch_db(pg_conn), pytest.raises(ValueError):
            ConversationService().save_user_question(
                conversation_id="00000000-0000-0000-0000-000000000000",
                question="q",
                decoded_token={"sub": "u"},
            )


class TestFinalizeMessage:
    def test_finalizes_complete(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-fin-ok"
        with _patch_db(pg_conn):
            svc = ConversationService()
            res = svc.save_user_question(
                conversation_id=None,
                question="q",
                decoded_token={"sub": user},
            )
            assert svc.finalize_message(
                res["message_id"],
                "real answer",
                thought="thinking",
                sources=[{"text": "x" * 2000, "title": "doc"}],
                tool_calls=[{"name": "search"}],
                model_id="gpt-4",
                metadata={"foo": "bar"},
                status="complete",
            ) is True

        msgs = ConversationsRepository(pg_conn).get_messages(
            res["conversation_id"],
        )
        assert msgs[0]["response"] == "real answer"
        assert msgs[0]["status"] == "complete"
        assert msgs[0]["thought"] == "thinking"
        assert msgs[0]["model_id"] == "gpt-4"
        # source text trimmed to 1000 chars at finalize time
        assert len(msgs[0]["sources"][0]["text"]) == 1000
        assert msgs[0]["metadata"]["foo"] == "bar"

    def test_finalizes_failed_records_error(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-fin-fail"
        with _patch_db(pg_conn):
            svc = ConversationService()
            res = svc.save_user_question(
                conversation_id=None,
                question="q",
                decoded_token={"sub": user},
            )
            err = RuntimeError("provider down")
            assert svc.finalize_message(
                res["message_id"],
                "fallback text",
                status="failed",
                error=err,
            ) is True

        msgs = ConversationsRepository(pg_conn).get_messages(
            res["conversation_id"],
        )
        assert msgs[0]["status"] == "failed"
        assert msgs[0]["metadata"]["error"] == "RuntimeError: provider down"

    def test_finalize_flips_executed_tool_calls(self, pg_conn):
        """finalize_message must mark tool_call_attempts.status='executed'
        rows as 'confirmed' for the same message_id."""
        from sqlalchemy import text as sql_text

        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        user = "u-fin-tools"
        with _patch_db(pg_conn):
            svc = ConversationService()
            res = svc.save_user_question(
                conversation_id=None,
                question="q",
                decoded_token={"sub": user},
            )
            pg_conn.execute(
                sql_text(
                    "INSERT INTO tool_call_attempts "
                    "(call_id, message_id, tool_name, action_name, arguments, status) "
                    "VALUES (:cid, CAST(:mid AS uuid), 't', 'a', '{}'::jsonb, 'executed')"
                ),
                {"cid": "c1", "mid": res["message_id"]},
            )
            assert svc.finalize_message(
                res["message_id"], "ans", status="complete",
            ) is True

        status = pg_conn.execute(
            sql_text("SELECT status FROM tool_call_attempts WHERE call_id = :cid"),
            {"cid": "c1"},
        ).scalar()
        assert status == "confirmed"

    def test_finalize_returns_false_for_unknown_message(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        with _patch_db(pg_conn):
            assert ConversationService().finalize_message(
                "00000000-0000-0000-0000-000000000000",
                "x",
                status="complete",
            ) is False

    def test_finalize_rolls_back_tool_call_confirm_on_message_update_failure(
        self, pg_conn
    ):
        """Atomicity: if ``update_message_by_id`` raises after the
        tool_call_attempts confirm ran on the same connection, the
        confirm rolls back with the rest of the transaction. The
        ``pg_conn`` fixture pins one connection inside an outer
        rolled-back transaction; we patch ``db_session`` to wrap each
        call in a SAVEPOINT so the production-code ``with`` block
        actually rolls back when the message-update raises.
        """
        from contextlib import contextmanager

        from sqlalchemy import text as sql_text

        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories import conversations as conv_module

        user = "u-fin-rollback"

        @contextmanager
        def _savepoint_session():
            nested = pg_conn.begin_nested()
            try:
                yield pg_conn
                nested.commit()
            except Exception:
                nested.rollback()
                raise

        with patch(
            "application.api.answer.services.conversation_service.db_session",
            _savepoint_session,
        ), patch(
            "application.api.answer.services.conversation_service.db_readonly",
            _savepoint_session,
        ):
            svc = ConversationService()
            res = svc.save_user_question(
                conversation_id=None,
                question="q",
                decoded_token={"sub": user},
            )
            pg_conn.execute(
                sql_text(
                    "INSERT INTO tool_call_attempts "
                    "(call_id, message_id, tool_name, action_name, "
                    "arguments, status) VALUES (:cid, CAST(:mid AS uuid), "
                    "'t', 'a', '{}'::jsonb, 'executed')"
                ),
                {"cid": "rb-1", "mid": res["message_id"]},
            )
            original = conv_module.ConversationsRepository.update_message_by_id

            def boom(self, *args, **kwargs):
                _ = (args, kwargs)
                raise RuntimeError("simulated message-update failure")

            conv_module.ConversationsRepository.update_message_by_id = boom
            try:
                with pytest.raises(RuntimeError):
                    svc.finalize_message(
                        res["message_id"], "answer", status="complete",
                    )
            finally:
                conv_module.ConversationsRepository.update_message_by_id = original

        # The tool_call confirm rolled back: row stays at ``executed``.
        status = pg_conn.execute(
            sql_text(
                "SELECT status FROM tool_call_attempts WHERE call_id = :cid"
            ),
            {"cid": "rb-1"},
        ).scalar()
        assert status == "executed"
        msg_status = pg_conn.execute(
            sql_text(
                "SELECT status FROM conversation_messages "
                "WHERE id = CAST(:mid AS uuid)"
            ),
            {"mid": res["message_id"]},
        ).scalar()
        assert msg_status == "pending"

    def test_finalize_generates_title_when_provided(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-fin-title"
        mock_llm = MagicMock()
        mock_llm.gen.return_value = "Short Title"
        with _patch_db(pg_conn):
            svc = ConversationService()
            res = svc.save_user_question(
                conversation_id=None,
                question="long question that becomes the fallback name",
                decoded_token={"sub": user},
            )
            assert svc.finalize_message(
                res["message_id"],
                "answer",
                status="complete",
                title_inputs={
                    "llm": mock_llm,
                    "question": "long question that becomes the fallback name",
                    "response": "answer",
                    "model_id": "gpt-4",
                    "fallback_name": (
                        "long question that becomes the fallback name"[:50]
                    ),
                },
            ) is True

        repo = ConversationsRepository(pg_conn)
        conv = repo.get_any(res["conversation_id"], user)
        assert conv["name"] == "Short Title"


class TestSaveUserQuestionFinalizeFailedFlow:
    """LLM fails immediately; question stays queryable with status='failed' + error metadata."""

    def test_failed_llm_leaves_question_persisted(self, pg_conn):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-acceptance"
        with _patch_db(pg_conn):
            svc = ConversationService()
            # Simulates the WAL pre-persist before LLM call.
            res = svc.save_user_question(
                conversation_id=None,
                question="why did this fail?",
                decoded_token={"sub": user},
            )
            # Simulates the LLM raising immediately, caught by complete_stream.
            try:
                raise RuntimeError("upstream 503")
            except RuntimeError as e:
                svc.finalize_message(
                    res["message_id"],
                    "",
                    status="failed",
                    error=e,
                )

        msgs = ConversationsRepository(pg_conn).get_messages(
            res["conversation_id"],
        )
        assert len(msgs) == 1
        assert msgs[0]["prompt"] == "why did this fail?"
        assert msgs[0]["status"] == "failed"
        assert "RuntimeError" in msgs[0]["metadata"]["error"]
        assert "upstream 503" in msgs[0]["metadata"]["error"]


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
