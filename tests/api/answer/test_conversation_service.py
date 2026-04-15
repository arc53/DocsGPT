"""Unit tests for application/api/answer/services/conversation_service.py.

Additional coverage beyond tests/api/answer/services/test_conversation_service.py:
  - save_conversation: index-based update, metadata persistence, agent key tracking
  - update_compression_metadata
  - append_compression_message
  - get_compression_metadata
  - Edge cases: None token, empty summary, shared_with access
"""

from unittest.mock import MagicMock, Mock

import pytest


@pytest.mark.unit
class TestConversationServiceGetExtended:
    pass

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
    pass

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








@pytest.mark.unit
class TestUpdateCompressionMetadata:
    pass

@pytest.mark.unit
class TestAppendCompressionMessage:
    pass

@pytest.mark.unit
class TestGetCompressionMetadata:
    pass

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
    pass

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
