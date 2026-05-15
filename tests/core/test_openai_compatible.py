"""Tests for the openai_compatible provider.

Covers YAML loading from a temp directory, multiple coexisting catalogs
(Mistral + Together), env-var-based credential resolution, the legacy
OPENAI_BASE_URL + LLM_NAME fallback, and end-to-end model dispatch
through LLMCreator.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest

from application.core.model_registry import ModelRegistry
from application.core.model_settings import ModelProvider


def _make_settings(**overrides):
    s = MagicMock()
    s.OPENAI_BASE_URL = None
    s.OPENAI_API_KEY = None
    s.OPENAI_API_BASE = None
    s.ANTHROPIC_API_KEY = None
    s.GOOGLE_API_KEY = None
    s.GROQ_API_KEY = None
    s.OPEN_ROUTER_API_KEY = None
    s.NOVITA_API_KEY = None
    s.HUGGINGFACE_API_KEY = None
    s.LLM_PROVIDER = ""
    s.LLM_NAME = None
    s.API_KEY = None
    s.MODELS_CONFIG_DIR = None
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _write_mistral_yaml(directory: Path) -> Path:
    path = directory / "mistral.yaml"
    path.write_text(dedent("""
        provider: openai_compatible
        display_provider: mistral
        api_key_env: MISTRAL_API_KEY
        base_url: https://api.mistral.ai/v1
        defaults:
          supports_tools: true
          context_window: 128000
        models:
          - id: mistral-large-latest
            display_name: Mistral Large
          - id: mistral-small-latest
            display_name: Mistral Small
    """))
    return path


def _write_together_yaml(directory: Path) -> Path:
    path = directory / "together.yaml"
    path.write_text(dedent("""
        provider: openai_compatible
        display_provider: together
        api_key_env: TOGETHER_API_KEY
        base_url: https://api.together.xyz/v1
        defaults:
          supports_tools: true
        models:
          - id: meta-llama/Llama-3.3-70B-Instruct-Turbo
            display_name: Llama 3.3 70B (Together)
    """))
    return path


@pytest.fixture(autouse=True)
def _reset_registry():
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


# ── YAML-driven catalogs ─────────────────────────────────────────────────


@pytest.mark.unit
class TestYAMLCompatibleProvider:
    def test_mistral_yaml_loads_with_env_key(
        self, tmp_path, monkeypatch
    ):
        _write_mistral_yaml(tmp_path)
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-mistral-test")

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        m = reg.get_model("mistral-large-latest")
        assert m is not None
        assert m.provider == ModelProvider.OPENAI_COMPATIBLE
        assert m.display_provider == "mistral"
        assert m.base_url == "https://api.mistral.ai/v1"
        assert m.api_key == "sk-mistral-test"
        assert m.capabilities.supports_tools is True
        assert m.capabilities.context_window == 128000

    def test_yaml_skipped_when_env_var_missing(
        self, tmp_path, monkeypatch
    ):
        _write_mistral_yaml(tmp_path)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        # Catalog skipped when no key — no Mistral models in the registry
        assert reg.get_model("mistral-large-latest") is None

    def test_two_compatible_catalogs_coexist_with_separate_keys(
        self, tmp_path, monkeypatch
    ):
        _write_mistral_yaml(tmp_path)
        _write_together_yaml(tmp_path)
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-mistral")
        monkeypatch.setenv("TOGETHER_API_KEY", "sk-together")

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        mistral = reg.get_model("mistral-large-latest")
        together = reg.get_model("meta-llama/Llama-3.3-70B-Instruct-Turbo")

        assert mistral.api_key == "sk-mistral"
        assert mistral.base_url == "https://api.mistral.ai/v1"
        assert mistral.display_provider == "mistral"

        assert together.api_key == "sk-together"
        assert together.base_url == "https://api.together.xyz/v1"
        assert together.display_provider == "together"

    def test_one_catalog_enabled_other_skipped(
        self, tmp_path, monkeypatch
    ):
        _write_mistral_yaml(tmp_path)
        _write_together_yaml(tmp_path)
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-mistral")
        monkeypatch.delenv("TOGETHER_API_KEY", raising=False)

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        assert reg.get_model("mistral-large-latest") is not None
        assert reg.get_model("meta-llama/Llama-3.3-70B-Instruct-Turbo") is None

    def test_missing_base_url_raises(self, tmp_path, monkeypatch):
        bad = tmp_path / "broken.yaml"
        bad.write_text(dedent("""
            provider: openai_compatible
            api_key_env: SOME_KEY
            models:
              - id: x
                display_name: X
        """))
        monkeypatch.setenv("SOME_KEY", "k")

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            with pytest.raises(ValueError, match="must set 'base_url'"):
                ModelRegistry()

    def test_missing_api_key_env_raises(self, tmp_path, monkeypatch):
        bad = tmp_path / "broken.yaml"
        bad.write_text(dedent("""
            provider: openai_compatible
            base_url: https://x/v1
            models:
              - id: x
                display_name: X
        """))

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            with pytest.raises(ValueError, match="must set 'api_key_env'"):
                ModelRegistry()

    def test_to_dict_uses_display_provider(
        self, tmp_path, monkeypatch
    ):
        _write_mistral_yaml(tmp_path)
        monkeypatch.setenv("MISTRAL_API_KEY", "sk")

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        d = reg.get_model("mistral-large-latest").to_dict()
        # /api/models response shows "mistral", not "openai_compatible"
        assert d["provider"] == "mistral"
        # api_key never leaks into the wire format
        assert "api_key" not in d
        for v in d.values():
            assert v != "sk"


# ── Legacy OPENAI_BASE_URL fallback ──────────────────────────────────────


@pytest.mark.unit
class TestLegacyOpenAIBaseURLPath:
    def test_legacy_models_now_provided_by_openai_compatible(self):
        s = _make_settings(
            OPENAI_BASE_URL="http://localhost:11434/v1",
            OPENAI_API_KEY="sk-local",
            LLM_PROVIDER="openai",
            LLM_NAME="llama3,gemma",
        )
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        ids = {m.id for m in reg.get_all_models()}
        assert ids == {"llama3", "gemma"}

        llama = reg.get_model("llama3")
        assert llama.base_url == "http://localhost:11434/v1"
        assert llama.api_key == "sk-local"
        assert llama.provider == ModelProvider.OPENAI_COMPATIBLE
        # Display provider preserves the historical "openai" label
        assert llama.display_provider == "openai"
        assert llama.to_dict()["provider"] == "openai"

    def test_legacy_uses_api_key_fallback_when_openai_api_key_missing(self):
        s = _make_settings(
            OPENAI_BASE_URL="http://localhost:11434/v1",
            OPENAI_API_KEY=None,
            API_KEY="sk-generic",
            LLM_PROVIDER="openai",
            LLM_NAME="llama3",
        )
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        assert reg.get_model("llama3").api_key == "sk-generic"


# ── Dispatch through LLMCreator ──────────────────────────────────────────


@pytest.mark.unit
class TestLLMCreatorDispatch:
    def test_llmcreator_uses_per_model_api_key_and_base_url(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: when an openai_compatible model is dispatched, the
        per-model api_key + base_url from the registry must override
        whatever the caller passed."""
        _write_mistral_yaml(tmp_path)
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-mistral-real")

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))

        captured = {}

        class _FakeLLM:
            def __init__(
                self, api_key, user_api_key, *args, **kwargs
            ):
                captured["api_key"] = api_key
                captured["base_url"] = kwargs.get("base_url")
                captured["model_id"] = kwargs.get("model_id")

        with patch("application.core.settings.settings", s):
            ModelRegistry.reset()
            ModelRegistry()  # warm up the registry under patched settings

            # Now patch the OpenAI plugin's class so we can capture the
            # constructor args without spinning up the real OpenAILLM.
            from application.llm.providers import PROVIDERS_BY_NAME

            with patch.object(
                PROVIDERS_BY_NAME["openai_compatible"],
                "llm_class",
                _FakeLLM,
            ):
                from application.llm.llm_creator import LLMCreator

                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="caller-passed-WRONG-key",
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    model_id="mistral-large-latest",
                )

        assert captured["api_key"] == "sk-mistral-real"
        assert captured["base_url"] == "https://api.mistral.ai/v1"
        assert captured["model_id"] == "mistral-large-latest"
