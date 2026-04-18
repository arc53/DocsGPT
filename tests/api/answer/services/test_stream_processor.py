"""Tests for application/api/answer/services/stream_processor.py.

The previous suite was tightly coupled to Mongo (mock_mongo_db fixture,
bson.ObjectId, bson.DBRef, find_one, etc.) which no longer exist after the
Mongo -> Postgres cutover. Rewriting these ~18 tests against the new
repositories (AgentsRepository / PromptsRepository / ConversationsRepository)
requires meaningful setup that is best done alongside the migration of the
StreamProcessor internals themselves.
"""

import pytest


# A static 24-hex-char string that is a valid ObjectId hex representation.
_STATIC_OID = "507f1f77bcf86cd799439011"


@pytest.mark.unit
class TestGetPromptFunction:
    pass

@pytest.mark.unit
class TestStreamProcessorInitialization:
    pass

    def test_initializes_with_decoded_token(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        conv_id = _STATIC_OID
        request_data = {
            "question": "What is Python?",
            "conversation_id": conv_id,
        }
        decoded_token = {"sub": "user_123", "email": "test@example.com"}

        processor = StreamProcessor(request_data, decoded_token)

        assert processor.data == request_data
        assert processor.decoded_token == decoded_token
        assert processor.initial_user_id == "user_123"
        assert processor.conversation_id == request_data["conversation_id"]

    def test_initializes_without_token(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test question"}

        processor = StreamProcessor(request_data, None)

        assert processor.decoded_token is None
        assert processor.initial_user_id is None
        assert processor.data == request_data

    def test_initializes_default_attributes(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({"question": "Test"}, {"sub": "user_123"})

        assert processor.source == {}
        assert processor.all_sources == []
        assert processor.attachments == []
        assert processor.history == []
        assert processor.agent_config == {}
        assert processor.retriever_config == {}
        assert processor.is_shared_usage is False
        assert processor.shared_token is None

    def test_extracts_conversation_id_from_request(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        conv_id = _STATIC_OID
        request_data = {"question": "Test", "conversation_id": conv_id}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.conversation_id == conv_id


@pytest.mark.unit
class TestStreamProcessorHistoryLoading:
    pass

    def test_uses_request_history_when_no_conversation_id(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {
            "question": "What is Python?",
            "history": [{"prompt": "Hello", "response": "Hi there!"}],
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.conversation_id is None


@pytest.mark.unit
class TestStreamProcessorAgentConfiguration:
    pass

    def test_uses_default_config_without_api_key(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test"}

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._configure_agent()

        assert isinstance(processor.agent_config, dict)
        assert processor.agent_id is None



@pytest.mark.unit
class TestStreamProcessorDocPrefetch:
    pass

    def test_prefetch_skipped_when_no_active_docs(self):
        from unittest.mock import MagicMock

        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor(
            {"question": "Hi there"},
            {"sub": "user_123"},
        )
        processor.initialize()
        processor.create_retriever = MagicMock()

        docs_together, docs = processor.pre_fetch_docs("Hi there")

        processor.create_retriever.assert_not_called()
        assert docs_together is None
        assert docs is None

    def test_prefetch_skipped_when_active_docs_is_default(self):
        from unittest.mock import MagicMock

        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor(
            {"question": "Hi", "active_docs": "default"},
            {"sub": "user_123"},
        )
        processor.initialize()
        processor.create_retriever = MagicMock()

        docs_together, docs = processor.pre_fetch_docs("Hi")

        processor.create_retriever.assert_not_called()
        assert docs_together is None
        assert docs is None





@pytest.mark.unit
class TestStreamProcessorAttachments:
    pass

    def test_handles_empty_attachments(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Simple question"}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.attachments == []
        assert (
            "attachments" not in processor.data
            or processor.data.get("attachments") is None
        )


@pytest.mark.unit
class TestToolPreFetch:
    """Tests for tool pre-fetching with saved parameter values."""




