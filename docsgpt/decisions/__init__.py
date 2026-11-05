"""Decision model client: typed questions about a state, answered with calibrated probabilities.

The decision model is arc-decide (``arc53/arc-decide-*``), a small classifier read at its last token, not a chat
model; it is unrelated to the guardrails' own ``StageDecision`` and decision journal. Every feature that calls it
ships off. Nothing is downloaded or loaded until one is turned on, ``DECISION_PRELOAD`` is set, or
``docsgpt decisions prefetch`` runs, and nothing at all happens at import.

    from docsgpt import decisions
    from docsgpt.decisions import Budget, Q, states

    res = decisions.decide(states.text(message), {"injection": Q.INJECTION, "severity": Q.SEVERITY},
                           feature="injection_input", budget=Budget.hot(0.9))
    if res is not None and res.p("injection") >= threshold:
        ...

Every call returns ``None`` (per item, with a reason) instead of raising when the model is off, loading or busy,
so a feature always has its old behaviour to fall back on. ``decisions.testing.FakeDecider`` stands in for it in
tests.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from docsgpt.decisions import states
from docsgpt.decisions.questions import Q
from docsgpt.decisions.states import max_state_tokens
from docsgpt.decisions.tokens import count_tokens, state_tokens
from docsgpt.decisions.types import BatchResult, Budget, Decision, FeatureSpec, ModelInfo, Request, Shape

__all__ = [
    "BatchResult", "Budget", "Decision", "FeatureSpec", "ModelInfo", "Q", "Request", "Shape", "auto_on",
    "available", "count_tokens", "decide", "decide_batch", "get_decider", "max_state_tokens", "model_info",
    "model_version", "predict_s", "reset", "speed", "start", "state_tokens", "states", "status", "warm",
]

_client = None
_client_lock = threading.Lock()


def get_decider():
    """The process-wide client (a ``DecisionClient``); never ``None``, and ``enabled`` is False in mode ``none``."""
    global _client
    if _client is None:
        from docsgpt.decisions.client import DecisionClient

        with _client_lock:
            if _client is None:
                _client = DecisionClient()
    return _client


def decide(state: Any, questions: dict[str, dict], *, feature: str, budget: Budget = Budget.HOT) -> Optional[Decision]:
    """Every question about one state, or ``None``; see ``DecisionClient.decide_batch``."""
    return get_decider().decide(state, questions, feature=feature, budget=budget)


def decide_batch(requests: list[Request], *, feature: str, budget: Budget = Budget.HOT) -> BatchResult:
    """Many states in one call; see ``DecisionClient.decide_batch``."""
    return get_decider().decide_batch(requests, feature=feature, budget=budget)


def available() -> bool:
    """Whether calls can be answered here now or once the model has loaded."""
    return get_decider().status()["available"]


def status() -> dict:
    """Mode, load status, model, speed and every feature's verdict, as ``/api/admin/decisions`` reports them."""
    return get_decider().status()


def warm() -> None:
    """Start loading the model in the background (downloading it first if needed); never blocks."""
    get_decider().warm()


def start() -> None:
    """Called once when an API process starts: warm the model if a setting asks for it then.

    That is ``DECISION_PRELOAD``, or any registered feature set to something other than ``off``
    (``features.wanted_at_start``; ``DECISION_RELEVANCE_ENABLED`` turns ``rag_rerank`` on and
    ``DECISION_INJECTION_ENABLED`` ``injection_input``). A Celery worker never loads the model.
    """
    from docsgpt.decisions import features

    decider = get_decider()
    if decider.enabled and features.wanted_at_start():
        decider.warm()


def speed():
    """This machine's measured ``SpeedProfile``, or ``None`` before the model has loaded."""
    return get_decider().speed()


def predict_s(shape: Shape) -> Optional[float]:
    """Predicted seconds for a call of this shape on this machine, or ``None`` before measurement."""
    profile = speed()
    return profile.predict_s(shape) if profile else None


def auto_on(feature: str) -> bool:
    """Whether a feature's predicted latency fits its budget here (the ``auto`` verdict, with hysteresis).

    Before the model is measured this is False, and it starts the load so a later call can say yes.
    """
    from docsgpt.decisions import features

    spec = next((s for s in features.specs() if s.name == feature), None)
    if spec is None:
        raise KeyError(f"no decision feature named {feature!r} is registered")
    profile = speed()
    if profile is None:
        warm()
    return features.verdict(spec, profile)[0]


def model_info() -> Optional[ModelInfo]:
    """The model calls go to, without loading it; ``None`` in mode ``none``."""
    return get_decider().model_info()


def model_version() -> Optional[str]:
    """``<repo>/p<prompt_hash>/c<calibration>``, the key for stored scores; needs no load or network."""
    return get_decider().model_version()


def reset() -> None:
    """Drop this process's client, tokenizer, verdicts and unwritten usage counts; run in a forked child so nothing
    crosses the fork."""
    global _client
    from docsgpt.decisions import features, tokens, usage

    with _client_lock:
        _client = None
    tokens.reset()
    features.reset()
    usage.reset()
