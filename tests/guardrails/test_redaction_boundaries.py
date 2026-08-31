"""Redaction must survive chunk boundaries and must not corrupt the journal.

Two bugs shared one cause: span offsets are computed against the text as
scanned, so anything that consumes them after ``_reduce`` has masked the text
is indexing a string that no longer exists.
"""

from __future__ import annotations

import pytest

from application.core.settings import settings
from application.guardrails.config import GuardrailsConfig
from application.guardrails.engine import GuardrailEngine
from application.guardrails.runtime import GuardrailRecorder
from application.guardrails.stream import StreamingOutputGuard
from application.guardrails.types import Stage

# Long enough that the guard splits mid-stream instead of scanning once at
# flush; below the window the bug is invisible, which is why it shipped.
PAD = ("The quick brown fox jumps over the lazy dog near the riverbank. " * 45)[:2700]

SECRETS = {
    # Hyphenated on purpose: these satisfy SECRET_PATTERNS but not GitHub's
    # push-protection detectors, which need long unbroken alphanumeric runs.
    "openai": "sk-not-a-real-openai-key-for-tests-only",
    "slack": "xoxb-not-a-real-slack-token-for-tests",
    "anthropic": "sk-ant-api03XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    "github_long": "ghp_" + "A" * 44,
}


def _guard(check, action="redact", **settings_over):
    config = GuardrailsConfig.model_validate(
        {
            "enabled": True,
            "mode": "scan_all",
            "controls": [
                {
                    "check": check,
                    "stage": "output",
                    "action": action,
                    "settings": settings_over,
                }
            ],
        }
    )
    return StreamingOutputGuard(GuardrailEngine(config))


def _stream(guard, text, chunk):
    out = []
    for i in range(0, len(text), chunk):
        out.append(guard.feed(text[i : i + chunk]).emit)
    out.append(guard.flush().emit)
    return "".join(out)


class TestStraddlingMatch:
    """A value whose regex is satisfied by a prefix still being streamed."""

    @pytest.mark.parametrize("name", sorted(SECRETS))
    def test_secret_longer_than_its_pattern_minimum_never_leaks(self, name):
        secret = SECRETS[name]
        emitted = _stream(_guard("secrets"), f"{PAD} key {secret} end.", chunk=4)
        assert "[REDACTED]" in emitted
        assert secret not in emitted
        # The tail is what used to survive: the detector matched a prefix, the
        # mask was written into the held buffer, and the rest appended after it.
        assert emitted.endswith("[REDACTED] end.")

    @pytest.mark.parametrize("chunk", [1, 3, 4, 17, 128, 1000])
    def test_result_is_independent_of_chunk_size(self, chunk):
        secret = SECRETS["openai"]
        emitted = _stream(_guard("secrets"), f"{PAD} key {secret} end.", chunk)
        assert secret not in emitted
        assert "not-a-real" not in emitted

    @pytest.mark.parametrize("pad", [200, 250, 400, 950])
    def test_email_at_the_window_boundary(self, pad):
        text = ("Padding sentence here. " * 60)[:pad] + " Write to a@example.com now."
        emitted = _stream(_guard("pii", entities=["EMAIL"]), text, chunk=4)
        assert "@" not in emitted
        assert emitted.endswith("Write to [EMAIL] now.")

    @pytest.mark.parametrize(
        "card", ["4575513137353792", "4111111111111111", "5500005555555559"]
    )
    def test_credit_card_trailing_digits_never_leak(self, card):
        emitted = _stream(
            _guard("pii", entities=["CREDIT_CARD"]), f"{PAD} card {card} end.", chunk=4
        )
        assert card not in emitted
        assert emitted.endswith("[CREDIT_CARD] end.")


class TestNoCollateralDamage:
    @pytest.mark.parametrize("chunk", [1, 4, 37, 500])
    def test_clean_text_passes_through_byte_identical(self, chunk):
        clean = PAD + " nothing sensitive here at all. end."
        assert _stream(_guard("secrets"), clean, chunk) == clean

    def test_held_tail_is_kept_unredacted(self):
        """The buffer is re-scanned every round, so masking it early is loss."""
        guard = _guard("secrets")
        guard.feed(PAD + " key sk-not-a-real-openai-key")
        assert "[REDACTED]" not in guard.pending


class TestAuditSpanOffsets:
    @pytest.fixture
    def store_text(self, monkeypatch):
        monkeypatch.setattr(settings, "GUARDRAILS_STORE_SCANNED_TEXT", True)

    @staticmethod
    def _rows(action):
        rows = []
        recorder = GuardrailRecorder(mode="scan_all")
        recorder._rows = rows
        config = GuardrailsConfig.model_validate(
            {
                "enabled": True,
                "mode": "scan_all",
                "controls": [{"check": "pii", "stage": "output", "action": action}],
            }
        )
        engine = GuardrailEngine(config, recorder=recorder)
        engine.evaluate(
            "Hello world, please contact alice@example.com right away "
            "and also bob@example.com thanks",
            Stage.OUTPUT,
        )
        return rows

    def test_redact_records_the_match_not_the_masked_text(self, store_text):
        assert self._rows("redact")[0]["matched_value"] == "alice@example.com"

    def test_flag_is_unaffected(self, store_text):
        assert self._rows("flag")[0]["matched_value"] == "alice@example.com"

    def test_nothing_is_stored_when_the_setting_is_off(self):
        assert self._rows("redact")[0]["matched_value"] is None
