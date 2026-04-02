"""Tests for application/api/answer/services/stream_processor.py — get_prompt and helpers.

Extended coverage for StreamProcessor including:
  - get_prompt: all presets and DB fallback
  - StreamProcessor init, _resolve_agent_id, _get_prompt_content
  - _get_required_tool_actions
  - _get_attachments_content: valid, invalid, empty
  - _configure_retriever
  - _validate_and_set_model
  - _get_agent_key
  - _get_data_from_api_key
  - _configure_source
  - pre_fetch_docs
"""

from unittest.mock import MagicMock, patch

import pytest

from application.api.answer.services.stream_processor import get_prompt


class TestGetPrompt:

    @pytest.mark.unit
    def test_default_preset(self):
        prompt = get_prompt("default")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    @pytest.mark.unit
    def test_creative_preset(self):
        prompt = get_prompt("creative")
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_strict_preset(self):
        prompt = get_prompt("strict")
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_reduce_preset(self):
        prompt = get_prompt("reduce")
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_agentic_default_preset(self):
        prompt = get_prompt("agentic_default")
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_agentic_creative_preset(self):
        prompt = get_prompt("agentic_creative")
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_agentic_strict_preset(self):
        prompt = get_prompt("agentic_strict")
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_mongo_prompt_by_id(self):
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {"_id": "abc", "content": "Custom prompt"}
        prompt = get_prompt("507f1f77bcf86cd799439011", prompts_collection=mock_collection)
        assert prompt == "Custom prompt"

    @pytest.mark.unit
    def test_mongo_prompt_not_found_raises(self):
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        with pytest.raises(ValueError, match="Invalid prompt ID"):
            get_prompt("507f1f77bcf86cd799439011", prompts_collection=mock_collection)

    @pytest.mark.unit
    def test_invalid_id_raises(self):
        mock_collection = MagicMock()
        mock_collection.find_one.side_effect = Exception("bad id")
        with pytest.raises(ValueError, match="Invalid prompt ID"):
            get_prompt("not-an-objectid", prompts_collection=mock_collection)

    @pytest.mark.unit
    def test_mongo_fallback_when_no_collection(self):
        """When no collection passed, it reads from MongoDB."""
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {"content": "From DB"}
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"
            MockMongo.get_client.return_value = {"test_db": mock_db}
            prompt = get_prompt("507f1f77bcf86cd799439011")
        assert prompt == "From DB"


class TestStreamProcessorInit:

    @pytest.mark.unit
    def test_init_sets_attributes(self):
        mock_db = MagicMock()
        mock_client = {"docsgpt": mock_db}

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = mock_client

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1", "agent_id": "a1"},
                decoded_token={"sub": "user1"},
            )
        assert sp.conversation_id == "conv1"
        assert sp.initial_user_id == "user1"
        assert sp.agent_id == "a1"
        assert sp.history == []
        assert sp.attachments == []

    @pytest.mark.unit
    def test_init_no_token(self):
        mock_db = MagicMock()
        mock_client = {"docsgpt": mock_db}

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = mock_client

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token=None)
        assert sp.initial_user_id is None

    @pytest.mark.unit
    def test_init_default_model_and_config(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        assert sp.model_id is None
        assert sp.is_shared_usage is False
        assert sp.shared_token is None
        assert sp.compressed_summary is None
        assert sp.compressed_summary_tokens == 0


class TestGetAttachmentsContent:

    @pytest.mark.unit
    def test_empty_ids_returns_empty(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        result = sp._get_attachments_content([], "u")
        assert result == []

    @pytest.mark.unit
    def test_returns_matching_attachments(self):
        mock_db = MagicMock()
        mock_attachments = MagicMock()
        mock_attachments.find_one.return_value = {"_id": "att1", "content": "data"}
        mock_db.__getitem__ = MagicMock(return_value=mock_attachments)

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        result = sp._get_attachments_content(["507f1f77bcf86cd799439011"], "u")
        assert len(result) == 1

    @pytest.mark.unit
    def test_invalid_attachment_id_continues(self):
        mock_db = MagicMock()
        mock_attachments = MagicMock()
        mock_attachments.find_one.side_effect = Exception("bad id")
        mock_db.__getitem__ = MagicMock(return_value=mock_attachments)

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        result = sp._get_attachments_content(["bad"], "u")
        assert result == []

    @pytest.mark.unit
    def test_none_ids_returns_empty(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        result = sp._get_attachments_content(None, "u")
        assert result == []


class TestResolveAgentId:

    @pytest.mark.unit
    def test_from_request_data(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"agent_id": "agent_123"},
                decoded_token={"sub": "u"},
            )
        assert sp._resolve_agent_id() == "agent_123"

    @pytest.mark.unit
    def test_no_agent_no_conversation(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        assert sp._resolve_agent_id() is None

    @pytest.mark.unit
    def test_from_conversation(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1"},
                decoded_token={"sub": "u"},
            )
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.return_value = {"agent_id": "from_conv"}
        assert sp._resolve_agent_id() == "from_conv"

    @pytest.mark.unit
    def test_conversation_not_found(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1"},
                decoded_token={"sub": "u"},
            )
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.return_value = None
        assert sp._resolve_agent_id() is None

    @pytest.mark.unit
    def test_conversation_lookup_exception(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1"},
                decoded_token={"sub": "u"},
            )
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.side_effect = Exception("db error")
        assert sp._resolve_agent_id() is None

    @pytest.mark.unit
    def test_conversation_without_agent_id(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1"},
                decoded_token={"sub": "u"},
            )
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.return_value = {"name": "test conv"}
        assert sp._resolve_agent_id() is None


class TestGetPromptContent:

    @pytest.mark.unit
    def test_caches_result(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {"prompt_id": "default"}
        result1 = sp._get_prompt_content()
        result2 = sp._get_prompt_content()
        assert result1 == result2
        assert result1 is not None

    @pytest.mark.unit
    def test_no_prompt_id(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {}
        assert sp._get_prompt_content() is None

    @pytest.mark.unit
    def test_invalid_prompt_id_returns_none(self):
        mock_db = MagicMock()
        mock_prompts = MagicMock()
        mock_prompts.find_one.side_effect = Exception("bad")
        mock_db.__getitem__ = MagicMock(return_value=mock_prompts)

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {"prompt_id": "bad_id"}
        assert sp._get_prompt_content() is None

    @pytest.mark.unit
    def test_agent_config_not_dict(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = "not_a_dict"
        assert sp._get_prompt_content() is None


class TestGetRequiredToolActions:

    @pytest.mark.unit
    def test_no_prompt_returns_none(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {}
        assert sp._get_required_tool_actions() is None

    @pytest.mark.unit
    def test_no_template_syntax_returns_empty(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {"prompt_id": "default"}
        sp._prompt_content = "No template syntax here"
        result = sp._get_required_tool_actions()
        assert result == {}

    @pytest.mark.unit
    def test_caches_result(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp._required_tool_actions = {"tool1": {"action1"}}
        result = sp._get_required_tool_actions()
        assert result == {"tool1": {"action1"}}


class TestConfigureRetriever:

    @pytest.mark.unit
    def test_default_values(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"question": "Q"},
                decoded_token={"sub": "u"},
            )
        sp.model_id = "test-model"
        sp.agent_key = None
        sp._configure_retriever()
        assert sp.retriever_config["retriever_name"] == "classic"
        assert sp.retriever_config["chunks"] == 2

    @pytest.mark.unit
    def test_isNoneDoc_sets_zero_chunks(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"question": "Q", "isNoneDoc": True},
                decoded_token={"sub": "u"},
            )
        sp.model_id = "test-model"
        sp.agent_key = None
        sp._configure_retriever()
        assert sp.retriever_config["chunks"] == 0

    @pytest.mark.unit
    def test_custom_retriever_and_chunks(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"question": "Q", "retriever": "hybrid", "chunks": "5"},
                decoded_token={"sub": "u"},
            )
        sp.model_id = "test-model"
        sp.agent_key = None
        sp._configure_retriever()
        assert sp.retriever_config["retriever_name"] == "hybrid"
        assert sp.retriever_config["chunks"] == 5

    @pytest.mark.unit
    def test_isNoneDoc_ignored_when_api_key_set(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"question": "Q", "isNoneDoc": True, "api_key": "k"},
                decoded_token={"sub": "u"},
            )
        sp.model_id = "test-model"
        sp.agent_key = None
        sp._configure_retriever()
        # When api_key is set, isNoneDoc branch is not entered
        assert sp.retriever_config["chunks"] == 2

    @pytest.mark.unit
    def test_isNoneDoc_ignored_when_agent_key_set(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"question": "Q", "isNoneDoc": True},
                decoded_token={"sub": "u"},
            )
        sp.model_id = "test-model"
        sp.agent_key = "some_key"
        sp._configure_retriever()
        # When agent_key is set, isNoneDoc branch is not entered
        assert sp.retriever_config["chunks"] == 2


class TestConfigureSource:

    @pytest.mark.unit
    def test_active_docs_from_request(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"question": "Q", "active_docs": "source_123"},
                decoded_token={"sub": "u"},
            )
        sp.agent_key = None
        sp._configure_source()
        assert sp.source == {"active_docs": "source_123"}

    @pytest.mark.unit
    def test_no_source_config(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"question": "Q"},
                decoded_token={"sub": "u"},
            )
        sp.agent_key = None
        sp._configure_source()
        assert sp.source == {}
        assert sp.all_sources == []

    @pytest.mark.unit
    def test_source_from_api_key_with_sources(self):
        """When api_key returns agent data with multiple sources."""
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"api_key": "test_key"},
                decoded_token={"sub": "u"},
            )
        sp.agent_key = None
        agent_data = {
            "sources": [
                {"id": "src1", "retriever": "classic"},
                {"id": "src2", "retriever": "hybrid"},
            ],
            "source": None,
        }
        sp._get_data_from_api_key = MagicMock(return_value=agent_data)
        sp._configure_source()
        assert sp.source == {"active_docs": ["src1", "src2"]}
        assert len(sp.all_sources) == 2

    @pytest.mark.unit
    def test_source_from_api_key_single_source(self):
        """When api_key returns agent data with single source (legacy)."""
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"api_key": "test_key"},
                decoded_token={"sub": "u"},
            )
        sp.agent_key = None
        agent_data = {
            "sources": [],
            "source": "single_src",
            "retriever": "classic",
        }
        sp._get_data_from_api_key = MagicMock(return_value=agent_data)
        sp._configure_source()
        assert sp.source == {"active_docs": "single_src"}
        assert len(sp.all_sources) == 1

    @pytest.mark.unit
    def test_source_from_api_key_no_source(self):
        """When api_key returns agent data with no source."""
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"api_key": "test_key"},
                decoded_token={"sub": "u"},
            )
        sp.agent_key = None
        agent_data = {"sources": [], "source": None}
        sp._get_data_from_api_key = MagicMock(return_value=agent_data)
        sp._configure_source()
        assert sp.source == {}
        assert sp.all_sources == []

    @pytest.mark.unit
    def test_source_from_agent_key(self):
        """When agent_key is set (no api_key in data), uses agent_key."""
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={},
                decoded_token={"sub": "u"},
            )
        sp.agent_key = "agent_key_123"
        agent_data = {
            "sources": [{"id": "s1", "retriever": "classic"}],
            "source": None,
        }
        sp._get_data_from_api_key = MagicMock(return_value=agent_data)
        sp._configure_source()
        assert sp.source == {"active_docs": ["s1"]}

    @pytest.mark.unit
    def test_source_from_api_key_sources_with_empty_ids(self):
        """Sources list entries without id should be filtered out."""
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"api_key": "k"},
                decoded_token={"sub": "u"},
            )
        sp.agent_key = None
        agent_data = {
            "sources": [{"id": None}, {"retriever": "classic"}],
            "source": None,
        }
        sp._get_data_from_api_key = MagicMock(return_value=agent_data)
        sp._configure_source()
        assert sp.source == {}


