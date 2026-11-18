"""Labels computed from the model's labels plus behaviour: gap type, resolution, experience score and rates.

Ported from arc-decide's ``arcd/analytics/derive.py`` (MIT). Everything here is a published rule, not a prediction.
Vendors that bill on "resolved" have had their definitions disputed, and satisfaction inferred from text agrees with
people barely better than people agree with each other (kappa 0.14 vs 0.20), so the model labels only what a
conversation shows, and these rules turn that evidence into outcomes anyone can read and argue with. Every rule
works on probabilities, so rates are sums of probabilities and nothing needs a threshold until display.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Optional

NEGATIVE_REACTIONS = ("re-ask", "correction or pushback", "complaint")
GAP_TYPES = ("not retrieved", "answer missed", "docs missing", "out of scope", "feature not supported",
             "needs account data", "ambiguous question", "other", "confidently ungrounded")
RESOLUTIONS = ("escalated", "abandoned", "confirmed", "assumed", "unresolved", "pending")


def gap_type(answer_status: dict[str, float], unanswered_reason: Optional[dict[str, float]],
             grounded: Optional[float], retrieval_relevance: Optional[float],
             answerable_from_corpus: Optional[float]) -> dict[str, float]:
    """Probability of each gap type for one assistant turn; the rest is 'none'.

    An unanswered turn whose reason is 'docs missing' is split by what the corpus shows: the docs had it but
    retrieval did not surface it ('not retrieved'), retrieval surfaced it and the answer still missed it ('answer
    missed'), or the corpus has nothing ('docs missing'). They need different fixes: search, the prompt, or a new
    page. A fully answered turn the sources do not support is 'confidently ungrounded'.
    """
    unanswered = sum(answer_status.get(k, 0.0) for k in
                     ("partially answered", "declined, no information", "asked a clarifying question"))
    reasons = unanswered_reason or {"other": 1.0}
    out = dict.fromkeys(GAP_TYPES, 0.0)
    docs = unanswered * reasons.get("docs missing", 0.0)
    a = answerable_from_corpus if answerable_from_corpus is not None else 0.0
    r = retrieval_relevance if retrieval_relevance is not None else 0.0
    out["not retrieved"] = docs * a * (1 - r)
    out["answer missed"] = docs * a * r
    out["docs missing"] = docs * (1 - a)
    for k in ("out of scope", "feature not supported", "needs account data", "ambiguous question", "other"):
        out[k] = unanswered * reasons.get(k, 0.0)
    if grounded is not None:
        out["confidently ungrounded"] = answer_status.get("fully answered", 0.0) * (1 - grounded)
    out["none"] = max(0.0, 1 - sum(out.values()))
    return out


@dataclass
class Turn:
    """One user message and the answer to it. ``reaction``, ``asks_human`` and ``frustrated`` describe the user
    message relative to the *previous* answer, so they are empty on the first turn."""

    answer_status: dict[str, float]
    grounded: Optional[float] = None
    reaction: Optional[dict[str, float]] = None
    asks_human: float = 0.0
    frustrated: float = 0.0


@dataclass
class Conversation:
    """The inputs of ``resolution`` and ``experience`` for one conversation."""

    turns: list[Turn]
    goal_met: float
    idle_hours: float
    handoff: bool = False
    window_hours: float = 24.0
    confidently_ungrounded: list[float] = field(default_factory=list)  # per turn, from gap_type


def resolution(c: Conversation) -> dict[str, float]:
    """Resolution state probabilities, applied top down:

    1. escalated   the user asked for a person, or a handoff happened
    2. abandoned   no substantive answer was ever given and the user has left (idle past the window)
    3. confirmed   the user's last message thanks the assistant or confirms the answer worked
    4. within the window everything else is pending; after it:
       assumed     silence after the last answer, weighted by goal_met and the absence of a negative last reaction
       unresolved  the rest
    """
    left = c.idle_hours >= c.window_hours
    p_esc = 1.0 if c.handoff else 1 - math.prod(1 - t.asks_human for t in c.turns)
    rest = 1 - p_esc
    never = math.prod(1 - t.answer_status.get("fully answered", 0.0) - t.answer_status.get("partially answered", 0.0)
                      for t in c.turns)
    p_aband = rest * max(0.0, never) if left else 0.0
    rest -= p_aband
    last = c.turns[-1].reaction or {}
    p_conf = rest * last.get("thanks or confirmation", 0.0)
    rest -= p_conf
    out = dict.fromkeys(RESOLUTIONS, 0.0)
    out.update(escalated=p_esc, abandoned=p_aband, confirmed=p_conf)
    if not left:
        out["pending"] = rest
    else:
        negative = sum(last.get(k, 0.0) for k in NEGATIVE_REACTIONS)
        ok = c.goal_met * (1 - negative)
        out["assumed"] = rest * ok
        out["unresolved"] = rest * (1 - ok)
    return out


# Experience score v0: published weights, applied to probabilities so the score is continuous. v1 refits them as an
# ordinal regression against thumbs and goal_met on real conversations, and publishes the fit.
EXPERIENCE_WEIGHTS = {"confirmed": 1.0, "assumed": 0.5, "unresolved": -1.0, "escalated": -0.5,
                      "frustrated": -1.0, "reasks": -0.5, "ungrounded": -0.5}


def experience(c: Conversation, res: Optional[dict[str, float]] = None) -> dict[str, float]:
    """1-5 experience score and the contribution of each component, so any score can be explained."""
    res = res or resolution(c)
    w = EXPERIENCE_WEIGHTS
    later = [t for t in c.turns[1:] if t.reaction]
    parts = {k: w[k] * res[k] for k in ("confirmed", "assumed", "unresolved", "escalated")}
    parts["frustrated"] = w["frustrated"] * (1 - math.prod(1 - t.frustrated for t in c.turns))
    expected_negative = sum(t.reaction.get("re-ask", 0.0) + t.reaction.get("correction or pushback", 0.0)
                            for t in later)
    parts["reasks"] = w["reasks"] * min(1.0, expected_negative / 2)
    parts["ungrounded"] = w["ungrounded"] * (1 - math.prod(1 - p for p in c.confidently_ungrounded))
    score = min(5.0, max(1.0, 3.0 + sum(parts.values())))
    return {"score": score, **parts}


def rate(probs: Sequence[float], calibration_error: float = 0.0) -> tuple[float, float, float]:
    """(rate, low, high): the expected share of items with the label, from probabilities rather than thresholded
    counts. The interval is the 95% binomial sampling interval widened by the label's measured calibration error."""
    n = len(probs)
    if n == 0:
        return 0.0, 0.0, 1.0
    m = sum(probs) / n
    half = 1.96 * math.sqrt(max(m * (1 - m), 1e-12) / n) + calibration_error
    return m, max(0.0, m - half), min(1.0, m + half)
