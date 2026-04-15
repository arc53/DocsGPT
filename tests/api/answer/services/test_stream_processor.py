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

    def test_loads_custom_prompt_from_database(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import get_prompt
        from application.core.settings import settings

        prompts_collection = mock_mongo_db[settings.MONGO_DB_NAME]["prompts"]

        result_meta = prompts_collection.insert_one(
            {
                "content": "Custom prompt from database",
                "user": "user_123",
            }
        )
        prompt_id = str(result_meta.inserted_id)

        result = get_prompt(prompt_id, prompts_collection)
        assert result == "Custom prompt from database"

    def test_raises_error_for_invalid_prompt_id(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import get_prompt
        from application.core.settings import settings

        prompts_collection = mock_mongo_db[settings.MONGO_DB_NAME]["prompts"]

        with pytest.raises(ValueError, match="Invalid prompt ID"):
            get_prompt(_STATIC_OID, prompts_collection)

    def test_raises_error_for_malformed_id(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import get_prompt
        from application.core.settings import settings

        prompts_collection = mock_mongo_db[settings.MONGO_DB_NAME]["prompts"]

        with pytest.raises(ValueError, match="Invalid prompt ID"):
            get_prompt("not_a_valid_id", prompts_collection)


@pytest.mark.unit
class TestStreamProcessorInitialization:

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

    def test_loads_history_from_existing_conversation(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        conversations_collection = mock_mongo_db[settings.MONGO_DB_NAME][
            "conversations"
        ]

        result = conversations_collection.insert_one(
            {
                "user": "user_123",
                "name": "Test Conv",
                "queries": [
                    {"prompt": "What is Python?", "response": "Python is a language"},
                    {"prompt": "Tell me more", "response": "Python is versatile"},
                ],
            }
        )
        conv_id = str(result.inserted_id)

        request_data = {
            "question": "How to install it?",
            "conversation_id": conv_id,
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

        result = conversations_collection.insert_one(
            {
                "user": "owner_123",
                "name": "Private Conv",
                "queries": [],
            }
        )
        conv_id = str(result.inserted_id)

        request_data = {"question": "Hack attempt", "conversation_id": conv_id}

        processor = StreamProcessor(request_data, {"sub": "hacker_456"})

        with pytest.raises(ValueError, match="Conversation not found or unauthorized"):
            processor._load_conversation_history()

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

    def test_configures_agent_from_valid_api_key(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]

        result = agents_collection.insert_one(
            {
                "key": "test_api_key_123",
                "endpoint": "openai",
                "model": "gpt-4",
                "prompt_id": "default",
                "user": "user_123",
            }
        )
        agent_id = str(result.inserted_id)

        request_data = {"question": "Test", "api_key": "test_api_key_123"}

        processor = StreamProcessor(request_data, None)

        try:
            processor._configure_agent()
            assert processor.agent_config is not None
            assert processor.agent_id == agent_id
        except Exception as e:
            assert "Invalid API Key" in str(e)

    def test_uses_default_config_without_api_key(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test"}

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._configure_agent()

        assert isinstance(processor.agent_config, dict)
        assert processor.agent_id is None

    def test_conversation_agent_overrides_request_active_docs(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor, DBRef
        from application.core.settings import settings

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]
        sources_collection = db["sources"]
        conversations_collection = db["conversations"]

        agent_src_result = sources_collection.insert_one(
            {"name": "Agent source", "retriever": "classic"}
        )
        req_src_result = sources_collection.insert_one(
            {"name": "Request source", "retriever": "hybrid"}
        )
        request_source_id = str(req_src_result.inserted_id)

        agent_result = agents_collection.insert_one(
            {
                "key": "agent_key_2",
                "user": "user_123",
                "prompt_id": "default",
                "agent_type": "classic",
                "source": DBRef("sources", agent_src_result.inserted_id),
            }
        )
        agent_id = str(agent_result.inserted_id)

        conv_result = conversations_collection.insert_one(
            {
                "user": "user_123",
                "agent_id": agent_id,
                "queries": [],
            }
        )
        conversation_id = str(conv_result.inserted_id)

        processor = StreamProcessor(
            {
                "question": "Test",
                "conversation_id": conversation_id,
                "active_docs": request_source_id,
            },
            {"sub": "user_123"},
        )

        processor._configure_agent()
        processor._configure_source()

        assert processor.agent_id == agent_id


@pytest.mark.unit
class TestStreamProcessorDocPrefetch:

    def test_prefetch_not_skipped_for_agent_when_isNoneDoc_true(self, mock_mongo_db):
        from unittest.mock import MagicMock

        from application.api.answer.services.stream_processor import StreamProcessor, DBRef
        from application.core.settings import settings

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]
        sources_collection = db["sources"]

        src_result = sources_collection.insert_one(
            {"name": "Agent source", "retriever": "classic"}
        )

        agent_result = agents_collection.insert_one(
            {
                "key": "agent_prefetch_key",
                "user": "user_123",
                "prompt_id": "default",
                "agent_type": "classic",
                "source": DBRef("sources", src_result.inserted_id),
            }
        )
        agent_id = str(agent_result.inserted_id)

        processor = StreamProcessor(
            {
                "question": "Summarize context",
                "agent_id": agent_id,
                "isNoneDoc": True,
            },
            {"sub": "user_123"},
        )
        processor.initialize()

        mock_retriever = MagicMock()
        mock_retriever.chunks = 2
        mock_retriever.doc_token_limit = 50000
        mock_retriever.search.return_value = [
            {"text": "Agent doc content", "source": "agent.pdf"}
        ]
        processor.create_retriever = MagicMock(return_value=mock_retriever)

        docs_together, docs = processor.pre_fetch_docs("Summarize context")

        processor.create_retriever.assert_called_once()
        assert docs is not None
        assert docs_together is not None
        assert "Agent doc content" in docs_together

    def test_configure_source_treats_default_string_as_no_docs(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]

        agents_collection.insert_one(
            {
                "key": "agent_default_source_key",
                "user": "user_123",
                "prompt_id": "default",
                "agent_type": "classic",
                "source": "default",
            }
        )

        processor = StreamProcessor(
            {"question": "Hi", "api_key": "agent_default_source_key"},
            None,
        )
        processor._configure_agent()
        processor._configure_source()

        assert processor.source == {}
        assert processor.all_sources == []

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

    def test_agent_retriever_and_chunks_propagate_to_retriever_config(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor, DBRef
        from application.core.settings import settings

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]
        src_result = db["sources"].insert_one(
            {"name": "src", "retriever": "hybrid", "chunks": 5}
        )

        agents_collection.insert_one(
            {
                "key": "agent_ret_key",
                "user": "user_123",
                "prompt_id": "default",
                "agent_type": "classic",
                "retriever": "hybrid",
                "chunks": 5,
                "source": DBRef("sources", src_result.inserted_id),
            }
        )

        processor = StreamProcessor(
            {"question": "Test", "api_key": "agent_ret_key"},
            None,
        )
        processor.initialize()

        assert processor.retriever_config["retriever_name"] == "hybrid"
        assert processor.retriever_config["chunks"] == 5

    def test_request_retriever_and_chunks_override_agent_config(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]

        agents_collection.insert_one(
            {
                "key": "agent_override_key",
                "user": "user_123",
                "prompt_id": "default",
                "agent_type": "classic",
                "retriever": "hybrid",
                "chunks": 5,
            }
        )

        processor = StreamProcessor(
            {
                "question": "Test",
                "api_key": "agent_override_key",
                "retriever": "classic",
                "chunks": 7,
            },
            None,
        )
        processor.initialize()

        assert processor.retriever_config["retriever_name"] == "classic"
        assert processor.retriever_config["chunks"] == 7

    def test_agent_data_fetched_once_per_request(self, mock_mongo_db):
        from unittest.mock import patch

        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]

        agents_collection.insert_one(
            {
                "key": "agent_once_key",
                "user": "user_123",
                "prompt_id": "default",
                "agent_type": "classic",
            }
        )

        processor = StreamProcessor(
            {"question": "Test", "api_key": "agent_once_key"},
            None,
        )

        with patch.object(
            processor, "_get_data_from_api_key", wraps=processor._get_data_from_api_key
        ) as spy:
            processor.initialize()
            assert spy.call_count == 1


@pytest.mark.unit
class TestStreamProcessorAttachments:

    def test_processes_attachments_from_request(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        attachments_collection = mock_mongo_db[settings.MONGO_DB_NAME]["attachments"]
        result = attachments_collection.insert_one(
            {
                "filename": "document.pdf",
                "content": "Document content",
                "user": "user_123",
            }
        )
        att_id = str(result.inserted_id)

        request_data = {"question": "Analyze this", "attachments": [att_id]}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.data.get("attachments") == [att_id]

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

    def test_cryptoprice_prefetch_with_saved_parameters(self, mock_mongo_db):
        """Test that cryptoprice tool is pre-fetched with saved parameter values."""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        result = tools_collection.insert_one(
            {
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
                                    "value": "BTC",
                                },
                                "currency": {
                                    "type": "string",
                                    "description": "Currency for price",
                                    "value": "USD",
                                },
                            },
                            "required": ["symbol", "currency"],
                        },
                    }
                ],
                "config": {"token": ""},
            }
        )
        tool_id = str(result.inserted_id)

        request_data = {
            "question": "What is the price of Bitcoin?",
            "tools": [tool_id],
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._required_tool_actions = {"cryptoprice": {"cryptoprice_get"}}

        with patch("application.agents.tools.tool_manager.ToolManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "cryptoprice_get",
                    "description": "Get cryptocurrency price",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Crypto symbol"},
                            "currency": {"type": "string", "description": "Currency for price"},
                        },
                        "required": ["symbol", "currency"],
                    },
                }
            ]

            mock_tool.execute_action.return_value = {
                "status_code": 200,
                "price": 45000.50,
                "message": "Price of BTC in USD retrieved successfully.",
            }

            tools_data = processor.pre_fetch_tools()

            assert mock_tool.execute_action.called

            call_args = mock_tool.execute_action.call_args
            assert call_args is not None
            assert call_args[0][0] == "cryptoprice_get"

            kwargs = call_args[1]
            assert kwargs.get("symbol") == "BTC"
            assert kwargs.get("currency") == "USD"

            assert "cryptoprice" in tools_data
            assert "cryptoprice_get" in tools_data["cryptoprice"]
            assert tools_data["cryptoprice"]["cryptoprice_get"]["price"] == 45000.50

    def test_prefetch_with_missing_saved_values_uses_defaults(self, mock_mongo_db):
        """Test that pre-fetch falls back to defaults when saved values are missing."""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        result = tools_collection.insert_one(
            {
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
                                    "default": "ETH",
                                },
                                "currency": {
                                    "type": "string",
                                    "description": "Currency",
                                    "default": "EUR",
                                },
                            },
                            "required": ["symbol", "currency"],
                        },
                    }
                ],
                "config": {},
            }
        )
        tool_id = str(result.inserted_id)

        request_data = {
            "question": "Crypto price?",
            "tools": [tool_id],
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._required_tool_actions = {"cryptoprice": {"cryptoprice_get"}}

        with patch("application.agents.tools.tool_manager.ToolManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "cryptoprice_get",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "default": "ETH"},
                            "currency": {"type": "string", "default": "EUR"},
                        },
                    },
                }
            ]

            mock_tool.execute_action.return_value = {
                "status_code": 200,
                "price": 2500.00,
            }

            processor.pre_fetch_tools()

            call_args = mock_tool.execute_action.call_args
            if call_args:
                kwargs = call_args[1]
                assert kwargs.get("symbol") in ["ETH", None]
                assert kwargs.get("currency") in ["EUR", None]

    def test_prefetch_with_tool_id_reference(self, mock_mongo_db):
        """Test that tools can be referenced by ID in templates."""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        result = tools_collection.insert_one(
            {
                "name": "memory",
                "user": "user_123",
                "status": True,
                "actions": [
                    {
                        "name": "memory_ls",
                        "description": "List files",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
                "config": {},
            }
        )
        tool_id = str(result.inserted_id)

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user_123"})

        processor._required_tool_actions = {
            tool_id: {"memory_ls"}
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {"name": "memory_ls", "description": "List files", "parameters": {"properties": {}}}
            ]
            mock_tool.execute_action.return_value = "Directory: /\n- file.txt"

            result_data = processor.pre_fetch_tools()

            assert result_data is not None
            assert "memory" in result_data
            assert tool_id in result_data
            assert result_data["memory"] == result_data[tool_id]
            assert "memory_ls" in result_data[tool_id]

    def test_prefetch_with_multiple_same_name_tools(self, mock_mongo_db):
        """Test that multiple tools with the same name can be distinguished by ID."""
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings
        from unittest.mock import patch, MagicMock

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]

        tools_collection.insert_one(
            {
                "name": "memory",
                "user": "user_123",
                "status": True,
                "actions": [{"name": "memory_ls", "parameters": {"properties": {}}}],
                "config": {"path": "/home"},
            }
        )
        r2 = tools_collection.insert_one(
            {
                "name": "memory",
                "user": "user_123",
                "status": True,
                "actions": [{"name": "memory_ls", "parameters": {"properties": {}}}],
                "config": {"path": "/work"},
            }
        )
        tool_id_2 = str(r2.inserted_id)

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user_123"})

        processor._required_tool_actions = {
            tool_id_2: {"memory_ls"}
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {"name": "memory_ls", "parameters": {"properties": {}}}
            ]
            mock_tool.execute_action.return_value = "Work directory"

            result_data = processor.pre_fetch_tools()

            assert result_data is not None
            assert tool_id_2 in result_data
            assert "memory" in result_data