# ---- Additional coverage: get_prompt edge cases ----

class TestGetPromptEdgeCases:

    @pytest.mark.unit
    def test_file_not_found_raises(self):
        """get_prompt raises FileNotFoundError when preset file is missing."""
        with patch("builtins.open", side_effect=FileNotFoundError("missing")):
            with pytest.raises(FileNotFoundError, match="Prompt file not found"):
                get_prompt("default")

    @pytest.mark.unit
    def test_prompt_doc_not_found_raises_value_error(self):
        """get_prompt wraps 'not found' in ValueError."""
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        with pytest.raises(ValueError, match="Invalid prompt ID"):
            get_prompt("507f1f77bcf86cd799439011", prompts_collection=mock_collection)


# ---- Additional coverage: _get_prompt_content with DB prompt ----

class TestGetPromptContentDBPrompt:

    @pytest.mark.unit
    def test_db_prompt_cached(self):
        """_get_prompt_content returns cached value on second call."""
        mock_db = MagicMock()
        mock_prompts = MagicMock()
        mock_prompts.find_one.return_value = {"content": "DB content"}
        mock_db.__getitem__ = MagicMock(return_value=mock_prompts)

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {"prompt_id": "507f1f77bcf86cd799439011"}
        r1 = sp._get_prompt_content()
        r2 = sp._get_prompt_content()
        assert r1 == r2

    @pytest.mark.unit
    def test_general_exception_returns_none(self):
        """_get_prompt_content catches general exceptions from get_prompt."""
        mock_db = MagicMock()
        mock_prompts = MagicMock()
        mock_prompts.find_one.side_effect = RuntimeError("connection lost")
        mock_db.__getitem__ = MagicMock(return_value=mock_prompts)

        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {"prompt_id": "not_a_preset_id"}
        result = sp._get_prompt_content()
        assert result is None


# ---- Additional coverage: _get_required_tool_actions with template syntax ----

class TestGetRequiredToolActionsTemplate:

    @pytest.mark.unit
    def test_template_syntax_extracts_usages(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})

        sp.agent_config = {"prompt_id": "default"}
        sp._prompt_content = "Use {{tool.my_tool.action1}} for data"

        with patch(
            "application.templates.template_engine.TemplateEngine.extract_tool_usages",
            return_value={"my_tool": {"action1"}},
        ):
            result = sp._get_required_tool_actions()
        assert result == {"my_tool": {"action1"}}

    @pytest.mark.unit
    def test_template_extraction_exception_returns_empty(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})

        sp.agent_config = {"prompt_id": "default"}
        sp._prompt_content = "Use {{broken}} template"

        with patch(
            "application.templates.template_engine.TemplateEngine.extract_tool_usages",
            side_effect=RuntimeError("parse error"),
        ):
            result = sp._get_required_tool_actions()
        assert result == {}


# ---- Additional coverage: _validate_and_set_model ----

class TestValidateAndSetModel:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_valid_requested_model(self):
        sp = self._make_sp()
        sp.data = {"model_id": "gpt-4"}
        with patch("application.api.answer.services.stream_processor.validate_model_id", return_value=True):
            sp._validate_and_set_model()
        assert sp.model_id == "gpt-4"

    @pytest.mark.unit
    def test_invalid_requested_model_raises(self):
        sp = self._make_sp()
        sp.data = {"model_id": "bad-model"}

        mock_registry_instance = MagicMock()
        mock_model = MagicMock()
        mock_model.id = "gpt-4"
        mock_registry_instance.get_enabled_models.return_value = [mock_model]

        with patch("application.api.answer.services.stream_processor.validate_model_id", return_value=False), \
             patch("application.core.model_settings.ModelRegistry.get_instance", return_value=mock_registry_instance):
            with pytest.raises(ValueError, match="Invalid model_id"):
                sp._validate_and_set_model()

    @pytest.mark.unit
    def test_invalid_model_with_more_than_5_available(self):
        sp = self._make_sp()
        sp.data = {"model_id": "bad-model"}

        mock_registry_instance = MagicMock()
        models = [MagicMock(id=f"model-{i}") for i in range(8)]
        mock_registry_instance.get_enabled_models.return_value = models

        with patch("application.api.answer.services.stream_processor.validate_model_id", return_value=False), \
             patch("application.core.model_settings.ModelRegistry.get_instance", return_value=mock_registry_instance):
            with pytest.raises(ValueError, match="and 3 more"):
                sp._validate_and_set_model()

    @pytest.mark.unit
    def test_no_requested_model_uses_agent_default(self):
        sp = self._make_sp()
        sp.data = {}
        sp.agent_config = {"default_model_id": "agent-model-1"}
        with patch("application.api.answer.services.stream_processor.validate_model_id", return_value=True), \
             patch("application.api.answer.services.stream_processor.get_default_model_id", return_value="fallback"):
            sp._validate_and_set_model()
        assert sp.model_id == "agent-model-1"

    @pytest.mark.unit
    def test_no_requested_model_invalid_agent_default_uses_global(self):
        sp = self._make_sp()
        sp.data = {}
        sp.agent_config = {"default_model_id": "bad-agent-model"}
        with patch("application.api.answer.services.stream_processor.validate_model_id", return_value=False), \
             patch("application.api.answer.services.stream_processor.get_default_model_id", return_value="global-default"):
            sp._validate_and_set_model()
        assert sp.model_id == "global-default"

    @pytest.mark.unit
    def test_no_requested_model_empty_agent_default_uses_global(self):
        sp = self._make_sp()
        sp.data = {}
        sp.agent_config = {"default_model_id": ""}
        with patch("application.api.answer.services.stream_processor.validate_model_id", return_value=False), \
             patch("application.api.answer.services.stream_processor.get_default_model_id", return_value="global-default"):
            sp._validate_and_set_model()
        assert sp.model_id == "global-default"


# ---- Additional coverage: _get_agent_key ----

