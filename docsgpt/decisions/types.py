"""Values that cross the decision client's interface: requests, budgets, answers and model identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

Lane = Literal["hot", "background"]

#: Per-item reasons that come from the backend rather than from the item; a batch whose items all failed for
#: one of these is ``unavailable``. ``backend_error`` is the backend failing on an item it was given: the runtime
#: raised, the server refused it (HTTP 4xx) or answered something that is not an answer to the questions asked.
#: ``bad_item`` is left for the item's own fault: a state that does not render, or one a server calls bad.
BACKEND_REASONS = frozenset(
    {
        "off", "loading", "queue_full", "no_decider", "memory", "download", "offline", "wrong_model", "load_failed",
        "circuit_open", "transport", "auth", "backend_error",
    }
)


@dataclass(frozen=True)
class Budget:
    """A lane and a deadline for one call.

    Attributes:
        lane: ``hot`` for work someone waits on, ``background`` for anything else.
        seconds: The deadline; ``None`` uses ``DECISION_HOT_TIMEOUT`` or ``DECISION_BACKGROUND_TIMEOUT``.
    """

    lane: Lane
    seconds: Optional[float] = None

    @classmethod
    def hot(cls, seconds: float) -> "Budget":
        """A deadline in the interactive lane."""
        return cls("hot", seconds)

    @classmethod
    def background(cls, seconds: float) -> "Budget":
        """A deadline in the background lane, which yields to interactive work and is throttled."""
        return cls("background", seconds)

    def timeout(self) -> float:
        """The deadline in seconds, reading the lane's default setting when none was given."""
        if self.seconds is not None:
            return self.seconds
        from docsgpt.core.settings import settings

        return settings.DECISION_HOT_TIMEOUT if self.lane == "hot" else settings.DECISION_BACKGROUND_TIMEOUT


Budget.HOT = Budget("hot")
Budget.BACKGROUND = Budget("background")


@dataclass(frozen=True)
class Request:
    """One state and every question about it, so the state is encoded once.

    Attributes:
        state: A string, or a JSON-serialisable structure built by ``docsgpt.decisions.states``.
        questions: Question key to question, in the order the answers should come back.
    """

    state: Any
    questions: dict[str, dict]


@dataclass(frozen=True)
class ModelInfo:
    """Which model answered, and how.

    Attributes:
        id: The model repository, e.g. ``arc53/arc-decide-0.4b-v0.2``.
        revision: The Hub commit the files came from (informational).
        runtime: ``onnx-int8`` or ``onnx-fp32`` here; in API mode ``vllm``, the runtime a ``decide`` server
            reports, or ``remote`` when it reports none.
        mode: The harness mode, ``local`` or ``api``.
        prompt_hash: Identifies the prompt wording.
        calibration: Identifies the heads and fitted temperatures.
        version: ``<id>/p<prompt_hash>/c<calibration>``, the key for anything stored from an answer.
    """

    id: str
    revision: str
    runtime: str
    mode: str
    prompt_hash: str
    calibration: str
    version: str


@dataclass(frozen=True)
class Decision:
    """The answers about one state.

    Attributes:
        answers: Question key to answer, in the wire shapes: ``noul`` carries ``noul`` (P(yes)); ``choice``
            carries ``choice``, ``confidence`` and every option's ``probabilities``; ``score`` carries ``score``
            (the expected level), ``confidence``, ``legend`` and ``probabilities``.
        model: The model that answered.
        ms: Compute time.
        queue_ms: Time spent waiting for the model.
        cached: Whether the answers came from the in-process cache.
        truncated: Whether the state was cut to the model's token limit.
        input_tokens: Tokens read, the state counted once.
    """

    answers: dict[str, dict]
    model: ModelInfo
    ms: float = 0.0
    queue_ms: float = 0.0
    cached: bool = False
    truncated: bool = False
    input_tokens: int = 0

    def p(self, key: str) -> float:
        """P(yes) of a ``noul`` answer."""
        return self.answers[key]["noul"]

    def probs(self, key: str) -> dict[str, float]:
        """Every option's probability; a ``noul`` answer reads as ``true``/``false``."""
        answer = self.answers[key]
        if answer["type"] == "noul":
            return {"true": answer["noul"], "false": 1.0 - answer["noul"]}
        return dict(answer["probabilities"])

    def top(self, key: str) -> tuple[str, float]:
        """The most likely option and its probability. Compare thresholds with this, not ``confidence``."""
        probs = self.probs(key)
        best = max(probs, key=probs.__getitem__)
        return best, probs[best]

    def score(self, key: str) -> float:
        """The expected level of a ``score`` answer."""
        return self.answers[key]["score"]


class BatchResult(list):
    """One ``Decision`` or ``None`` per request, in request order, with why each ``None`` happened.

    Attributes:
        reasons: ``None`` for an answered item, else ``bad_item``, ``timeout`` or a backend reason (``off``,
            ``loading``, ``queue_full``, ``no_decider``, ``memory``, ``download``, ``offline``, ``wrong_model``,
            ``load_failed``, ``backend_error``, and in API mode ``circuit_open``, ``transport`` and ``auth``).
        status: ``ok`` (all answered), ``partial``, ``timeout`` (nothing answered in time) or ``unavailable``
            (nothing answered, for a backend reason: stop, do not retry item by item).
    """

    def __init__(self, decisions: list[Optional[Decision]], reasons: list[Optional[str]]):
        super().__init__(decisions)
        self.reasons = reasons
        self.status = _batch_status(decisions, reasons)


def _batch_status(decisions: list[Optional[Decision]], reasons: list[Optional[str]]) -> str:
    answered = sum(d is not None for d in decisions)
    if answered == len(decisions):
        return "ok"
    if answered:
        return "partial"
    if any(r in BACKEND_REASONS for r in reasons):
        return "unavailable"
    return "timeout" if "timeout" in reasons else "partial"


@dataclass(frozen=True)
class Shape:
    """The p95 call a feature makes, which its predicted latency is computed for.

    Attributes:
        state_tokens: Tokens in one rendered state.
        question_tokens: Tokens in each question's rendered suffix.
        states: States per call.
        lane: The lane the call runs in; it decides the pass plan.
    """

    state_tokens: int
    question_tokens: tuple[int, ...]
    states: int = 1
    lane: Lane = "hot"


@dataclass(frozen=True)
class FeatureSpec:
    """A feature that calls the decision model, as ``auto`` needs to judge it.

    Attributes:
        name: The feature label callers pass as ``feature``.
        mode_setting: The setting holding ``off``, ``monitor``, ``on`` or ``auto``, or a boolean switch (``on``
            when true).
        budget_setting: The setting holding the latency budget, in seconds, that ``auto`` compares against;
            ``None`` for a feature whose budget is ``budget_s``.
        shape: The call the prediction is for.
        auto_mode: What ``auto`` turns into when the prediction fits: ``on``, or ``monitor`` for a feature that
            starts in shadow mode.
        shape_for: For a feature whose call depends on settings or on where the model runs: ``(settings,
            runtime)`` to the call's shape, ``runtime`` being ``ModelInfo.runtime`` or ``None`` when unknown;
            ``shape`` is then the shape for the defaults (see ``features.shape_of``).
        budget_s: The budget, in seconds, of a feature without a ``budget_setting``.
    """

    name: str
    mode_setting: str
    budget_setting: Optional[str]
    shape: Shape
    auto_mode: Literal["on", "monitor"] = "on"
    shape_for: Optional[Callable[[Any, Optional[str]], Shape]] = None
    budget_s: Optional[float] = None
