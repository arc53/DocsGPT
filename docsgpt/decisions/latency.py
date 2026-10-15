"""How long a decision takes on this machine: the pass plan, the latency model and its fit.

"Calibration" here means timing, unrelated to the model's probability calibration (``calibration_hash``). The ONNX
backend runs a call as a fixed sequence of passes (``plan``), and one pass that appends ``n`` tokens after ``k``
cached rows costs ``c + n * (a + b * k)``. A short timing run at load fits ``c``, ``a`` and ``b``, so the time of any
call shape is predicted by summing its passes; real passes then keep a running ratio of measured to predicted time
(``drift``) that scales every prediction.
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


def plan(prefix: int, suffixes: Sequence[int], lane: Lane) -> list[Pass]:
    """The passes a call runs, in order.

    A hot call with one question is one pass, as in the release client. Otherwise the prompt is prefilled in
    256-token passes and every question extends it; the background lane always takes this path, so it can yield
    to hot work between passes.

    Args:
        prefix: Tokens of the prompt with the state in it.
        suffixes: Tokens of each question's suffix.
        lane: ``hot`` or ``background``.
    """
    if lane == "hot" and len(suffixes) == 1:
        return [Pass(-1, 0, prefix + suffixes[0], 0, single=True)]
    passes = [Pass(-1, a, b, a) for a, b, _ in steps(prefix, 0, CHUNK)]
    for i, n in enumerate(suffixes):
        passes += [Pass(i, a, b, prefix + a) for a, b, _ in steps(n, prefix, CHUNK)]
    return passes


def fit(samples: Sequence[tuple[int, int, float]]) -> tuple[float, float, float]:
    """Least-squares ``c, a, b`` (all >= 0) of ``t = c + n * (a + b * k)`` over timed passes.

    Exact non-negative least squares for three unknowns: solve on every subset of free coefficients (the rest
    fixed at 0) and keep the best fit that has no negative coefficient.

    Args:
        samples: ``(n, k, seconds)`` per timed pass.
    """
    import numpy as np

    x = np.array([[1.0, n, n * k] for n, k, _ in samples])
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
        b: Seconds per appended token per cached row.
        overhead: Tokens the prompt adds around a rendered state.
        threads: Threads the model ran with.
        measured_at: Unix time of the timing run.
        drift: Running ratio of measured to predicted pass time; scales every prediction.
    """

    c: float
    a: float
    b: float
    overhead: int
    threads: int
    measured_at: float = field(default_factory=time.time)
    drift: float = 1.0

    def pass_s(self, tokens: int, cached: int) -> float:
        """Unscaled seconds of one pass."""
        return self.c + tokens * (self.a + self.b * cached)

    def predict_s(self, shape: Shape) -> float:
        """Seconds a call of this shape takes, drift included (queueing excluded)."""
        passes = plan(shape.state_tokens + self.overhead, shape.question_tokens, shape.lane)
        return self.drift * shape.states * sum(self.pass_s(p.tokens, p.cached) for p in passes)

    def observe(self, step: Pass, seconds: float) -> None:
        """Fold one measured pass into ``drift``."""
        expected = self.pass_s(step.tokens, step.cached)
        if expected > 0:
            self.drift += DRIFT_ALPHA * (seconds / expected - self.drift)

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
