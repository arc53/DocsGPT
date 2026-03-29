"""Tests for application/api/answer/services/stream_processor.py — get_prompt and helpers."""

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
