"""Tests for application/api/answer/services/compression/orchestrator.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.api.answer.services.compression.orchestrator import (
    CompressionOrchestrator,
)
from application.api.answer.services.compression.types import (
    CompressionMetadata,
    CompressionResult,
)


@pytest.fixture
def mock_conversation_service():
    svc = MagicMock()
    return svc


@pytest.fixture
def mock_threshold_checker():
    checker = MagicMock()
    return checker


@pytest.fixture
def orchestrator(mock_conversation_service, mock_threshold_checker):
    return CompressionOrchestrator(
        conversation_service=mock_conversation_service,
        threshold_checker=mock_threshold_checker,
    )


@pytest.fixture
def sample_conversation():
    return {
        "queries": [
            {"prompt": "q0", "response": "r0"},
            {"prompt": "q1", "response": "r1"},
            {"prompt": "q2", "response": "r2"},
        ],
        "compression_metadata": {},
        "agent_id": "agent-1",
    }


@pytest.fixture
def decoded_token():
    return {"sub": "user123"}


@pytest.mark.unit
class TestCompressIfNeeded:
    def test_conversation_not_found_returns_failure(
        self, orchestrator, mock_conversation_service
    ):
        mock_conversation_service.get_conversation.return_value = None

        result = orchestrator.compress_if_needed(
            conversation_id="conv1",
            user_id="user1",
            model_id="gpt-4",
            decoded_token={"sub": "user1"},
        )

        assert result.success is False
        assert "not found" in result.error

    def test_no_compression_needed(
        self,
        orchestrator,
        mock_conversation_service,
        mock_threshold_checker,
        sample_conversation,
    ):
        mock_conversation_service.get_conversation.return_value = sample_conversation
        mock_threshold_checker.should_compress.return_value = False

        result = orchestrator.compress_if_needed(
            conversation_id="conv1",
            user_id="user1",
            model_id="gpt-4",
            decoded_token={"sub": "user1"},
        )

        assert result.success is True
        assert result.compression_performed is False
        assert len(result.recent_queries) == 3

    def test_compression_performed_successfully(
        self,
        orchestrator,
        mock_conversation_service,
        mock_threshold_checker,
        sample_conversation,
        decoded_token,
    ):
        mock_conversation_service.get_conversation.return_value = sample_conversation
        mock_threshold_checker.should_compress.return_value = True

        mock_metadata = MagicMock(spec=CompressionMetadata)
        mock_metadata.compression_ratio = 5.0
        mock_metadata.original_token_count = 1000
        mock_metadata.compressed_token_count = 200
        mock_metadata.to_dict.return_value = {"query_index": 2}

        with patch.object(
            orchestrator, "_perform_compression"
        ) as mock_perform:
            mock_perform.return_value = CompressionResult.success_with_compression(
                "compressed summary",
                [{"prompt": "q2", "response": "r2"}],
                mock_metadata,
            )

            result = orchestrator.compress_if_needed(
                conversation_id="conv1",
                user_id="user1",
                model_id="gpt-4",
                decoded_token=decoded_token,
            )

            assert result.success is True
            assert result.compression_performed is True
            assert result.compressed_summary == "compressed summary"
            mock_perform.assert_called_once()

    def test_exception_returns_failure(
        self,
        orchestrator,
        mock_conversation_service,
    ):
        mock_conversation_service.get_conversation.side_effect = RuntimeError("DB down")

        result = orchestrator.compress_if_needed(
            conversation_id="conv1",
            user_id="user1",
            model_id="gpt-4",
            decoded_token={"sub": "user1"},
        )

        assert result.success is False
        assert "DB down" in result.error

    def test_custom_query_tokens(
        self,
        orchestrator,
        mock_conversation_service,
        mock_threshold_checker,
        sample_conversation,
    ):
        mock_conversation_service.get_conversation.return_value = sample_conversation
        mock_threshold_checker.should_compress.return_value = False

        orchestrator.compress_if_needed(
            conversation_id="conv1",
            user_id="user1",
            model_id="gpt-4",
            decoded_token={"sub": "user1"},
            current_query_tokens=1000,
        )

        # user_id flows through so BYOM custom-model UUIDs resolve to
        # the user's declared context window in the threshold check.
        mock_threshold_checker.should_compress.assert_called_once_with(
            sample_conversation, "gpt-4", 1000, user_id="user1"
        )


@pytest.mark.unit
class TestPerformCompression:
    @patch(
        "application.api.answer.services.compression.orchestrator.get_provider_from_model_id"
    )
    @patch(
        "application.api.answer.services.compression.orchestrator.get_api_key_for_provider"
    )
    @patch("application.api.answer.services.compression.orchestrator.LLMCreator")
    @patch("application.api.answer.services.compression.orchestrator.CompressionService")
    @patch("application.api.answer.services.compression.orchestrator.settings")
    def test_successful_compression(
        self,
        mock_settings,
        MockCompressionService,
        MockLLMCreator,
        mock_get_api_key,
        mock_get_provider,
        mock_conversation_service,
        mock_threshold_checker,
        sample_conversation,
        decoded_token,
    ):
        mock_settings.COMPRESSION_MODEL_OVERRIDE = None
        mock_get_provider.return_value = "openai"
        mock_get_api_key.return_value = "sk-test"
        MockLLMCreator.create_llm.return_value = MagicMock()

        mock_metadata = MagicMock(spec=CompressionMetadata)
        mock_metadata.compression_ratio = 5.0
        mock_metadata.original_token_count = 500
        mock_metadata.compressed_token_count = 100

        mock_svc_instance = MagicMock()
        mock_svc_instance.compress_and_save.return_value = mock_metadata
        mock_svc_instance.get_compressed_context.return_value = (
            "compressed text",
            [{"prompt": "q2", "response": "r2"}],
        )
        MockCompressionService.return_value = mock_svc_instance

        # After compression, reload conversation
        mock_conversation_service.get_conversation.return_value = sample_conversation

        orch = CompressionOrchestrator(
            conversation_service=mock_conversation_service,
            threshold_checker=mock_threshold_checker,
        )

        result = orch._perform_compression(
            "conv1", sample_conversation, "gpt-4", decoded_token
        )

        assert result.success is True
        assert result.compression_performed is True
        assert result.compressed_summary == "compressed text"
        mock_svc_instance.compress_and_save.assert_called_once()

    @patch(
        "application.api.answer.services.compression.orchestrator.get_provider_from_model_id"
    )
    @patch(
        "application.api.answer.services.compression.orchestrator.get_api_key_for_provider"
    )
    @patch("application.api.answer.services.compression.orchestrator.LLMCreator")
    @patch("application.api.answer.services.compression.orchestrator.settings")
    def test_uses_compression_model_override(
        self,
        mock_settings,
        MockLLMCreator,
        mock_get_api_key,
        mock_get_provider,
        mock_conversation_service,
        mock_threshold_checker,
        decoded_token,
    ):
        mock_settings.COMPRESSION_MODEL_OVERRIDE = "gpt-3.5-turbo"
        mock_get_provider.return_value = "openai"
        mock_get_api_key.return_value = "sk-test"
        MockLLMCreator.create_llm.return_value = MagicMock()

        conversation = {"queries": [{"prompt": "q", "response": "r"}], "agent_id": "a"}

        with patch(
            "application.api.answer.services.compression.orchestrator.CompressionService"
        ) as MockCS:
            mock_svc = MagicMock()
            mock_svc.compress_and_save.return_value = MagicMock(
                compression_ratio=3.0,
                original_token_count=300,
                compressed_token_count=100,
            )
            mock_svc.get_compressed_context.return_value = ("s", [])
            MockCS.return_value = mock_svc

            mock_conversation_service.get_conversation.return_value = conversation

            orch = CompressionOrchestrator(
                conversation_service=mock_conversation_service,
                threshold_checker=mock_threshold_checker,
            )
            orch._perform_compression("c1", conversation, "gpt-4", decoded_token)

            # Verify the override model was used. user_id flows from
            # decoded_token['sub'] so per-user BYOM custom-model UUIDs
            # resolve.
            mock_get_provider.assert_called_with(
                "gpt-3.5-turbo", user_id=decoded_token["sub"]
            )

    @patch(
        "application.api.answer.services.compression.orchestrator.get_provider_from_model_id"
    )
    @patch(
        "application.api.answer.services.compression.orchestrator.get_api_key_for_provider"
    )
    @patch("application.api.answer.services.compression.orchestrator.LLMCreator")
    @patch("application.api.answer.services.compression.orchestrator.CompressionService")
    @patch("application.api.answer.services.compression.orchestrator.settings")
    def test_no_queries_returns_no_compression(
        self,
        mock_settings,
        MockCompressionService,
        MockLLMCreator,
        mock_get_api_key,
        mock_get_provider,
        mock_conversation_service,
        mock_threshold_checker,
        decoded_token,
    ):
        mock_settings.COMPRESSION_MODEL_OVERRIDE = None
        mock_get_provider.return_value = "openai"
        mock_get_api_key.return_value = "sk-test"
        MockLLMCreator.create_llm.return_value = MagicMock()

        conversation = {"queries": [], "agent_id": "a"}

        orch = CompressionOrchestrator(
            conversation_service=mock_conversation_service,
            threshold_checker=mock_threshold_checker,
        )
        result = orch._perform_compression("c1", conversation, "gpt-4", decoded_token)

        assert result.success is True
        assert result.compression_performed is False

    def test_exception_returns_failure(
        self,
        mock_conversation_service,
        mock_threshold_checker,
        decoded_token,
    ):
        conversation = {
            "queries": [{"prompt": "q", "response": "r"}],
            "agent_id": "a",
        }

        with patch(
            "application.api.answer.services.compression.orchestrator.settings"
        ) as mock_settings, patch(
            "application.api.answer.services.compression.orchestrator.get_provider_from_model_id",
            side_effect=RuntimeError("provider error"),
        ):
            mock_settings.COMPRESSION_MODEL_OVERRIDE = None

            orch = CompressionOrchestrator(
                conversation_service=mock_conversation_service,
                threshold_checker=mock_threshold_checker,
            )
            result = orch._perform_compression(
                "c1", conversation, "gpt-4", decoded_token
            )

            assert result.success is False
            assert "provider error" in result.error


@pytest.mark.unit
class TestCompressMidExecution:
    def test_with_provided_conversation(
        self,
        orchestrator,
        sample_conversation,
        decoded_token,
    ):
        with patch.object(
            orchestrator, "_perform_compression"
        ) as mock_perform:
            mock_perform.return_value = CompressionResult.success_no_compression([])

            orchestrator.compress_mid_execution(
                conversation_id="conv1",
                user_id="user1",
                model_id="gpt-4",
                decoded_token=decoded_token,
                current_conversation=sample_conversation,
            )

            mock_perform.assert_called_once_with(
                "conv1",
                sample_conversation,
                "gpt-4",
                decoded_token,
                user_id="user1",
                model_user_id=None,
            )

    def test_loads_conversation_when_not_provided(
        self,
        orchestrator,
        mock_conversation_service,
        sample_conversation,
        decoded_token,
    ):
        mock_conversation_service.get_conversation.return_value = sample_conversation

        with patch.object(
            orchestrator, "_perform_compression"
        ) as mock_perform:
            mock_perform.return_value = CompressionResult.success_no_compression([])

            orchestrator.compress_mid_execution(
                conversation_id="conv1",
                user_id="user1",
                model_id="gpt-4",
                decoded_token=decoded_token,
            )

            mock_conversation_service.get_conversation.assert_called_once_with(
                "conv1", "user1"
            )
            mock_perform.assert_called_once()

    def test_conversation_not_found_returns_failure(
        self,
        orchestrator,
        mock_conversation_service,
        decoded_token,
    ):
        mock_conversation_service.get_conversation.return_value = None

        result = orchestrator.compress_mid_execution(
            conversation_id="conv1",
            user_id="user1",
            model_id="gpt-4",
            decoded_token=decoded_token,
        )

        assert result.success is False
        assert "not found" in result.error

    def test_exception_returns_failure(
        self,
        orchestrator,
        mock_conversation_service,
        decoded_token,
    ):
        mock_conversation_service.get_conversation.side_effect = RuntimeError("fail")

        result = orchestrator.compress_mid_execution(
            conversation_id="conv1",
            user_id="user1",
            model_id="gpt-4",
            decoded_token=decoded_token,
        )

        assert result.success is False
        assert "fail" in result.error


@pytest.mark.unit
class TestOrchestratorInit:
    def test_default_threshold_checker(self, mock_conversation_service):
        orch = CompressionOrchestrator(
            conversation_service=mock_conversation_service
        )
        assert orch.threshold_checker is not None
        assert orch.conversation_service is mock_conversation_service

    def test_custom_threshold_checker(
        self, mock_conversation_service, mock_threshold_checker
    ):
        orch = CompressionOrchestrator(
            conversation_service=mock_conversation_service,
            threshold_checker=mock_threshold_checker,
        )
        assert orch.threshold_checker is mock_threshold_checker
