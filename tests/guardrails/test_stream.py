"""Streaming output guarding: nothing unsafe may reach the wire."""

from __future__ import annotations

import pytest

from application.guardrails.base import GuardrailCheck
from application.guardrails.config import GuardrailsConfig
from application.guardrails.engine import GuardrailEngine
from application.guardrails.guardrail_creator import GuardrailCreator
from application.guardrails.stream import MAX_HOLD_CHARS, StreamingOutputGuard
from application.guardrails.types import CheckOutcome, Stage


class RemoteFlagCheck(GuardrailCheck):
    """Stands in for a judge: remote, so it forces segment accumulation."""

    name = "_test_remote"
    label = "Remote"
    supported_stages = {Stage.OUTPUT}
    remote = True
    calls = 0

    def scan(self, text, stage, context):
        type(self).calls += 1
        return CheckOutcome.hit(categories=["BAD"]) if "forbidden" in text else CheckOutcome.clean()


@pytest.fixture(autouse=True)
def _register():
    GuardrailCreator._ensure_builtin()
    GuardrailCreator.register(RemoteFlagCheck.name, RemoteFlagCheck)
    RemoteFlagCheck.calls = 0
    yield
    GuardrailCreator.checks.pop(RemoteFlagCheck.name, None)


def _guard(controls, mode="scan_all", **over):
    config = GuardrailsConfig.model_validate(
        {"enabled": True, "mode": mode, "controls": controls, **over}
    )
    return StreamingOutputGuard(GuardrailEngine(config))


def _drive(guard, chunks):
    """Feed chunks, return (emitted_text, blocked)."""
    out = []
    for chunk in chunks:
        step = guard.feed(chunk)
        out.append(step.emit)
        if step.blocked:
            return "".join(out), True
    step = guard.flush()
    out.append(step.emit)
    return "".join(out), step.blocked


REDACT_EMAIL = [
    {"check": "pii", "stage": "output", "action": "redact",
     "settings": {"entities": ["EMAIL"]}}
]
BLOCK_TERM = [
    {"check": "denylist", "stage": "output", "action": "block",
     "settings": {"terms": ["forbidden"]}}
]


class TestPassthrough:
    def test_no_output_controls_streams_verbatim(self):
        guard = _guard([{"check": "pii", "stage": "input", "action": "flag"}])
        text, blocked = _drive(guard, ["hello ", "world"])
        assert (text, blocked) == ("hello world", False)

    def test_clean_stream_is_reassembled_exactly(self):
        guard = _guard(REDACT_EMAIL)
        chunks = ["The ", "quick ", "brown ", "fox ", "jumps."]
        text, blocked = _drive(guard, chunks)
        assert text == "".join(chunks)
        assert blocked is False

    def test_empty_chunks_are_harmless(self):
        guard = _guard(REDACT_EMAIL)
        text, _ = _drive(guard, ["a", "", "b", "", "c"])
        assert text == "abc"


class TestLookbackRedaction:
    def test_pii_split_across_chunk_boundary_is_still_caught(self):
        """The whole point of the lookback: 'ada@exa' + 'mple.com' must not leak."""
        guard = _guard(REDACT_EMAIL)
        text, _ = _drive(guard, ["contact ada@exa", "mple.com today"])
        assert "ada@example.com" not in text
        assert "[EMAIL]" in text
        assert text == "contact [EMAIL] today"

    def test_pii_split_one_character_at_a_time(self):
        guard = _guard(REDACT_EMAIL)
        text, _ = _drive(guard, list("mail ada@example.com now"))
        assert "ada@example.com" not in text
        assert text == "mail [EMAIL] now"

    def test_nothing_leaks_before_the_lookback_window_fills(self):
        """Early feeds must withhold; a short stream reveals nothing until flush."""
        guard = _guard(REDACT_EMAIL)
        step = guard.feed("ada@example.com")
        assert step.emit == "", "a buffer shorter than the lookback must not release"
        assert "[EMAIL]" in guard.flush().emit

    def test_long_clean_stream_releases_progressively(self):
        guard = _guard(REDACT_EMAIL)
        released = ""
        for _ in range(30):
            released += guard.feed("x" * 50).emit
        assert released, "a long stream must not buffer indefinitely"
        assert len(released) >= 1500 - guard.lookback

    def test_held_tail_never_exceeds_the_window_on_clean_text(self):
        guard = _guard(REDACT_EMAIL)
        for _ in range(30):
            guard.feed("y" * 40)
        assert len(guard.pending) <= guard.lookback

    def test_secret_split_across_boundary_is_redacted(self):
        guard = _guard(
            [{"check": "secrets", "stage": "output", "action": "redact"}]
        )
        token = "ghp_" + "a" * 36
        text, _ = _drive(guard, ["token ", token[:10], token[10:], " done"])
        assert token not in text
        assert "[REDACTED]" in text


