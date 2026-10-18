"""Prompt injection scored by the decision model rather than matched by patterns.

The check asks the decision model (``docsgpt.decisions``) its trained ``injection`` question about the text and
gets a probability back. One control carries two thresholds: from ``flag_threshold`` the text is flagged as
suspected, which is recorded and never enforced; from ``threshold`` the control's own action applies.

The operator decides only whether the model may run at all (``DECISION_INJECTION_ENABLED``); while it may not, the
check is unavailable and asks nothing. A text the model could not score (the switch is off, the model is off, still
loading, or out of time) is not a pass: the outcome is *not evaluated* and the agent's ``fail_open`` decides for a
control that blocks. A control that only flags, such as the floor's or the defaults' flag-only rule, never stops a
turn it could not score.

Texts are scored through ``docsgpt.guardrails.injection_scoring``, which windows long text and caches scores by
content. One window over the flag threshold settles the verdict; otherwise every window must be scored, or the
outcome is *not evaluated* and says how many were (``windows=2/13``).

At ``input`` and ``tool_result`` the check scores the one text live, under the stage deadline. At ``retrieval``
and ``attachment`` it scores each document or file on its own (``item_level``), so ``block`` withholds that item
alone. An item is clean when its source's owner marked it safe; otherwise its score comes from the score stored
with it (an attachment parsed with a scan), the cache, the model within the stage deadline (at most
``GUARDRAILS_INJECTION_LIVE_ITEMS`` items), or not at all this turn: it is *not evaluated* and queued to be scored
in the background, so the next turn that uses it finds the score cached.

Every evaluation that asks the model or the cache is also an entry in the request's decision record
(``docsgpt.decisions.record``): the probability, the thresholds and how many windows or items were scored, never
the text. ``applied`` is false when the control only flags (its action is ``flag``, or the agent runs
``monitor_only``).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence

from docsgpt import decisions
from docsgpt.core.settings import settings as instance
from docsgpt.decisions import Budget, record
from docsgpt.decisions.features import (
    INJECTION_ATTACHMENT,
    INJECTION_INPUT,
    INJECTION_RETRIEVAL,
    INJECTION_TOOL_RESULT,
    STAGE_TIMEOUT_S,
)
from docsgpt.decisions.latency import GUARD
from docsgpt.decisions.types import BACKEND_REASONS, ModelInfo, Shape
from docsgpt.guardrails import injection_scoring as scoring
from docsgpt.guardrails.base import GuardrailCheck, ScanContext, stage_time_left
from docsgpt.guardrails.injection_scoring import WINDOW_OVERLAP, WINDOW_TOKENS, InjectionScore
from docsgpt.guardrails.types import Action, CheckOutcome, ControlVerdict, Stage

#: Seconds kept back from the stage deadline. The model admits a window only if its predicted time fits, and a
#: window that runs past its prediction must still finish before the engine gives up on the check, or every window
#: already scored is lost with it.
DEADLINE_MARGIN_S = 0.25
#: A control's default ``threshold``, from which its action applies, and ``flag_threshold``, from which a text is
#: flagged as suspected. Precision first: enforcing is the owner's opt-in at 0.9, while the band from 0.5 records the
#: indirect injections the model under-scores.
THRESHOLD = 0.9
FLAG_THRESHOLD = 0.5
#: The ``feature`` label of each stage's calls: it names the ``decision`` spans and the decision-record entry, and
#: keys the ``decision_usage`` counts.
FEATURES = {
    Stage.INPUT: INJECTION_INPUT.name,
    Stage.RETRIEVAL: INJECTION_RETRIEVAL,
    Stage.TOOL_RESULT: INJECTION_TOOL_RESULT,
    Stage.ATTACHMENT: INJECTION_ATTACHMENT,
}
#: Items scored with the model during a turn under ``GUARDRAILS_INJECTION_LIVE_ITEMS=auto``, where that many full
#: chunks are predicted to fit the stage deadline.
AUTO_LIVE_ITEMS = 4


def chunk_shape() -> Shape:
    """A full-size DocsGPT chunk (the chunker's default ``max_tokens``) scored as windows in the background lane."""
    from docsgpt.storage.db.source_config import ChunkingConfig

    step = WINDOW_TOKENS - WINDOW_OVERLAP
    count = 1 + math.ceil(max(0, ChunkingConfig().max_tokens - WINDOW_TOKENS) / step)
    return Shape(state_tokens=WINDOW_TOKENS, question_tokens=GUARD.question_tokens, states=count, lane="background")


def live_items(seconds: Optional[float]) -> int:
    """Items an item stage may score with the model this turn (``GUARDRAILS_INJECTION_LIVE_ITEMS``).

    ``auto`` is ``AUTO_LIVE_ITEMS`` where that many full chunks are predicted to fit ``seconds`` in the hot lane,
    else 0: on a CPU one chunk takes longer than the default stage deadline, and the background scoring fills the
    cache instead. Before the model is measured it is 0.

    Args:
        seconds: The time the stage has left; the default stage deadline when unknown.
    """
    configured = instance.GUARDRAILS_INJECTION_LIVE_ITEMS
    if configured != "auto":
        return int(configured)
    profile = decisions.speed()
    if profile is None:
        return 0
    chunk = chunk_shape()
    shape = replace(chunk, states=AUTO_LIVE_ITEMS * chunk.states, lane="hot")
    limit = STAGE_TIMEOUT_S if seconds is None else seconds
    return AUTO_LIVE_ITEMS if profile.predict_s(shape) <= limit else 0


def _probability(settings: Dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(settings.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{key} must be between 0 and 1")
    return value


class ModelInjectionCheck(GuardrailCheck):
    name = "injection_model"
    label = "Prompt injection (model)"
    description = (
        "Scores the user's message, retrieved documents, tool results and attached files with the decision model, "
        "a small classifier trained on direct and indirect prompt injections in several languages. Flags from the "
        "flag threshold; the control's action applies from the threshold, and on documents and files it withholds "
        "only the flagged one. Runs on this server; the first use downloads the model (about 0.5 GB)."
    )
    supported_stages = {Stage.INPUT, Stage.RETRIEVAL, Stage.TOOL_RESULT, Stage.ATTACHMENT}
    supports_redaction = False
    # A guard on a short message on a 4-vCPU server; the catalog shows this
    # machine's measured figure once the model has loaded.
    latency_hint_ms = 300
    remote = True
    item_level = True
    max_match_chars = 0  # verdicts are whole-text, never span-based

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        threshold = _probability(settings, "threshold", THRESHOLD)
        flag_threshold = _probability(settings, "flag_threshold", min(FLAG_THRESHOLD, threshold))
        if flag_threshold > threshold:
            raise ValueError("flag_threshold must not exceed threshold")
        return {"threshold": threshold, "flag_threshold": flag_threshold}

    @classmethod
    def is_available(cls) -> bool:
        """True while the operator lets the model scan (``DECISION_INJECTION_ENABLED``) and it is configured.

        A model that is not loaded yet still counts: the first scan starts the load, and until it is ready the
        check reports *not evaluated*. ``DECISION_MODE=none`` or a misconfigured model makes it unavailable.
        """
        return bool(instance.DECISION_INJECTION_ENABLED) and decisions.model_version() is not None

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        entry = super().describe()
        predicted = decisions.predict_s(INJECTION_INPUT.shape)
        if predicted is not None:
            entry["latency_hint_ms"] = max(1, round(predicted * 1000))
        return entry

    def _thresholds(self) -> tuple[float, float]:
        return (float(self.settings.get("flag_threshold", FLAG_THRESHOLD)),
                float(self.settings.get("threshold", THRESHOLD)))

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        if not text.strip():
            return CheckOutcome.clean()
        if not instance.DECISION_INJECTION_ENABLED:
            return CheckOutcome.not_evaluated("unscored: off")
        flag_threshold, threshold = self._thresholds()
        feature = FEATURES.get(stage, INJECTION_INPUT.name)
        left = stage_time_left()
        if left is not None and left <= DEADLINE_MARGIN_S:
            self._entry = (feature, _record_entry("timeout", None, flag_threshold, threshold))
            return CheckOutcome.not_evaluated("timeout")
        budget = Budget.HOT if left is None else Budget.hot(left - DEADLINE_MARGIN_S)
        # A user's message or a tool result is rarely seen twice; the harness's
        # own answer cache covers the repeats, so the table is left out.
        result = scoring.score([text], feature=feature, budget=budget, cache=False)
        score, reason, total = result[0], result.reasons[0], result.totals[0]
        outcome, why = _judge(score, reason, total, flag_threshold, threshold)
        windows = [score.windows_scored if score else 0, score.windows_total if score else total or 0]
        self._entry = (feature, _record_entry("ok" if outcome.evaluated else _status(why), outcome.score,
                                              flag_threshold, threshold, windows, result.ms, result.model))
        return outcome

    def settled(self, action: Action, verdict: ControlVerdict) -> None:
        entry = getattr(self, "_entry", None)
        if entry is not None:
            feature, fields = entry
            record.add(feature, applied=action is not Action.FLAG, **fields)

    def scan_items(self, texts: Sequence[str], stage: Stage, context: ScanContext) -> List[CheckOutcome]:
        """Score each document or file: the owner's allowlist, a stored score, the cache, live, else later.

        The misses past ``live_items`` (and those the deadline cut) are *not evaluated* this turn and queued for
        background scoring.
        """
        if not instance.DECISION_INJECTION_ENABLED:
            return [CheckOutcome.clean() if not t.strip() else CheckOutcome.not_evaluated("unscored: off")
                    for t in texts]
        flag_threshold, threshold = self._thresholds()
        feature = FEATURES.get(stage, INJECTION_RETRIEVAL)
        hints = list(context.item_hints or [])
        outcomes: List[Optional[CheckOutcome]] = [None] * len(texts)
        scores: List[Optional[InjectionScore]] = [None] * len(texts)
        reasons: List[Optional[str]] = [None] * len(texts)
        totals: List[Optional[int]] = [None] * len(texts)
        stored = 0
        pending = []
        for i, text in enumerate(texts):
            hint = hints[i] if i < len(hints) and isinstance(hints[i], dict) else {}
            # A stored score stands for the file even when its text was not
            # loaded (a file from an earlier turn).
            if hint.get("allowed"):
                outcomes[i] = CheckOutcome(triggered=False, detail="owner-allowed")
            elif (known := scoring.from_metadata(hint.get("injection"))) is not None:
                scores[i] = known
                stored += 1
            elif not text.strip():
                outcomes[i] = CheckOutcome.clean()
            else:
                pending.append(i)
        left = stage_time_left()
        out_of_time = left is not None and left <= DEADLINE_MARGIN_S
        budget = Budget.HOT if left is None else Budget.hot(max(left - DEADLINE_MARGIN_S, 0.0))
        result = scoring.score([texts[i] for i in pending], feature=feature, budget=budget,
                               live=0 if out_of_time else live_items(left))
        for j, i in enumerate(pending):
            scores[i], reasons[i], totals[i] = result[j], result.reasons[j], result.totals[j]
        # What the deadline or the live limit left unscored is scored in the
        # background, so the next turn that uses it reads the cache.
        later = [texts[i] for i in pending
                 if reasons[i] not in (None, "bad_item") and (scores[i] is None or scores[i].p < flag_threshold)]
        queued = scoring.enqueue_lazy(later)
        why_not = None
        for i, outcome in enumerate(outcomes):
            if outcome is None:
                outcomes[i], why = _judge(scores[i], reasons[i], totals[i], flag_threshold, threshold)
                why_not = why_not or why
        scored = [s.p for s in scores if s is not None]
        self.item_stats = {"cache_hits": stored + result.cache_hits, "live": result.live, "lazy": queued}
        self._items_entry = (
            feature,
            {
                "items": len(texts), **self.item_stats,
                "max_p": round(max(scored), 4) if scored else None,
                "flag_threshold": flag_threshold, "threshold": threshold,
            },
            "ok" if why_not is None else _status(why_not),
            result.ms if result.live else None,
            result.model,
        )
        return outcomes

    def settled_items(self, action: Action, verdicts: List[ControlVerdict], withheld: List[bool]) -> None:
        entry = getattr(self, "_items_entry", None)
        if entry is None:
            return
        feature, outcome, status, ms, model = entry
        record.add(feature, {**outcome, "withheld": sum(withheld)}, status=status,
                   applied=action is not Action.FLAG, ms=ms, model=model)


def _judge(score: Optional[InjectionScore], reason: Optional[str], total: Optional[int], flag_threshold: float,
           threshold: float) -> tuple[CheckOutcome, Optional[str]]:
    """The outcome of one text's score, and why it is not evaluated when it is not.

    A window over the flag threshold settles it even when others went unscored; anything less needs every window
    of the text, including those past the window cap that were never sent.
    """
    if score is None or (score.p < flag_threshold and not score.complete):
        why = reason or ("too_long" if score is not None else "unscored")
        error = "timeout" if why == "timeout" else f"unscored: {why}"
        parts = [error]
        if score is not None:
            parts += [f"p={score.p:.3f}", f"windows={score.windows_scored}/{score.windows_total}"]
        elif total:
            parts.append(f"windows=0/{total}")
        return CheckOutcome(evaluated=False, error=error, detail=" ".join(parts),
                            score=score.p if score else None), why
    p = score.p
    detail = f"p={p:.3f} windows={score.windows_scored}/{score.windows_total}"
    if score.truncated:
        detail += " trunc"
    if score.cached:
        detail += " cached"
    if p >= threshold:
        return CheckOutcome.hit(categories=["PROMPT_INJECTION"], score=p, detail=detail), None
    if p >= flag_threshold:
        return CheckOutcome.hit(
            categories=["PROMPT_INJECTION_SUSPECTED"], score=p, detail=detail, at_most=Action.FLAG
        ), None
    return CheckOutcome(triggered=False, score=p, detail=detail), None


def _status(reason: Optional[str]) -> str:
    """The decision-record status of a scan left unevaluated for ``reason``."""
    if reason in BACKEND_REASONS:
        return "unavailable"
    if reason == "timeout":
        return "timeout"
    return "skipped" if reason in ("too_long", scoring.DEFERRED, "unscored") else "error"


def _record_entry(status: str, p: Optional[float], flag_threshold: float, threshold: float,
                  scored: Optional[list] = None, ms: Optional[float] = None,
                  model: Optional[ModelInfo] = None) -> Dict[str, Any]:
    """The decision-record entry of one scan, without ``applied``, which the control's action decides.

    Args:
        status: ``ok``, or why the scan was not evaluated.
        p: The highest probability among the scored windows.
        flag_threshold: The control's flag threshold.
        threshold: The control's threshold.
        scored: ``[windows scored, windows in the text]``; ``None`` when the model was not asked.
        ms: How long the scan waited for the model.
        model: The model that answered.
    """
    return {
        "outcome": {
            "p": None if p is None else round(p, 4),
            "flag_threshold": flag_threshold,
            "threshold": threshold,
            "windows": scored,
        },
        "status": status,
        "ms": ms,
        "model": model,
    }
