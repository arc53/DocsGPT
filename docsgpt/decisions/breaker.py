"""The circuit breaker in front of a decision server: a dead endpoint costs a few timeouts, not one per call.

After ``failures`` consecutive transport failures (no connection, a timeout, a 5xx, a reply that is not the
contract) the breaker opens and calls are skipped for ``cooldown`` seconds. Then one call is let through: its
success closes the breaker, its failure opens it for another cooldown. An answer the server refuses for the item's
sake (``bad_item``, a 4xx) proves the server is up and counts as a success.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class Breaker:
    """Closed, open or half-open, shared by every call of one process."""

    def __init__(self, failures: int, cooldown: float, clock: Callable[[], float] = time.monotonic):
        """Create a closed breaker.

        Args:
            failures: Consecutive failures that open it.
            cooldown: Seconds it stays open.
            clock: Monotonic clock (tests pass a fake one).
        """
        self.failures = max(1, failures)
        self.cooldown = max(0.0, cooldown)
        self._clock = clock
        self._lock = threading.Lock()
        self._count = 0
        self._open_until = 0.0
        self._trial_since = None  # when the one call let through after a cooldown went out

    def allow(self) -> bool:
        """Whether a call may go out now; after a cooldown, only the first caller gets through."""
        with self._lock:
            if self._count < self.failures:
                return True
            now = self._clock()
            if now < self._open_until:
                return False
            # a trial that never reported (its caller gave up before sending) frees the slot after a cooldown
            if self._trial_since is not None and now - self._trial_since < self.cooldown:
                return False
            self._trial_since = now
            return True

    @property
    def open(self) -> bool:
        """Whether calls are being skipped (open, or half-open with its trial out)."""
        with self._lock:
            return self._count >= self.failures

    def success(self) -> bool:
        """Record a call the server answered.

        Returns:
            True when this closed a breaker that was open.
        """
        with self._lock:
            was_open = self._count >= self.failures
            self._count, self._open_until, self._trial_since = 0, 0.0, None
            return was_open

    def failure(self) -> bool:
        """Record a transport failure.

        Returns:
            True when this opened the breaker (or kept it open after a failed trial).
        """
        with self._lock:
            self._count += 1
            self._trial_since = None
            if self._count >= self.failures:
                self._open_until = self._clock() + self.cooldown
                return True
            return False
