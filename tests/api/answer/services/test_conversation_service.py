from unittest.mock import Mock

import pytest
from bson import ObjectId


@pytest.mark.unit
class TestConversationServiceGet:

    def test_returns_none_when_no_conversation_id(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        result = service.get_conversation("", "user_123")

        assert result is None

    def test_returns_none_when_no_user_id(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        result = service.get_conversation(str(ObjectId()), "")

        assert result is None

    def test_returns_conversation_for_owner(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        conv_id = ObjectId()
        conversation = {
            "_id": conv_id,
            "user": "user_123",
            "name": "Test Conv",
            "queries": [],
        }
        collection.insert_one(conversation)

        result = service.get_conversation(str(conv_id), "user_123")

        assert result is not None
        assert result["name"] == "Test Conv"
        assert result["_id"] == str(conv_id)

    def test_returns_none_for_unauthorized_user(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        conv_id = ObjectId()
        collection.insert_one(
            {"_id": conv_id, "user": "owner_123", "name": "Private Conv"}
        )

        result = service.get_conversation(str(conv_id), "hacker_456")

        assert result is None

    def test_converts_objectid_to_string(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        conv_id = ObjectId()
        collection.insert_one({"_id": conv_id, "user": "user_123", "name": "Test"})

        result = service.get_conversation(str(conv_id), "user_123")

        assert isinstance(result["_id"], str)
        assert result["_id"] == str(conv_id)


@pytest.mark.unit
class TestConversationServiceSave:

    def test_raises_error_when_no_user_in_token(self, mock_mongo_db):
        """Test validation: user ID required"""
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService()
        mock_llm = Mock()

        with pytest.raises(ValueError, match="User ID not found"):
            service.save_conversation(
                conversation_id=None,
                question="Test?",
                response="Answer",
                thought="",
                sources=[],
                tool_calls=[],
                llm=mock_llm,
                model_id="gpt-4",
                decoded_token={},  # No 'sub' key
            )

    def test_truncates_long_source_text(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings
        from bson import ObjectId

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        mock_llm = Mock()
        mock_llm.gen.return_value = "Test Summary"

        long_text = "x" * 2000
        sources = [{"text": long_text, "title": "Doc"}]

        conv_id = service.save_conversation(
            conversation_id=None,
            question="Question",
            response="Response",
            thought="",
            sources=sources,
            tool_calls=[],
            llm=mock_llm,
            model_id="gpt-4",
            decoded_token={"sub": "user_123"},
        )

        saved_conv = collection.find_one({"_id": ObjectId(conv_id)})
        saved_source_text = saved_conv["queries"][0]["sources"][0]["text"]

        assert len(saved_source_text) == 1000
        assert saved_source_text == "x" * 1000

    def test_creates_new_conversation_with_summary(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings
        from bson import ObjectId

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        mock_llm = Mock()
        mock_llm.gen.return_value = "Python Basics"

        conv_id = service.save_conversation(
            conversation_id=None,
            question="What is Python?",
            response="Python is a programming language",
            thought="",
            sources=[],
            tool_calls=[],
            llm=mock_llm,
            model_id="gpt-4",
            decoded_token={"sub": "user_123"},
        )

        assert conv_id is not None
        saved_conv = collection.find_one({"_id": ObjectId(conv_id)})
        assert saved_conv["name"] == "Python Basics"
        assert saved_conv["user"] == "user_123"
        assert len(saved_conv["queries"]) == 1
        assert saved_conv["queries"][0]["prompt"] == "What is Python?"

    def test_appends_to_existing_conversation(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings
        from bson import ObjectId

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        existing_conv_id = ObjectId()
        collection.insert_one(
            {
                "_id": existing_conv_id,
                "user": "user_123",
                "name": "Old Conv",
                "queries": [{"prompt": "Q1", "response": "A1"}],
            }
        )

        mock_llm = Mock()

        result = service.save_conversation(
            conversation_id=str(existing_conv_id),
            question="Q2",
            response="A2",
            thought="",
            sources=[],
            tool_calls=[],
            llm=mock_llm,
            model_id="gpt-4",
            decoded_token={"sub": "user_123"},
        )

        assert result == str(existing_conv_id)

    def test_prevents_unauthorized_conversation_update(self, mock_mongo_db):
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )
        from application.core.settings import settings

        service = ConversationService()
        collection = mock_mongo_db[settings.MONGO_DB_NAME]["conversations"]

        conv_id = ObjectId()
        collection.insert_one({"_id": conv_id, "user": "owner_123", "queries": []})

        mock_llm = Mock()

        with pytest.raises(ValueError, match="not found or unauthorized"):
            service.save_conversation(
                conversation_id=str(conv_id),
                question="Hack",
                response="Attempt",
                thought="",
                sources=[],
                tool_calls=[],
                llm=mock_llm,
                model_id="gpt-4",
                decoded_token={"sub": "hacker_456"},
            )
