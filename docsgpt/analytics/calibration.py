"""Calibration error per analytics label, which widens every rate's interval (``derive.rate``).

Each constant is the worst expected calibration error (top-label ECE) measured for the label across arc-decide's
held-out simulated conversations, its realistic-profile set and 2,500 real hosted conversations labelled by an
independent model (``an-hosted``, measured on v5.1, the recipe both releases share; it measures agreement, not
correctness). The constants belong to a model and its fitted temperatures, so they are keyed by
``decisions.model_version()``: a new checkpoint or calibration ships its own. A version this table does not know
falls back to its repository's constants, else to the worst value over every known model.
"""

from __future__ import annotations

import math
from typing import Optional

from docsgpt.decisions.models import V01, V02, version

# arc53/arc-decide-0.4b-v0.2: `an-native` and `an-realistic` measured on its checkpoint, `an-hosted` on v5.1.
ECE_V02 = {
    "answer_status": 0.044, "unanswered_reason": 0.132, "reaction": 0.100, "request_type": 0.154,
    "sentiment": 0.029, "frustrated": 0.024, "asks_human": 0.014, "goal_met": 0.067, "topic": 0.102, "tag": 0.022,
}
# arc53/arc-decide-0.6b-v0.1: the same three sets.
ECE_V01 = {
    "answer_status": 0.044, "unanswered_reason": 0.132, "reaction": 0.100, "request_type": 0.154,
    "sentiment": 0.029, "frustrated": 0.023, "asks_human": 0.013, "goal_met": 0.057, "topic": 0.111, "tag": 0.025,
}

BY_VERSION: dict[str, dict[str, float]] = {version(V02): ECE_V02, version(V01): ECE_V01}
BY_REPOSITORY: dict[str, dict[str, float]] = {V02.id: ECE_V02, V01.id: ECE_V01}
FALLBACK: dict[str, float] = {label: max(table[label] for table in BY_VERSION.values()) for label in ECE_V02}

#: Labels read through another label's constant: a gap type is answer status times the unanswered reason, whose
#: error is the larger; the effective topic mixes topic answers; every ``tag:<id>`` is a ``tag``.
_SOURCE = {"gap_type": "unanswered_reason", "topic_effective": "topic"}


def constants(model_version: Optional[str]) -> dict[str, float]:
    """The table for a model version: its own, its repository's, or the worst over every known model.

    Args:
        model_version: ``<repo>/p<prompt_hash>/c<calibration>``, as stored on each label row.
    """
    if model_version in BY_VERSION:
        return BY_VERSION[model_version]
    repository = (model_version or "").rsplit("/p", 1)[0]
    return BY_REPOSITORY.get(repository, FALLBACK)


def ece(label: str, model_version: Optional[str]) -> float:
    """The calibration error added to a label's interval.

    Args:
        label: A stored label name: a question key (``tag:<id>`` included) or ``gap_type`` / ``topic_effective``.
        model_version: The version the label rows were made with.

    Raises:
        KeyError: For a label that has no measured constant (``resolution``, ``experience``).
    """
    family = label.split(":", 1)[0]
    return constants(model_version)[_SOURCE.get(family, family)]


def interval(label: str, total: float, n: int, model_version: Optional[str]) -> tuple[float, float, float]:
    """``derive.rate`` from aggregates: the rate of ``n`` labels whose probabilities sum to ``total``.

    Args:
        label: The stored label name.
        total: ``SUM(p)`` over the rows.
        n: ``COUNT(*)`` of the rows.
        model_version: The version the rows were made with.

    Returns:
        ``(rate, low, high)``; ``(0, 0, 1)`` with no rows.
    """
    if n <= 0:
        return 0.0, 0.0, 1.0
    m = total / n
    half = 1.96 * math.sqrt(max(m * (1 - m), 1e-12) / n) + ece(label, model_version)
    return m, max(0.0, m - half), min(1.0, m + half)
