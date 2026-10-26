"""Bound blocking synchronous streams without advancing abandoned iterators."""

from contextvars import copy_context
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Callable, Iterator

from docsgpt.core.run_budget import RunDeadlineExceeded, remaining_seconds


class StreamStalledError(TimeoutError):
    """A provider missed its first-token or inter-chunk deadline; fallback is allowed."""


def timed_stream(factory: Callable[[], Iterator[Any]], *, first_token: float, stall: float) -> Iterator[Any]:
    """Read one chunk at a time with deadlines, including stream creation.

    A daemon owns the blocking iterator and closes it when a pending read
    returns. It advances only on demand: timing out never starts another read
    or executes trailing provider code. Context is copied for billing/tracing.
    The transport's own read timeout remains the backstop for an in-flight read.
    """
    results: Queue[tuple[bool, Any]] = Queue(maxsize=1)
    demand = Event()
    done = Event()

    def produce() -> None:
        iterator = None
        try:
            demand.wait()
            if done.is_set():
                return
            iterator = iter(factory())
            while not done.is_set():
                demand.wait()
                demand.clear()
                if done.is_set():
                    return
                try:
                    chunk = next(iterator)
                except BaseException as exc:
                    # Relay cancellation/process-control errors across this
                    # thread boundary too; the consumer re-raises them.
                    results.put((False, exc))
                    return
                results.put((True, chunk))
        except BaseException as exc:
            results.put((False, exc))
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()

    context = copy_context()
    reader = Thread(target=context.run, args=(produce,), name="llm-stream-reader", daemon=True)
    reader.start()
    timeout = first_token
    try:
        while True:
            remaining = remaining_seconds()
            if remaining is not None and remaining <= 0:
                raise RunDeadlineExceeded("Stopped: time limit.")
            wait = min(timeout, remaining) if remaining is not None else timeout
            demand.set()
            try:
                ok, value = results.get(timeout=wait)
            except Empty:
                remaining = remaining_seconds()
                if remaining is not None and remaining <= 0:
                    raise RunDeadlineExceeded("Stopped: time limit.") from None
                raise StreamStalledError(f"Provider stream produced no chunk for {wait:g} seconds.") from None
            if not ok:
                if isinstance(value, StopIteration):
                    return
                raise value
            yield value
            timeout = stall
    finally:
        done.set()
        demand.set()
