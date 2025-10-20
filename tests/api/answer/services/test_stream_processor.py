import pytest
from bson import ObjectId


@pytest.mark.unit
class TestGetPromptFunction:

    def test_loads_custom_prompt_from_database(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import get_prompt
        from application.core.settings import settings

        prompts_collection = mock_mongo_db[settings.MONGO_DB_NAME]["prompts"]
        prompt_id = ObjectId()

        prompts_collection.insert_one(
            {
                "_id": prompt_id,
                "content": "Custom prompt from database",
                "user": "user_123",
            }
        )

        result = get_prompt(str(prompt_id), prompts_collection)
        assert result == "Custom prompt from database"

    def test_raises_error_for_invalid_prompt_id(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import get_prompt
        from application.core.settings import settings

        prompts_collection = mock_mongo_db[settings.MONGO_DB_NAME]["prompts"]

        with pytest.raises(ValueError, match="Invalid prompt ID"):
            get_prompt(str(ObjectId()), prompts_collection)

    def test_raises_error_for_malformed_id(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import get_prompt
        from application.core.settings import settings

        prompts_collection = mock_mongo_db[settings.MONGO_DB_NAME]["prompts"]

        with pytest.raises(ValueError, match="Invalid prompt ID"):
            get_prompt("not_a_valid_id", prompts_collection)


@pytest.mark.unit
class TestStreamProcessorInitialization:

    def test_initializes_with_decoded_token(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {
            "question": "What is Python?",
            "conversation_id": str(ObjectId()),
        }
        decoded_token = {"sub": "user_123", "email": "test@example.com"}

        processor = StreamProcessor(request_data, decoded_token)

        assert processor.data == request_data
        assert processor.decoded_token == decoded_token
        assert processor.initial_user_id == "user_123"
        assert processor.conversation_id == request_data["conversation_id"]

    def test_initializes_without_token(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test question"}

        processor = StreamProcessor(request_data, None)

        assert processor.decoded_token is None
        assert processor.initial_user_id is None
        assert processor.data == request_data

    def test_initializes_default_attributes(self, mock_mongo_db):
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

    def test_extracts_conversation_id_from_request(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        conv_id = str(ObjectId())
        request_data = {"question": "Test", "conversation_id": conv_id}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.conversation_id == conv_id


@pytest.mark.unit
class TestStreamProcessorHistoryLoading:

    def test_loads_history_from_existing_conversation(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        conversations_collection = mock_mongo_db[settings.MONGO_DB_NAME][
            "conversations"
        ]
        conv_id = ObjectId()

        conversations_collection.insert_one(
            {
                "_id": conv_id,
                "user": "user_123",
                "name": "Test Conv",
                "queries": [
                    {"prompt": "What is Python?", "response": "Python is a language"},
                    {"prompt": "Tell me more", "response": "Python is versatile"},
                ],
            }
        )

        request_data = {
            "question": "How to install it?",
            "conversation_id": str(conv_id),
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._load_conversation_history()

        assert len(processor.history) == 2
        assert processor.history[0]["prompt"] == "What is Python?"
        assert processor.history[1]["response"] == "Python is versatile"

    def test_raises_error_for_unauthorized_conversation(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        conversations_collection = mock_mongo_db[settings.MONGO_DB_NAME][
            "conversations"
        ]
        conv_id = ObjectId()

        conversations_collection.insert_one(
            {
                "_id": conv_id,
                "user": "owner_123",
                "name": "Private Conv",
                "queries": [],
            }
        )

        request_data = {"question": "Hack attempt", "conversation_id": str(conv_id)}

        processor = StreamProcessor(request_data, {"sub": "hacker_456"})

        with pytest.raises(ValueError, match="Conversation not found or unauthorized"):
            processor._load_conversation_history()

    def test_uses_request_history_when_no_conversation_id(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {
            "question": "What is Python?",
            "history": [{"prompt": "Hello", "response": "Hi there!"}],
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.conversation_id is None


@pytest.mark.unit
class TestStreamProcessorAgentConfiguration:

    def test_configures_agent_from_valid_api_key(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
        agent_id = ObjectId()

        agents_collection.insert_one(
            {
                "_id": agent_id,
                "key": "test_api_key_123",
                "endpoint": "openai",
                "model": "gpt-4",
                "prompt_id": "default",
                "user": "user_123",
            }
        )

        request_data = {"question": "Test", "api_key": "test_api_key_123"}

        processor = StreamProcessor(request_data, None)

        try:
            processor._configure_agent()
            assert processor.agent_config is not None
        except Exception as e:
            assert "Invalid API Key" in str(e)

    def test_uses_default_config_without_api_key(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test"}

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._configure_agent()

        assert isinstance(processor.agent_config, dict)


@pytest.mark.unit
class TestStreamProcessorAttachments:

    def test_processes_attachments_from_request(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        attachments_collection = mock_mongo_db[settings.MONGO_DB_NAME]["attachments"]
        att_id = ObjectId()

        attachments_collection.insert_one(
            {
                "_id": att_id,
                "filename": "document.pdf",
                "content": "Document content",
                "user": "user_123",
            }
        )

        request_data = {"question": "Analyze this", "attachments": [str(att_id)]}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.data.get("attachments") == [str(att_id)]

    def test_handles_empty_attachments(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Simple question"}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.attachments == []
        assert (
            "attachments" not in processor.data
            or processor.data.get("attachments") is None
        )
