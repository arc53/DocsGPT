"""Tests for application/api/answer/services/continuation_service.py using pg_conn."""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.answer.services.continuation_service.db_readonly",
        _yield,
    ), patch(
        "application.api.answer.services.continuation_service.db_session",
        _yield,
    ):
        yield


class TestMakeSerializable:
    def test_uuid_becomes_string(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        u = uuid4()
        assert _make_serializable(u) == str(u)

    def test_dict_keys_stringified(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        got = _make_serializable({42: "a", "b": 2})
        assert got == {"42": "a", "b": 2}

    def test_list_elements_recursively_serialized(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        u = uuid4()
        got = _make_serializable([u, {"x": u}, 1])
        assert got == [str(u), {"x": str(u)}, 1]

    def test_bytes_decoded_to_string(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        assert _make_serializable(b"hello") == "hello"

    def test_bytes_invalid_utf8_replaced(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        # Invalid UTF-8 byte sequence
        got = _make_serializable(b"\xff\xfe")
        assert isinstance(got, str)

    def test_passes_through_primitives(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        assert _make_serializable("hello") == "hello"
        assert _make_serializable(42) == 42
        assert _make_serializable(None) is None
        assert _make_serializable(True) is True


class TestContinuationServiceSaveLoad:
    def test_save_and_load_state(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-cont"
        conv = ConversationsRepository(pg_conn).create(user, name="c")
        conv_id = str(conv["id"])

        service = ContinuationService()
        with _patch_db(pg_conn):
            service.save_state(
                conversation_id=conv_id,
                user=user,
                messages=[{"role": "user", "content": "hi"}],
                pending_tool_calls=[{"id": "call-1", "name": "search"}],
                tools_dict={"search": {"arg": "value"}},
                tool_schemas=[{"name": "search", "params": {}}],
                agent_config={"model_id": "gpt-4"},
                client_tools=[{"name": "client-tool"}],
            )
            loaded = service.load_state(conv_id, user)
        assert loaded is not None
        assert loaded["messages"] == [{"role": "user", "content": "hi"}]

    def test_load_state_returns_none_when_not_found(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        with _patch_db(pg_conn):
            got = service.load_state(
                "00000000-0000-0000-0000-000000000000", "u",
            )
        assert got is None

    def test_save_state_no_client_tools(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-no-client"
        conv = ConversationsRepository(pg_conn).create(user, name="c")
        conv_id = str(conv["id"])

        service = ContinuationService()
        with _patch_db(pg_conn):
            service.save_state(
                conversation_id=conv_id,
                user=user,
                messages=[],
                pending_tool_calls=[{"id": "c"}],
                tools_dict={},
                tool_schemas=[],
                agent_config={},
                client_tools=None,
            )
            loaded = service.load_state(conv_id, user)
        assert loaded is not None

    def test_delete_state_returns_true_when_deleted(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-del"
        conv = ConversationsRepository(pg_conn).create(user, name="c")
        conv_id = str(conv["id"])

        service = ContinuationService()
        with _patch_db(pg_conn):
            service.save_state(
                conversation_id=conv_id,
                user=user,
                messages=[],
                pending_tool_calls=[{"id": "c"}],
                tools_dict={},
                tool_schemas=[],
                agent_config={},
            )
            got = service.delete_state(conv_id, user)
        assert got is True

    def test_delete_state_returns_false_when_missing(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        with _patch_db(pg_conn):
            got = service.delete_state(
                "00000000-0000-0000-0000-000000000000", "u",
            )
        assert got is False
