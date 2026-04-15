"""Unit tests for application/api/answer/services/conversation_service.py.

Additional coverage beyond tests/api/answer/services/test_conversation_service.py:
  - save_conversation: index-based update, metadata persistence, agent key tracking
  - update_compression_metadata
  - append_compression_message
  - get_compression_metadata
  - Edge cases: None token, empty summary, shared_with access
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock

import pytest


@pytest.mark.unit
class TestConversationServiceGetExtended:

    def test_returns_conversation_for_shared_user(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        result = collection.insert_one(
            {
                "user": "owner_123",
                "shared_with": ["shared_user"],
                "name": "Shared Conv",
                "queries": [],
            }
        )
        conv_id = str(result.inserted_id)

        conv = service.get_conversation(conv_id, "shared_user")
        assert conv is not None
        assert conv["name"] == "Shared Conv"

    def test_handles_exception_gracefully(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        # Pass an invalid ObjectId
        result = service.get_conversation("not-an-objectid", "user_123")
        assert result is None


@pytest.mark.unit
class TestSaveConversationExtended:

    def test_raises_for_none_token(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        with pytest.raises(ValueError, match="Invalid or missing authentication"):
            service.save_conversation(
                conversation_id=None,
                question="Q",
                response="A",
                thought="",
                sources=[],
                tool_calls=[],
                llm=Mock(),
                model_id="m",
                decoded_token=None,
            )

    def test_update_existing_at_index(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        insert_result = collection.insert_one(
            {
                "user": "user_123",
                "name": "Conv",
                "queries": [
                    {
                        "prompt": "Q1",
                        "response": "A1",
                        "thought": "",
                        "sources": [],
                        "tool_calls": [],
                    },
                    {
                        "prompt": "Q2",
                        "response": "A2",
                        "thought": "",
                        "sources": [],
                        "tool_calls": [],
                    },
                ],
            }
        )
        conv_id = str(insert_result.inserted_id)

        result = service.save_conversation(
            conversation_id=conv_id,
            question="Q1_updated",
            response="A1_updated",
            thought="thinking",
            sources=[],
            tool_calls=[],
            llm=Mock(),
            model_id="gpt-4",
            decoded_token={"sub": "user_123"},
            index=0,
        )
        assert result == conv_id

        saved = collection.find_one({"_id": insert_result.inserted_id})
        assert saved["queries"][0]["prompt"] == "Q1_updated"
        assert saved["queries"][0]["response"] == "A1_updated"

    def test_update_at_index_unauthorized(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        insert_result = collection.insert_one(
            {
                "user": "owner",
                "queries": [{"prompt": "Q", "response": "A"}],
            }
        )
        conv_id = str(insert_result.inserted_id)

        with pytest.raises(ValueError, match="not found or unauthorized"):
            service.save_conversation(
                conversation_id=conv_id,
                question="Hack",
                response="Attempt",
                thought="",
                sources=[],
                tool_calls=[],
                llm=Mock(),
                model_id="m",
                decoded_token={"sub": "hacker"},
                index=0,
            )

    def test_saves_metadata(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        mock_llm = Mock()
        mock_llm.gen.return_value = "Title"

        service.save_conversation(
            conversation_id=None,
            question="Q",
            response="A",
            thought="",
            sources=[],
            tool_calls=[],
            llm=mock_llm,
            model_id="m",
            decoded_token={"sub": "user_123"},
            metadata={"search_query": "rewritten query"},
        )

        saved = collection.find_one({"user": "user_123"})
        assert saved["queries"][0]["metadata"] == {"search_query": "rewritten query"}

    def test_no_metadata_when_none(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        mock_llm = Mock()
        mock_llm.gen.return_value = "Title"

        service.save_conversation(
            conversation_id=None,
            question="Q",
            response="A",
            thought="",
            sources=[],
            tool_calls=[],
            llm=mock_llm,
            model_id="m",
            decoded_token={"sub": "user_123"},
            metadata=None,
        )

        saved = collection.find_one({"user": "user_123"})
        assert "metadata" not in saved["queries"][0]

    def test_saves_with_api_key_and_agent(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]
        agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]

        agent_result = agents_collection.insert_one(
            {"key": "agent_key_123", "user": "user_123"}
        )
        agent_id = str(agent_result.inserted_id)

        mock_llm = Mock()
        mock_llm.gen.return_value = "Title"

        service.save_conversation(
            conversation_id=None,
            question="Q",
            response="A",
            thought="",
            sources=[],
            tool_calls=[],
            llm=mock_llm,
            model_id="m",
            decoded_token={"sub": "user_123"},
            api_key="agent_key_123",
            agent_id=agent_id,
        )

        saved = collection.find_one({"user": "user_123"})
        assert saved["api_key"] == "agent_key_123"
        assert saved["agent_id"] == agent_id

    def test_empty_completion_uses_question_prefix(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        mock_llm = Mock()
        mock_llm.gen.return_value = "   "  # whitespace only

        service.save_conversation(
            conversation_id=None,
            question="What is the meaning of life in programming?",
            response="42",
            thought="",
            sources=[],
            tool_calls=[],
            llm=mock_llm,
            model_id="m",
            decoded_token={"sub": "user_123"},
        )

        saved = collection.find_one({"user": "user_123"})
        assert saved["name"] == "What is the meaning of life in programming?"[:50]


@pytest.mark.unit
class TestUpdateCompressionMetadata:

    def test_updates_compression_fields(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        insert_result = collection.insert_one(
            {"user": "u", "queries": []}
        )
        conv_id = str(insert_result.inserted_id)

        meta = {
            "timestamp": datetime.now(timezone.utc),
            "compressed_summary": "Summary of conversation",
            "model_used": "gpt-4",
        }

        service.update_compression_metadata(conv_id, meta)

        saved = collection.find_one({"_id": insert_result.inserted_id})
        assert saved["compression_metadata"]["is_compressed"] is True
        assert len(saved["compression_metadata"]["compression_points"]) == 1


@pytest.mark.unit
class TestAppendCompressionMessage:

    def test_appends_summary_query(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        insert_result = collection.insert_one(
            {"user": "u", "queries": []}
        )
        conv_id = str(insert_result.inserted_id)

        meta = {
            "compressed_summary": "This is the summary",
            "timestamp": datetime.now(timezone.utc),
            "model_used": "gpt-4",
        }

        service.append_compression_message(conv_id, meta)

        saved = collection.find_one({"_id": insert_result.inserted_id})
        assert len(saved["queries"]) == 1
        assert saved["queries"][0]["prompt"] == "[Context Compression Summary]"
        assert saved["queries"][0]["response"] == "This is the summary"

    def test_empty_summary_does_nothing(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        insert_result = collection.insert_one(
            {"user": "u", "queries": []}
        )
        conv_id = str(insert_result.inserted_id)

        service.append_compression_message(conv_id, {"compressed_summary": ""})

        saved = collection.find_one({"_id": insert_result.inserted_id})
        assert len(saved["queries"]) == 0


@pytest.mark.unit
class TestGetCompressionMetadata:

    def test_returns_metadata(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        insert_result = collection.insert_one(
            {
                "user": "u",
                "compression_metadata": {"is_compressed": True},
            }
        )
        conv_id = str(insert_result.inserted_id)

        result = service.get_compression_metadata(conv_id)
        assert result is not None
        assert result["is_compressed"] is True

    def test_returns_none_for_no_metadata(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        insert_result = collection.insert_one({"user": "u"})
        conv_id = str(insert_result.inserted_id)

        result = service.get_compression_metadata(conv_id)
        assert result is None

    def test_returns_none_for_missing_conversation(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        result = service.get_compression_metadata("507f1f77bcf86cd799439011")
        assert result is None

    def test_handles_invalid_id(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        result = service.get_compression_metadata("invalid-id")
        assert result is None


# =====================================================================
# Coverage gap tests  (lines 233-237, 258, 261)
# =====================================================================


@pytest.mark.unit
class TestConversationServiceGaps:

    def test_update_compression_metadata_exception_raises(self, mock_mongo_db):
        """Cover lines 233-237: exception during update raises."""
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        service.conversations_collection = MagicMock()
        service.conversations_collection.update_one.side_effect = Exception("db error")

        with pytest.raises(Exception, match="db error"):
            service.update_compression_metadata(
                "507f1f77bcf86cd799439011",
                {
                    "compressed_summary": "summary",
                    "query_index": 5,
                    "compressed_token_count": 100,
                    "original_token_count": 1000,
                },
            )

    def test_append_compression_message_with_summary(self, mock_mongo_db):
        """Cover lines 258, 261: appends compression message to conversation."""
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        service.conversations_collection = MagicMock()

        conv_id = "507f1f77bcf86cd799439011"
        metadata = {
            "compressed_summary": "This is a summary of the conversation.",
            "timestamp": "2024-01-01T00:00:00",
            "model_used": "gpt-4",
        }
        service.append_compression_message(conv_id, metadata)
        service.conversations_collection.update_one.assert_called_once()

    def test_append_compression_message_empty_summary_skips(self, mock_mongo_db):
        """Cover: empty summary does not insert."""
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        service.conversations_collection = MagicMock()

        service.append_compression_message(
            "507f1f77bcf86cd799439011", {"compressed_summary": ""}
        )
        service.conversations_collection.update_one.assert_not_called()
