"""Prompt injection scored by the decision model rather than matched by patterns.

The check asks the decision model (``docsgpt.decisions``) its trained ``injection`` question about the text and
gets a probability back. One control carries two thresholds: from ``flag_threshold`` the text is flagged as
suspected, which is recorded and never enforced; from ``threshold`` the control's own action applies.

The operator decides only whether the model may run at all (``DECISION_INJECTION_ENABLED``); while it may not, the
check is unavailable and asks nothing. A text the model could not score (the switch is off, the model is off, still
loading, or out of time) is not a pass: the outcome is *not evaluated* and the agent's ``fail_open`` decides for a
control that blocks. A control that only flags, such as the floor's or the defaults' flag-only rule, never stops a
turn it could not score.

A long text is split into short windows, scored in one call in the order most likely to matter: the last window
(where an appended payload sits), the first, then the rest from the end backwards. The decision model answers a
call's states in order and returns those it finished when the stage deadline cuts it short, so on a slow machine
the windows that matter most are the ones read. One window over the flag threshold settles the verdict; otherwise
every window must be scored, or the outcome is *not evaluated* and says how many were (``windows=2/13``).

Every scan that asks the model is also an entry in the request's decision record (``docsgpt.decisions.record``):
the probability, the thresholds and how many windows were scored, never the text. ``applied`` is false when the
control only flags (its action is ``flag``, or the agent runs ``monitor_only``).

Only the ``input`` stage is offered for now. Retrieved documents and tool results are long, and on CPU they need
scores computed before the turn rather than during it.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional, Sequence

from docsgpt import decisions
from docsgpt.core.settings import settings as instance
from docsgpt.decisions import Budget, Q, Request, record, states, tokens
from docsgpt.decisions.features import INJECTION_INPUT
from docsgpt.decisions.latency import GUARD
from docsgpt.decisions.types import BACKEND_REASONS, Decision, Shape
from docsgpt.guardrails.base import GuardrailCheck, ScanContext, stage_time_left
from docsgpt.guardrails.types import Action, CheckOutcome, ControlVerdict, Stage

#: Model tokens per window of a long text, and the overlap between windows, so a payload on a boundary is read whole
#: in one of them. A short window is about 0.7 s on 4 vCPU, so two or three fit the default 2 s stage deadline
#: (one 1,600-token window did not), it is close to the length of the texts the model was trained on, and a short
#: payload is not diluted by a long benign window around it.
WINDOW_TOKENS = 512
WINDOW_OVERLAP = 50
#: Windows considered per text (about 11,000 tokens); past it the first and the last ``MAX_WINDOWS - 1`` are
#: considered. On CPU the deadline stops far sooner.
MAX_WINDOWS = 24
#: Seconds kept back from the stage deadline. The model admits a window only if its predicted time fits, and a
#: window that runs past its prediction must still finish before the engine gives up on the check, or every window
#: already scored is lost with it.
DEADLINE_MARGIN_S = 0.25
#: A control's default ``threshold``, from which its action applies, and ``flag_threshold``, from which a text is
#: flagged as suspected. Precision first: enforcing is the owner's opt-in at 0.9, while the band from 0.5 records the
#: indirect injections the model under-scores.
THRESHOLD = 0.9
FLAG_THRESHOLD = 0.5


def windows(text: str) -> tuple[list[str], int]:
    """The windows of ``text`` to score, in the order to score them, and how many it has in all.

    The order is the last window, the first, then the rest from the end backwards. Windows are counted in model
    tokens; before the tokenizer has loaded they are counted in characters, one per token at worst, which gives
    more and shorter windows and still reads every part of the text.

    Args:
        text: The text to score.

    Returns:
        The windows to score (at most ``MAX_WINDOWS``) and the number of windows the whole text spans.
    """
    ids = tokens.encode(text)
    units: Any = ids if ids is not None else text
    starts = [0]
    while starts[-1] + WINDOW_TOKENS < len(units):
        starts.append(starts[-1] + WINDOW_TOKENS - WINDOW_OVERLAP)
    total = len(starts)
    order = [starts[-1]] + starts[:1] + starts[-2:0:-1] if total > 1 else starts
    pieces = [units[start : start + WINDOW_TOKENS] for start in order[:MAX_WINDOWS]]
    if ids is not None:
        pieces = [tokens.decode(piece) for piece in pieces]
    return pieces, total


def chunk_shape() -> Shape:
    """A full-size DocsGPT chunk (the chunker's default ``max_tokens``) scored as windows in the background lane.

    What scanning one chunk for prompt injection costs; the admin pages show its prediction.
    """
    from docsgpt.storage.db.source_config import ChunkingConfig

    step = WINDOW_TOKENS - WINDOW_OVERLAP
    count = 1 + math.ceil(max(0, ChunkingConfig().max_tokens - WINDOW_TOKENS) / step)
    return Shape(state_tokens=WINDOW_TOKENS, question_tokens=GUARD.question_tokens, states=count, lane="background")


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
        "Scores the user's message with the decision model, a small classifier trained on direct and indirect "
        "prompt injections in several languages. Flags from the flag threshold; the control's action applies "
        "from the threshold. Runs on this server; the first use downloads the model (about 0.5 GB)."
    )
    supported_stages = {Stage.INPUT}
    supports_redaction = False
    # A guard on a short message on a 4-vCPU server; the catalog shows this
    # machine's measured figure once the model has loaded.
    latency_hint_ms = 300
    remote = True
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

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        if not text.strip():
            return CheckOutcome.clean()
        if not instance.DECISION_INJECTION_ENABLED:
            return CheckOutcome.not_evaluated("unscored: off")
        flag_threshold = float(self.settings.get("flag_threshold", FLAG_THRESHOLD))
        threshold = float(self.settings.get("threshold", THRESHOLD))
        left = stage_time_left()
        if left is not None and left <= DEADLINE_MARGIN_S:
            self._entry = _record_entry("timeout", None, flag_threshold, threshold)
            return CheckOutcome.not_evaluated("timeout")
        budget = Budget.HOT if left is None else Budget.hot(left - DEADLINE_MARGIN_S)
        pieces, total = windows(text)
        started = time.monotonic()
        batch = decisions.decide_batch(
            [Request(states.text(piece), {"injection": Q.INJECTION}) for piece in pieces],
            feature=INJECTION_INPUT.name,
            budget=budget,
        )
        ms = (time.monotonic() - started) * 1000
        answered = [d for d in batch if d is not None]
        p = max((d.p("injection") for d in answered), default=None)
        scored = f"windows={len(answered)}/{total}"
        # A window over the flag threshold settles it even when others went
        # unscored; anything less needs every window of the text, including
        # those past MAX_WINDOWS that were never sent.
        if p is None or (p < flag_threshold and len(answered) < total):
            reason = next((r for r in batch.reasons if r), "too_long" if len(answered) == len(pieces) else "unscored")
            self._entry = _record_entry(_status(reason), p, flag_threshold, threshold, [len(answered), total], ms,
                                        answered)
            error = "timeout" if reason == "timeout" else f"unscored: {reason}"
            seen = f" p={p:.3f}" if p is not None else ""
            return CheckOutcome(evaluated=False, error=error, detail=f"{error}{seen} {scored}")
        self._entry = _record_entry("ok", p, flag_threshold, threshold, [len(answered), total], ms, answered)
        detail = f"p={p:.3f} {scored}"
        if any(d.truncated for d in answered):
            detail += " trunc"
        if all(d.cached for d in answered):
            detail += " cached"
        if p >= threshold:
            return CheckOutcome.hit(categories=["PROMPT_INJECTION"], score=p, detail=detail)
        if p >= flag_threshold:
            return CheckOutcome.hit(
                categories=["PROMPT_INJECTION_SUSPECTED"], score=p, detail=detail, at_most=Action.FLAG
            )
        return CheckOutcome(triggered=False, score=p, detail=detail)

    def settled(self, action: Action, verdict: ControlVerdict) -> None:
        entry = getattr(self, "_entry", None)
        if entry is not None:
            record.add(INJECTION_INPUT.name, applied=action is not Action.FLAG, **entry)


def _status(reason: str) -> str:
    """The decision-record status of a scan left unevaluated for ``reason``."""
    if reason in BACKEND_REASONS:
        return "unavailable"
    if reason == "timeout":
        return "timeout"
    return "skipped" if reason == "too_long" else "error"


def _record_entry(status: str, p: Optional[float], flag_threshold: float, threshold: float,
                  scored: Optional[list] = None, ms: Optional[float] = None,
                  answered: Sequence[Decision] = ()) -> Dict[str, Any]:
    """The decision-record entry of one scan, without ``applied``, which the control's action decides.

    Args:
        status: ``ok``, or why the scan was not evaluated.
        p: The highest probability among the scored windows.
        flag_threshold: The control's flag threshold.
        threshold: The control's threshold.
        scored: ``[windows scored, windows in the text]``; ``None`` when the model was not asked.
        ms: How long the scan waited for the model.
        answered: The windows' answers, for the model that gave them.
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
        "model": answered[0].model if answered else None,
    }
