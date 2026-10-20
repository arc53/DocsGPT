"""Runs the controls attached to a stage and reduces them to one decision."""

from __future__ import annotations

import logging
from threading import Lock, Thread
from time import monotonic
import copy
from typing import Any, Callable, Dict, List, Optional, Sequence

from docsgpt import tracing
from docsgpt.guardrails.base import ScanContext, stage_deadline
from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.guardrails.guardrail_creator import GuardrailCreator
from docsgpt.guardrails.types import (
    ITEM_STAGES,
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
    def _verdict(control, stage: Stage, outcome: CheckOutcome, item_ref: Optional[str] = None) -> ControlVerdict:
        """The control's verdict, its action capped by what the outcome may carry."""
        return ControlVerdict(
            check=control.check,
            stage=stage,
            action=capped(control.action, outcome.at_most),
            outcome=outcome,
            item_ref=item_ref,
        )

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

    def evaluate(
        self, text: str, stage: Stage, controls=None, item_level: Optional[bool] = None
    ) -> StageDecision:
        """Scan ``text`` for ``stage`` and reduce to the most restrictive outcome.

        Args:
            text: The text.
            stage: The stage.
            controls: A subset of the stage's controls to run; the streaming
                guard uses it to defer complete-text checks to the final scan.
            item_level: Which of the stage's controls run (see
                ``GuardrailsConfig.controls_for``). At an item stage the text
                is the joined items, which the item-level checks already scored
                one by one (``evaluate_items``), so they are always left out.
        """
        decision = StageDecision(stage=stage, text=text, original_text=text)
        if controls is None:
            controls = self.config.controls_for(stage, item_level=False if stage in ITEM_STAGES else item_level)
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
        """Run controls on one text in parallel under a single stage-wide deadline."""
        return self._concurrently(
            controls,
            stage,
            lambda control, publish: self._run_control(control, text, stage, publish),
            lambda control, error: self._verdict(control, stage, CheckOutcome.not_evaluated(error)),
        )

    def _concurrently(self, controls, stage: Stage, run: Callable, missing: Callable) -> List[Any]:
        """Run ``run(control, publish)`` for each control in parallel under a single stage-wide deadline.

        Raw daemon threads rather than a ThreadPoolExecutor: a check that
        overruns is abandoned, and executor threads are non-daemon and joined
        by an atexit hook, so a stuck judge call would block worker shutdown.
        Daemon threads let the process exit regardless.

        Args:
            controls: The controls.
            stage: The stage, for the log line past the concurrency cap.
            run: Scans with one control and hands its result to ``publish``.
            missing: ``(control, error)`` to the result of a control that gave
                none in time (``timeout``) or never ran.

        Returns:
            One result per control, in order.
        """
        deadline = monotonic() + max(self.config.timeout_ms, 100) / 1000.0
        slots: List[dict] = []
        for control in controls[:_MAX_WORKERS]:
            slot: dict = {"control": control, "verdict": None, "abandoned": False, "lock": Lock()}
            thread = Thread(
                target=tracing.wrap(self._fill_slot),
                args=(slot, run, missing, deadline),
                daemon=True,
                name=f"guardrail-{control.check}",
            )
            thread.start()
            slot["thread"] = thread
            slots.append(slot)

        results: List[Any] = []
        for slot in slots:
            slot["thread"].join(timeout=max(0.0, deadline - monotonic()))
            with slot["lock"]:
                result = slot["verdict"]
                slot["abandoned"] = result is None
            results.append(missing(slot["control"], "timeout") if result is None else result)

        if len(controls) > _MAX_WORKERS:
            logger.warning(
                "Stage %s has %d controls; only the first %d ran",
                stage.value,
                len(controls),
                _MAX_WORKERS,
            )
            results.extend(missing(control, "concurrency cap") for control in controls[_MAX_WORKERS:])
        return results

    def _fill_slot(self, slot: dict, run: Callable, missing: Callable, deadline: float) -> None:
        # Set here, in the check's own thread, so the check can size its
        # remote call to the time the stage has left.
        stage_deadline.set(deadline)
        control = slot["control"]
        try:
            run(control, lambda result: self._publish(slot, result))
        except Exception as exc:
            self._publish(slot, missing(control, f"error: {type(exc).__name__}"))

    def evaluate_items(
        self,
        items: Sequence[str],
        stage: Stage,
        refs: Sequence[str],
        hints: Optional[List[Dict[str, Any]]] = None,
    ) -> List[StageDecision]:
        """Scan each item for ``stage`` with the stage's item-level controls; one decision per item.

        Runs under the same deadline and thread rules as ``evaluate``, and each
        item is reduced on its own, so a ``blocked`` decision withholds that
        item only. Every non-clean decision is recorded, with its item's ref.

        Args:
            items: The items' texts.
            stage: The stage (``retrieval`` or ``attachment``).
            refs: Per item, the ref its verdicts and journal rows carry.
            hints: Per item, what the caller knows about it (see
                ``ScanContext.item_hints``).

        Returns:
            One decision per item, in order; all clean when no control applies.
        """
        decisions = [StageDecision(stage=stage, text=text, original_text=text) for text in items]
        controls = self.config.controls_for(stage, item_level=True)
        if not controls or not decisions:
            return decisions
        context = copy.copy(self.context)
        context.item_hints = list(hints) if hints is not None else None
        stats: Dict[str, int] = {}
        with _start_guardrail_span(stage, controls) as span:
            per_control = self._concurrently(
                controls,
                stage,
                lambda control, publish: self._run_control_items(
                    control, list(items), list(refs), stage, context, stats, publish
                ),
                lambda control, error: [
                    self._verdict(control, stage, CheckOutcome.not_evaluated(error), ref) for ref in refs
                ],
            )
            for index, decision in enumerate(decisions):
                decision.verdicts = [verdicts[index] for verdicts in per_control]
                self._reduce(decision)
            span.set(
                **{
                    "docsgpt.guardrail.items": len(decisions),
                    "docsgpt.guardrail.withheld": sum(d.blocked for d in decisions),
                    **{f"docsgpt.guardrail.{key}": value for key, value in stats.items()},
                }
            )
            if any(_content_fired(d) for d in decisions):
                tracing.mark_content_blocked()
        for decision in decisions:
            self._record(decision)
        return decisions

    def _run_control_items(
        self,
        control,
        items: List[str],
        refs: List[str],
        stage: Stage,
        context: ScanContext,
        stats: Dict[str, int],
        publish: Callable[[List[ControlVerdict]], bool],
    ) -> None:
        """Scan the items with one control and tell its check the verdicts, as ``_run_control`` does for one text.

        A check that reports ``item_stats`` (cache hits, live and deferred
        items) adds them to ``stats`` for the stage's span.
        """
        try:
            check = GuardrailCreator.create(control.check, control.settings)
        except Exception as exc:
            logger.warning("Guardrail check %s unavailable: %s", control.check, exc)
            publish([self._verdict(control, stage, CheckOutcome.not_evaluated(f"unavailable: {exc}"), r)
                     for r in refs])
            return
        try:
            outcomes = check.scan_items(items, stage, context)
            if len(outcomes) != len(items):
                raise ValueError(f"{len(outcomes)} outcomes for {len(items)} items")
        except Exception as exc:
            logger.warning(
                "Guardrail check %s raised on items at stage %s: %s", control.check, stage.value, exc
            )
            outcomes = [CheckOutcome.not_evaluated(f"error: {type(exc).__name__}")] * len(items)
        verdicts = [self._verdict(control, stage, outcome, ref) for outcome, ref in zip(outcomes, refs)]
        for key, value in (getattr(check, "item_stats", None) or {}).items():
            stats[key] = stats.get(key, 0) + value
        if not publish(verdicts):
            return
        try:
            check.settled_items(control.action, verdicts, [self._withholds(v) for v in verdicts])
        except Exception:
            logger.exception("Guardrail check %s failed after its item verdicts", control.check)

    def _withholds(self, verdict: ControlVerdict) -> bool:
        """Whether one verdict blocks its text, by ``_reduce``'s rules."""
        if not verdict.outcome.evaluated:
            return not self.config.fail_open and verdict.action in (Action.BLOCK, Action.REDACT)
        return verdict.blocking

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
