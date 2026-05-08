"""Tests for application/api/answer/services/continuation_service.py using pg_conn."""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4



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

    def test_bytes_base64_encoded(self):
        # Migrated from UTF-8-replace to base64 once the helper moved to
        # the shared serialization module — base64 is lossless and round-
        # trippable (UTF-8-replace silently corrupted binary payloads).
        import base64
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        got = _make_serializable(b"hello")
        assert got == base64.b64encode(b"hello").decode("ascii")

    def test_bytes_arbitrary_binary_roundtrips(self):
        import base64
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        raw = b"\xff\xfe\x00\x10"
        got = _make_serializable(raw)
        assert isinstance(got, str)
        assert base64.b64decode(got) == raw

    def test_passes_through_primitives(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        assert _make_serializable("hello") == "hello"
        assert _make_serializable(42) == 42
        assert _make_serializable(None) is None
        assert _make_serializable(True) is True

    def test_datetime_becomes_iso_string(self):
        # PG SELECT * pulls timestamptz columns through as datetime —
        # tools_dict carries ``created_at``/``updated_at`` from user_tools
        # rows, which would otherwise blow up json.dumps in pending_tool_state.
        import json
        from datetime import datetime, timezone
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )

        ts = datetime(2026, 5, 2, 12, 14, 32, tzinfo=timezone.utc)
        got = _make_serializable(ts)
        assert got == "2026-05-02T12:14:32+00:00"
        json.dumps(got)  # would raise on raw datetime

    def test_datetime_nested_in_tools_dict(self):
        # Mirrors the production failure: tools_dict is a dict-of-dicts
        # where each tool row has timestamp fields buried under string keys.
        import json
        from datetime import datetime, timezone
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )

        ts = datetime(2026, 5, 2, 12, 14, 32, tzinfo=timezone.utc)
        tools_dict = {
            "0": {
                "name": "mcp_tool",
                "actions": [{"name": "search", "active": True}],
                "created_at": ts,
                "updated_at": ts,
            }
        }
        got = _make_serializable(tools_dict)
        json.dumps(got)
        assert got["0"]["created_at"] == "2026-05-02T12:14:32+00:00"

    def test_date_becomes_iso_string(self):
        from datetime import date
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )
        assert _make_serializable(date(2026, 5, 2)) == "2026-05-02"


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


class TestContinuationServiceLegacyIdHandling:
    """An unresolvable Mongo ObjectId must not reach ``CAST(:conv_id AS uuid)``
    in ``PendingToolStateRepository`` — that cast raises and aborts the
    enclosing transaction. This can happen when an OpenAI-compatible client
    echoes back a ``chatcmpl-<legacy_objectid>`` id from before the PG
    cutover and the conversation hasn't been backfilled."""

    LEGACY_OBJECTID = "507f1f77bcf86cd799439011"

    def test_load_state_unresolvable_legacy_id_returns_none(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        with _patch_db(pg_conn):
            got = service.load_state(self.LEGACY_OBJECTID, "u")
        assert got is None

    def test_delete_state_unresolvable_legacy_id_returns_false(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        with _patch_db(pg_conn):
            got = service.delete_state(self.LEGACY_OBJECTID, "u")
        assert got is False

    def test_save_state_unresolvable_legacy_id_raises(self, pg_conn):
        import pytest

        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        with _patch_db(pg_conn):
            with pytest.raises(ValueError):
                service.save_state(
                    conversation_id=self.LEGACY_OBJECTID,
                    user="u",
                    messages=[],
                    pending_tool_calls=[{"id": "c"}],
                    tools_dict={},
                    tool_schemas=[],
                    agent_config={},
                )

    def test_load_state_resolves_backfilled_legacy_id(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "legacy-cont"
        ConversationsRepository(pg_conn).create(
            user, name="c", legacy_mongo_id=self.LEGACY_OBJECTID,
        )

        service = ContinuationService()
        with _patch_db(pg_conn):
            # Save via the legacy id — should resolve to the PG UUID internally.
            service.save_state(
                conversation_id=self.LEGACY_OBJECTID,
                user=user,
                messages=[{"role": "user", "content": "hi"}],
                pending_tool_calls=[{"id": "c"}],
                tools_dict={},
                tool_schemas=[],
                agent_config={},
            )
            # And load via the legacy id — should round-trip.
            loaded = service.load_state(self.LEGACY_OBJECTID, user)
        assert loaded is not None
        assert loaded["messages"] == [{"role": "user", "content": "hi"}]
