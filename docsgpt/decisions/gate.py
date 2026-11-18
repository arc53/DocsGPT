"""One decision-model pass at a time, interactive work first, background work throttled.

A pass is compute-bound: two at once would only share the same cores, so the gate admits one. It is taken per
pass, not per call, so a hot call waits at most for the background pass in progress. Within a lane, waiters go in
arrival order, and a background waiter yields to any hot one. After a background pass of ``t`` seconds the next
may not start for ``t * (1 - share) / share``, so a sweep keeps the cores busy for at most ``share`` of the wall
time; hot passes are never throttled.

A waiter leaves as soon as the time left before its deadline is less than its next pass is predicted to take: a
guardrail thread abandoned at its stage deadline never gets a pass run for nobody.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from docsgpt.decisions.types import Lane


class GateTimeout(Exception):
    """The deadline would pass before the pass could finish."""


class Gate:
    """The pass-level lock shared by both lanes of one model session."""

    def __init__(self, share: float, clock: Callable[[], float] = time.monotonic):
        """Create an open gate.

        Args:
            share: ``DECISION_BACKGROUND_SHARE``, the largest share of wall time background passes may take.
            clock: Monotonic clock; tests pass a fake one.
        """
        self.share = share
        self._clock = clock
        self._cond = threading.Condition()
        self._busy = False
        self._waiting: dict[Lane, deque] = {"hot": deque(), "background": deque()}
        self._background_after = 0.0

    def acquire(self, lane: Lane, deadline: float, predicted: float) -> float:
        """Wait for the gate.

        Args:
            lane: The caller's lane.
            deadline: Clock time by which the pass must be done.
            predicted: Seconds the pass is predicted to take (0 before measurement).

        Returns:
            Seconds spent waiting.

        Raises:
            GateTimeout: When the deadline leaves no time for the pass.
        """
        start = self._clock()
        ticket = object()
        with self._cond:
            queue = self._waiting[lane]
            queue.append(ticket)
            try:
                while True:
                    now = self._clock()
                    left = deadline - now - predicted
                    if left <= 0:
                        raise GateTimeout()
                    hold = 0.0 if lane == "hot" else self._background_after - now
                    if not self._busy and queue[0] is ticket and hold <= 0 and (
                        lane == "hot" or not self._waiting["hot"]
                    ):
                        self._busy = True
                        return now - start
                    self._cond.wait(min(left, hold) if hold > 0 else left)
            finally:
                queue.remove(ticket)
                self._cond.notify_all()

    def release(self, lane: Lane, seconds: float) -> None:
        """Open the gate after a pass of ``seconds``; a background pass also starts the throttle pause."""
        with self._cond:
            self._busy = False
            if lane == "background":
                self._background_after = self._clock() + seconds * (1 - self.share) / self.share
            self._cond.notify_all()
