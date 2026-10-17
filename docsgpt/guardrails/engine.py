"""Runs the controls attached to a stage and reduces them to one decision."""

from __future__ import annotations

import logging
from threading import Lock, Thread
from time import monotonic
from typing import Any, Callable, List, Optional, Sequence

from docsgpt import tracing
from docsgpt.guardrails.base import ScanContext, stage_deadline
from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.guardrails.guardrail_creator import GuardrailCreator
from docsgpt.guardrails.types import (
    Action,
    CheckOutcome,
    ControlVerdict,
    Span,
    Stage,
    StageDecision,
    apply_spans,
    capped,
)

logger = logging.getLogger(__name__)

# Hard cap on threads one stage evaluation may spawn.
_MAX_WORKERS = 8


def _start_guardrail_span(stage: Stage, controls: Sequence[Any]) -> "tracing.Span":
    """Open a ``guardrail`` span for evaluating ``controls`` at ``stage``."""
    return tracing.start_span(
        tracing.KIND_GUARDRAIL,
        f"guardrail {stage.value}",
        attributes={
            "docsgpt.guardrail.stage": stage.value,
            "docsgpt.guardrail.checks": [c.check for c in controls],
        },
    )


def _content_fired(decision: StageDecision) -> bool:
    """True when a check matched, or the text was blocked or redacted."""
    return bool(decision.triggered or decision.blocked or decision.redacted)


def _decision_key(decision: StageDecision) -> tuple:
    """Identity of a guardrail outcome, for recording each distinct one once."""
    return (
        "guardrail",
        decision.stage.value,
        tuple(sorted(v.check for v in decision.triggered)),
        tuple(sorted(v.check for v in decision.unevaluated)),
        decision.blocked,
        decision.redacted,
    )


def _describe_decision(span: "tracing.Span", decision: StageDecision) -> None:
    """Record a stage decision on its span; a firing guardrail drops trace previews."""
    triggered = [v.check for v in decision.triggered]
    span.set(
        **{
            "docsgpt.guardrail.triggered": triggered or None,
            "docsgpt.guardrail.blocked": decision.blocked,
            "docsgpt.guardrail.redacted": decision.redacted,
            "docsgpt.guardrail.categories": decision.categories() or None,
            "docsgpt.guardrail.unevaluated": [v.check for v in decision.unevaluated] or None,
        }
    )
    if _content_fired(decision):
        # The scanned text (or text near it) sits in other spans' previews:
        # the retrieval query, tool results, the answer. Keep none of it.
        tracing.mark_content_blocked()