class TestBlocking:
    def test_block_stops_the_stream(self):
        guard = _guard(BLOCK_TERM)
        text, blocked = _drive(guard, ["this is ", "forbidden ", "content"])
        assert blocked is True
        assert "forbidden" not in text

    def test_blocked_guard_stays_blocked(self):
        guard = _guard(BLOCK_TERM)
        _drive(guard, ["forbidden " + "x " * 100])
        step = guard.feed("more text")
        assert step.blocked is True
        assert step.emit == ""

    def test_block_message_is_surfaced(self):
        guard = _guard(BLOCK_TERM, block_message="Nope.")
        for chunk in ["forbidden ", "x " * 100]:
            step = guard.feed(chunk)
            if step.blocked:
                assert step.block_message == "Nope."
                return
        assert guard.flush().block_message == "Nope."

    def test_term_split_across_boundary_still_blocks(self):
        guard = _guard(BLOCK_TERM)
        _, blocked = _drive(guard, ["this is forb", "idden text"])
        assert blocked is True

    def test_flush_catches_a_violation_in_the_tail(self):
        guard = _guard(BLOCK_TERM)
        step = guard.feed("short forbidden")
        assert step.emit == ""
        assert guard.flush().blocked is True


class TestMonitorMode:
    def test_monitor_only_never_blocks_the_stream(self):
        guard = _guard(BLOCK_TERM, mode="monitor_only")
        text, blocked = _drive(guard, ["this is forbidden content"])
        assert blocked is False
        assert "forbidden" in text, "monitor mode observes without altering output"
        assert any(d.triggered for d in guard.decisions)

    def test_monitor_only_does_not_redact(self):
        guard = _guard(REDACT_EMAIL, mode="monitor_only")
        text, _ = _drive(guard, ["mail ada@example.com now"])
        assert "ada@example.com" in text


class TestRemoteSegmentation:
    def test_remote_check_waits_for_a_sentence_boundary(self):
        guard = _guard([{"check": "_test_remote", "stage": "output", "action": "block"}])
        step = guard.feed("A short clause without a terminator")
        assert step.emit == ""
        assert RemoteFlagCheck.calls == 0, "no judge call before a boundary exists"

    def test_remote_check_releases_a_completed_segment(self):
        guard = _guard([{"check": "_test_remote", "stage": "output", "action": "block"}])
        guard.feed("word " * 100)
        step = guard.feed("End of it. ")
        assert step.emit, "a completed segment past the threshold must release"
        assert RemoteFlagCheck.calls >= 1

    def test_remote_check_blocks_a_bad_segment(self):
        guard = _guard([{"check": "_test_remote", "stage": "output", "action": "block"}])
        _, blocked = _drive(guard, ["something forbidden here. " + "pad " * 120])
        assert blocked is True

    def test_judge_is_not_called_per_token(self):
        """Cost control: segment accumulation, not one call per chunk."""
        guard = _guard([{"check": "_test_remote", "stage": "output", "action": "flag"}])
        _drive(guard, ["token " for _ in range(200)])
        assert RemoteFlagCheck.calls <= 5, f"{RemoteFlagCheck.calls} judge calls is too many"


class TestBackpressure:
    def test_buffer_cannot_grow_without_bound(self):
        """A remote check plus prose with no terminator must still make progress."""
        guard = _guard([{"check": "_test_remote", "stage": "output", "action": "flag"}])
        released = ""
        for _ in range(60):
            released += guard.feed("nopunctuation " * 20).emit
        assert released, "the stream must not stall forever waiting for a boundary"
        assert len(guard.pending) <= MAX_HOLD_CHARS

    def test_flush_on_empty_guard_is_safe(self):
        guard = _guard(REDACT_EMAIL)
        assert guard.flush().emit == ""
        assert guard.flush().blocked is False


class TestReassembly:
    @pytest.mark.parametrize("size", [1, 3, 7, 64, 500])
    def test_clean_text_survives_any_chunking(self, size):
        body = ("Postgres stores configuration in JSONB. " * 20).strip()
        guard = _guard(REDACT_EMAIL)
        chunks = [body[i : i + size] for i in range(0, len(body), size)]
        text, blocked = _drive(guard, chunks)
        assert blocked is False
        assert text == body, f"reassembly differed at chunk size {size}"
