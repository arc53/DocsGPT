"""Regressions for defects found in review. Each test names the hole it closes."""

from __future__ import annotations

import pytest

from application.guardrails.base import GuardrailCheck
from application.guardrails.config import GuardrailsConfig
from application.guardrails.engine import GuardrailEngine
from application.guardrails.guardrail_creator import GuardrailCreator
from application.guardrails.runtime import merge_floor
from application.guardrails.stream import StreamingOutputGuard
from application.guardrails.types import Action, CheckOutcome, Span, Stage, apply_spans


def _cfg(**over):
    return GuardrailsConfig.model_validate(over)


def _guard(controls, **over):
    return StreamingOutputGuard(
        GuardrailEngine(
            _cfg(enabled=True, mode="scan_all", controls=controls, **over)
        )
    )


def _drive(guard, chunks):
    out = []
    for chunk in chunks:
        step = guard.feed(chunk)
        out.append(step.emit)
        if step.blocked:
            return "".join(out), True
    step = guard.flush()
    out.append(step.emit)
    return "".join(out), step.blocked


class TestFloorSettingsAreAuthoritative:
    """An agent redeclaring a floor control must not supply its own settings."""

    def test_agent_settings_cannot_replace_floor_settings(self):
        floor = _cfg(
            enabled=True,
            controls=[{"check": "denylist", "stage": "output", "action": "block",
                       "settings": {"terms": ["project-raven"]}}],
        )
        agent = _cfg(
            enabled=True,
            controls=[{"check": "denylist", "stage": "output", "action": "block",
                       "settings": {"terms": ["zzz"]}}],
        )
        merged = merge_floor(agent, floor)
        assert merged.controls[0].settings["terms"] == ["project-raven"], (
            "an agent that can rewrite the floor's settings has defeated the floor"
        )

    def test_the_floor_term_is_actually_enforced_after_merge(self):
        floor = _cfg(
            enabled=True,
            controls=[{"check": "denylist", "stage": "output", "action": "block",
                       "settings": {"terms": ["raven"]}}],
        )
        agent = _cfg(
            enabled=True, mode="scan_all",
            controls=[{"check": "denylist", "stage": "output", "action": "block",
                       "settings": {"terms": ["zzz"]}}],
        )
        engine = GuardrailEngine(merge_floor(agent, floor))
        assert engine.evaluate("the raven flies", Stage.OUTPUT).blocked is True

    def test_agent_may_still_tighten_the_action(self):
        floor = _cfg(
            enabled=True,
            controls=[{"check": "secrets", "stage": "output", "action": "flag"}],
        )
        agent = _cfg(
            enabled=True,
            controls=[{"check": "secrets", "stage": "output", "action": "block"}],
        )
        assert merge_floor(agent, floor).controls[0].action is Action.BLOCK

    def test_pii_entity_narrowing_is_rejected(self):
        floor = _cfg(
            enabled=True,
            controls=[{"check": "pii", "stage": "output", "action": "redact",
                       "settings": {"entities": ["EMAIL", "US_SSN"]}}],
        )
        agent = _cfg(
            enabled=True,
            controls=[{"check": "pii", "stage": "output", "action": "redact",
                       "settings": {"entities": ["EMAIL"]}}],
        )
        merged = merge_floor(agent, floor)
        assert "US_SSN" in merged.controls[0].settings["entities"]


class TestModeMerge:
    """A floor that enforces must pull a monitoring agent up with it."""

    def test_floor_enforcement_wins(self):
        floor = _cfg(
            enabled=True, mode="scan_all",
            controls=[{"check": "pii", "stage": "output", "action": "redact"}],
        )
        agent = _cfg(enabled=True, mode="monitor_only")
        assert merge_floor(agent, floor).mode == "scan_all"

    def test_monitoring_floor_leaves_the_agent_alone(self):
        floor = _cfg(enabled=True, mode="monitor_only")
        agent = _cfg(enabled=True, mode="scan_all")
        assert merge_floor(agent, floor).mode == "scan_all"


