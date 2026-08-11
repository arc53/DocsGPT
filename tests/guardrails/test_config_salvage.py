"""A stale control must not take the rest of an agent's guardrails with it.

Also pins ``GUARDRAILS_CHECKS_ENABLED`` to the registry keys. The equivalent
setting for retrievers drifted from its registry once already, and the failure
is silent both times: an unmatched value is filtered out, not rejected.
"""

from __future__ import annotations

import logging

import pytest

from application.core.settings import settings
from application.guardrails.config import AgentConfig, GuardrailsConfig
from application.guardrails.guardrail_creator import GuardrailCreator
from application.guardrails.runtime import resolve_config

TWO_CONTROLS = {
    "enabled": True,
    "mode": "scan_all",
    "controls": [
        {"check": "secrets", "stage": "output", "action": "redact"},
        {"check": "pii", "stage": "output", "action": "redact"},
    ],
}


def _checks(config):
    return [c.check for c in config.controls]


@pytest.fixture
def narrowed(monkeypatch):
    """Allow only ``pii``, as an operator tightening the allowlist would."""
    monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", ["pii"])
    monkeypatch.setattr(GuardrailCreator, "_bootstrapped", False)
    yield


class TestAllowlistMatchesRegistry:
    def test_default_allowlist_is_empty_meaning_everything(self):
        assert settings.GUARDRAILS_CHECKS_ENABLED == []
        assert GuardrailCreator.enabled_keys() == sorted(GuardrailCreator.checks)

    def test_every_configured_value_is_a_registry_key(self):
        """Guards against the drift that silently disabled a retriever."""
        configured = settings.GUARDRAILS_CHECKS_ENABLED or []
        GuardrailCreator._ensure_builtin()
        unknown = set(configured) - set(GuardrailCreator.checks)
        assert not unknown, f"not registry keys: {sorted(unknown)}"

    def test_catalog_only_exposes_enabled_keys(self, narrowed):
        assert [entry["name"] for entry in GuardrailCreator.catalog()] == ["pii"]

    def test_a_typo_is_filtered_not_rejected(self, monkeypatch):
        """Documents the sharp edge the test above exists to catch."""
        monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", ["pii", "secrets_"])
        monkeypatch.setattr(GuardrailCreator, "_bootstrapped", False)
        assert GuardrailCreator.enabled_keys() == ["pii"]


class TestSalvage:
    def test_disallowed_control_is_dropped_alone(self, narrowed):
        parsed = GuardrailsConfig.parse(TWO_CONTROLS)
        assert parsed.enabled is True
        assert _checks(parsed) == ["pii"]

    def test_agent_config_wrapper_salvages_too(self, narrowed):
        parsed = AgentConfig.parse({"guardrails": TWO_CONTROLS}).guardrails
        assert _checks(parsed) == ["pii"]

    def test_resolve_config_end_to_end(self, narrowed):
        assert _checks(resolve_config({"guardrails": TWO_CONTROLS})) == ["pii"]

    def test_unknown_check_from_an_upgrade_is_dropped_alone(self):
        raw = {
            "enabled": True,
            "mode": "scan_all",
            "controls": [
                {"check": "moderation", "stage": "output", "action": "flag"},
                {"check": "secrets", "stage": "output", "action": "redact"},
            ],
        }
        assert _checks(GuardrailsConfig.parse(raw)) == ["secrets"]

    def test_mode_preserved_while_salvaging(self, narrowed):
        assert GuardrailsConfig.parse(TWO_CONTROLS).mode == "scan_all"

    def test_drop_is_logged_with_the_reason(self, narrowed, caplog):
        with caplog.at_level(logging.WARNING, logger="application.guardrails.config"):
            GuardrailsConfig.parse(TWO_CONTROLS)
        assert "secrets:output" in caplog.text
        assert "not enabled on this instance" in caplog.text

    def test_unusable_config_still_degrades_to_disabled(self, caplog):
        with caplog.at_level(logging.WARNING, logger="application.guardrails.config"):
            parsed = GuardrailsConfig.parse({"enabled": True, "mode": "not_a_mode"})
        assert parsed.enabled is False
        assert "unusable" in caplog.text

    def test_valid_config_is_untouched(self):
        assert _checks(GuardrailsConfig.parse(TWO_CONTROLS)) == ["secrets", "pii"]
