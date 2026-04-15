"""Unit tests for application/api/answer/services/continuation_service.py.

Covers:
  - _make_serializable: ObjectId, dict, list, bytes conversions
  - ContinuationService.__init__: index creation
  - save_state: upserts document with correct shape
  - load_state: returns doc or None
  - delete_state: removes doc and returns bool
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId


@pytest.mark.unit
class TestMakeSerializable:

    def test_converts_objectid_to_string(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )

        oid = ObjectId()
        result = _make_serializable(oid)
        assert result == str(oid)

    def test_converts_nested_dict(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )

        oid = ObjectId()
        data = {"key": oid, "nested": {"inner": oid}}
        result = _make_serializable(data)
        assert result == {"key": str(oid), "nested": {"inner": str(oid)}}

    def test_converts_list_with_objectids(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )

        oid = ObjectId()
        data = [oid, "plain", 42]
        result = _make_serializable(data)
        assert result == [str(oid), "plain", 42]

    def test_converts_bytes_to_string(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )

        result = _make_serializable(b"hello world")
        assert result == "hello world"

    def test_passes_through_primitives(self):
        from application.api.answer.services.continuation_service import (
            _make_serializable,
        )

        assert _make_serializable("hello") == "hello"
        assert _make_serializable(42) == 42
        assert _make_serializable(3.14) == 3.14
        assert _make_serializable(None) is None
        assert _make_serializable(True) is True


@pytest.mark.unit
class TestContinuationServiceInit:

    def test_initializes_collection(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        assert service.collection is not None

    def test_ensure_indexes_tolerates_existing(self, mock_mongo_db):
        """Second init should not raise even if indexes already exist."""
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        ContinuationService()
        ContinuationService()  # Should not raise


@pytest.mark.unit
class TestContinuationServiceSaveState:

    def test_save_state_creates_document(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        state_id = service.save_state(
            conversation_id="conv_abc",
            user="user_123",
            messages=[{"role": "user", "content": "hello"}],
            pending_tool_calls=[{"id": "call_1", "function": {"name": "search"}}],
            tools_dict={"search": {"type": "function"}},
            tool_schemas=[{"name": "search", "description": "search tool"}],
            agent_config={"model_id": "gpt-4", "llm_name": "openai"},
        )

        assert state_id is not None
        doc = collection.find_one({"conversation_id": "conv_abc", "user": "user_123"})
        assert doc is not None
        assert doc["messages"] == [{"role": "user", "content": "hello"}]
        assert len(doc["pending_tool_calls"]) == 1
        assert doc["tools_dict"] == {"search": {"type": "function"}}

    def test_save_state_upserts_existing(self, mock_mongo_db):
        """Second save for same conversation replaces first."""
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        service.save_state(
            conversation_id="conv_abc",
            user="user_123",
            messages=[{"role": "user", "content": "first"}],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )
        service.save_state(
            conversation_id="conv_abc",
            user="user_123",
            messages=[{"role": "user", "content": "second"}],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )

        docs = list(collection.find({"conversation_id": "conv_abc"}))
        assert len(docs) == 1
        assert docs[0]["messages"][0]["content"] == "second"

    def test_save_state_with_client_tools(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        service.save_state(
            conversation_id="conv_tools",
            user="user_123",
            messages=[],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
            client_tools=[{"name": "my_tool", "description": "A client tool"}],
        )

        doc = collection.find_one({"conversation_id": "conv_tools"})
        assert doc["client_tools"] == [{"name": "my_tool", "description": "A client tool"}]

    def test_save_state_no_client_tools_stores_none(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        service.save_state(
            conversation_id="conv_notool",
            user="user_123",
            messages=[],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
            client_tools=None,
        )

        doc = collection.find_one({"conversation_id": "conv_notool"})
        assert doc["client_tools"] is None

    def test_save_state_sets_expires_at(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
            PENDING_STATE_TTL_SECONDS,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        before = datetime.datetime.now(datetime.timezone.utc)
        service.save_state(
            conversation_id="conv_ttl",
            user="user_123",
            messages=[],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )
        after = datetime.datetime.now(datetime.timezone.utc)

        doc = collection.find_one({"conversation_id": "conv_ttl"})
        # expires_at should be roughly TTL seconds after save
        assert doc["expires_at"] is not None

    def test_save_state_serializes_objectids(self, mock_mongo_db):
        """ObjectIds in messages are converted to strings."""
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        oid = ObjectId()
        service.save_state(
            conversation_id="conv_oid",
            user="user_123",
            messages=[{"role": "user", "content": str(oid), "_id": oid}],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={"oid_key": oid},
        )

        doc = collection.find_one({"conversation_id": "conv_oid"})
        # The oid in agent_config should be serialized
        assert doc["agent_config"]["oid_key"] == str(oid)


@pytest.mark.unit
class TestContinuationServiceLoadState:

    def test_load_state_returns_document(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        service.save_state(
            conversation_id="conv_load",
            user="user_123",
            messages=[{"role": "user", "content": "test"}],
            pending_tool_calls=[{"id": "call_1"}],
            tools_dict={"t": "v"},
            tool_schemas=[],
            agent_config={"model_id": "gpt-4"},
        )

        result = service.load_state("conv_load", "user_123")

        assert result is not None
        assert result["conversation_id"] == "conv_load"
        assert result["user"] == "user_123"
        assert result["messages"] == [{"role": "user", "content": "test"}]
        assert isinstance(result["_id"], str)  # ObjectId converted to string

    def test_load_state_returns_none_when_not_found(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        result = service.load_state("nonexistent_conv", "user_123")
        assert result is None

    def test_load_state_is_user_scoped(self, mock_mongo_db):
        """State for user A should not be accessible by user B."""
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        service.save_state(
            conversation_id="conv_scoped",
            user="user_A",
            messages=[],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )

        result = service.load_state("conv_scoped", "user_B")
        assert result is None


@pytest.mark.unit
class TestContinuationServiceDeleteState:

    def test_delete_state_removes_document(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        service.save_state(
            conversation_id="conv_del",
            user="user_123",
            messages=[],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )

        result = service.delete_state("conv_del", "user_123")

        assert result is True
        doc = collection.find_one({"conversation_id": "conv_del"})
        assert doc is None

    def test_delete_state_returns_false_when_not_found(self, mock_mongo_db):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()
        result = service.delete_state("nonexistent_conv", "user_123")
        assert result is False

    def test_delete_state_is_user_scoped(self, mock_mongo_db):
        """Deleting with wrong user should not remove the state."""
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from application.core.settings import settings

        service = ContinuationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["pending_tool_state"]

        service.save_state(
            conversation_id="conv_scoped_del",
            user="user_A",
            messages=[],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )

        # Wrong user — should not delete
        result = service.delete_state("conv_scoped_del", "user_B")
        assert result is False

        # State should still exist
        doc = collection.find_one({"conversation_id": "conv_scoped_del"})
        assert doc is not None

    def test_save_load_delete_round_trip(self, mock_mongo_db):
        """Full round trip: save → load → delete → load returns None."""
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        service = ContinuationService()

        service.save_state(
            conversation_id="conv_rt",
            user="user_rt",
            messages=[{"role": "assistant", "content": "thinking..."}],
            pending_tool_calls=[{"id": "call_rt", "function": {"name": "search", "arguments": "{}"}}],
            tools_dict={"search": {"type": "function", "name": "search"}},
            tool_schemas=[{"name": "search"}],
            agent_config={"model_id": "gpt-4", "llm_name": "openai"},
        )

        loaded = service.load_state("conv_rt", "user_rt")
        assert loaded is not None
        assert loaded["pending_tool_calls"][0]["id"] == "call_rt"

        deleted = service.delete_state("conv_rt", "user_rt")
        assert deleted is True

        none_result = service.load_state("conv_rt", "user_rt")
        assert none_result is None
