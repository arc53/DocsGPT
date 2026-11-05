"""``FakeDecider``: the decision client's stand-in for tests, with scripted answers and recorded calls.

    from docsgpt.decisions.testing import FakeDecider, installed

    fake = FakeDecider({"injection": 0.97, "intent": {"billing": 0.8, "other": 0.2}})
    with installed(fake):
        ...  # code under test calls docsgpt.decisions as usual
    assert fake.calls[0].feature == "injection_input"

It validates exactly as the real client does, so a malformed question fails a test the way it would fail in
production.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional, Union

from docsgpt.decisions import tokens
from docsgpt.decisions.client import validate
from docsgpt.decisions.models import V02, version
from docsgpt.decisions.questions import family
from docsgpt.decisions.types import BatchResult, Budget, Decision, ModelInfo, Request
from docsgpt.decisions.vendor.arc_decide import Decider as _Release

#: A scripted answer: P(yes) for ``noul``; an option name, ``{option: p}`` or a list of probabilities for
#: ``choice`` and ``score``; a complete wire answer (a dict with ``type``); or a callable of ``(state, question)``
#: returning one of those.
Script = Union[float, str, dict, list, Callable[[Any, dict], Any]]


@dataclass(frozen=True)
class Call:
    """One recorded call."""

    feature: str
    budget: Budget
    requests: list[Request]


def answer_for(question: dict, value: Any) -> dict:
    """The wire-shaped answer a scripted value stands for; an unscripted question gets even odds."""
    if isinstance(value, dict) and "type" in value:
        return value
    kind = question.get("type", "noul")
    if kind == "noul":
        p = 0.5 if value is None else float(value)
        return _Release._answer(question, "noul", [p, 1.0 - p])
    names = list(question["criteria"]) if kind == "choice" else [str(i) for i in range(len(question["criteria"]))]
    if value is None:
        probs = [1.0 / len(names)] * len(names)
    elif isinstance(value, str):
        probs = [float(name == value) for name in names]
    elif isinstance(value, dict):
        probs = [float(value.get(name, 0.0)) for name in names]
    else:
        probs = [float(v) for v in value]
    total = sum(probs) or 1.0
    return _Release._answer(question, kind, [p / total for p in probs])


class FakeDecider:
    """Scripted answers by question key or family, scripted failures by feature, and every call recorded.

    Attributes:
        answers: Question key (or family, e.g. ``tag``) to a ``Script``.
        reasons: Feature name (or ``*``) to the reason every item of its calls fails with.
        calls: Every call, in order.
        profile: What ``speed()`` returns; set a ``SpeedProfile`` to test ``auto``.
        warmed: How many times ``warm()`` was called.
    """

    def __init__(self, answers: Optional[dict[str, Script]] = None, *, reasons: Optional[dict[str, str]] = None,
                 profile: Any = None, model_version: str = version(V02), tokenizer: Any = None):
        self.answers = dict(answers or {})
        self.reasons = dict(reasons or {})
        self.calls: list[Call] = []
        self.profile = profile
        self.tokenizer = tokenizer
        self.warmed = 0
        self.enabled = True
        self.mode = "local"
        self.info = ModelInfo(id=V02.id, revision=V02.revision, runtime="fake", mode="local",
                              prompt_hash=V02.prompt_hash, calibration=V02.calibration, version=model_version)

    def _answer(self, key: str, question: dict, state: Any) -> dict:
        value = self.answers.get(key, self.answers.get(family(key)))
        if callable(value):
            value = value(state, question)
        return answer_for(question, value)

    def decide(self, state: Any, questions: dict[str, dict], *, feature: str,
               budget: Budget = Budget.HOT) -> Optional[Decision]:
        """As ``DecisionClient.decide``."""
        return self.decide_batch([Request(state, questions)], feature=feature, budget=budget)[0]

    def decide_batch(self, requests: list[Request], *, feature: str, budget: Budget = Budget.HOT) -> BatchResult:
        """As ``DecisionClient.decide_batch``: the same validation, then the scripted answers or failure."""
        validate(requests)
        self.calls.append(Call(feature, budget, list(requests)))
        reason = self.reasons.get(feature) or self.reasons.get("*")
        if reason:
            return BatchResult([None] * len(requests), [reason] * len(requests))
        decisions = [
            Decision({key: self._answer(key, q, r.state) for key, q in r.questions.items()}, self.info)
            for r in requests
        ]
        return BatchResult(decisions, [None] * len(requests))

    def warm(self) -> None:
        self.warmed += 1

    def probe(self, timeout: float = 5.0) -> Optional[bool]:
        """As ``DecisionClient.probe`` for a local model: there is no server to ask."""
        return None

    def model_info(self) -> ModelInfo:
        return self.info

    def model_version(self) -> str:
        return self.info.version

    def speed(self) -> Any:
        return self.profile

    def status(self) -> dict:
        return {
            "available": True, "mode": "local", "status": "ready" if self.profile else "idle", "reason": None,
            "model": self.info.id, "version": self.info.version, "runtime": self.info.runtime,
            "speed": self.profile.report() if self.profile else None, "features": {},
        }


@contextlib.contextmanager
def installed(fake: FakeDecider) -> Iterator[FakeDecider]:
    """Make ``fake`` the process's decision client (and its tokenizer the token counter) for the block."""
    import docsgpt.decisions as decisions

    previous = decisions._client
    decisions._client = fake
    if fake.tokenizer is not None:
        tokens.use(fake.tokenizer)
    try:
        yield fake
    finally:
        decisions._client = previous
        if fake.tokenizer is not None:
            tokens.reset()
