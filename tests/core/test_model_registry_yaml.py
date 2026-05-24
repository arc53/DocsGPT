"""Regression tests for the YAML-driven ModelRegistry.

These tests encode the contract that persisted agent / workflow /
conversation references depend on: every model id and core capability
that existed in the old ``model_configs.py`` lists must continue to be
produced by the new YAML-backed registry.

If a future YAML edit accidentally renames an id or changes a
capability, these tests fail at CI before merge — protecting agents and
workflows from silent fallback to the system default.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from application.core.model_registry import ModelRegistry
from application.core.model_yaml import (
    BUILTIN_MODELS_DIR,
    load_model_yamls,
)


# ── Per-provider expected IDs ─────────────────────────────────────────────
# Snapshot of the current built-in catalog. If you intentionally change
# what models a provider's YAML lists, update this constant in the same
# commit. The test exists to catch *unintentional* renames (e.g. a typo
# in an upstream model id) that would silently break every agent that
# references the old id.
EXPECTED_IDS = {
    "openai": {"gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano"},
    "anthropic": {
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    },
    "google": {
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
    },
    "groq": {
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    },
    "openrouter": {
        "qwen/qwen3-coder:free",
        "deepseek/deepseek-v3.2",
        "anthropic/claude-sonnet-4.6",
    },
    "novita": {
        "deepseek/deepseek-v4-pro",
        "moonshotai/kimi-k2.6",
        "zai-org/glm-5",
    },
    "azure_openai": {
        "azure-gpt-5.5",
        "azure-gpt-5.4-mini",
        "azure-gpt-5.4-nano",
    },
    "docsgpt": {"docsgpt-local"},
    "huggingface": {"huggingface-local"},
}


def _make_settings(**overrides):
    s = MagicMock()
    # All credential / mode flags off by default so each test opts in.
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


@pytest.fixture(autouse=True)
def _reset_registry():
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


# ── YAML schema / loader ─────────────────────────────────────────────────


def _by_provider(catalogs):
    """Group a list of catalogs by provider name. Mirrors the registry's
    own grouping; useful for asserting per-provider model sets in tests."""
    out = {}
    for c in catalogs:
        out.setdefault(c.provider, []).append(c)
    return out


@pytest.mark.unit
class TestYAMLLoader:
    def test_loader_produces_expected_provider_set(self):
        catalogs = load_model_yamls([BUILTIN_MODELS_DIR])
        providers = {c.provider for c in catalogs}
        assert providers == set(EXPECTED_IDS.keys())

    def test_each_provider_has_expected_ids(self):
        grouped = _by_provider(load_model_yamls([BUILTIN_MODELS_DIR]))
        for provider, expected in EXPECTED_IDS.items():
            actual = {m.id for c in grouped[provider] for m in c.models}
            assert actual == expected, f"{provider}: expected {expected}, got {actual}"

    def test_attachment_alias_image_expands_to_five_mime_types(self):
        grouped = _by_provider(load_model_yamls([BUILTIN_MODELS_DIR]))
        # OpenAI uses `attachments: [image]` in its defaults block.
        for c in grouped["openai"]:
            for m in c.models:
                assert "image/png" in m.capabilities.supported_attachment_types
                assert "image/jpeg" in m.capabilities.supported_attachment_types
                assert "image/webp" in m.capabilities.supported_attachment_types
                assert len(m.capabilities.supported_attachment_types) == 5

    def test_attachment_alias_pdf_plus_image_for_google(self):
        grouped = _by_provider(load_model_yamls([BUILTIN_MODELS_DIR]))
        for c in grouped["google"]:
            for m in c.models:
                assert "application/pdf" in m.capabilities.supported_attachment_types
                assert "image/png" in m.capabilities.supported_attachment_types
                assert len(m.capabilities.supported_attachment_types) == 6

    def test_per_model_context_window_overrides_provider_default(self):
        grouped = _by_provider(load_model_yamls([BUILTIN_MODELS_DIR]))
        openai = {m.id: m for c in grouped["openai"] for m in c.models}
        # Provider default is 400_000; gpt-5.5 overrides to 1_050_000.
        assert openai["gpt-5.4-mini"].capabilities.context_window == 400_000
        assert openai["gpt-5.5"].capabilities.context_window == 1_050_000


# ── Registry × settings: every documented .env permutation ───────────────


@pytest.mark.unit
class TestRegistryPermutations:
    def test_openai_only(self):
        s = _make_settings(OPENAI_API_KEY="sk-test", LLM_PROVIDER="openai")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["openai"] | EXPECTED_IDS["docsgpt"]

    def test_openai_base_url_replaces_catalog_with_dynamic(self):
        s = _make_settings(
            OPENAI_BASE_URL="http://localhost:11434/v1",
            OPENAI_API_KEY="sk-test",
            LLM_PROVIDER="openai",
            LLM_NAME="llama3,gemma",
        )
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        # Custom local endpoint suppresses both the openai catalog AND
        # the docsgpt model (matching legacy behavior).
        assert ids == {"llama3", "gemma"}

    def test_anthropic_only(self):
        s = _make_settings(ANTHROPIC_API_KEY="sk-ant")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["anthropic"] | EXPECTED_IDS["docsgpt"]

    def test_anthropic_via_llm_provider_with_llm_name(self):
        # Mirrors the historical _add_anthropic_models filter: when only
        # API_KEY (not ANTHROPIC_API_KEY) is set and LLM_NAME matches a
        # known model, only that model is loaded.
        s = _make_settings(
            LLM_PROVIDER="anthropic", API_KEY="key", LLM_NAME="claude-haiku-4-5"
        )
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        anthropic_ids = {
            m.id for m in reg.get_all_models() if m.provider.value == "anthropic"
        }
        assert anthropic_ids == {"claude-haiku-4-5"}

    def test_google_only(self):
        s = _make_settings(GOOGLE_API_KEY="g-test")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["google"] | EXPECTED_IDS["docsgpt"]

    def test_groq_only(self):
        s = _make_settings(GROQ_API_KEY="g-test")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["groq"] | EXPECTED_IDS["docsgpt"]

    def test_openrouter_only(self):
        s = _make_settings(OPEN_ROUTER_API_KEY="or-test")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["openrouter"] | EXPECTED_IDS["docsgpt"]

    def test_novita_only(self):
        s = _make_settings(NOVITA_API_KEY="n-test")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["novita"] | EXPECTED_IDS["docsgpt"]

    def test_huggingface_only(self):
        s = _make_settings(HUGGINGFACE_API_KEY="hf-test")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["huggingface"] | EXPECTED_IDS["docsgpt"]

    def test_no_credentials_only_docsgpt(self):
        s = _make_settings()
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert ids == EXPECTED_IDS["docsgpt"]

    def test_azure_via_provider(self):
        s = _make_settings(LLM_PROVIDER="azure_openai", API_KEY="key")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert "azure-gpt-5.5" in ids

    def test_azure_via_api_base(self):
        s = _make_settings(OPENAI_API_BASE="https://x.openai.azure.com")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        assert "azure-gpt-5.5" in ids

    def test_everything_set(self):
        s = _make_settings(
            OPENAI_API_KEY="x",
            ANTHROPIC_API_KEY="x",
            GOOGLE_API_KEY="x",
            GROQ_API_KEY="x",
            OPEN_ROUTER_API_KEY="x",
            NOVITA_API_KEY="x",
            HUGGINGFACE_API_KEY="x",
            OPENAI_API_BASE="x",
        )
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        ids = {m.id for m in reg.get_all_models()}
        all_expected = set()
        for v in EXPECTED_IDS.values():
            all_expected |= v
        assert ids == all_expected


# ── Default model resolution ─────────────────────────────────────────────


@pytest.mark.unit
class TestDefaultModelResolution:
    def test_llm_name_picks_default(self):
        s = _make_settings(
            ANTHROPIC_API_KEY="sk-ant", LLM_NAME="claude-opus-4-7"
        )
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        assert reg.default_model_id == "claude-opus-4-7"

    def test_falls_back_to_first_model_when_no_match(self):
        s = _make_settings()
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        assert reg.default_model_id is not None
        assert reg.default_model_id in reg.models


# ── Forward-compat: user_id parameter is accepted everywhere ─────────────


@pytest.mark.unit
class TestUserIdForwardCompat:
    def test_lookup_methods_accept_user_id(self):
        s = _make_settings(OPENAI_API_KEY="sk-test")
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
        # All lookup methods must accept user_id (currently ignored,
        # reserved for end-user BYOM).
        assert reg.get_model("gpt-5.5", user_id="alice") is not None
        assert len(reg.get_all_models(user_id="alice")) > 0
        assert len(reg.get_enabled_models(user_id="alice")) > 0
        assert reg.model_exists("gpt-5.5", user_id="alice") is True
