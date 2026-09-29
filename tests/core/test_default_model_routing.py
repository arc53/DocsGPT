"""Which model answers by default, for each way a deployment is configured.

The first registered model is ``docsgpt-local``, which answers through the
hosted DocsGPT API. A configuration that names another provider but ends up
defaulting to it sends prompts, retrieved chunks and chat history off the
machine without saying so. These tests pin the default for every shape of
``.env`` the installer, the setup scripts and the docs produce, and check the
diagnostics that flag the configurations that still fall through.
"""

from __future__ import annotations

import logging
from typing import Optional

import pytest

from docsgpt.core.model_registry import (
    ModelRegistry,
    check_model_setup,
    diagnose_model_setup,
    load_catalog_models,
    resolve_default_model_id,
)
from docsgpt.core.model_yaml import BUILTIN_MODELS_DIR, load_model_yamls
from docsgpt.core.settings import Settings


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """Build every ``Settings`` from the test's own values only.

    Settings fields and the ``api_key_env`` variables of the built-in
    ``openai_compatible`` catalogs are read from the process environment, so
    a developer's shell must not leak into the matrix.
    """
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    for catalog in load_model_yamls([BUILTIN_MODELS_DIR]):
        if catalog.api_key_env:
            monkeypatch.delenv(catalog.api_key_env, raising=False)
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


def _settings(monkeypatch, **values: str) -> Settings:
    """Settings as the app would read them from a ``.env`` holding ``values``."""
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def _default(settings: Settings) -> tuple[Optional[str], Optional[str]]:
    """Return ``(default model id, its provider)`` for ``settings``."""
    models = load_catalog_models(settings)
    default = resolve_default_model_id(settings, models)
    return default, (models[default].provider.value if default else None)