class TestFailClosedCoversRedact:
    """fail_open=False exists so unscanned text never reaches the user."""

    def test_broken_redact_check_blocks_under_fail_closed(self):
        class Exploding(GuardrailCheck):
            name = "_rg_boom"
            supported_stages = {Stage.OUTPUT}
            supports_redaction = True

            def scan(self, text, stage, context):
                raise RuntimeError("detector down")

        GuardrailCreator.register(Exploding.name, Exploding)
        try:
            controls = [{"check": "_rg_boom", "stage": "output", "action": "redact"}]
            engine = GuardrailEngine(
                _cfg(enabled=True, mode="scan_all", fail_open=False, controls=controls)
            )
            assert engine.evaluate("my SSN is 123-45-6789", Stage.OUTPUT).blocked is True
            # And the consequence that actually matters: nothing reaches the wire.
            guard = _guard(controls, fail_open=False)
            text, blocked = _drive(guard, ["my SSN is ", "123-45-6789"])
            assert blocked is True
            assert "123-45-6789" not in text
        finally:
            GuardrailCreator.checks.pop(Exploding.name, None)

    def test_fail_open_still_lets_it_through(self):
        class Exploding(GuardrailCheck):
            name = "_rg_boom2"
            supported_stages = {Stage.OUTPUT}
            supports_redaction = True

            def scan(self, text, stage, context):
                raise RuntimeError("detector down")

        GuardrailCreator.register(Exploding.name, Exploding)
        try:
            engine = GuardrailEngine(
                _cfg(enabled=True, mode="scan_all", fail_open=True,
                     controls=[{"check": "_rg_boom2", "stage": "output",
                                "action": "redact"}])
            )
            assert engine.evaluate("hello", Stage.OUTPUT).blocked is False
        finally:
            GuardrailCreator.checks.pop(Exploding.name, None)


class TestSpanUnion:
    """Overlapping spans must union; the shorter must not win."""

    def test_longer_overlapping_span_is_not_discarded(self):
        text = "card 4111111111111111 end"
        out = apply_spans(
            text, [Span(5, 21, "CREDIT_CARD"), Span(5, 9, "BIN")]
        )
        assert "111111111111" not in out, f"card digits survived redaction: {out}"

    def test_partial_overlap_unions(self):
        out = apply_spans("abcdefghij", [Span(0, 5, "A"), Span(3, 9, "B")])
        assert out == "[A]j"

    def test_out_of_range_span_is_clamped_not_dropped(self):
        out = apply_spans("secret", [Span(0, 999, "X")])
        assert out == "[X]", "an over-long span must still redact what exists"

    def test_disjoint_spans_both_apply(self):
        out = apply_spans("aa bb cc", [Span(0, 2, "A"), Span(6, 8, "C")])
        assert out == "[A] bb [C]"

    def test_negative_start_is_clamped(self):
        assert apply_spans("abc", [Span(-5, 2, "X")]) == "[X]c"


class TestStreamingWindowCoversLongMatches:
    """A match longer than the default window must not survive streaming."""

    def _jwt(self) -> str:
        return "eyJhbGciOiJIUzI1NiJ9." + "A" * 300 + "." + "B" * 300

    @pytest.mark.parametrize("chunk_size", [1, 8, 64, 10000])
    def test_long_jwt_is_redacted_at_every_chunk_size(self, chunk_size):
        token = self._jwt()
        body = f"Here it is {token} done."
        guard = _guard(
            [{"check": "secrets", "stage": "output", "action": "redact"}]
        )
        chunks = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)]
        text, _ = _drive(guard, chunks)
        assert token not in text, (
            f"the JWT leaked whole at chunk size {chunk_size}"
        )
        assert "[REDACTED]" in text

    def test_window_is_sized_from_the_active_check(self):
        secrets = _guard([{"check": "secrets", "stage": "output", "action": "redact"}])
        email = _guard(
            [{"check": "pii", "stage": "output", "action": "redact",
              "settings": {"entities": ["EMAIL"]}}]
        )
        assert secrets.lookback > email.lookback, (
            "secrets can match far longer strings than an email and needs more window"
        )

    def test_long_denylist_term_widens_the_window(self):
        term = "x" * 100
        guard = _guard(
            [{"check": "denylist", "stage": "output", "action": "block",
              "settings": {"terms": [term]}}]
        )
        assert guard.lookback >= len(term) + 2
        _, blocked = _drive(guard, list(f"start {term} end"))
        assert blocked is True, "a long term split per character must still block"


