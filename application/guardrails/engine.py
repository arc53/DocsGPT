"""Runs the controls attached to a stage and reduces them to one decision."""

from __future__ import annotations

import logging
from threading import Thread
from time import monotonic
from typing import List, Optional

from application.guardrails.base import ScanContext
from application.guardrails.config import GuardrailsConfig
from application.guardrails.guardrail_creator import GuardrailCreator
from application.guardrails.types import (
    Action,
    CheckOutcome,
    ControlVerdict,
    Span,
    Stage,
    StageDecision,
    apply_spans,
)

logger = logging.getLogger(__name__)

# Hard cap on threads one stage evaluation may spawn.
_MAX_WORKERS = 8


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

    def _run_control(self, control, text: str, stage: Stage) -> ControlVerdict:
        try:
            check = GuardrailCreator.create(control.check, control.settings)
        except Exception as exc:
            logger.warning("Guardrail check %s unavailable: %s", control.check, exc)
            return ControlVerdict(
                check=control.check,
                stage=stage,
                action=control.action,
                outcome=CheckOutcome.not_evaluated(f"unavailable: {exc}"),
            )
        try:
            outcome = check.scan(text, stage, self.context)
        except Exception as exc:
            logger.warning(
                "Guardrail check %s raised at stage %s: %s", control.check, stage.value, exc
            )
            outcome = CheckOutcome.not_evaluated(f"error: {type(exc).__name__}")
        return ControlVerdict(
            check=control.check, stage=stage, action=control.action, outcome=outcome
        )

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
        decision = StageDecision(stage=stage, text=text)
        if controls is None:
            controls = self.config.controls_for(stage)
        if not controls:
            return decision

        if any(self._needs_deadline(c) for c in controls):
            decision.verdicts = self._run_concurrent(controls, text, stage)
        else:
            # Bounded local checks are pattern matches measured in
            # microseconds. Running them inline keeps the streaming hot loop
            # free of thread churn.
            decision.verdicts = [self._run_control(c, text, stage) for c in controls]

        self._reduce(decision)
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
            slot: dict = {"control": control, "verdict": None}
            thread = Thread(
                target=self._fill_slot,
                args=(slot, control, text, stage),
                daemon=True,
                name=f"guardrail-{control.check}",
            )
            thread.start()
            slot["thread"] = thread
            slots.append(slot)

        verdicts: List[ControlVerdict] = []
        for slot in slots:
            slot["thread"].join(timeout=max(0.0, deadline - monotonic()))
            verdict = slot["verdict"]
            if verdict is None:
                verdict = ControlVerdict(
                    check=slot["control"].check,
                    stage=stage,
                    action=slot["control"].action,
                    outcome=CheckOutcome.not_evaluated("timeout"),
                )
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
                    ControlVerdict(
                        check=control.check,
                        stage=stage,
                        action=control.action,
                        outcome=CheckOutcome.not_evaluated("concurrency cap"),
                    )
                )
        return verdicts

    def _fill_slot(self, slot: dict, control, text: str, stage: Stage) -> None:
        try:
            slot["verdict"] = self._run_control(control, text, stage)
        except Exception as exc:
            slot["verdict"] = ControlVerdict(
                check=control.check,
                stage=stage,
                action=control.action,
                outcome=CheckOutcome.not_evaluated(f"error: {type(exc).__name__}"),
            )

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