class TestGetAgentKey:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_no_agent_id(self):
        sp = self._make_sp()
        key, is_shared, shared_token = sp._get_agent_key(None, "user1")
        assert key is None
        assert is_shared is False
        assert shared_token is None

    @pytest.mark.unit
    def test_agent_not_found_raises(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = None
        with pytest.raises(Exception, match="Agent not found"):
            sp._get_agent_key("507f1f77bcf86cd799439011", "user1")

    @pytest.mark.unit
    def test_unauthorized_access_raises(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "user": "other_user",
            "shared_publicly": False,
            "shared_with": [],
            "key": "agent_key",
        }
        with pytest.raises(Exception, match="Unauthorized"):
            sp._get_agent_key("507f1f77bcf86cd799439011", "user1")

    @pytest.mark.unit
    def test_owner_updates_last_used(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "user": "user1",
            "shared_publicly": False,
            "shared_with": [],
            "key": "agent_key",
            "shared_token": "stoken",
        }
        key, is_shared, shared_token = sp._get_agent_key(
            "507f1f77bcf86cd799439011", "user1"
        )
        assert key == "agent_key"
        assert is_shared is False
        assert shared_token == "stoken"
        sp.agents_collection.update_one.assert_called_once()

    @pytest.mark.unit
    def test_shared_with_user(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "user": "owner",
            "shared_publicly": False,
            "shared_with": ["user1"],
            "key": "agent_key",
            "shared_token": "st",
        }
        key, is_shared, shared_token = sp._get_agent_key(
            "507f1f77bcf86cd799439011", "user1"
        )
        assert key == "agent_key"
        assert is_shared is True
        assert shared_token == "st"
        # Shared user should NOT trigger update_one
        sp.agents_collection.update_one.assert_not_called()

    @pytest.mark.unit
    def test_shared_publicly(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "user": "owner",
            "shared_publicly": True,
            "shared_with": [],
            "key": "agent_key",
        }
        key, is_shared, _ = sp._get_agent_key(
            "507f1f77bcf86cd799439011", "user1"
        )
        assert key == "agent_key"
        assert is_shared is True


# ---- Additional coverage: _get_data_from_api_key ----

class TestGetDataFromApiKey:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_invalid_api_key_raises(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = None
        with pytest.raises(Exception, match="Invalid API Key"):
            sp._get_data_from_api_key("bad_key")

    @pytest.mark.unit
    def test_valid_key_with_default_source(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": "default",
            "sources": [],
        }
        data = sp._get_data_from_api_key("valid_key")
        assert data["source"] == "default"
        assert data["default_model_id"] == ""

    @pytest.mark.unit
    def test_valid_key_with_none_source(self):
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": "something_else",
            "sources": [],
        }
        data = sp._get_data_from_api_key("valid_key")
        assert data["source"] is None

    @pytest.mark.unit
    def test_valid_key_with_dbref_source(self):
        from bson.dbref import DBRef
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        source_ref = DBRef("sources", "source_id_1")
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": source_ref,
            "sources": [],
        }
        sp.db = MagicMock()
        sp.db.dereference.return_value = {
            "_id": "source_id_1",
            "retriever": "hybrid",
            "chunks": "5",
        }
        data = sp._get_data_from_api_key("valid_key")
        assert data["source"] == "source_id_1"
        assert data["retriever"] == "hybrid"
        assert data["chunks"] == "5"

    @pytest.mark.unit
    def test_valid_key_with_dbref_source_none_doc(self):
        from bson.dbref import DBRef
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        source_ref = DBRef("sources", "source_id_1")
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": source_ref,
            "sources": [],
        }
        sp.db = MagicMock()
        sp.db.dereference.return_value = None
        data = sp._get_data_from_api_key("valid_key")
        assert data["source"] is None

    @pytest.mark.unit
    def test_sources_list_with_dbref_entries(self):
        from bson.dbref import DBRef
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        ref1 = DBRef("sources", "sid1")
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": "default",
            "sources": ["default", ref1],
            "chunks": "3",
        }
        sp.db = MagicMock()
        sp.db.dereference.return_value = {
            "_id": "sid1",
            "retriever": "semantic",
            "chunks": "4",
        }
        data = sp._get_data_from_api_key("valid_key")
        assert len(data["sources"]) == 2
        assert data["sources"][0]["id"] == "default"
        assert data["sources"][0]["retriever"] == "classic"
        assert data["sources"][1]["id"] == "sid1"
        assert data["sources"][1]["retriever"] == "semantic"


# ---- Additional coverage: _configure_agent ----