@pytest.mark.unit
class TestDefaultModelMatrix:
    def test_openai_with_the_generic_api_key(self, monkeypatch):
        # What ``docsgpt up --provider openai --api-key`` and the setup scripts write.
        s = _settings(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-test")
        assert _default(s) == ("gpt-5.5", "openai")

    def test_openai_with_the_generic_api_key_and_a_catalog_name(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-test", LLM_NAME="gpt-5.4-mini")
        assert _default(s) == ("gpt-5.4-mini", "openai")

    def test_openai_with_only_the_provider_key(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-test")
        assert _default(s) == ("gpt-5.5", "openai")

    def test_anthropic_with_the_generic_api_key(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="anthropic", API_KEY="sk-ant")
        assert _default(s) == ("claude-opus-4-7", "anthropic")

    @pytest.mark.parametrize(
        ("provider", "key", "expected"),
        [
            ("anthropic", "ANTHROPIC_API_KEY", "claude-opus-4-7"),
            ("google", "GOOGLE_API_KEY", "gemini-3.1-pro-preview"),
            ("groq", "GROQ_API_KEY", "openai/gpt-oss-120b"),
            ("openrouter", "OPEN_ROUTER_API_KEY", "qwen/qwen3-coder:free"),
            ("novita", "NOVITA_API_KEY", "deepseek/deepseek-v4-pro"),
        ],
    )
    def test_only_a_provider_specific_key(self, monkeypatch, provider, key, expected):
        s = _settings(monkeypatch, LLM_PROVIDER=provider, **{key: "k"})
        assert _default(s) == (expected, provider)

    def test_several_provider_keys_follow_llm_provider(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk", ANTHROPIC_API_KEY="ak")
        assert _default(s) == ("gpt-5.5", "openai")

    def test_openai_compatible_catalog_key(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="openai_compatible", DEEPSEEK_API_KEY="dk")
        assert _default(s) == ("deepseek-v4-flash", "openai_compatible")

    def test_own_openai_compatible_server(self, monkeypatch):
        s = _settings(
            monkeypatch, LLM_PROVIDER="openai", OPENAI_BASE_URL="http://localhost:11434/v1", LLM_NAME="llama3"
        )
        assert _default(s) == ("llama3", "openai_compatible")

    def test_own_server_with_several_model_names(self, monkeypatch):
        s = _settings(
            monkeypatch,
            LLM_PROVIDER="openai",
            OPENAI_BASE_URL="http://localhost:11434/v1",
            LLM_NAME="llama3, qwen2",
        )
        models = load_catalog_models(s)
        assert set(models) == {"llama3", "qwen2"}
        assert resolve_default_model_id(s, models) == "llama3"

    def test_docsgpt_default(self, monkeypatch):
        s = _settings(monkeypatch)
        assert _default(s) == ("docsgpt-local", "docsgpt")

    def test_docsgpt_stays_the_default_when_other_keys_are_set(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="docsgpt", ANTHROPIC_API_KEY="ak")
        assert _default(s) == ("docsgpt-local", "docsgpt")

    def test_an_unregistered_llm_name_falls_back_to_the_providers_first_model(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk", LLM_NAME="gpt-4o")
        assert _default(s) == ("gpt-5.5", "openai")

    def test_the_singleton_uses_the_same_rules(self, monkeypatch):
        from unittest.mock import patch

        s = _settings(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-test")
        with patch("docsgpt.core.settings.settings", s):
            registry = ModelRegistry()
        assert registry.default_model_id == "gpt-5.5"


def _problems(settings: Settings) -> list:
    models = load_catalog_models(settings)
    return diagnose_model_setup(settings, models, resolve_default_model_id(settings, models))


@pytest.mark.unit
class TestDiagnostics:
    def test_a_working_setup_has_no_problems(self, monkeypatch):
        assert _problems(_settings(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk")) == []

    def test_the_docsgpt_default_has_no_problems(self, monkeypatch):
        assert _problems(_settings(monkeypatch)) == []

    def test_a_provider_without_a_key_routes_to_the_hosted_api(self, monkeypatch):
        (problem,) = _problems(_settings(monkeypatch, LLM_PROVIDER="anthropic"))
        assert problem.level == logging.ERROR
        assert problem.hosted_fallback
        assert "hosted DocsGPT API" in problem.message
        assert "ANTHROPIC_API_KEY" in problem.message and "API_KEY" in problem.message

    def test_an_unknown_provider_routes_to_the_hosted_api(self, monkeypatch):
        # A provider name that is not a plugin; LLM_NAME=llama3 is also reported as ignored.
        problems = _problems(_settings(monkeypatch, LLM_PROVIDER="ollama", LLM_NAME="llama3"))
        assert [p.level for p in problems] == [logging.ERROR, logging.WARNING]
        assert problems[0].hosted_fallback
        assert "not a known provider" in problems[0].message
        assert "OPENAI_BASE_URL" in problems[0].message

    def test_the_old_native_llama_cpp_recipe_is_flagged(self, monkeypatch):
        """``LLM_PROVIDER=llama.cpp`` never loaded a model; llama.cpp is reached through its server now."""
        from docsgpt.llm.providers import PROVIDERS_BY_NAME

        assert "llama.cpp" not in PROVIDERS_BY_NAME
        (problem,) = _problems(_settings(monkeypatch, LLM_PROVIDER="llama.cpp"))
        assert problem.hosted_fallback
        assert "not a known provider" in problem.message and "llama.cpp server" in problem.message

    def test_openai_compatible_without_a_model(self, monkeypatch):
        problems = _problems(
            _settings(monkeypatch, LLM_PROVIDER="openai_compatible", API_KEY="x", LLM_NAME="deepseek-chat")
        )
        hosted = [p for p in problems if p.hosted_fallback]
        assert len(hosted) == 1
        assert "OPENAI_BASE_URL" in hosted[0].message

    def test_explicitly_choosing_the_hosted_model_is_not_a_problem(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="openai", LLM_NAME="docsgpt-local")
        assert _problems(s) == []

    def test_an_unregistered_llm_name_is_a_warning(self, monkeypatch):
        (problem,) = _problems(_settings(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk", LLM_NAME="gpt-4o"))
        assert problem.level == logging.WARNING
        assert not problem.hosted_fallback
        assert "gpt-4o" in problem.message and "gpt-5.5" in problem.message

    def test_own_server_without_llm_name_is_a_warning(self, monkeypatch):
        s = _settings(monkeypatch, LLM_PROVIDER="openai", OPENAI_BASE_URL="http://localhost:11434/v1", LLM_NAME="None")
        (problem,) = _problems(s)
        assert problem.level == logging.WARNING
        assert "LLM_NAME" in problem.message


@pytest.mark.unit
class TestStartupCheck:
    def test_logs_an_error_when_chats_would_go_to_the_hosted_api(self, monkeypatch, caplog):
        s = _settings(monkeypatch, LLM_PROVIDER="google")
        with caplog.at_level(logging.WARNING, logger="docsgpt.core.model_registry"):
            problems = check_model_setup(s)
        assert [p.hosted_fallback for p in problems] == [True]
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1 and "GOOGLE_API_KEY" in errors[0].getMessage()

    def test_is_quiet_for_a_working_setup(self, monkeypatch, caplog):
        s = _settings(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk")
        with caplog.at_level(logging.WARNING, logger="docsgpt.core.model_registry"):
            assert check_model_setup(s) == []
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_never_raises(self, monkeypatch, caplog):
        from unittest.mock import patch

        s = _settings(monkeypatch)
        with patch("docsgpt.core.model_registry.load_catalog_models", side_effect=ValueError("bad yaml")):
            with caplog.at_level(logging.ERROR, logger="docsgpt.core.model_registry"):
                assert check_model_setup(s) == []
        assert "bad yaml" in caplog.text
