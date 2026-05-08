"""Tests for application/core/model_settings.py.

The provider-specific load logic that used to live in private
``_add_<X>_models`` methods now lives in plugin classes under
``application/llm/providers/`` and YAML catalogs under
``application/core/models/``. End-to-end coverage of the registry +
plugin pipeline is in ``tests/core/test_model_registry_yaml.py``.

This file covers the data classes (``AvailableModel``,
``ModelCapabilities``, ``ModelProvider``) and the singleton/lookup
contract on ``ModelRegistry``.
"""

from unittest.mock import patch

import pytest

from application.core.model_settings import (
    AvailableModel,
    ModelCapabilities,
    ModelProvider,
    ModelRegistry,
)


class TestModelProvider:
    @pytest.mark.unit
    def test_all_providers_exist(self):
        assert ModelProvider.OPENAI == "openai"
        assert ModelProvider.ANTHROPIC == "anthropic"
        assert ModelProvider.GOOGLE == "google"
        assert ModelProvider.GROQ == "groq"
        assert ModelProvider.DOCSGPT == "docsgpt"
        assert ModelProvider.HUGGINGFACE == "huggingface"
        assert ModelProvider.NOVITA == "novita"
        assert ModelProvider.OPENROUTER == "openrouter"
        assert ModelProvider.SAGEMAKER == "sagemaker"
        assert ModelProvider.PREMAI == "premai"
        assert ModelProvider.LLAMA_CPP == "llama.cpp"
        assert ModelProvider.AZURE_OPENAI == "azure_openai"


class TestModelCapabilities:
    @pytest.mark.unit
    def test_defaults(self):
        caps = ModelCapabilities()
        assert caps.supports_tools is False
        assert caps.supports_structured_output is False
        assert caps.supports_streaming is True
        assert caps.supported_attachment_types == []
        assert caps.context_window == 128000
        assert caps.input_cost_per_token is None
        assert caps.output_cost_per_token is None

    @pytest.mark.unit
    def test_custom_values(self):
        caps = ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            context_window=32000,
            input_cost_per_token=0.001,
        )
        assert caps.supports_tools is True
        assert caps.context_window == 32000


class TestAvailableModel:
    @pytest.mark.unit
    def test_to_dict_basic(self):
        model = AvailableModel(
            id="gpt-4",
            provider=ModelProvider.OPENAI,
            display_name="GPT-4",
            description="OpenAI GPT-4",
        )
        d = model.to_dict()
        assert d["id"] == "gpt-4"
        assert d["provider"] == "openai"
        assert d["display_name"] == "GPT-4"
        assert d["enabled"] is True
        assert "base_url" not in d

    @pytest.mark.unit
    def test_to_dict_with_base_url(self):
        model = AvailableModel(
            id="local-model",
            provider=ModelProvider.OPENAI,
            display_name="Local",
            base_url="http://localhost:11434/v1",
        )
        d = model.to_dict()
        assert d["base_url"] == "http://localhost:11434/v1"

    @pytest.mark.unit
    def test_to_dict_includes_capabilities(self):
        caps = ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            context_window=200000,
            supported_attachment_types=["image/png"],
        )
        model = AvailableModel(
            id="m",
            provider=ModelProvider.OPENAI,
            display_name="M",
            capabilities=caps,
        )
        d = model.to_dict()
        assert d["supports_tools"] is True
        assert d["supports_structured_output"] is True
        assert d["context_window"] == 200000
        assert d["supported_attachment_types"] == ["image/png"]

    @pytest.mark.unit
    def test_to_dict_disabled_model(self):
        model = AvailableModel(
            id="disabled",
            provider=ModelProvider.OPENAI,
            display_name="Disabled",
            enabled=False,
        )
        d = model.to_dict()
        assert d["enabled"] is False

    @pytest.mark.unit
    def test_api_key_field_never_serialized(self):
        """Forward-compat hook: AvailableModel.api_key (reserved for the
        future end-user BYOM phase) must never leak into the wire format."""
        model = AvailableModel(
            id="byom",
            provider=ModelProvider.OPENAI,
            display_name="BYOM",
            api_key="secret-key-do-not-leak",
        )
        d = model.to_dict()
        assert "api_key" not in d
        for v in d.values():
            assert v != "secret-key-do-not-leak"


class TestModelRegistryPublicAPI:
    """Covers the public lookup contract. Loading behavior is exercised
    end-to-end in tests/core/test_model_registry_yaml.py."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        ModelRegistry.reset()
        yield
        ModelRegistry.reset()

    @pytest.mark.unit
    def test_singleton(self):
        with patch.object(ModelRegistry, "_load_models"):
            r1 = ModelRegistry()
            r2 = ModelRegistry()
            assert r1 is r2

    @pytest.mark.unit
    def test_get_instance(self):
        with patch.object(ModelRegistry, "_load_models"):
            r = ModelRegistry.get_instance()
            assert isinstance(r, ModelRegistry)

    @pytest.mark.unit
    def test_get_model(self):
        with patch.object(ModelRegistry, "_load_models"):
            reg = ModelRegistry()
            model = AvailableModel(
                id="test", provider=ModelProvider.OPENAI, display_name="Test"
            )
            reg.models["test"] = model
            assert reg.get_model("test") is model
            assert reg.get_model("nonexistent") is None

    @pytest.mark.unit
    def test_get_all_models(self):
        with patch.object(ModelRegistry, "_load_models"):
            reg = ModelRegistry()
            reg.models["m1"] = AvailableModel(
                id="m1", provider=ModelProvider.OPENAI, display_name="M1"
            )
            reg.models["m2"] = AvailableModel(
                id="m2", provider=ModelProvider.ANTHROPIC, display_name="M2"
            )
            assert len(reg.get_all_models()) == 2

    @pytest.mark.unit
    def test_get_enabled_models(self):
        with patch.object(ModelRegistry, "_load_models"):
            reg = ModelRegistry()
            reg.models["m1"] = AvailableModel(
                id="m1",
                provider=ModelProvider.OPENAI,
                display_name="M1",
                enabled=True,
            )
            reg.models["m2"] = AvailableModel(
                id="m2",
                provider=ModelProvider.OPENAI,
                display_name="M2",
                enabled=False,
            )
            enabled = reg.get_enabled_models()
            assert len(enabled) == 1
            assert enabled[0].id == "m1"

    @pytest.mark.unit
    def test_model_exists(self):
        with patch.object(ModelRegistry, "_load_models"):
            reg = ModelRegistry()
            reg.models["m1"] = AvailableModel(
                id="m1", provider=ModelProvider.OPENAI, display_name="M1"
            )
            assert reg.model_exists("m1") is True
            assert reg.model_exists("m2") is False

    @pytest.mark.unit
    def test_lookups_accept_user_id_kwarg(self):
        """Reserved for the future end-user BYOM phase. Currently ignored."""
        with patch.object(ModelRegistry, "_load_models"):
            reg = ModelRegistry()
            reg.models["m1"] = AvailableModel(
                id="m1", provider=ModelProvider.OPENAI, display_name="M1"
            )
            assert reg.get_model("m1", user_id="alice") is not None
            assert reg.model_exists("m1", user_id="alice") is True
            assert len(reg.get_all_models(user_id="alice")) == 1
            assert len(reg.get_enabled_models(user_id="alice")) == 1

    @pytest.mark.unit
    def test_reset(self):
        with patch.object(ModelRegistry, "_load_models"):
            r1 = ModelRegistry()
            ModelRegistry.reset()
            r2 = ModelRegistry()
            assert r1 is not r2
