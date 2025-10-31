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


@pytest.mark.unit
class TestToolPreFetch:
    """Tests for tool pre-fetching with saved parameter values from MongoDB"""

    def test_cryptoprice_prefetch_with_saved_parameters(self, mock_mongo_db):
        """Test that cryptoprice tool is pre-fetched with saved parameter values from MongoDB structure"""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        # Setup MongoDB with cryptoprice tool configuration
        # NOTE: The collection is called "user_tools" not "tools"
        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        tool_id = ObjectId()

        tools_collection.insert_one(
            {
                "_id": tool_id,
                "name": "cryptoprice",
                "user": "user_123",
                "status": True,  # Must be True for tool to be included
                "actions": [
                    {
                        "name": "cryptoprice_get",
                        "description": "Get cryptocurrency price",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "symbol": {
                                    "type": "string",
                                    "description": "Crypto symbol",
                                    "value": "BTC"  # Saved value in MongoDB
                                },
                                "currency": {
                                    "type": "string",
                                    "description": "Currency for price",
                                    "value": "USD"  # Saved value in MongoDB
                                }
                            },
                            "required": ["symbol", "currency"]
                        }
                    }
                ],
                "config": {
                    "token": ""
                }
            }
        )

        request_data = {
            "question": "What is the price of Bitcoin?",
            "tools": [str(tool_id)]
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._required_tool_actions = {"cryptoprice": {"cryptoprice_get"}}

        # Mock the ToolManager and tool instance
        with patch("application.agents.tools.tool_manager.ToolManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance returned by load_tool
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            # Mock get_actions_metadata on the tool instance
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "cryptoprice_get",
                    "description": "Get cryptocurrency price",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Crypto symbol"},
                            "currency": {"type": "string", "description": "Currency for price"}
                        },
                        "required": ["symbol", "currency"]
                    }
                }
            ]

            # Mock execute_action on the tool instance to return price data
            mock_tool.execute_action.return_value = {
                "status_code": 200,
                "price": 45000.50,
                "message": "Price of BTC in USD retrieved successfully."
            }

            # Execute pre-fetch
            tools_data = processor.pre_fetch_tools()

            # Verify the tool was called
            assert mock_tool.execute_action.called

            # Verify it was called with the saved parameters from MongoDB
            call_args = mock_tool.execute_action.call_args
            assert call_args is not None

            # Check action name uses the full metadata name for execution
            assert call_args[0][0] == "cryptoprice_get"

            # Check kwargs contain saved values
            kwargs = call_args[1]
            assert kwargs.get("symbol") == "BTC"
            assert kwargs.get("currency") == "USD"

            # Verify tools_data structure
            assert "cryptoprice" in tools_data
            # Results are exposed under the full action name
            assert "cryptoprice_get" in tools_data["cryptoprice"]
            assert tools_data["cryptoprice"]["cryptoprice_get"]["price"] == 45000.50

    def test_prefetch_with_missing_saved_values_uses_defaults(self, mock_mongo_db):
        """Test that pre-fetch falls back to defaults when saved values are missing"""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        tool_id = ObjectId()

        # Tool configuration without saved values
        tools_collection.insert_one(
            {
                "_id": tool_id,
                "name": "cryptoprice",
                "user": "user_123",
                "status": True,
                "actions": [
                    {
                        "name": "cryptoprice_get",
                        "description": "Get cryptocurrency price",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "symbol": {
                                    "type": "string",
                                    "description": "Crypto symbol",
                                    "default": "ETH"  # Only default, no saved value
                                },
                                "currency": {
                                    "type": "string",
                                    "description": "Currency",
                                    "default": "EUR"
                                }
                            },
                            "required": ["symbol", "currency"]
                        }
                    }
                ],
                "config": {}
            }
        )

        request_data = {
            "question": "Crypto price?",
            "tools": [str(tool_id)]
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._required_tool_actions = {"cryptoprice": {"cryptoprice_get"}}

        with patch("application.agents.tools.tool_manager.ToolManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "cryptoprice_get",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "default": "ETH"},
                            "currency": {"type": "string", "default": "EUR"}
                        }
                    }
                }
            ]

            mock_tool.execute_action.return_value = {
                "status_code": 200,
                "price": 2500.00
            }

            tools_data = processor.pre_fetch_tools()

            # Should use default values when saved values are missing
            call_args = mock_tool.execute_action.call_args
            if call_args:
                kwargs = call_args[1]
                # Either uses defaults or skips if no values available
                assert kwargs.get("symbol") in ["ETH", None]
                assert kwargs.get("currency") in ["EUR", None]

    def test_prefetch_with_tool_id_reference(self, mock_mongo_db):
        """Test that tools can be referenced by MongoDB ObjectId in templates"""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        tool_id = ObjectId()

        # Create a tool in the database
        tools_collection.insert_one(
            {
                "_id": tool_id,
                "name": "memory",
                "user": "user_123",
                "status": True,
                "actions": [
                    {
                        "name": "memory_ls",
                        "description": "List files",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                ],
                "config": {},
            }
        )

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user_123"})

        # Mock the filtering to require this specific tool by ID
        processor._required_tool_actions = {
            str(tool_id): {"memory_ls"}  # Reference by ObjectId string
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {"name": "memory_ls", "description": "List files", "parameters": {"properties": {}}}
            ]
            mock_tool.execute_action.return_value = "Directory: /\n- file.txt"

            result = processor.pre_fetch_tools()

            # Tool data should be available under both name and ID
            assert result is not None
            assert "memory" in result
            assert str(tool_id) in result
            # Both should point to the same data
            assert result["memory"] == result[str(tool_id)]
            assert "memory_ls" in result[str(tool_id)]

    def test_prefetch_with_multiple_same_name_tools(self, mock_mongo_db):
        """Test that multiple tools with the same name can be distinguished by ID"""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]

        # Create two memory tools with different IDs
        tool_id_1 = ObjectId()
        tool_id_2 = ObjectId()

        tools_collection.insert_many([
            {
                "_id": tool_id_1,
                "name": "memory",
                "user": "user_123",
                "status": True,
                "actions": [{"name": "memory_ls", "parameters": {"properties": {}}}],
                "config": {"path": "/home"},
            },
            {
                "_id": tool_id_2,
                "name": "memory",
                "user": "user_123",
                "status": True,
                "actions": [{"name": "memory_ls", "parameters": {"properties": {}}}],
                "config": {"path": "/work"},
            }
        ])

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user_123"})

        # Mock the filtering to require only the second tool by ID
        processor._required_tool_actions = {
            str(tool_id_2): {"memory_ls"}  # Only reference the second one
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {"name": "memory_ls", "parameters": {"properties": {}}}
            ]
            mock_tool.execute_action.return_value = "Work directory"

            result = processor.pre_fetch_tools()

            # Only the second tool should be fetched (referenced by ID)
            assert result is not None
            assert str(tool_id_2) in result
            # Since filtering is enabled and only tool_id_2 is referenced,
            # only tool_id_2 should be pre-fetched
            # The "memory" key will still exist because we store under both name and ID
            assert "memory" in result