class TestConfigureAgent:

    def _make_sp(self, request_data=None, decoded_token=None):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.AGENT_NAME = "classic"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data=request_data or {},
                decoded_token=decoded_token or {"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_configure_agent_no_key_defaults(self):
        sp = self._make_sp()
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        sp._configure_agent()
        assert sp.agent_config["agent_type"] == "classic"
        assert sp.agent_config["prompt_id"] == "default"
        assert sp.agent_config["user_api_key"] is None

    @pytest.mark.unit
    def test_configure_agent_with_workflow_in_data(self):
        sp = self._make_sp(
            request_data={"workflow": {"nodes": [], "edges": []}},
            decoded_token={"sub": "user1"},
        )
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        sp._configure_agent()
        assert sp.agent_config["agent_type"] == "workflow"
        assert sp.agent_config["workflow"] == {"nodes": [], "edges": []}
        assert sp.agent_config["workflow_owner"] == "user1"

    @pytest.mark.unit
    def test_configure_agent_with_api_key(self):
        sp = self._make_sp(request_data={"api_key": "test_api_key"})
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        sp._get_data_from_api_key = MagicMock(return_value={
            "_id": "agent_abc",
            "prompt_id": "creative",
            "agent_type": "agentic",
            "key": "test_api_key",
            "json_schema": None,
            "default_model_id": "gpt-4",
            "models": ["gpt-4", "gpt-3.5"],
            "user": "api_owner",
            "source": "src1",
        })
        sp._configure_agent()
        assert sp.agent_config["prompt_id"] == "creative"
        assert sp.agent_config["agent_type"] == "agentic"
        assert sp.agent_id == "agent_abc"
        # External API key sets decoded_token to owner
        assert sp.decoded_token == {"sub": "api_owner"}

    @pytest.mark.unit
    def test_configure_agent_shared_keeps_caller_identity(self):
        sp = self._make_sp(decoded_token={"sub": "caller_user"})
        sp._resolve_agent_id = MagicMock(return_value="agent_id_1")
        sp._get_agent_key = MagicMock(return_value=("agent_key", True, "st"))
        sp._get_data_from_api_key = MagicMock(return_value={
            "_id": "agent_id_1",
            "prompt_id": "default",
            "agent_type": "classic",
            "key": "agent_key",
            "json_schema": None,
            "default_model_id": "",
            "models": [],
            "user": "owner_user",
        })
        sp._configure_agent()
        # Shared agent: keeps the caller's identity
        assert sp.decoded_token == {"sub": "caller_user"}

    @pytest.mark.unit
    def test_configure_agent_with_workflow_config(self):
        sp = self._make_sp()
        sp._resolve_agent_id = MagicMock(return_value="agent_id_1")
        sp._get_agent_key = MagicMock(return_value=("agent_key", False, None))
        sp._get_data_from_api_key = MagicMock(return_value={
            "_id": "agent_id_1",
            "prompt_id": "default",
            "agent_type": "classic",
            "key": "agent_key",
            "json_schema": None,
            "default_model_id": "",
            "models": [],
            "user": "user1",
            "workflow": "wf_123",
            "retriever": "hybrid",
            "chunks": "5",
        })
        sp._configure_agent()
        assert sp.agent_config["workflow"] == "wf_123"
        assert sp.agent_config["workflow_owner"] == "user1"
        assert sp.retriever_config["retriever_name"] == "hybrid"
        assert sp.retriever_config["chunks"] == 5

    @pytest.mark.unit
    def test_configure_agent_invalid_chunks_defaults_to_2(self):
        sp = self._make_sp()
        sp._resolve_agent_id = MagicMock(return_value="agent_id_1")
        sp._get_agent_key = MagicMock(return_value=("agent_key", False, None))
        sp._get_data_from_api_key = MagicMock(return_value={
            "_id": "agent_id_1",
            "prompt_id": "default",
            "agent_type": "classic",
            "key": "agent_key",
            "json_schema": None,
            "default_model_id": "",
            "models": [],
            "user": "user1",
            "chunks": "not_a_number",
        })
        sp._configure_agent()
        assert sp.retriever_config["chunks"] == 2


# ---- Additional coverage: _load_conversation_history ----

class TestLoadConversationHistory:

    def _make_sp(self, request_data=None, decoded_token=None):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.ENABLE_CONVERSATION_COMPRESSION = False
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data=request_data or {},
                decoded_token=decoded_token or {"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_load_from_db_no_compression(self):
        sp = self._make_sp(request_data={"conversation_id": "conv1"})
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.return_value = {
            "queries": [
                {"prompt": "Hi", "response": "Hello"},
                {"prompt": "Q", "response": "A", "metadata": {"key": "val"}},
            ]
        }
        with patch("application.api.answer.services.stream_processor.settings") as mock_s:
            mock_s.ENABLE_CONVERSATION_COMPRESSION = False
            sp._load_conversation_history()
        assert len(sp.history) == 2
        assert sp.history[1]["metadata"] == {"key": "val"}
        assert "metadata" not in sp.history[0]

    @pytest.mark.unit
    def test_load_conversation_not_found_raises(self):
        sp = self._make_sp(request_data={"conversation_id": "conv1"})
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.return_value = None
        with patch("application.api.answer.services.stream_processor.settings") as mock_s:
            mock_s.ENABLE_CONVERSATION_COMPRESSION = False
            with pytest.raises(ValueError, match="Conversation not found"):
                sp._load_conversation_history()

    @pytest.mark.unit
    def test_load_from_request_data(self):
        import json
        history_data = [{"prompt": "Q", "response": "A"}]
        sp = self._make_sp(request_data={"history": json.dumps(history_data)})
        sp.conversation_id = None
        with patch("application.api.answer.services.stream_processor.limit_chat_history",
                    return_value=history_data):
            sp._load_conversation_history()
        assert sp.history == history_data


# ---- Additional coverage: _handle_compression ----

class TestHandleCompression:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1"},
                decoded_token={"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_compression_failed_uses_full_history(self):
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        result = MagicMock()
        result.success = False
        result.error = "Some error"
        sp.compression_orchestrator.compress_if_needed.return_value = result
        conversation = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }
        sp._handle_compression(conversation)
        assert len(sp.history) == 1
        assert sp.history[0]["prompt"] == "Q"

    @pytest.mark.unit
    def test_compression_performed_sets_summary(self):
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        result = MagicMock()
        result.success = True
        result.compression_performed = True
        result.compressed_summary = "Summary text"
        result.recent_queries = [{"prompt": "Q", "response": "A"}]
        result.as_history.return_value = [{"prompt": "Q", "response": "A"}]
        sp.compression_orchestrator.compress_if_needed.return_value = result

        with patch("application.api.answer.services.stream_processor.TokenCounter") as MockTC:
            MockTC.count_message_tokens.return_value = 42
            sp._handle_compression({"queries": [{"prompt": "Q", "response": "A"}]})

        assert sp.compressed_summary == "Summary text"
        assert sp.compressed_summary_tokens == 42

    @pytest.mark.unit
    def test_compression_exception_falls_back(self):
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        sp.compression_orchestrator.compress_if_needed.side_effect = RuntimeError("boom")
        conversation = {"queries": [{"prompt": "Q", "response": "A"}]}
        sp._handle_compression(conversation)
        assert len(sp.history) == 1

    @pytest.mark.unit
    def test_compression_not_performed_still_sets_history(self):
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        result = MagicMock()
        result.success = True
        result.compression_performed = False
        result.compressed_summary = None
        result.recent_queries = [{"prompt": "Q", "response": "A"}]
        result.as_history.return_value = [{"prompt": "Q", "response": "A"}]
        sp.compression_orchestrator.compress_if_needed.return_value = result
        sp._handle_compression({"queries": [{"prompt": "Q", "response": "A"}]})
        assert len(sp.history) == 1
        assert sp.compressed_summary is None


# ---- Additional coverage: build_agent ----

class TestBuildAgent:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={},
                decoded_token={"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_build_agent_agentic_skips_prefetch_docs(self):
        sp = self._make_sp()
        sp.initialize = MagicMock()
        sp.agent_config = {"agent_type": "agentic"}
        sp.pre_fetch_tools = MagicMock(return_value=None)
        sp.pre_fetch_docs = MagicMock()
        sp.create_agent = MagicMock(return_value="agent_obj")

        result = sp.build_agent("question?")
        assert result == "agent_obj"
        sp.pre_fetch_docs.assert_not_called()
        sp.create_agent.assert_called_once_with(tools_data=None)

    @pytest.mark.unit
    def test_build_agent_research_skips_prefetch_docs(self):
        sp = self._make_sp()
        sp.initialize = MagicMock()
        sp.agent_config = {"agent_type": "research"}
        sp.pre_fetch_tools = MagicMock(return_value={"t": "d"})
        sp.pre_fetch_docs = MagicMock()
        sp.create_agent = MagicMock(return_value="agent_obj")

        result = sp.build_agent("question?")
        assert result == "agent_obj"
        sp.pre_fetch_docs.assert_not_called()

    @pytest.mark.unit
    def test_build_agent_classic_calls_prefetch_docs(self):
        sp = self._make_sp()
        sp.initialize = MagicMock()
        sp.agent_config = {"agent_type": "classic"}
        sp.pre_fetch_tools = MagicMock(return_value=None)
        sp.pre_fetch_docs = MagicMock(return_value=("docs_text", [{"text": "d"}]))
        sp.create_agent = MagicMock(return_value="agent_obj")

        result = sp.build_agent("question?")
        assert result == "agent_obj"
        sp.pre_fetch_docs.assert_called_once_with("question?")
        sp.create_agent.assert_called_once_with(
            docs_together="docs_text",
            docs=[{"text": "d"}],
            tools_data=None,
        )


# ---------------------------------------------------------------------------
# Additional coverage: _handle_compression metadata preservation (line 219)
# ---------------------------------------------------------------------------


class TestHandleCompressionMetadataPreservation:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1"},
                decoded_token={"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_metadata_copied_from_recent_queries(self):
        """Cover line 219: entry['metadata'] = recent[qi]['metadata']."""
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        result = MagicMock()
        result.success = True
        result.compression_performed = True
        result.compressed_summary = "Summary"
        result.recent_queries = [
            {"prompt": "Q1", "response": "A1", "metadata": {"tool": "search"}},
            {"prompt": "Q2", "response": "A2"},
        ]
        result.as_history.return_value = [
            {"prompt": "Q1", "response": "A1"},
            {"prompt": "Q2", "response": "A2"},
        ]
        sp.compression_orchestrator.compress_if_needed.return_value = result

        with patch(
            "application.api.answer.services.stream_processor.TokenCounter"
        ) as MockTC:
            MockTC.count_message_tokens.return_value = 10
            sp._handle_compression(
                {
                    "queries": [
                        {"prompt": "Q1", "response": "A1", "metadata": {"tool": "search"}},
                        {"prompt": "Q2", "response": "A2"},
                    ]
                }
            )

        assert sp.history[0].get("metadata") == {"tool": "search"}
        assert "metadata" not in sp.history[1]

    @pytest.mark.unit
    def test_exception_fallback_with_metadata(self):
        """Cover lines 222, 228-232: exception path with metadata in queries."""
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        sp.compression_orchestrator.compress_if_needed.side_effect = RuntimeError("fail")
        conversation = {
            "queries": [
                {"prompt": "Q", "response": "A", "metadata": {"key": "val"}},
                {"prompt": "Q2", "response": "A2"},
            ]
        }
        sp._handle_compression(conversation)
        assert len(sp.history) == 2
        assert sp.history[0]["metadata"] == {"key": "val"}
        assert "metadata" not in sp.history[1]


# ---------------------------------------------------------------------------
# Additional coverage: _get_data_from_api_key full path (lines 267-295, 341-358)
# ---------------------------------------------------------------------------


class TestGetDataFromApiKeyFullPaths:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_sources_list_with_default_entry(self):
        """Cover lines 337-343: 'default' string in sources list."""
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": "default",
            "sources": ["default"],
            "chunks": "4",
        }
        data = sp._get_data_from_api_key("valid_key")
        assert len(data["sources"]) == 1
        assert data["sources"][0]["id"] == "default"
        assert data["sources"][0]["retriever"] == "classic"
        assert data["sources"][0]["chunks"] == "4"

    @pytest.mark.unit
    def test_sources_list_with_dbref_returns_none(self):
        """Cover lines 344-352: DBRef entry in sources where dereference returns None."""
        from bson.dbref import DBRef
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        ref1 = DBRef("sources", "missing_id")
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": "default",
            "sources": [ref1],
            "chunks": "2",
        }
        sp.db = MagicMock()
        sp.db.dereference.return_value = None
        data = sp._get_data_from_api_key("valid_key")
        # Missing dereference means the DBRef entry is skipped
        assert data["sources"] == []

    @pytest.mark.unit
    def test_sources_not_list_returns_empty(self):
        """Cover lines 354-355: sources is not a list."""
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": "default",
            "sources": "not_a_list",
        }
        data = sp._get_data_from_api_key("valid_key")
        assert data["sources"] == []

    @pytest.mark.unit
    def test_default_model_id_preserved(self):
        """Cover line 357: default_model_id extracted."""
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "agent1",
            "key": "valid_key",
            "source": "default",
            "sources": [],
            "default_model_id": "gpt-4",
        }
        data = sp._get_data_from_api_key("valid_key")
        assert data["default_model_id"] == "gpt-4"


# ---------------------------------------------------------------------------
# Additional coverage: _load_conversation_history compression branch (lines 341-365)
# ---------------------------------------------------------------------------


