"""Unit tests for application/api/answer/services/conversation_service.py.

Additional coverage beyond tests/api/answer/services/test_conversation_service.py:
  - save_conversation: index-based update, metadata persistence, agent key tracking
  - update_compression_metadata
  - append_compression_message
  - get_compression_metadata
  - Edge cases: None token, empty summary, shared_with access
"""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from bson import ObjectId


@pytest.mark.unit
class TestConversationServiceGetExtended:

    def test_returns_conversation_for_shared_user(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        conv_id = ObjectId()
        collection.insert_one(
            {
                "_id": conv_id,
                "user": "owner_123",
                "shared_with": ["shared_user"],
                "name": "Shared Conv",
                "queries": [],
            }
        )

        result = service.get_conversation(str(conv_id), "shared_user")
        assert result is not None
        assert result["name"] == "Shared Conv"

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

        conv_id = ObjectId()
        collection.insert_one(
            {
                "_id": conv_id,
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

        result = service.save_conversation(
            conversation_id=str(conv_id),
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
        assert result == str(conv_id)

        saved = collection.find_one({"_id": conv_id})
        assert saved["queries"][0]["prompt"] == "Q1_updated"
        assert saved["queries"][0]["response"] == "A1_updated"

    def test_update_at_index_unauthorized(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        conv_id = ObjectId()
        collection.insert_one(
            {
                "_id": conv_id,
                "user": "owner",
                "queries": [{"prompt": "Q", "response": "A"}],
            }
        )

        with pytest.raises(ValueError, match="not found or unauthorized"):
            service.save_conversation(
                conversation_id=str(conv_id),
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

        conv_id = service.save_conversation(
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

        saved = collection.find_one({"_id": ObjectId(conv_id)})
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

        conv_id = service.save_conversation(
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

        saved = collection.find_one({"_id": ObjectId(conv_id)})
        assert "metadata" not in saved["queries"][0]

    def test_saves_with_api_key_and_agent(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]
        agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]

        agent_id = ObjectId()
        agents_collection.insert_one(
            {"_id": agent_id, "key": "agent_key_123", "user": "user_123"}
        )

        mock_llm = Mock()
        mock_llm.gen.return_value = "Title"

        conv_id = service.save_conversation(
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
            agent_id=str(agent_id),
        )

        saved = collection.find_one({"_id": ObjectId(conv_id)})
        assert saved["api_key"] == "agent_key_123"
        assert saved["agent_id"] == str(agent_id)

    def test_empty_completion_uses_question_prefix(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        mock_llm = Mock()
        mock_llm.gen.return_value = "   "  # whitespace only

        conv_id = service.save_conversation(
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

        saved = collection.find_one({"_id": ObjectId(conv_id)})
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

        conv_id = ObjectId()
        collection.insert_one(
            {"_id": conv_id, "user": "u", "queries": []}
        )

        meta = {
            "timestamp": datetime.now(timezone.utc),
            "compressed_summary": "Summary of conversation",
            "model_used": "gpt-4",
        }

        service.update_compression_metadata(str(conv_id), meta)

        saved = collection.find_one({"_id": conv_id})
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

        conv_id = ObjectId()
        collection.insert_one(
            {"_id": conv_id, "user": "u", "queries": []}
        )

        meta = {
            "compressed_summary": "This is the summary",
            "timestamp": datetime.now(timezone.utc),
            "model_used": "gpt-4",
        }

        service.append_compression_message(str(conv_id), meta)

        saved = collection.find_one({"_id": conv_id})
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

        conv_id = ObjectId()
        collection.insert_one(
            {"_id": conv_id, "user": "u", "queries": []}
        )

        service.append_compression_message(str(conv_id), {"compressed_summary": ""})

        saved = collection.find_one({"_id": conv_id})
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

        conv_id = ObjectId()
        collection.insert_one(
            {
                "_id": conv_id,
                "user": "u",
                "compression_metadata": {"is_compressed": True},
            }
        )

        result = service.get_compression_metadata(str(conv_id))
        assert result is not None
        assert result["is_compressed"] is True

    def test_returns_none_for_no_metadata(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        conv_id = ObjectId()
        collection.insert_one({"_id": conv_id, "user": "u"})

        result = service.get_compression_metadata(str(conv_id))
        assert result is None

    def test_returns_none_for_missing_conversation(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        result = service.get_compression_metadata(str(ObjectId()))
        assert result is None

    def test_handles_invalid_id(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        result = service.get_compression_metadata("invalid-id")
        assert result is None