class GuardrailEngine:
    """Stateless evaluator bound to one agent's resolved config."""

    def __init__(
        self,
        config: GuardrailsConfig,
        context: Optional[ScanContext] = None,
        recorder=None,
    ):
        self.config = config
        self.context = context or ScanContext()
        self.recorder = recorder

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def has_stage(self, stage: Stage) -> bool:
        return self.config.has_any(stage)

    @staticmethod
    def _verdict(control, stage: Stage, outcome: CheckOutcome) -> ControlVerdict:
        """The control's verdict, its action capped by what the outcome may carry.

        An outcome that could not be evaluated is also capped by its check's
        ``unevaluated_at_most``, so a check that must never stop a turn it
        could not scan stays a flag even on a fail-closed agent.
        """
        action = capped(control.action, outcome.at_most)
        if not outcome.evaluated:
            try:
                limit = GuardrailCreator.get(control.check).unevaluated_at_most(control.settings)
            except Exception:
                limit = None
            action = capped(action, limit)
        return ControlVerdict(check=control.check, stage=stage, action=action, outcome=outcome)

    def _run_control(
        self,
        control,
        text: str,
        stage: Stage,
        publish: Optional[Callable[[ControlVerdict], bool]] = None,
    ) -> ControlVerdict:
        """Scan with one control and tell its check the verdict.

        ``publish`` hands the verdict to a stage running controls in parallel;
        when it returns False the stage already gave up on this control, so the
        check is not told a verdict the stage never used.
        """
        try:
            check = GuardrailCreator.create(control.check, control.settings)
        except Exception as exc:
            logger.warning("Guardrail check %s unavailable: %s", control.check, exc)
            verdict = self._verdict(control, stage, CheckOutcome.not_evaluated(f"unavailable: {exc}"))
            if publish is not None:
                publish(verdict)
            return verdict
        try:
            outcome = check.scan(text, stage, self.context)
        except Exception as exc:
            logger.warning(
                "Guardrail check %s raised at stage %s: %s", control.check, stage.value, exc
            )
            outcome = CheckOutcome.not_evaluated(f"error: {type(exc).__name__}")
        verdict = self._verdict(control, stage, outcome)
        if publish is not None and not publish(verdict):
            return verdict
        try:
            check.settled(control.action, verdict)
        except Exception:
            logger.exception("Guardrail check %s failed after its verdict", control.check)
        return verdict

    @staticmethod
    def _needs_deadline(control) -> bool:
        """True when this control must be run under the stage deadline.

        Only remote checks block on I/O. Everything else is a bounded local
        pattern match and runs inline.
        """
        try:
            return bool(GuardrailCreator.get(control.check).remote)
        except Exception:
            return True

    def evaluate(self, text: str, stage: Stage, controls=None) -> StageDecision:
        """Scan ``text`` for ``stage`` and reduce to the most restrictive outcome.

        ``controls`` narrows the run to a subset of the stage's controls; the
        streaming guard uses it to defer complete-text checks to the final scan.
        """
        decision = StageDecision(stage=stage, text=text, original_text=text)
        if controls is None:
            controls = self.config.controls_for(stage)
        if not controls:
            return decision

        if any(self._needs_deadline(c) for c in controls):
            # Remote checks (e.g. an LLM judge) cost real time, so they are
            # always traced; the judge's own LLM call nests under this span.
            with _start_guardrail_span(stage, controls) as span:
                decision.verdicts = self._run_concurrent(controls, text, stage)
                self._reduce(decision)
                _describe_decision(span, decision)
        else:
            # Bounded local checks are pattern matches measured in
            # microseconds. Running them inline keeps the streaming hot loop
            # free of thread churn.
            decision.verdicts = [self._run_control(c, text, stage) for c in controls]
            self._reduce(decision)
            # The output guard evaluates every streamed segment; tracing each
            # clean local scan would bury the trace, so only a firing is kept,
            # and a firing that repeats unchanged segment after segment is
            # recorded once so it cannot use up the trace's span cap.
            if not decision.clean or decision.unevaluated:
                if tracing.first_occurrence(_decision_key(decision)):
                    with _start_guardrail_span(stage, controls) as span:
                        _describe_decision(span, decision)
                elif _content_fired(decision):
                    tracing.mark_content_blocked()

        self._record(decision)
        return decision

    def _run_concurrent(self, controls, text: str, stage: Stage) -> List[ControlVerdict]:
        """Run controls in parallel under a single stage-wide deadline.

        Raw daemon threads rather than a ThreadPoolExecutor: a check that
        overruns is abandoned, and executor threads are non-daemon and joined
        by an atexit hook, so a stuck judge call would block worker shutdown.
        Daemon threads let the process exit regardless.
        """
        deadline = monotonic() + max(self.config.timeout_ms, 100) / 1000.0
        slots: List[dict] = []
        for control in controls[:_MAX_WORKERS]:
            slot: dict = {"control": control, "verdict": None, "abandoned": False, "lock": Lock()}
            thread = Thread(
                target=tracing.wrap(self._fill_slot),
                args=(slot, control, text, stage, deadline),
                daemon=True,
                name=f"guardrail-{control.check}",
            )
            thread.start()
            slot["thread"] = thread
            slots.append(slot)

        verdicts: List[ControlVerdict] = []
        for slot in slots:
            slot["thread"].join(timeout=max(0.0, deadline - monotonic()))
            with slot["lock"]:
                verdict = slot["verdict"]
                slot["abandoned"] = verdict is None
            if verdict is None:
                verdict = self._verdict(slot["control"], stage, CheckOutcome.not_evaluated("timeout"))
            verdicts.append(verdict)

        if len(controls) > _MAX_WORKERS:
            logger.warning(
                "Stage %s has %d controls; only the first %d ran",
                stage.value,
                len(controls),
                _MAX_WORKERS,
            )
            for control in controls[_MAX_WORKERS:]:
                verdicts.append(
                    self._verdict(control, stage, CheckOutcome.not_evaluated("concurrency cap"))
                )
        return verdicts

    def _fill_slot(self, slot: dict, control, text: str, stage: Stage, deadline: float) -> None:
        # Set here, in the check's own thread, so the check can size its
        # remote call to the time the stage has left.
        stage_deadline.set(deadline)
        try:
            self._run_control(control, text, stage, lambda verdict: self._publish(slot, verdict))
        except Exception as exc:
            self._publish(
                slot,
                self._verdict(control, stage, CheckOutcome.not_evaluated(f"error: {type(exc).__name__}")),
            )

    @staticmethod
    def _publish(slot: dict, verdict: ControlVerdict) -> bool:
        """Hand a control's verdict to its stage; False once the stage stopped waiting for it."""
        with slot["lock"]:
            if slot["abandoned"]:
                return False
            slot["verdict"] = verdict
            return True

    def _reduce(self, decision: StageDecision) -> None:
        """Fold verdicts into the decision. Most restrictive outcome wins."""
        redact_spans: List[Span] = []
        for verdict in decision.verdicts:
            if not verdict.outcome.evaluated:
                # A check that could not run is not a pass. Under fail-closed
                # it stops the turn; under fail-open it is logged and ignored.
                # REDACT counts: fail-closed exists precisely so unscanned text
                # never reaches the user, and a broken PII detector would
                # otherwise release the PII it was there to remove.
                if not self.config.fail_open and verdict.action in (
                    Action.BLOCK,
                    Action.REDACT,
                ):
                    decision.blocked = True
                    decision.block_message = self.config.block_message
                continue
            if not verdict.outcome.triggered:
                continue
            if verdict.action is Action.BLOCK:
                decision.blocked = True
                decision.block_message = self.config.block_message
            elif verdict.action is Action.REDACT:
                redact_spans.extend(verdict.outcome.spans)

        if redact_spans and not decision.blocked:
            redacted = apply_spans(decision.text, redact_spans)
            if redacted != decision.text:
                decision.text = redacted
                decision.redacted = True

    def _record(self, decision: StageDecision) -> None:
        if self.recorder is None:
            return
        if decision.clean and not decision.unevaluated:
            return
        try:
            self.recorder(decision)
        except Exception:
            logger.exception("Guardrail audit recording failed")