class TestLoadConversationHistoryCompressionEnabled:

    def _make_sp(self, request_data=None, decoded_token=None):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.ENABLE_CONVERSATION_COMPRESSION = True
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data=request_data or {"conversation_id": "conv1"},
                decoded_token=decoded_token or {"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_load_with_compression_enabled(self):
        """Cover lines 341-358: compression enabled path."""
        sp = self._make_sp()
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.return_value = {
            "queries": [
                {"prompt": "Q1", "response": "A1"},
                {"prompt": "Q2", "response": "A2"},
            ]
        }
        sp._handle_compression = MagicMock()
        with patch("application.api.answer.services.stream_processor.settings") as mock_s:
            mock_s.ENABLE_CONVERSATION_COMPRESSION = True
            sp._load_conversation_history()
        sp._handle_compression.assert_called_once()

    @pytest.mark.unit
    def test_load_without_conversation_id_uses_request_history(self):
        """Cover lines 361-365: no conversation_id, loads from request."""
        import json
        history_data = [{"prompt": "Q", "response": "A"}]
        sp = self._make_sp(request_data={"history": json.dumps(history_data)})
        sp.conversation_id = None
        with patch(
            "application.api.answer.services.stream_processor.limit_chat_history",
            return_value=history_data,
        ):
            sp._load_conversation_history()
        assert sp.history == history_data

    @pytest.mark.unit
    def test_load_without_user_id_uses_request_history(self):
        """Cover line 361-365: no user_id, loads from request."""
        import json
        history_data = [{"prompt": "Q", "response": "A"}]
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.ENABLE_CONVERSATION_COMPRESSION = False
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={
                    "conversation_id": "c1",
                    "history": json.dumps(history_data),
                },
                decoded_token=None,  # This sets initial_user_id to None
            )
        # initial_user_id should be None because decoded_token is None
        assert sp.initial_user_id is None
        with patch(
            "application.api.answer.services.stream_processor.limit_chat_history",
            return_value=history_data,
        ):
            sp._load_conversation_history()
        assert sp.history == history_data


# ---------------------------------------------------------------------------
# Additional coverage: _handle_compression failure path with metadata (lines 376-407)
# ---------------------------------------------------------------------------


class TestHandleCompressionFailurePath:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data={"conversation_id": "conv1"},
                decoded_token={"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_compression_failed_with_metadata_queries(self):
        """Cover lines 376-378, 381-398: failure path with metadata in queries."""
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        result = MagicMock()
        result.success = False
        result.error = "compression error"
        sp.compression_orchestrator.compress_if_needed.return_value = result
        conversation = {
            "queries": [
                {"prompt": "Q1", "response": "A1", "metadata": {"m": 1}},
                {"prompt": "Q2", "response": "A2"},
            ]
        }
        sp._handle_compression(conversation)
        assert len(sp.history) == 2
        assert sp.history[0]["metadata"] == {"m": 1}
        assert "metadata" not in sp.history[1]

    @pytest.mark.unit
    def test_compression_success_no_compression_performed(self):
        """Cover lines 399-407: success but no compression performed, recent_queries None."""
        sp = self._make_sp()
        sp.compression_orchestrator = MagicMock()
        result = MagicMock()
        result.success = True
        result.compression_performed = False
        result.compressed_summary = None
        result.recent_queries = None
        result.as_history.return_value = [{"prompt": "Q", "response": "A"}]
        sp.compression_orchestrator.compress_if_needed.return_value = result
        conversation = {
            "queries": [
                {"prompt": "Q", "response": "A", "metadata": {"k": "v"}},
            ]
        }
        sp._handle_compression(conversation)
        assert len(sp.history) == 1
        # When recent_queries is None, it falls back to conversation queries
        assert sp.history[0].get("metadata") == {"k": "v"}


# ---------------------------------------------------------------------------
# Additional coverage: _configure_agent full paths (lines 418-477)
# ---------------------------------------------------------------------------


class TestConfigureAgentAdditionalPaths:

    def _make_sp(self, request_data=None, decoded_token=None):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.AGENT_NAME = "classic"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data=request_data or {},
                decoded_token=decoded_token or {"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_configure_agent_owner_sets_decoded_token(self):
        """Cover lines 460-461: owner (not shared, not external api_key) sets decoded_token."""
        sp = self._make_sp(decoded_token={"sub": "user1"})
        sp._resolve_agent_id = MagicMock(return_value="agent_id_1")
        sp._get_agent_key = MagicMock(return_value=("agent_key", False, None))
        sp._get_data_from_api_key = MagicMock(return_value={
            "_id": "agent_id_1",
            "prompt_id": "default",
            "agent_type": "classic",
            "key": "agent_key",
            "json_schema": None,
            "default_model_id": "",
            "models": [],
            "user": "owner_user",
        })
        sp._configure_agent()
        # Owner path: decoded_token set to data_key user
        assert sp.decoded_token == {"sub": "owner_user"}

    @pytest.mark.unit
    def test_configure_agent_with_source_in_data_key(self):
        """Cover line 463-464: data_key has 'source' set."""
        sp = self._make_sp()
        sp._resolve_agent_id = MagicMock(return_value="agent_id_1")
        sp._get_agent_key = MagicMock(return_value=("agent_key", False, None))
        sp._get_data_from_api_key = MagicMock(return_value={
            "_id": "agent_id_1",
            "prompt_id": "default",
            "agent_type": "classic",
            "key": "agent_key",
            "json_schema": None,
            "default_model_id": "",
            "models": [],
            "user": "user1",
            "source": "my_source",
        })
        sp._configure_agent()
        assert sp.source == {"active_docs": "my_source"}

    @pytest.mark.unit
    def test_configure_agent_without_id_in_data_key(self):
        """Cover line 437-438: data_key has no _id."""
        sp = self._make_sp(request_data={"api_key": "ext_key"})
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        sp._get_data_from_api_key = MagicMock(return_value={
            "prompt_id": "default",
            "agent_type": "classic",
            "key": "ext_key",
            "json_schema": None,
            "default_model_id": "",
            "models": [],
            "user": "ext_owner",
        })
        sp._configure_agent()
        # agent_id should not be updated when _id is missing
        assert sp.agent_id is None

    @pytest.mark.unit
    def test_configure_agent_chunks_none_is_skipped(self):
        """Cover line 470: chunks is None (no chunks key at all)."""
        sp = self._make_sp()
        sp._resolve_agent_id = MagicMock(return_value="agent_id_1")
        sp._get_agent_key = MagicMock(return_value=("agent_key", False, None))
        sp._get_data_from_api_key = MagicMock(return_value={
            "_id": "agent_id_1",
            "prompt_id": "default",
            "agent_type": "classic",
            "key": "agent_key",
            "json_schema": None,
            "default_model_id": "",
            "models": [],
            "user": "user1",
            # no "chunks" key at all
        })
        sp._configure_agent()
        # chunks should not be in retriever_config since we skipped that branch
        assert "chunks" not in sp.retriever_config


# ---------------------------------------------------------------------------
# Additional coverage: _configure_agent else branch (lines 481-497)
# ---------------------------------------------------------------------------


class TestConfigureAgentElseBranch:

    def _make_sp(self, request_data=None, decoded_token=None):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.AGENT_NAME = "classic"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(
                request_data=request_data or {},
                decoded_token=decoded_token or {"sub": "user1"},
            )
        return sp

    @pytest.mark.unit
    def test_no_key_no_workflow_defaults(self):
        """Cover lines 480-497: no effective key, no workflow."""
        sp = self._make_sp(request_data={"prompt_id": "creative"})
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        with patch("application.api.answer.services.stream_processor.settings") as mock_s:
            mock_s.AGENT_NAME = "classic"
            sp._configure_agent()
        assert sp.agent_config["agent_type"] == "classic"
        assert sp.agent_config["prompt_id"] == "creative"
        assert sp.agent_config["user_api_key"] is None
        assert sp.agent_config["json_schema"] is None
        assert sp.agent_config["default_model_id"] == ""

    @pytest.mark.unit
    def test_no_key_with_workflow_dict(self):
        """Cover lines 481-487: workflow dict in request data."""
        wf = {"nodes": [{"id": "n1"}], "edges": []}
        sp = self._make_sp(
            request_data={"workflow": wf},
            decoded_token={"sub": "wf_user"},
        )
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        with patch("application.api.answer.services.stream_processor.settings") as mock_s:
            mock_s.AGENT_NAME = "classic"
            sp._configure_agent()
        assert sp.agent_config["agent_type"] == "workflow"
        assert sp.agent_config["workflow"] == wf
        assert sp.agent_config["workflow_owner"] == "wf_user"

    @pytest.mark.unit
    def test_no_key_workflow_not_dict_ignored(self):
        """Cover lines 481-482: workflow in request but not a dict."""
        sp = self._make_sp(request_data={"workflow": "string_workflow"})
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        with patch("application.api.answer.services.stream_processor.settings") as mock_s:
            mock_s.AGENT_NAME = "classic"
            sp._configure_agent()
        assert sp.agent_config["agent_type"] == "classic"
        assert "workflow" not in sp.agent_config


# ---------------------------------------------------------------------------
# Additional coverage: create_retriever (lines 512-524)
# ---------------------------------------------------------------------------


class TestCreateRetriever:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_create_retriever_calls_creator(self):
        """Cover lines 512-524: create_retriever delegates to RetrieverCreator."""
        sp = self._make_sp()
        sp.retriever_config = {
            "retriever_name": "classic",
            "chunks": 2,
            "doc_token_limit": 50000,
        }
        sp.agent_config = {"prompt_id": "default", "user_api_key": None}
        sp.source = {}
        sp.history = []
        sp.model_id = "test-model"
        sp.agent_id = None
        sp.decoded_token = {"sub": "u"}

        mock_retriever = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.RetrieverCreator.create_retriever",
            return_value=mock_retriever,
        ) as mock_create:
            result = sp.create_retriever()

        assert result is mock_retriever
        mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# Additional coverage: _validate_and_set_model edge cases (lines 259-295)
# ---------------------------------------------------------------------------


class TestValidateAndSetModelEdgeCases:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_invalid_model_with_exactly_5_models(self):
        """Cover lines 272-276: exactly 5 available models (no 'and N more')."""
        sp = self._make_sp()
        sp.data = {"model_id": "bad-model"}

        mock_registry_instance = MagicMock()
        models = [MagicMock(id=f"model-{i}") for i in range(5)]
        mock_registry_instance.get_enabled_models.return_value = models

        with patch(
            "application.api.answer.services.stream_processor.validate_model_id",
            return_value=False,
        ), patch(
            "application.core.model_settings.ModelRegistry.get_instance",
            return_value=mock_registry_instance,
        ):
            with pytest.raises(ValueError) as exc_info:
                sp._validate_and_set_model()
            assert "and" not in str(exc_info.value) or "more" not in str(exc_info.value)

    @pytest.mark.unit
    def test_no_requested_no_agent_default(self):
        """Cover lines 283-284: no requested model, no agent default model."""
        sp = self._make_sp()
        sp.data = {}
        sp.agent_config = {}  # no default_model_id key at all
        with patch(
            "application.api.answer.services.stream_processor.validate_model_id",
            return_value=False,
        ), patch(
            "application.api.answer.services.stream_processor.get_default_model_id",
            return_value="global-fallback",
        ):
            sp._validate_and_set_model()
        assert sp.model_id == "global-fallback"


# ---------------------------------------------------------------------------
# Additional coverage: _get_agent_key edge cases (lines 228-251)
# ---------------------------------------------------------------------------


class TestGetAgentKeyEdgeCases:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch("application.api.answer.services.stream_processor.MongoDB") as MockMongo, \
             patch("application.api.answer.services.stream_processor.settings") as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import StreamProcessor
            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_agent_found_shared_publicly_no_shared_token(self):
        """Cover lines 249-251: shared publicly, no shared_token key."""
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "user": "owner",
            "shared_publicly": True,
            "shared_with": [],
            "key": "the_key",
            # no shared_token key
        }
        key, is_shared, shared_token = sp._get_agent_key(
            "507f1f77bcf86cd799439011", "other_user"
        )
        assert key == "the_key"
        assert is_shared is True
        assert shared_token is None

    @pytest.mark.unit
    def test_agent_find_raises_exception(self):
        """Cover lines 228-232: ObjectId conversion or DB lookup fails."""
        sp = self._make_sp()
        sp.agents_collection = MagicMock()
        sp.agents_collection.find_one.side_effect = Exception("DB connection lost")
        with pytest.raises(Exception, match="DB connection lost"):
            sp._get_agent_key("507f1f77bcf86cd799439011", "user1")