class TestRemoteDoesNotWeakenLocal:
    """Adding a judge must not cost the deterministic checks their overlap."""

    def test_local_term_straddling_a_segment_boundary_still_blocks(self):
        class Judge(GuardrailCheck):
            name = "_rg_judge"
            supported_stages = {Stage.OUTPUT}
            remote = True

            def scan(self, text, stage, context):
                return CheckOutcome.clean()

        GuardrailCreator.register(Judge.name, Judge)
        try:
            controls = [
                {"check": "_rg_judge", "stage": "output", "action": "flag"},
                {"check": "denylist", "stage": "output", "action": "block",
                 "settings": {"terms": ["codename. raven"]}},
            ]
            guard = _guard(controls)
            _, blocked = _drive(
                guard,
                ["padding " * 60 + "the codename.", " raven is here."],
            )
            assert blocked is True, (
                "the denylist lost its overlap window because a judge was present"
            )
        finally:
            GuardrailCreator.checks.pop(Judge.name, None)


class TestGroundednessDeferredToCompleteAnswer:
    """Overlap against a half-written answer is meaningless."""

    def test_groundedness_does_not_run_per_chunk(self):
        docs = [{"text": "Postgres stores the agent configuration in JSONB."}]
        guard = _guard(
            [{"check": "groundedness", "stage": "output", "action": "flag",
              "settings": {"min_overlap": 0.9, "min_words": 3}}]
        )
        guard.engine.context.retrieved_docs = docs
        _drive(guard, ["Postgres stores ", "the agent ", "configuration in JSONB."])
        assert len(guard.decisions) == 1, (
            "groundedness must be evaluated once, over the finished answer"
        )

    def test_complete_answer_is_judged_not_the_tail(self):
        docs = [{"text": "Wholly unrelated source material about gardening."}]
        guard = _guard(
            [{"check": "groundedness", "stage": "output", "action": "flag",
              "settings": {"min_overlap": 0.5, "min_words": 5}}]
        )
        guard.engine.context.retrieved_docs = docs
        _drive(guard, ["Postgres stores ", "the agent configuration ", "inside JSONB columns."])
        triggered = [d for d in guard.decisions if d.triggered]
        assert triggered, "an ungrounded finished answer must be flagged"


class TestKeylessAgentsStillLoadConfig:
    """A draft agent has key = NULL, and the builder preview runs that path.

    Config used to be read only inside ``if effective_key:``, so the one place
    an operator would try a guardrail before publishing was the one place it
    did not run.
    """

    def test_configure_agent_loads_config_without_an_api_key(self, monkeypatch):
        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor.__new__(StreamProcessor)
        processor.data = {}
        processor.agent_config = {}
        processor.decoded_token = {"sub": "u"}
        processor.initial_user_id = "u"
        processor.agent_id = None
        processor.is_shared_usage = False
        processor.shared_token = None
        processor._agent_data = {}
        processor._authorized_agent_row = {
            "id": "abc",
            "config": {"guardrails": {"enabled": True}},
        }
        monkeypatch.setattr(
            StreamProcessor, "_resolve_agent_id", lambda self: "abc"
        )
        monkeypatch.setattr(
            StreamProcessor,
            "_get_agent_key",
            lambda self, agent_id, user_id: (None, False, None),
        )
        StreamProcessor._configure_agent(processor)
        assert processor.agent_config.get("config") == {
            "guardrails": {"enabled": True}
        }, "a keyless (draft) agent must still carry its guardrails"
