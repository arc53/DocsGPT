"""How long a decision takes on this machine: the pass plan, the latency model and its fit.

"Calibration" here means timing, unrelated to the model's probability calibration (``calibration_hash``). The ONNX
backend runs a call as a fixed sequence of passes (``plan``; the torch runtime of ``docsgpt decide-server`` has a
plan of its own), and one pass that appends ``n`` tokens after ``k`` cached rows costs
``c + n * (a + b * (k + n / 2))``: a fixed cost per pass, the weights per token, and attention per
token over the rows it reads, which are the cached ones plus, causally, on average half of the pass's own. Short
passes barely show that last part; one long single pass (a whole relevance chunk) pays it in full. A short timing
run at load fits ``c``, ``a`` and ``b``, so the time of any call shape is predicted by summing its passes; real
passes then keep a running ratio of measured to predicted time (``drift``) that scales every prediction.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Sequence

from docsgpt.decisions.types import Lane, Shape
from docsgpt.decisions.vendor.arc_decide_onnx import CHUNK, steps

#: Weight of each new pass in the drift average.
DRIFT_ALPHA = 0.05

#: Drift inside this band keeps the profile; outside it, the timing run is due again.
DRIFT_BAND = (0.67, 1.5)

#: The timing run's state: constant text, never user data.
TIMING_TEXT = (
    "The service stores each document as a sequence of short passages. A search embeds the question, compares it "
    "with every passage of the selected sources and returns the closest ones, which the assistant reads before it "
    "answers. Passages keep their headings, so a result can be traced back to the section it came from. "
)
#: Tokens of the timing run's single-pass call and of its multi-pass state. The state's prefill passes run on 0,
#: 256 and 512 cached rows and its questions on 768, so the per-row attention cost, which an analytics turn pays
#: at 2,000 rows and a long single pass pays within itself, is measured over a range rather than at one point.
TIMING_SINGLE, TIMING_STATE = 200, 768

#: Reference shapes reported in ``/api/admin/decisions``: an injection check on a short message, one relevance chunk of
#: DocsGPT's default size, and an analytics turn (a full state and eight questions, in the background).
GUARD = Shape(state_tokens=20, question_tokens=(100,))
RELEVANCE = Shape(state_tokens=1220, question_tokens=(30,))
ANALYTICS = Shape(state_tokens=2048, question_tokens=(90,) * 8, lane="background")


@dataclass(frozen=True)
class Pass:
    """One forward pass of a call.

    Attributes:
        segment: ``-1`` for the state's prompt, else the index of the question whose suffix this pass reads.
        begin: First id of the segment this pass appends.
        end: One past the last.
        cached: Rows already in the KV buffer.
        single: The one pass of a single-question hot call, which reads prompt and suffix together on the
            one-layer buffer (``segment`` is then ``-1`` and the ids run on into the suffix).
    """

    segment: int
    begin: int
    end: int
    cached: int
    single: bool = False

    @property
    def tokens(self) -> int:
        return self.end - self.begin


def plan(prefix: int, suffixes: Sequence[int], lane: Lane, kind: str = "onnx") -> list[Pass]:
    """The passes a call runs, in order.

    On ONNX, a hot call with one question is one pass, as in the release client. Otherwise the prompt is
    prefilled in 256-token passes and every question extends it; the background lane always takes this path, so
    it can yield to hot work between passes. On torch, as in the release PyTorch client, the prompt is one pass
    and every question one more, in either lane.

    Args:
        prefix: Tokens of the prompt with the state in it.
        suffixes: Tokens of each question's suffix.
        lane: ``hot`` or ``background``.
        kind: ``onnx`` or ``torch``, the runtime whose plan this is.
    """
    if kind == "torch":
        return [Pass(-1, 0, prefix, 0)] + [Pass(i, 0, n, prefix) for i, n in enumerate(suffixes)]
    if lane == "hot" and len(suffixes) == 1:
        return [Pass(-1, 0, prefix + suffixes[0], 0, single=True)]
    passes = [Pass(-1, a, b, a) for a, b, _ in steps(prefix, 0, CHUNK)]
    for i, n in enumerate(suffixes):
        passes += [Pass(i, a, b, prefix + a) for a, b, _ in steps(n, prefix, CHUNK)]
    return passes


def attended(tokens: int, cached: int) -> float:
    """Rows the tokens of one pass attend to, summed: each reads the cached rows and the ones before it in the pass."""
    return tokens * (cached + tokens / 2)


def fit(samples: Sequence[tuple[int, int, float]]) -> tuple[float, float, float]:
    """Least-squares ``c, a, b`` (all >= 0) of ``t = c + n * a + b * attended(n, k)`` over timed passes.

    Exact non-negative least squares for three unknowns: solve on every subset of free coefficients (the rest
    fixed at 0) and keep the best fit that has no negative coefficient.

    Args:
        samples: ``(n, k, seconds)`` per timed pass.
    """
    import numpy as np

    x = np.array([[1.0, n, attended(n, k)] for n, k, _ in samples])
    y = np.array([t for _, _, t in samples])
    best, best_err = (0.0, 0.0, 0.0), float(np.sum(y**2))
    for size in (1, 2, 3):
        for free in itertools.combinations(range(3), size):
            coef, *_ = np.linalg.lstsq(x[:, free], y, rcond=None)
            if (coef < 0).any():
                continue
            err = float(np.sum((x[:, free] @ coef - y) ** 2))
            if err < best_err:
                full = [0.0, 0.0, 0.0]
                for i, v in zip(free, coef):
                    full[i] = float(v)
                best, best_err = tuple(full), err
    return best


@dataclass
class SpeedProfile:
    """This machine's fitted latency model.

    Attributes:
        c: Seconds per pass.
        a: Seconds per appended token.
        b: Seconds per row an appended token attends to (``attended``).
        overhead: Tokens the prompt adds around a rendered state.
        threads: Threads the model ran with.
        measured_at: Unix time of the timing run.
        drift: Running ratio of measured to predicted pass time; scales every prediction.
        plan: The pass plan predictions follow, ``onnx`` or ``torch`` (see ``plan``).
    """

    c: float
    a: float
    b: float
    overhead: int
    threads: int
    measured_at: float = field(default_factory=time.time)
    drift: float = 1.0
    plan: str = "onnx"

    def pass_s(self, tokens: int, cached: int) -> float:
        """Unscaled seconds of one pass."""
        return self.c + tokens * self.a + self.b * attended(tokens, cached)

    def predict_s(self, shape: Shape) -> float:
        """Seconds a call of this shape takes, drift included (queueing excluded)."""
        passes = plan(shape.state_tokens + self.overhead, shape.question_tokens, shape.lane, self.plan)
        return self.drift * shape.states * sum(self.pass_s(p.tokens, p.cached) for p in passes)

    def observe(self, step: Pass, seconds: float) -> None:
        """Fold one measured pass into ``drift``."""
        expected = self.pass_s(step.tokens, step.cached)
        if expected > 0:
            self.drift += DRIFT_ALPHA * (seconds / expected - self.drift)

    def steady(self) -> bool:
        """Whether ``drift`` is still inside ``DRIFT_BAND``."""
        return DRIFT_BAND[0] <= self.drift <= DRIFT_BAND[1]

    def wire(self) -> dict:
        """The fitted numbers, as a decision server reports them on ``GET /v1/models`` (``speed``)."""
        return {"c": self.c, "a": self.a, "b": self.b, "overhead": self.overhead, "threads": self.threads,
                "measured_at": self.measured_at, "drift": self.drift, "plan": self.plan}

    @classmethod
    def from_wire(cls, data: dict) -> "SpeedProfile":
        """A profile a decision server reported.

        Raises:
            KeyError, TypeError, ValueError: When ``data`` lacks a coefficient or holds a non-number.
        """
        measured_at = data.get("measured_at")
        return cls(float(data["c"]), float(data["a"]), float(data["b"]), overhead=int(data["overhead"]),
                   threads=int(data.get("threads") or 0),
                   measured_at=time.time() if measured_at is None else float(measured_at),
                   drift=float(data.get("drift") or 1.0), plan="torch" if data.get("plan") == "torch" else "onnx")

    def report(self) -> dict:
        """The profile as ``/api/admin/decisions`` shows it."""
        from datetime import datetime, timezone

        return {
            "threads": self.threads,
            "measured_at": datetime.fromtimestamp(self.measured_at, timezone.utc).isoformat(timespec="seconds"),
            "drift": round(self.drift, 3),
            "guard_s": round(self.predict_s(GUARD), 3),
            "relevance_s": round(self.predict_s(RELEVANCE), 3),
            "analytics_s": round(self.predict_s(ANALYTICS), 3),
        }
