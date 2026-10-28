"""Wall-clock budgets shared by a run's agents, tools and provider attempts."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Iterator

from celery.exceptions import SoftTimeLimitExceeded


class RunDeadlineExceeded(TimeoutError):
    """The run has no time left, including for a fallback."""


class RoundDeferred(BaseException):
    """End a healthy round at a safe boundary and resume in another task."""


class StreamCancelled(BaseException):
    """A newer turn superseded this stream."""


@dataclass(frozen=True)
class RunBudget:
    """A round's monotonic deadline, the time reserved for saving it, and an optional hard cutoff.

    The round deadline is checked only at boundaries. Work in flight runs on
    until ``hard``: the point a task must stop to save before its time limit.
    """

    deadline: float
    margin: float
    hard: float | None = None

    def remaining(self) -> float:
        """Seconds left before the round's deadline."""
        return max(0.0, self.deadline - monotonic())

    def hard_remaining(self) -> float | None:
        """Seconds left before the hard cutoff, or None without one."""
        return None if self.hard is None else max(0.0, self.hard - monotonic())


_current: ContextVar[RunBudget | None] = ContextVar("run_budget", default=None)


def is_budget_exhausted(exc: BaseException) -> bool:
    """Whether an error must escape provider fallback and tool error recovery."""
    return isinstance(exc, (SoftTimeLimitExceeded, RunDeadlineExceeded))


def remaining_seconds() -> float | None:
    """How long in-flight work may still wait, or None without a hard cutoff."""
    budget = _current.get()
    return budget.hard_remaining() if budget else None


def check_round() -> None:
    """Defer before starting work that would eat the round's saving margin.

    Nothing is in flight at a boundary, so a round that overran its deadline
    (a slow tool) still defers rather than failing.
    """
    budget = _current.get()
    if budget is not None and budget.remaining() <= budget.margin:
        raise RoundDeferred()


@contextmanager
def run_budget(seconds: float, *, margin: float = 30, hard: float | None = None) -> Iterator[RunBudget]:
    """Bind a round deadline and optional hard cutoff, preserving tighter enclosing ones."""
    parent = _current.get()
    now = monotonic()
    deadline = now + seconds
    cutoff = None if hard is None else now + hard
    if parent is not None:
        deadline = min(deadline, parent.deadline)
        if parent.hard is not None:
            cutoff = parent.hard if cutoff is None else min(cutoff, parent.hard)
    budget = RunBudget(deadline, min(margin, seconds / 2), cutoff)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def bounded_round(events: Iterator, *, seconds: float = 570, margin: float = 30) -> Iterator:
    """Consume an interactive round under a deadline, closing its source on exit."""
    with run_budget(seconds, margin=margin):
        try:
            yield from events
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                close()
