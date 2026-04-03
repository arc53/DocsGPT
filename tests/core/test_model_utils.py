from unittest.mock import MagicMock, patch

import pytest

from application.core.model_settings import (
    AvailableModel,
    ModelCapabilities,
    ModelProvider,
    ModelRegistry,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset ModelRegistry singleton between tests."""
    ModelRegistry._instance = None
    ModelRegistry._initialized = False
    yield
    ModelRegistry._instance = None
    ModelRegistry._initialized = False


def _make_model(
    model_id="test-model",
    provider=ModelProvider.OPENAI,
    display_name="Test Model",
    context_window=128000,
    supports_tools=True,
    supports_structured_output=False,
    supported_attachment_types=None,
    enabled=True,
    base_url=None,
):
    return AvailableModel(
        id=model_id,
        provider=provider,
        display_name=display_name,
        capabilities=ModelCapabilities(
            supports_tools=supports_tools,
            supports_structured_output=supports_structured_output,
            supported_attachment_types=supported_attachment_types or [],
            context_window=context_window,
        ),
        enabled=enabled,
        base_url=base_url,
    )


# ── get_api_key_for_provider ─────────────────────────────────────────────────


class TestGetApiKeyForProvider:
    """settings is lazily imported inside the function body, so we patch
    at application.core.settings.settings (the actual module attribute)."""

    @pytest.mark.unit
    def test_openai_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "sk-openai"
            mock_settings.API_KEY = "sk-fallback"
            mock_settings.OPEN_ROUTER_API_KEY = None
            mock_settings.NOVITA_API_KEY = None
            mock_settings.ANTHROPIC_API_KEY = None
            mock_settings.GOOGLE_API_KEY = None
            mock_settings.GROQ_API_KEY = None
            mock_settings.HUGGINGFACE_API_KEY = None

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("openai") == "sk-openai"

    @pytest.mark.unit
    def test_anthropic_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.ANTHROPIC_API_KEY = "sk-anthropic"
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("anthropic") == "sk-anthropic"

    @pytest.mark.unit
    def test_google_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.GOOGLE_API_KEY = "sk-google"
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("google") == "sk-google"

    @pytest.mark.unit
    def test_groq_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.GROQ_API_KEY = "sk-groq"
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("groq") == "sk-groq"

    @pytest.mark.unit
    def test_openrouter_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.OPEN_ROUTER_API_KEY = "sk-or"
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("openrouter") == "sk-or"

    @pytest.mark.unit
    def test_novita_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.NOVITA_API_KEY = "sk-novita"
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("novita") == "sk-novita"

    @pytest.mark.unit
    def test_qianfan_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.QIANFAN_API_KEY = "sk-qianfan"
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("qianfan") == "sk-qianfan"

    @pytest.mark.unit
    def test_huggingface_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.HUGGINGFACE_API_KEY = "hf-key"
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("huggingface") == "hf-key"

    @pytest.mark.unit
    def test_docsgpt_returns_fallback(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("docsgpt") == "sk-fallback"

    @pytest.mark.unit
    def test_llama_cpp_returns_fallback(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("llama.cpp") == "sk-fallback"

    @pytest.mark.unit
    def test_unknown_provider_returns_fallback(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.API_KEY = "sk-fallback"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("unknown_provider") == "sk-fallback"

    @pytest.mark.unit
    def test_azure_openai_key(self):
        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.API_KEY = "sk-azure"

            from application.core.model_utils import get_api_key_for_provider

            assert get_api_key_for_provider("azure_openai") == "sk-azure"


# ── get_all_available_models ─────────────────────────────────────────────────


class TestGetAllAvailableModels:
    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_returns_enabled_models_as_dict(self, mock_get_instance):
        model_a = _make_model("model-a", display_name="Model A")
        model_b = _make_model("model-b", display_name="Model B")
        mock_registry = MagicMock()
        mock_registry.get_enabled_models.return_value = [model_a, model_b]
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_all_available_models

        result = get_all_available_models()

        assert "model-a" in result
        assert "model-b" in result
        assert result["model-a"]["display_name"] == "Model A"
        assert result["model-b"]["display_name"] == "Model B"

    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_empty_registry(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.get_enabled_models.return_value = []
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_all_available_models

        assert get_all_available_models() == {}


# ── validate_model_id ────────────────────────────────────────────────────────


class TestValidateModelId:
    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_exists(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.model_exists.return_value = True
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import validate_model_id

        assert validate_model_id("gpt-4") is True

    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_not_exists(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.model_exists.return_value = False
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import validate_model_id

        assert validate_model_id("nonexistent") is False


# ── get_model_capabilities ───────────────────────────────────────────────────


class TestGetModelCapabilities:
    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_found(self, mock_get_instance):
        model = _make_model(
            "gpt-4",
            context_window=8192,
            supports_tools=True,
            supports_structured_output=True,
            supported_attachment_types=["image/png"],
        )
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = model
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_model_capabilities

        caps = get_model_capabilities("gpt-4")

        assert caps is not None
        assert caps["supported_attachment_types"] == ["image/png"]
        assert caps["supports_tools"] is True
        assert caps["supports_structured_output"] is True
        assert caps["context_window"] == 8192

    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_not_found(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = None
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_model_capabilities

        assert get_model_capabilities("nonexistent") is None


# ── get_default_model_id ─────────────────────────────────────────────────────


class TestGetDefaultModelId:
    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_returns_default(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.default_model_id = "gpt-4"
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_default_model_id

        assert get_default_model_id() == "gpt-4"


# ── get_provider_from_model_id ───────────────────────────────────────────────


class TestGetProviderFromModelId:
    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_found(self, mock_get_instance):
        model = _make_model("gpt-4", provider=ModelProvider.OPENAI)
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = model
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_provider_from_model_id

        assert get_provider_from_model_id("gpt-4") == "openai"

    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_not_found(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = None
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_provider_from_model_id

        assert get_provider_from_model_id("nonexistent") is None


# ── get_token_limit ──────────────────────────────────────────────────────────


class TestGetTokenLimit:
    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_found(self, mock_get_instance):
        model = _make_model("gpt-4", context_window=8192)
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = model
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_token_limit

        assert get_token_limit("gpt-4") == 8192

    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_not_found_returns_default(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = None
        mock_get_instance.return_value = mock_registry

        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.DEFAULT_LLM_TOKEN_LIMIT = 128000

            from application.core.model_utils import get_token_limit

            assert get_token_limit("nonexistent") == 128000


# ── get_base_url_for_model ───────────────────────────────────────────────────


class TestGetBaseUrlForModel:
    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_with_base_url(self, mock_get_instance):
        model = _make_model("custom-model", base_url="http://localhost:8080")
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = model
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_base_url_for_model

        assert get_base_url_for_model("custom-model") == "http://localhost:8080"

    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_without_base_url(self, mock_get_instance):
        model = _make_model("gpt-4", base_url=None)
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = model
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_base_url_for_model

        assert get_base_url_for_model("gpt-4") is None

    @pytest.mark.unit
    @patch("application.core.model_utils.ModelRegistry.get_instance")
    def test_model_not_found(self, mock_get_instance):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = None
        mock_get_instance.return_value = mock_registry

        from application.core.model_utils import get_base_url_for_model

        assert get_base_url_for_model("nonexistent") is None
