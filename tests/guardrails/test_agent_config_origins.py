"""``AgentConfig.restrict_origins`` / ``allowed_origins``: strict on write, fail-closed on read."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docsgpt.api.user.agents.routes import normalize_agent_config
from docsgpt.guardrails.config import AgentConfig


@pytest.mark.unit
class TestWrite:
    def test_defaults_leave_the_key_unrestricted(self):
        config = AgentConfig()
        assert config.restrict_origins is False
        assert config.allowed_origins == []
        assert config.origin_allowed(None, []) is True

    def test_entries_are_normalized_and_deduplicated_in_order(self):
        config = AgentConfig.model_validate(
            {
                "restrict_origins": True,
                "allowed_origins": [
                    "https://B.example.com/",
                    "https://a.example.com:443",
                    "https://b.example.com",
                ],
            }
        )
        assert config.allowed_origins == ["https://b.example.com", "https://a.example.com"]

    def test_a_list_is_kept_while_the_restriction_is_off(self):
        config = AgentConfig.model_validate({"allowed_origins": ["https://a.com"]})
        assert config.allowed_origins == ["https://a.com"]
        assert config.origin_allowed("https://elsewhere.com", []) is True

    @pytest.mark.parametrize("entry", ["a.com", "https://a.com/path", "https://*.a.com", ""])
    def test_an_invalid_entry_is_refused(self, entry):
        with pytest.raises(ValidationError):
            AgentConfig.model_validate({"allowed_origins": [entry]})

    def test_restricting_with_an_empty_list_is_refused(self):
        with pytest.raises(ValidationError, match="at least one entry"):
            AgentConfig.model_validate({"restrict_origins": True, "allowed_origins": []})

    def test_at_most_100_entries(self):
        many = [f"https://site{i}.example.com" for i in range(101)]
        with pytest.raises(ValidationError, match="at most 100"):
            AgentConfig.model_validate({"allowed_origins": many})

    def test_route_validation_names_the_bad_entry(self):
        with pytest.raises(ValueError, match="https://a.com/path"):
            normalize_agent_config({"restrict_origins": True, "allowed_origins": ["https://a.com/path"]})

    def test_route_validation_returns_the_normalized_config(self):
        stored = normalize_agent_config('{"restrict_origins": true, "allowed_origins": ["HTTPS://A.com/"]}')
        assert stored["restrict_origins"] is True
        assert stored["allowed_origins"] == ["https://a.com"]


@pytest.mark.unit
class TestOriginAllowed:
    config = AgentConfig(restrict_origins=True, allowed_origins=["https://a.com"])

    def test_listed_origin(self):
        assert self.config.origin_allowed("https://a.com", []) is True

    def test_unlisted_origin(self):
        assert self.config.origin_allowed("https://b.com", []) is False

    def test_no_origin(self):
        assert self.config.origin_allowed(None, []) is False

    def test_trusted_origin(self):
        assert self.config.origin_allowed("https://app.docsgpt.cloud", ["https://app.docsgpt.cloud"]) is True


@pytest.mark.unit
class TestLenientRead:
    def test_a_valid_row_parses_as_is(self):
        config = AgentConfig.parse({"restrict_origins": True, "allowed_origins": ["https://a.com"]})
        assert config.restrict_origins is True
        assert config.allowed_origins == ["https://a.com"]

    def test_a_bad_entry_keeps_the_restriction_on(self):
        # Dropping the whole config on a bad entry would turn the key
        # unrestricted; the restriction must stay with what still parses.
        config = AgentConfig.parse(
            {"restrict_origins": True, "allowed_origins": ["https://a.com", "not an origin", 7]}
        )
        assert config.restrict_origins is True
        assert config.allowed_origins == ["https://a.com"]
        assert config.origin_allowed("https://evil.com", []) is False

    def test_a_restriction_with_nothing_left_refuses_every_origin(self):
        config = AgentConfig.parse({"restrict_origins": True, "allowed_origins": ["garbage"]})
        assert config.origin_allowed("https://a.com", []) is False

    def test_a_bad_allowlist_does_not_lift_the_restriction(self):
        config = AgentConfig.parse(
            {
                "restrict_origins": True,
                "allowed_origins": ["https://a.com"],
                "api_write_allowlist": ["no-colon"],
            }
        )
        assert config.api_write_allowlist == []
        assert config.origin_allowed("https://evil.com", []) is False
        assert config.origin_allowed("https://a.com", []) is True

    @pytest.mark.parametrize("flag", [False, "false", "False", "no", "off", 0, "0"])
    def test_a_flag_saved_off_stays_off(self, flag):
        # Read the flag the way a write does: a quoted "false" in a YAML is off.
        config = AgentConfig.parse(
            {"restrict_origins": flag, "allowed_origins": ["https://a.com"], "api_write_allowlist": ["no-colon"]}
        )
        assert config.restrict_origins is False

    @pytest.mark.parametrize("flag", [True, "true", "yes", 1])
    def test_a_flag_saved_on_stays_on(self, flag):
        config = AgentConfig.parse(
            {"restrict_origins": flag, "allowed_origins": ["https://a.com"], "api_write_allowlist": ["no-colon"]}
        )
        assert config.restrict_origins is True

    @pytest.mark.parametrize("flag", ["sometimes", None, [], {}])
    def test_an_unreadable_flag_keeps_the_restriction_on(self, flag):
        # An explicit null is invalid too (a write refuses it), unlike a missing field.
        config = AgentConfig.parse({"restrict_origins": flag, "allowed_origins": ["https://a.com"]})
        assert config.restrict_origins is True
        assert config.origin_allowed("https://evil.com", []) is False

    def test_a_missing_flag_is_off(self):
        config = AgentConfig.parse({"allowed_origins": ["https://a.com/path"]})
        assert config.restrict_origins is False

    def test_a_bad_row_without_origins_stays_unrestricted(self):
        config = AgentConfig.parse({"api_write_allowlist": ["no-colon"]})
        assert config.origin_allowed(None, []) is True


@pytest.mark.unit
class TestImport:
    """A hand-edited YAML with a bad entry must not import as an unrestricted agent."""

    def _import(self, config):
        from flask import Flask

        from docsgpt.api.user.agents.portability import _import_config

        with Flask(__name__).app_context():
            return _import_config({"config": config}, None, [])

    def test_a_valid_config_is_normalized(self):
        stored = self._import({"restrict_origins": True, "allowed_origins": ["HTTPS://A.com/"]})
        assert stored["restrict_origins"] is True
        assert stored["allowed_origins"] == ["https://a.com"]

    def test_a_bad_entry_keeps_the_restriction_and_the_valid_entries(self):
        stored = self._import(
            {"restrict_origins": True, "allowed_origins": ["https://a.com", "https://b.com/path"]}
        )
        assert stored["restrict_origins"] is True
        assert stored["allowed_origins"] == ["https://a.com"]
        assert AgentConfig.parse(stored).origin_allowed("https://evil.com", []) is False

    def test_nothing_valid_left_still_refuses_every_origin(self):
        stored = self._import({"restrict_origins": True, "allowed_origins": ["not an origin"]})
        assert AgentConfig.parse(stored).origin_allowed("https://a.com", []) is False

    def test_no_config_imports_as_empty(self):
        assert self._import(None) == {}