# ---------------------------------------------------------------------------
# Additional coverage: pre_fetch_docs full paths (lines 540-560)
# ---------------------------------------------------------------------------


class TestPreFetchDocsFullPaths:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.MongoDB"
        ) as MockMongo, patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import (
                StreamProcessor,
            )

            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        sp.agent_config = {"prompt_id": "default", "user_api_key": None}
        sp.retriever_config = {
            "retriever_name": "classic",
            "chunks": 2,
            "doc_token_limit": 50000,
        }
        sp.source = {}
        sp.model_id = "test-model"
        sp.agent_id = None
        return sp

    @pytest.mark.unit
    def test_no_docs_returned(self):
        """Cover lines 540-541: search returns empty list."""
        sp = self._make_sp()
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = []
        sp.create_retriever = MagicMock(return_value=mock_retriever)

        result = sp.pre_fetch_docs("question?")
        assert result == (None, None)

    @pytest.mark.unit
    def test_docs_with_filename(self):
        """Cover lines 548-549: doc has filename, builds chunk header."""
        sp = self._make_sp()
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            {"text": "content1", "filename": "file1.md"},
        ]
        sp.create_retriever = MagicMock(return_value=mock_retriever)

        docs_together, docs = sp.pre_fetch_docs("question?")
        assert docs_together is not None
        assert "file1.md" in docs_together
        assert "content1" in docs_together
        assert len(docs) == 1

    @pytest.mark.unit
    def test_docs_without_filename(self):
        """Cover lines 550-551: doc has no filename/title/source."""
        sp = self._make_sp()
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            {"text": "raw content only"},
        ]
        sp.create_retriever = MagicMock(return_value=mock_retriever)

        docs_together, docs = sp.pre_fetch_docs("question?")
        assert "raw content only" in docs_together
        assert len(docs) == 1

    @pytest.mark.unit
    def test_docs_with_title_fallback(self):
        """Cover line 546: filename is None but title is present."""
        sp = self._make_sp()
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            {"text": "content", "title": "My Title"},
        ]
        sp.create_retriever = MagicMock(return_value=mock_retriever)

        docs_together, docs = sp.pre_fetch_docs("question?")
        assert "My Title" in docs_together

    @pytest.mark.unit
    def test_docs_successful_return(self):
        """Cover lines 555-556: successful return of docs_together and docs."""
        sp = self._make_sp()
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            {"text": "a", "filename": "f1"},
            {"text": "b"},
        ]
        sp.create_retriever = MagicMock(return_value=mock_retriever)

        docs_together, docs = sp.pre_fetch_docs("question?")
        assert docs_together is not None
        assert docs is not None
        assert len(docs) == 2
        assert sp.retrieved_docs == docs

    @pytest.mark.unit
    def test_exception_returns_none(self):
        """Cover lines 559-560: exception during pre_fetch_docs."""
        sp = self._make_sp()
        sp.create_retriever = MagicMock(side_effect=RuntimeError("retriever error"))

        result = sp.pre_fetch_docs("question?")
        assert result == (None, None)


# ---------------------------------------------------------------------------
# Additional coverage: pre_fetch_tools full paths (lines 566-614)
# ---------------------------------------------------------------------------


class TestPreFetchToolsFullPaths:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.MongoDB"
        ) as MockMongo, patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.ENABLE_TOOL_PREFETCH = True
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import (
                StreamProcessor,
            )

            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_tool_prefetch_disabled_globally(self):
        """Cover lines 566-567: ENABLE_TOOL_PREFETCH is False."""
        sp = self._make_sp()
        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = False
            result = sp.pre_fetch_tools()
        assert result is None

    @pytest.mark.unit
    def test_tool_prefetch_disabled_per_request(self):
        """Cover lines 570-571: disable_tool_prefetch in request data."""
        sp = self._make_sp()
        sp.data = {"disable_tool_prefetch": True}
        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()
        assert result is None

    @pytest.mark.unit
    def test_no_user_tools_returns_none(self):
        """Cover lines 576-585: no user tools found in DB."""
        sp = self._make_sp()
        sp.data = {}
        sp._get_required_tool_actions = MagicMock(return_value=None)

        mock_user_tools_collection = MagicMock()
        mock_user_tools_collection.find.return_value = []
        sp.db = MagicMock()
        sp.db.__getitem__ = MagicMock(return_value=mock_user_tools_collection)

        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()
        assert result is None

    @pytest.mark.unit
    def test_tools_found_no_filtering(self):
        """Cover lines 586-611: tools found, no filtering enabled."""
        sp = self._make_sp()
        sp.data = {}
        sp._get_required_tool_actions = MagicMock(return_value=None)

        tool_doc = {"_id": "tool1", "name": "my_tool", "config": {}}
        mock_user_tools_collection = MagicMock()
        mock_user_tools_collection.find.return_value = [tool_doc]
        sp.db = MagicMock()
        sp.db.__getitem__ = MagicMock(return_value=mock_user_tools_collection)

        sp._fetch_tool_data = MagicMock(return_value={"action1": "result1"})

        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()

        assert result is not None
        assert "my_tool" in result
        assert "tool1" in result
        sp._fetch_tool_data.assert_called_once_with(tool_doc, None)

    @pytest.mark.unit
    def test_tools_found_with_filtering_matching(self):
        """Cover lines 593-602: filtering enabled, tool matches."""
        sp = self._make_sp()
        sp.data = {}
        sp._get_required_tool_actions = MagicMock(
            return_value={"my_tool": {"action1"}}
        )

        tool_doc = {"_id": "tool1", "name": "my_tool", "config": {}}
        mock_user_tools_collection = MagicMock()
        mock_user_tools_collection.find.return_value = [tool_doc]
        sp.db = MagicMock()
        sp.db.__getitem__ = MagicMock(return_value=mock_user_tools_collection)

        sp._fetch_tool_data = MagicMock(return_value={"action1": "result1"})

        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()

        assert result is not None
        assert "my_tool" in result

    @pytest.mark.unit
    def test_tools_found_with_filtering_no_match(self):
        """Cover lines 601-602: filtering enabled, tool not in required."""
        sp = self._make_sp()
        sp.data = {}
        sp._get_required_tool_actions = MagicMock(
            return_value={"other_tool": {"action1"}}
        )

        tool_doc = {"_id": "tool1", "name": "my_tool", "config": {}}
        mock_user_tools_collection = MagicMock()
        mock_user_tools_collection.find.return_value = [tool_doc]
        sp.db = MagicMock()
        sp.db.__getitem__ = MagicMock(return_value=mock_user_tools_collection)

        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()

        assert result is None

    @pytest.mark.unit
    def test_fetch_tool_data_returns_none_skipped(self):
        """Cover lines 606-611: _fetch_tool_data returns None, tools_data empty."""
        sp = self._make_sp()
        sp.data = {}
        sp._get_required_tool_actions = MagicMock(return_value=None)

        tool_doc = {"_id": "tool1", "name": "my_tool", "config": {}}
        mock_user_tools_collection = MagicMock()
        mock_user_tools_collection.find.return_value = [tool_doc]
        sp.db = MagicMock()
        sp.db.__getitem__ = MagicMock(return_value=mock_user_tools_collection)

        sp._fetch_tool_data = MagicMock(return_value=None)

        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()

        assert result is None

    @pytest.mark.unit
    def test_exception_returns_none(self):
        """Cover lines 612-614: exception during pre_fetch_tools."""
        sp = self._make_sp()
        sp.data = {}
        sp._get_required_tool_actions = MagicMock(return_value=None)

        sp.db = MagicMock()
        sp.db.__getitem__ = MagicMock(side_effect=RuntimeError("DB error"))

        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()

        assert result is None

    @pytest.mark.unit
    def test_tools_filtering_by_id(self):
        """Cover lines 597: required_actions matched by tool_id."""
        sp = self._make_sp()
        sp.data = {}
        sp._get_required_tool_actions = MagicMock(
            return_value={"tool1": {"action1"}}
        )

        tool_doc = {"_id": "tool1", "name": "my_tool", "config": {}}
        mock_user_tools_collection = MagicMock()
        mock_user_tools_collection.find.return_value = [tool_doc]
        sp.db = MagicMock()
        sp.db.__getitem__ = MagicMock(return_value=mock_user_tools_collection)

        sp._fetch_tool_data = MagicMock(return_value={"action1": "result1"})

        with patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s:
            mock_s.ENABLE_TOOL_PREFETCH = True
            result = sp.pre_fetch_tools()

        assert result is not None
        assert "tool1" in result


