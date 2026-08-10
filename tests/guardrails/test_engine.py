"""Engine reduction, config validation, and fail-open/fail-closed semantics."""

from __future__ import annotations

import threading
import time

import pytest

from application.guardrails.base import GuardrailCheck, ScanContext
from application.guardrails.config import AgentConfig, GuardrailsConfig
from application.guardrails.engine import GuardrailEngine
from application.guardrails.guardrail_creator import GuardrailCreator
from application.guardrails.types import Action, CheckOutcome, Span, Stage


class AlwaysHitCheck(GuardrailCheck):
    name = "_test_always"
    label = "Always hits"
    supported_stages = {Stage.INPUT, Stage.OUTPUT}
    supports_redaction = True

    def scan(self, text, stage, context):
        return CheckOutcome.hit(categories=["TEST"], spans=[Span(0, 4, "X")])


class NeverHitCheck(GuardrailCheck):
    name = "_test_never"
    label = "Never hits"
    supported_stages = {Stage.INPUT, Stage.OUTPUT}

    def scan(self, text, stage, context):
        return CheckOutcome.clean()


class ExplodingCheck(GuardrailCheck):
    name = "_test_boom"
    label = "Raises"
    supported_stages = {Stage.INPUT, Stage.OUTPUT}

    def scan(self, text, stage, context):
        raise RuntimeError("detector exploded")


class SlowCheck(GuardrailCheck):
    name = "_test_slow"
    label = "Slow"
    supported_stages = {Stage.INPUT, Stage.OUTPUT}
    remote = True

    def scan(self, text, stage, context):
        time.sleep(2.0)
        return CheckOutcome.clean()


@pytest.fixture(autouse=True)
def _register_test_checks():
    GuardrailCreator._ensure_builtin()
    for cls in (AlwaysHitCheck, NeverHitCheck, ExplodingCheck, SlowCheck):
        GuardrailCreator.register(cls.name, cls)
    yield
    for cls in (AlwaysHitCheck, NeverHitCheck, ExplodingCheck, SlowCheck):
        GuardrailCreator.checks.pop(cls.name, None)


def _config(**over):
    base = {
        "enabled": True,
        "mode": "scan_all",
        "controls": [{"check": "_test_always", "stage": "input", "action": "block"}],
    }
    base.update(over)
    return GuardrailsConfig.model_validate(base)


class TestReduction:
    def test_block_action_blocks(self):
        engine = GuardrailEngine(_config())
        decision = engine.evaluate("some text", Stage.INPUT)
        assert decision.blocked is True
        assert decision.block_message

    def test_flag_action_does_not_block(self):
        engine = GuardrailEngine(
            _config(controls=[{"check": "_test_always", "stage": "input", "action": "flag"}])
        )
        decision = engine.evaluate("some text", Stage.INPUT)
        assert decision.blocked is False
        assert len(decision.triggered) == 1

    def test_redact_action_rewrites_text(self):
        engine = GuardrailEngine(
            _config(controls=[{"check": "_test_always", "stage": "input", "action": "redact"}])
        )
        decision = engine.evaluate("some text", Stage.INPUT)
        assert decision.redacted is True
        assert decision.text == "[X] text"
        assert decision.blocked is False

    def test_block_wins_over_redact(self):
        engine = GuardrailEngine(
            _config(
                controls=[
                    {"check": "_test_always", "stage": "input", "action": "redact"},
                    {"check": "denylist", "stage": "input", "action": "block",
                     "settings": {"terms": ["text"]}},
                ]
            )
        )
        decision = engine.evaluate("some text", Stage.INPUT)
        assert decision.blocked is True
        assert decision.text == "some text", "blocked turns must not leak a rewrite"

    def test_clean_scan_is_clean(self):
        engine = GuardrailEngine(
            _config(controls=[{"check": "_test_never", "stage": "input", "action": "block"}])
        )
        decision = engine.evaluate("some text", Stage.INPUT)
        assert decision.clean is True
        assert decision.blocked is False

    def test_no_controls_for_stage_is_a_noop(self):
        engine = GuardrailEngine(_config())
        decision = engine.evaluate("some text", Stage.OUTPUT)
        assert decision.verdicts == []
        assert decision.clean is True


