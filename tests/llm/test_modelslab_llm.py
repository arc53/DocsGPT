"""Tests for the ModelsLab LLM provider."""
from unittest.mock import MagicMock, patch

import pytest

from application.llm.modelslab import MODELSLAB_BASE_URL, ModelsLabLLM


class TestModelsLabLLM:
    """Tests for ModelsLabLLM provider."""

    def test_inherits_openai_llm(self):
        """ModelsLabLLM should extend OpenAILLM."""
        from application.llm.openai import OpenAILLM

        assert issubclass(ModelsLabLLM, OpenAILLM)

    def test_default_base_url(self):
        """MODELSLAB_BASE_URL constant should point to ModelsLab uncensored chat API."""
        assert MODELSLAB_BASE_URL == "https://modelslab.com/api/uncensored-chat/v1"

    @patch("application.llm.openai.OpenAI")
    def test_uses_modelslab_base_url_when_no_override(self, mock_openai):
        """When no base_url is provided, use MODELSLAB_BASE_URL."""
        mock_openai.return_value = MagicMock()
        llm = ModelsLabLLM(api_key="test-key")
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs.get("base_url") == MODELSLAB_BASE_URL

    @patch("application.llm.openai.OpenAI")
    def test_custom_base_url_override(self, mock_openai):
        """When base_url is provided, it should override the default."""
        mock_openai.return_value = MagicMock()
        custom_url = "https://custom.modelslab.com/v1"
        llm = ModelsLabLLM(api_key="test-key", base_url=custom_url)
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs.get("base_url") == custom_url

    @patch("application.llm.openai.OpenAI")
    def test_uses_provided_api_key(self, mock_openai):
        """API key passed directly should be used."""
        mock_openai.return_value = MagicMock()
        llm = ModelsLabLLM(api_key="modelslab-key-123")
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs.get("api_key") == "modelslab-key-123"

    @patch("application.llm.openai.OpenAI")
    @patch("application.llm.modelslab.settings")
    def test_falls_back_to_settings_api_key(self, mock_settings, mock_openai):
        """Falls back to MODELSLAB_API_KEY from settings when no key provided."""
        mock_openai.return_value = MagicMock()
        mock_settings.MODELSLAB_API_KEY = "settings-key"
        mock_settings.API_KEY = None
        llm = ModelsLabLLM()
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs.get("api_key") == "settings-key"


class TestModelsLabRegistration:
    """Tests for ModelsLab registration in LLMCreator."""

    def test_modelslab_in_llm_creator(self):
        """ModelsLab should be registered in LLMCreator.llms."""
        from application.llm.llm_creator import LLMCreator

        assert "modelslab" in LLMCreator.llms
        assert LLMCreator.llms["modelslab"] is ModelsLabLLM

    def test_modelslab_provider_enum(self):
        """ModelProvider enum should include MODELSLAB."""
        from application.core.model_settings import ModelProvider

        assert hasattr(ModelProvider, "MODELSLAB")
        assert ModelProvider.MODELSLAB.value == "modelslab"

    def test_modelslab_models_defined(self):
        """MODELSLAB_MODELS should contain at least one model."""
        from application.core.model_configs import MODELSLAB_MODELS
        from application.core.model_settings import ModelProvider

        assert len(MODELSLAB_MODELS) > 0
        for model in MODELSLAB_MODELS:
            assert model.provider == ModelProvider.MODELSLAB
            assert model.id
            assert model.display_name