# ---------------------------------------------------------------------------
# Additional coverage: _fetch_tool_data full paths (lines 619-704)
# ---------------------------------------------------------------------------


class TestFetchToolDataFullPaths:

    def _make_sp(self):
        mock_db = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.MongoDB"
        ) as MockMongo, patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import (
                StreamProcessor,
            )

            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    @pytest.mark.unit
    def test_tool_fails_to_load(self):
        """Cover lines 633-635: tool_manager.load_tool returns None."""
        sp = self._make_sp()
        tool_doc = {"_id": "t1", "name": "my_tool", "config": {}}

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = None
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is None

    @pytest.mark.unit
    def test_tool_no_actions_metadata(self):
        """Cover lines 637-640: tool has no actions metadata."""
        sp = self._make_sp()
        tool_doc = {"_id": "t1", "name": "my_tool", "config": {}}

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = []
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is None

    @pytest.mark.unit
    def test_include_all_actions_when_required_none(self):
        """Cover lines 644-651, 693-695, 700-701: required_actions=None
        means include all actions."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {"properties": {}},
                }
            ]
            mock_tool.execute_action.return_value = "result1"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        assert result["action1"] == "result1"

    @pytest.mark.unit
    def test_include_all_actions_when_none_in_required(self):
        """Cover lines 644-645: required_actions contains None,
        so include_all_actions is True."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {"properties": {}},
                }
            ]
            mock_tool.execute_action.return_value = "result_all"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, {None, "action1"})

        assert result is not None
        assert result["action1"] == "result_all"

    @pytest.mark.unit
    def test_filter_actions_by_allowed_set(self):
        """Cover lines 658-663: action not in allowed_actions is skipped."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {"properties": {}},
                },
                {
                    "name": "action2",
                    "parameters": {"properties": {}},
                },
            ]
            mock_tool.execute_action.return_value = "filtered_result"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            # Only action1 is required; action2 should be skipped
            result = sp._fetch_tool_data(tool_doc, {"action1"})

        assert result is not None
        assert "action1" in result
        assert "action2" not in result
        mock_tool.execute_action.assert_called_once_with("action1")

    @pytest.mark.unit
    def test_action_name_none_skipped(self):
        """Cover lines 655-657: action_meta with name=None is skipped."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {"name": None, "parameters": {"properties": {}}},
                {"name": "action1", "parameters": {"properties": {}}},
            ]
            mock_tool.execute_action.return_value = "result1"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        assert "action1" in result
        mock_tool.execute_action.assert_called_once_with("action1")

    @pytest.mark.unit
    def test_kwargs_from_saved_action(self):
        """Cover lines 666-685: kwargs populated from saved_action parameters."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {"value": "saved_value"},
                        }
                    },
                }
            ],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {"type": "string"},
                        }
                    },
                }
            ]
            mock_tool.execute_action.return_value = "saved_result"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        mock_tool.execute_action.assert_called_once_with(
            "action1", param1="saved_value"
        )

    @pytest.mark.unit
    def test_kwargs_from_tool_config(self):
        """Cover lines 687-688: param found in tool_config."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {"param1": "config_value"},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {"type": "string"},
                        }
                    },
                }
            ]
            mock_tool.execute_action.return_value = "config_result"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        mock_tool.execute_action.assert_called_once_with(
            "action1", param1="config_value"
        )

    @pytest.mark.unit
    def test_kwargs_from_default(self):
        """Cover lines 689-690: param has default in param_spec."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {
                                "type": "string",
                                "default": "default_value",
                            },
                        }
                    },
                }
            ]
            mock_tool.execute_action.return_value = "default_result"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        mock_tool.execute_action.assert_called_once_with(
            "action1", param1="default_value"
        )

    @pytest.mark.unit
    def test_action_execution_exception_continues(self):
        """Cover lines 694-698: action execution raises, continues to next."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {"name": "bad_action", "parameters": {"properties": {}}},
                {"name": "good_action", "parameters": {"properties": {}}},
            ]
            mock_tool.execute_action.side_effect = [
                RuntimeError("boom"),
                "good_result",
            ]
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        assert "good_action" in result
        assert "bad_action" not in result

    @pytest.mark.unit
    def test_all_actions_fail_returns_none(self):
        """Cover line 700: action_results empty after all failures."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {"name": "action1", "parameters": {"properties": {}}},
            ]
            mock_tool.execute_action.side_effect = RuntimeError("fail")
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is None

    @pytest.mark.unit
    def test_outer_exception_returns_none(self):
        """Cover lines 702-704: outer exception in _fetch_tool_data."""
        sp = self._make_sp()
        tool_doc = {"_id": "t1", "name": "my_tool", "config": {}}

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            MockTM.side_effect = RuntimeError("import error")
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is None

    @pytest.mark.unit
    def test_saved_action_value_none_falls_through(self):
        """Cover lines 682-684: saved_action param_value is None,
        falls through to tool_config/default."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {"param1": "config_fallback"},
            "actions": [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {"value": None},
                        }
                    },
                }
            ],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {"type": "string"},
                        }
                    },
                }
            ]
            mock_tool.execute_action.return_value = "fallback_result"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        # Should fall through to tool_config value
        mock_tool.execute_action.assert_called_once_with(
            "action1", param1="config_fallback"
        )

    @pytest.mark.unit
    def test_saved_action_param_not_in_saved_props(self):
        """Cover lines 677-680: saved_action exists but param not
        in saved_props, falls to tool_config."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {"param1": "from_config"},
            "actions": [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "other_param": {"value": "other_val"},
                        }
                    },
                }
            ],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {"type": "string"},
                        }
                    },
                }
            ]
            mock_tool.execute_action.return_value = "result"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        mock_tool.execute_action.assert_called_once_with(
            "action1", param1="from_config"
        )

    @pytest.mark.unit
    def test_no_saved_action_no_config_no_default(self):
        """Cover lines 676-690: param not in saved_action, not in
        tool_config, no default => kwargs empty for that param."""
        sp = self._make_sp()
        tool_doc = {
            "_id": "t1",
            "name": "my_tool",
            "config": {},
            "actions": [],
        }

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as MockTM:
            mock_tool = MagicMock()
            mock_tool.get_actions_metadata.return_value = [
                {
                    "name": "action1",
                    "parameters": {
                        "properties": {
                            "param1": {"type": "string"},
                        }
                    },
                }
            ]
            mock_tool.execute_action.return_value = "no_param_result"
            mock_manager = MagicMock()
            mock_manager.load_tool.return_value = mock_tool
            MockTM.return_value = mock_manager
            result = sp._fetch_tool_data(tool_doc, None)

        assert result is not None
        # param1 has no source, so kwargs should be empty
        mock_tool.execute_action.assert_called_once_with("action1")


# ---------------------------------------------------------------------------
# Additional coverage: _get_prompt_content exception branch (lines 722-724),
# _get_required_tool_actions extraction + error (lines 740-750),
# _fetch_memory_tool_data (lines 754-755, 759-760, 764-765, 769-771, 775-776),
# create_agent (lines 779-806, 811-822)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPromptContentGenericException:
    """Cover lines 722-724: generic exception in _get_prompt_content."""

    def _make_sp(self):
        mock_db = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.MongoDB"
        ) as MockMongo, patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import (
                StreamProcessor,
            )

            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    def test_generic_exception_sets_none(self):
        sp = self._make_sp()
        sp.agent_config = {"prompt_id": "some_prompt"}
        sp._prompt_content = None
        with patch(
            "application.api.answer.services.stream_processor.get_prompt",
            side_effect=RuntimeError("DB down"),
        ):
            result = sp._get_prompt_content()
        assert result is None
        assert sp._prompt_content is None


@pytest.mark.unit
class TestGetRequiredToolActionsExtract:
    """Cover lines 740-750: TemplateEngine extraction + exception."""

    def _make_sp(self):
        mock_db = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.MongoDB"
        ) as MockMongo, patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import (
                StreamProcessor,
            )

            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    def test_template_engine_extraction_success(self):
        sp = self._make_sp()
        sp._required_tool_actions = None
        sp._get_prompt_content = MagicMock(
            return_value="Hello {{tool.action}} world"
        )
        mock_engine = MagicMock()
        mock_engine.extract_tool_usages.return_value = {"tool": {"action"}}
        with patch(
            "application.templates.template_engine.TemplateEngine",
            return_value=mock_engine,
        ):
            result = sp._get_required_tool_actions()
        assert result == {"tool": {"action"}}

    def test_template_engine_extraction_exception(self):
        sp = self._make_sp()
        sp._required_tool_actions = None
        sp._get_prompt_content = MagicMock(
            return_value="Hello {{tool.action}} world"
        )
        with patch(
            "application.templates.template_engine.TemplateEngine",
            side_effect=RuntimeError("import err"),
        ):
            result = sp._get_required_tool_actions()
        assert result == {}


@pytest.mark.unit
class TestFetchMemoryToolData:
    """Cover lines 754-755, 759-760, 764-765, 769-771."""

    def _make_sp(self):
        mock_db = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.MongoDB"
        ) as MockMongo, patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import (
                StreamProcessor,
            )

            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    def test_memory_tool_success(self):
        """Cover lines 759-760, 764, 769: success path returning data."""
        sp = self._make_sp()
        tool_doc = {"_id": "t1", "config": {"key": "val"}}
        mock_memory_tool = MagicMock()
        mock_memory_tool.execute_action.return_value = "root content here"
        with patch(
            "application.agents.tools.memory.MemoryTool",
            return_value=mock_memory_tool,
        ):
            result = sp._fetch_memory_tool_data(tool_doc)
        assert result == {"root": "root content here", "available": True}

    def test_memory_tool_error_in_view(self):
        """Cover lines 764-766: view returns error string."""
        sp = self._make_sp()
        tool_doc = {"_id": "t1", "config": {}}
        mock_memory_tool = MagicMock()
        mock_memory_tool.execute_action.return_value = "Error: no data"
        with patch(
            "application.agents.tools.memory.MemoryTool",
            return_value=mock_memory_tool,
        ):
            result = sp._fetch_memory_tool_data(tool_doc)
        assert result is None

    def test_memory_tool_empty_view(self):
        """Cover line 766: empty root_view."""
        sp = self._make_sp()
        tool_doc = {"_id": "t1", "config": {}}
        mock_memory_tool = MagicMock()
        mock_memory_tool.execute_action.return_value = "   "
        with patch(
            "application.agents.tools.memory.MemoryTool",
            return_value=mock_memory_tool,
        ):
            result = sp._fetch_memory_tool_data(tool_doc)
        assert result is None

    def test_memory_tool_exception(self):
        """Cover lines 770-771: exception returns None."""
        sp = self._make_sp()
        tool_doc = {"_id": "t1", "config": {}}
        with patch(
            "application.agents.tools.memory.MemoryTool",
            side_effect=RuntimeError("fail"),
        ):
            result = sp._fetch_memory_tool_data(tool_doc)
        assert result is None


@pytest.mark.unit
class TestCreateAgentPaths:
    """Cover lines 779-806, 811-816, 820-822: create_agent various prompt paths."""

    def _make_sp(self):
        mock_db = MagicMock()
        with patch(
            "application.api.answer.services.stream_processor.MongoDB"
        ) as MockMongo, patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "docsgpt"
            mock_settings.LLM_PROVIDER = "openai"
            MockMongo.get_client.return_value = {"docsgpt": mock_db}

            from application.api.answer.services.stream_processor import (
                StreamProcessor,
            )

            sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"})
        return sp

    def test_create_agent_agentic_preset(self):
        """Cover lines 786-796: raw_prompt is None, agentic preset path."""
        sp = self._make_sp()
        sp._prompt_content = None
        sp._get_prompt_content = MagicMock(return_value=None)
        sp.agent_config = {
            "agent_type": "agentic",
            "prompt_id": "default",
            "user_api_key": None,
            "models": ["m1", "m2"],
        }
        sp.model_id = "m1"
        sp.prompt_renderer = MagicMock()
        sp.prompt_renderer.render_prompt.return_value = "rendered"
        sp.data = {}
        sp.history = []
        sp.retrieved_docs = []
        sp.attachments = []
        sp.source = {}
        sp.retriever_config = {}
        sp.conversation_id = None

        mock_llm = MagicMock()
        mock_handler = MagicMock()
        mock_agent = MagicMock()

        with patch(
            "application.api.answer.services.stream_processor.get_prompt",
            return_value="agentic prompt",
        ) as mock_gp, patch(
            "application.api.answer.services.stream_processor.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "application.api.answer.services.stream_processor.get_api_key_for_provider",
            return_value="key",
        ), patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s, patch(
            "application.llm.llm_creator.LLMCreator.create_llm",
            return_value=mock_llm,
        ), patch(
            "application.llm.handlers.handler_creator.LLMHandlerCreator.create_handler",
            return_value=mock_handler,
        ), patch(
            "application.agents.agent_creator.AgentCreator.create_agent",
            return_value=mock_agent,
        ):
            mock_s.LLM_PROVIDER = "openai"
            sp.create_agent(docs_together="docs", docs=[], tools_data={})
        # Verify agentic_default prompt was requested
        mock_gp.assert_any_call("agentic_default", sp.prompts_collection)

    def test_create_agent_non_agentic_no_prompt(self):
        """Cover lines 794-796: non-agentic agent, raw_prompt None, uses normal preset."""
        sp = self._make_sp()
        sp._prompt_content = None
        sp._get_prompt_content = MagicMock(return_value=None)
        sp.agent_config = {
            "agent_type": "classic",
            "prompt_id": "default",
            "user_api_key": None,
            "models": [],
        }
        sp.model_id = None
        sp.prompt_renderer = MagicMock()
        sp.prompt_renderer.render_prompt.return_value = "rendered"
        sp.data = {}
        sp.history = []
        sp.retrieved_docs = []
        sp.attachments = []
        sp.source = {}
        sp.retriever_config = {}
        sp.conversation_id = None
        sp.decoded_token = {"sub": "u"}

        mock_llm = MagicMock()
        mock_handler = MagicMock()
        mock_agent = MagicMock()

        with patch(
            "application.api.answer.services.stream_processor.get_prompt",
            return_value="normal prompt",
        ) as mock_gp, patch(
            "application.api.answer.services.stream_processor.get_provider_from_model_id",
            return_value=None,
        ), patch(
            "application.api.answer.services.stream_processor.get_api_key_for_provider",
            return_value="key",
        ), patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s, patch(
            "application.llm.llm_creator.LLMCreator.create_llm",
            return_value=mock_llm,
        ), patch(
            "application.llm.handlers.handler_creator.LLMHandlerCreator.create_handler",
            return_value=mock_handler,
        ), patch(
            "application.agents.agent_creator.AgentCreator.create_agent",
            return_value=mock_agent,
        ):
            mock_s.LLM_PROVIDER = "openai"
            sp.create_agent()
        mock_gp.assert_any_call("default", sp.prompts_collection)

    def test_create_agent_backup_models_computed(self):
        """Cover lines 820-822: backup_models excludes current model."""
        sp = self._make_sp()
        sp._prompt_content = None
        sp._get_prompt_content = MagicMock(return_value="existing prompt")
        sp.agent_config = {
            "agent_type": "classic",
            "prompt_id": "default",
            "user_api_key": None,
            "models": ["m1", "m2", "m3"],
        }
        sp.model_id = "m2"
        sp.prompt_renderer = MagicMock()
        sp.prompt_renderer.render_prompt.return_value = "rendered"
        sp.data = {}
        sp.history = []
        sp.retrieved_docs = []
        sp.attachments = []
        sp.source = {}
        sp.retriever_config = {}
        sp.conversation_id = None
        sp.decoded_token = {"sub": "u"}

        captured_kwargs = {}

        def capture_create(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        with patch(
            "application.api.answer.services.stream_processor.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "application.api.answer.services.stream_processor.get_api_key_for_provider",
            return_value="key",
        ), patch(
            "application.api.answer.services.stream_processor.settings"
        ) as mock_s, patch(
            "application.llm.llm_creator.LLMCreator.create_llm",
            side_effect=capture_create,
        ), patch(
            "application.llm.handlers.handler_creator.LLMHandlerCreator.create_handler",
            return_value=MagicMock(),
        ), patch(
            "application.agents.agent_creator.AgentCreator.create_agent",
            return_value=MagicMock(),
        ):
            mock_s.LLM_PROVIDER = "openai"
            sp.create_agent()
        assert captured_kwargs["backup_models"] == ["m1", "m3"]