class TestFailureSemantics:
    def test_raising_check_is_not_evaluated_not_clean(self):
        engine = GuardrailEngine(
            _config(controls=[{"check": "_test_boom", "stage": "input", "action": "block"}])
        )
        decision = engine.evaluate("some text", Stage.INPUT)
        assert len(decision.unevaluated) == 1
        assert decision.unevaluated[0].outcome.evaluated is False

    def test_fail_open_lets_a_broken_check_through(self):
        engine = GuardrailEngine(
            _config(
                fail_open=True,
                controls=[{"check": "_test_boom", "stage": "input", "action": "block"}],
            )
        )
        assert engine.evaluate("some text", Stage.INPUT).blocked is False

    def test_fail_closed_blocks_a_broken_check(self):
        engine = GuardrailEngine(
            _config(
                fail_open=False,
                controls=[{"check": "_test_boom", "stage": "input", "action": "block"}],
            )
        )
        assert engine.evaluate("some text", Stage.INPUT).blocked is True

    def test_fail_closed_does_not_block_a_flag_control(self):
        """A monitoring control that errors should not take the turn down."""
        engine = GuardrailEngine(
            _config(
                fail_open=False,
                controls=[{"check": "_test_boom", "stage": "input", "action": "flag"}],
            )
        )
        assert engine.evaluate("some text", Stage.INPUT).blocked is False

    def test_timeout_marks_not_evaluated(self):
        engine = GuardrailEngine(
            _config(
                timeout_ms=150,
                controls=[{"check": "_test_slow", "stage": "input", "action": "block"}],
            )
        )
        started = time.monotonic()
        decision = engine.evaluate("some text", Stage.INPUT)
        elapsed = time.monotonic() - started
        assert decision.unevaluated, "a timed-out check must not read as clean"
        assert decision.unevaluated[0].outcome.error == "timeout"
        assert elapsed < 1.5, f"timeout was not enforced (took {elapsed:.2f}s)"

    def test_stage_deadline_is_shared_not_per_check(self):
        """Three slow checks must not cost 3x the timeout."""
        engine = GuardrailEngine(
            _config(
                timeout_ms=200,
                controls=[
                    {"check": "_test_slow", "stage": "input", "action": "flag"},
                    {"check": "_test_slow", "stage": "output", "action": "flag"},
                ],
            )
        )
        started = time.monotonic()
        engine.evaluate("some text", Stage.INPUT)
        engine.evaluate("some text", Stage.OUTPUT)
        assert time.monotonic() - started < 1.5

    def test_local_checks_run_without_a_thread_pool(self):
        """The streaming hot loop must not pay for thread churn per chunk."""
        engine = GuardrailEngine(
            _config(controls=[{"check": "_test_always", "stage": "input", "action": "flag"}])
        )
        before = threading.active_count()
        for _ in range(50):
            engine.evaluate("some text", Stage.INPUT)
        assert threading.active_count() <= before + 1


class TestModes:
    def test_monitor_only_downgrades_block_to_flag(self):
        engine = GuardrailEngine(_config(mode="monitor_only"))
        decision = engine.evaluate("some text", Stage.INPUT)
        assert decision.blocked is False
        assert len(decision.triggered) == 1, "still observed, just not enforced"

    def test_dangerous_tools_only_skips_non_tool_stages(self):
        engine = GuardrailEngine(_config(mode="dangerous_tools_only"))
        assert engine.evaluate("some text", Stage.INPUT).verdicts == []

    def test_disabled_config_runs_nothing(self):
        engine = GuardrailEngine(_config(enabled=False))
        assert engine.evaluate("some text", Stage.INPUT).verdicts == []


