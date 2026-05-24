"""Tests for the operator MODELS_CONFIG_DIR.

Covers the operator-supplied directory of model YAMLs that's loaded
after the built-in catalog. Operators use this to add new
``openai_compatible`` providers, extend an existing provider's catalog
with extra models, or override a built-in model's capabilities — all
without forking the repo.
"""

from __future__ import annotations

import logging
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest

from application.core.model_registry import ModelRegistry


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


@pytest.fixture(autouse=True)
def _reset_registry():
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


# ── New provider via openai_compatible ───────────────────────────────────


@pytest.mark.unit
class TestOperatorAddsNewProvider:
    def test_drop_in_yaml_appears_in_registry(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "fireworks.yaml").write_text(dedent("""
            provider: openai_compatible
            display_provider: fireworks
            api_key_env: FIREWORKS_API_KEY
            base_url: https://api.fireworks.ai/inference/v1
            defaults:
              supports_tools: true
            models:
              - id: accounts/fireworks/models/llama-v3p3-70b-instruct
                display_name: Llama 3.3 70B (Fireworks)
        """))
        monkeypatch.setenv("FIREWORKS_API_KEY", "fw-key")

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        m = reg.get_model("accounts/fireworks/models/llama-v3p3-70b-instruct")
        assert m is not None
        assert m.api_key == "fw-key"
        assert m.base_url == "https://api.fireworks.ai/inference/v1"
        assert m.display_provider == "fireworks"


# ── Extending an existing provider's catalog ─────────────────────────────


@pytest.mark.unit
class TestOperatorExtendsExistingProvider:
    def test_operator_adds_anthropic_model_to_builtin_catalog(
        self, tmp_path
    ):
        (tmp_path / "anthropic-extra.yaml").write_text(dedent("""
            provider: anthropic
            defaults:
              supports_tools: true
              context_window: 200000
            models:
              - id: claude-haiku-5-0-future
                display_name: Claude Haiku 5.0
        """))

        s = _make_settings(
            ANTHROPIC_API_KEY="sk-ant",
            MODELS_CONFIG_DIR=str(tmp_path),
        )
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()

        # Built-in models still present
        assert reg.get_model("claude-sonnet-4-6") is not None
        assert reg.get_model("claude-opus-4-7") is not None
        # Operator-added model also present
        added = reg.get_model("claude-haiku-5-0-future")
        assert added is not None
        assert added.display_name == "Claude Haiku 5.0"


# ── Overriding a built-in model's capabilities ───────────────────────────


@pytest.mark.unit
class TestOperatorOverridesBuiltinCapabilities:
    def test_operator_yaml_overrides_builtin_context_window(
        self, tmp_path, caplog
    ):
        # Override anthropic claude-haiku-4-5 to claim a 1M context window
        (tmp_path / "anthropic-override.yaml").write_text(dedent("""
            provider: anthropic
            defaults:
              supports_tools: true
              attachments: [image]
              context_window: 1000000
            models:
              - id: claude-haiku-4-5
                display_name: Claude Haiku 4.5 (extended)
                description: Operator-overridden capabilities
        """))

        s = _make_settings(
            ANTHROPIC_API_KEY="sk-ant",
            MODELS_CONFIG_DIR=str(tmp_path),
        )
        with caplog.at_level(logging.WARNING):
            with patch("application.core.settings.settings", s):
                reg = ModelRegistry()

        m = reg.get_model("claude-haiku-4-5")
        assert m.display_name == "Claude Haiku 4.5 (extended)"
        assert m.description == "Operator-overridden capabilities"
        assert m.capabilities.context_window == 1_000_000

        # And the override warning fires so the operator can audit it
        assert any(
            "claude-haiku-4-5" in rec.message and "redefined" in rec.message
            for rec in caplog.records
        )


# ── Misconfigured MODELS_CONFIG_DIR ──────────────────────────────────────


@pytest.mark.unit
class TestMisconfiguredOperatorDir:
    def test_missing_dir_logs_warning_and_continues(
        self, tmp_path, caplog
    ):
        bogus = tmp_path / "does-not-exist"
        s = _make_settings(MODELS_CONFIG_DIR=str(bogus))

        with caplog.at_level(logging.WARNING):
            with patch("application.core.settings.settings", s):
                reg = ModelRegistry()

        # Built-in catalog still loaded
        assert reg.get_model("docsgpt-local") is not None
        # And the operator was warned
        assert any("does not exist" in rec.message for rec in caplog.records)

    def test_path_is_a_file_logs_warning(self, tmp_path, caplog):
        afile = tmp_path / "not-a-dir.yaml"
        afile.write_text("provider: anthropic\nmodels: []")

        s = _make_settings(MODELS_CONFIG_DIR=str(afile))
        with caplog.at_level(logging.WARNING):
            with patch("application.core.settings.settings", s):
                reg = ModelRegistry()

        assert reg.get_model("docsgpt-local") is not None
        assert any("not a directory" in rec.message for rec in caplog.records)


# ── Validation: unknown provider rejected ────────────────────────────────


@pytest.mark.unit
class TestOperatorValidation:
    def test_unknown_provider_in_operator_yaml_aborts_boot(self, tmp_path):
        (tmp_path / "bogus.yaml").write_text(dedent("""
            provider: not_a_real_provider
            models:
              - id: x
                display_name: X
        """))

        s = _make_settings(MODELS_CONFIG_DIR=str(tmp_path))
        with patch("application.core.settings.settings", s):
            with pytest.raises(Exception) as exc_info:
                ModelRegistry()
        # Could be ModelYAMLError (enum check) or ValueError (registry check);
        # either way the message must surface what's wrong.
        msg = str(exc_info.value)
        assert "not_a_real_provider" in msg