class TestConfigValidation:
    def test_unknown_check_rejected(self):
        with pytest.raises(ValueError, match="unknown check"):
            GuardrailsConfig.model_validate(
                {"controls": [{"check": "nope", "stage": "input"}]}
            )

    def test_stage_unsupported_by_check_rejected(self):
        with pytest.raises(ValueError, match="does not support stage"):
            GuardrailsConfig.model_validate(
                {"controls": [{"check": "tool_policy", "stage": "input",
                               "settings": {"block_tools": ["x"]}}]}
            )

    def test_require_approval_rejected_outside_tool_stage(self):
        with pytest.raises(ValueError, match="not valid at stage"):
            GuardrailsConfig.model_validate(
                {"controls": [{"check": "pii", "stage": "input",
                               "action": "require_approval"}]}
            )

    def test_redact_rejected_for_check_without_spans(self):
        with pytest.raises(ValueError, match="cannot redact"):
            GuardrailsConfig.model_validate(
                {"controls": [{"check": "groundedness", "stage": "output",
                               "action": "redact"}]}
            )

    def test_duplicate_control_rejected(self):
        with pytest.raises(ValueError, match="duplicate control"):
            GuardrailsConfig.model_validate(
                {"controls": [
                    {"check": "pii", "stage": "input"},
                    {"check": "pii", "stage": "input"},
                ]}
            )

    def test_bad_settings_rejected_on_write(self):
        with pytest.raises(ValueError):
            GuardrailsConfig.model_validate(
                {"controls": [{"check": "denylist", "stage": "input", "settings": {}}]}
            )

    def test_settings_normalised_on_write(self):
        config = GuardrailsConfig.model_validate(
            {"controls": [{"check": "pii", "stage": "input"}]}
        )
        assert config.controls[0].settings["entities"], "defaults are filled in"

    def test_block_message_length_bounded(self):
        with pytest.raises(ValueError, match="500 characters"):
            GuardrailsConfig.model_validate({"block_message": "x" * 501})

    def test_extra_keys_forbidden(self):
        with pytest.raises(ValueError):
            GuardrailsConfig.model_validate({"nope": 1})


class TestLenientRead:
    @pytest.mark.parametrize("raw", [None, {}, [], "garbage", {"controls": "bad"}])
    def test_parse_never_raises(self, raw):
        config = GuardrailsConfig.parse(raw)
        assert config.enabled is False

    def test_agent_config_parse_survives_bad_guardrails(self):
        config = AgentConfig.parse({"guardrails": {"mode": "not-a-mode"}})
        assert config.guardrails.enabled is False

    def test_agent_config_roundtrips(self):
        raw = {"guardrails": {"enabled": True, "mode": "scan_all",
                              "controls": [{"check": "pii", "stage": "input"}]}}
        config = AgentConfig.model_validate(raw)
        assert config.guardrails.enabled is True
        assert AgentConfig.parse(config.model_dump(mode="json")).guardrails.enabled is True


class TestRecorder:
    def test_recorder_sees_triggered_decisions(self):
        seen = []
        engine = GuardrailEngine(_config(), recorder=seen.append)
        engine.evaluate("some text", Stage.INPUT)
        assert len(seen) == 1
        assert seen[0].blocked is True

    def test_recorder_skipped_on_clean_scan(self):
        seen = []
        engine = GuardrailEngine(
            _config(controls=[{"check": "_test_never", "stage": "input", "action": "block"}]),
            recorder=seen.append,
        )
        engine.evaluate("some text", Stage.INPUT)
        assert seen == []

    def test_recorder_failure_does_not_break_the_turn(self):
        def boom(_decision):
            raise RuntimeError("audit down")

        engine = GuardrailEngine(_config(), recorder=boom)
        assert engine.evaluate("some text", Stage.INPUT).blocked is True


class TestContextPassing:
    def test_scan_context_reaches_the_check(self):
        seen = {}

        class ContextProbe(GuardrailCheck):
            name = "_test_ctx"
            supported_stages = {Stage.INPUT}

            def scan(self, text, stage, context):
                seen["tool"] = context.tool_name
                return CheckOutcome.clean()

        GuardrailCreator.register(ContextProbe.name, ContextProbe)
        try:
            engine = GuardrailEngine(
                _config(controls=[{"check": "_test_ctx", "stage": "input"}]),
                context=ScanContext(tool_name="shell"),
            )
            engine.evaluate("x", Stage.INPUT)
            assert seen["tool"] == "shell"
        finally:
            GuardrailCreator.checks.pop(ContextProbe.name, None)


def test_action_enum_serialises_as_value():
    config = GuardrailsConfig.model_validate(
        {"controls": [{"check": "pii", "stage": "input", "action": "redact"}]}
    )
    dumped = config.model_dump(mode="json")
    assert dumped["controls"][0]["action"] == Action.REDACT.value
    assert dumped["controls"][0]["stage"] == Stage.INPUT.value
