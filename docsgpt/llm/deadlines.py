"""Bound blocking synchronous streams without advancing abandoned iterators."""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable, Iterable, Iterator

from docsgpt.core.run_budget import RunDeadlineExceeded, remaining_seconds


class StreamStalledError(TimeoutError):
    """A provider missed its first-token or inter-chunk deadline; fallback is allowed."""


class StreamAbandoned(BaseException):
    """The consumer gave up on this stream; its reader stops at the next provider event."""


@dataclass
class _ReaderState:
    """Shared between a stream's consumer and the thread reading it."""

    done: Event = field(default_factory=Event)
    lock: Lock = field(default_factory=Lock)
    activity: float = field(default_factory=monotonic)


_reader: ContextVar[_ReaderState | None] = ContextVar("llm_stream_reader", default=None)
_interrupt: ContextVar[Callable[[], BaseException | None] | None] = ContextVar("llm_stream_interrupt", default=None)

# How often a waiting stream asks whether it was stopped.
_INTERRUPT_POLL = 0.25


def interruptible(events: Iterable[Any], check: Callable[[], BaseException | None]) -> Iterator[Any]:
    """Iterate ``events`` so a Stop can end an in-flight provider read, not just the next chunk.

    ``check`` returns the exception a waiting stream raises, or None. It is
    bound around each step only, never across a yield, so the binding can't
    leak into whatever else the thread runs.
    """
    iterator = iter(events)
    try:
        while True:
            token = _interrupt.set(check)
            try:
                event = next(iterator)
            except StopIteration:
                return
            finally:
                _interrupt.reset(token)
            yield event
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()


def provider_event() -> None:
    """Note one raw provider event from an adapter's read loop.

    Events the adapter doesn't yield (tool-call arguments, server-side tools)
    still prove the stream is alive, so they refresh the stall clock. A read
    the consumer abandoned stops here, and the adapter's ``finally`` closes
    the connection instead of reading the rest of the response.
    """
    state = _reader.get()
    if state is None:
        return
    if state.done.is_set():
        raise StreamAbandoned()
    state.activity = monotonic()


@contextmanager
def stream_commit() -> Iterator[None]:
    """Guard writes of per-call provider state; an abandoned read must not make them."""
    state = _reader.get()
    if state is None:
        yield
        return
    with state.lock:
        if state.done.is_set():
            raise StreamAbandoned()
        yield


def _is_thought(chunk: Any) -> bool:
    return isinstance(chunk, dict) and chunk.get("type") == "thought"


def timed_stream(factory: Callable[[], Iterator[Any]], *, first_token: float, stall: float) -> Iterator[Any]:
    """Read one chunk at a time with deadlines, including stream creation.

    A daemon owns the blocking iterator and closes it when a pending read
    returns. It advances only on demand: timing out never starts another read
    or executes trailing provider code. Adapters that call
    :func:`provider_event` keep a stream that is busy but not yielding alive,
    and stop reading at their next event once the consumer is gone.
    Context is copied for billing/tracing. The transport's own read timeout
    remains the backstop for an in-flight read on a silent connection.
    """
    results: Queue[tuple[bool, Any]] = Queue(maxsize=1)
    demand = Event()
    state = _ReaderState()

    def produce() -> None:
        _reader.set(state)
        iterator = None
        try:
            demand.wait()
            if state.done.is_set():
                return
            iterator = iter(factory())
            while not state.done.is_set():
                demand.wait()
                demand.clear()
                if state.done.is_set():
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
            state.activity = monotonic()
            demand.set()
            while True:
                check = _interrupt.get()
                interrupt = check() if check is not None else None
                if interrupt is not None:
                    raise interrupt
                remaining = remaining_seconds()
                if remaining is not None and remaining <= 0:
                    raise RunDeadlineExceeded("Stopped: time limit.")
                idle_left = timeout - (monotonic() - state.activity)
                if idle_left <= 0:
                    raise StreamStalledError(f"Provider stream produced no event for {timeout:g} seconds.")
                wait = min(idle_left, remaining) if remaining is not None else idle_left
                if check is not None:
                    wait = min(wait, _INTERRUPT_POLL)
                try:
                    ok, value = results.get(timeout=wait)
                    break
                except Empty:
                    continue
            if not ok:
                if isinstance(value, StopIteration):
                    return
                raise value
            yield value
            # A reasoning model can think silently between summary parts; that is not a stall.
            timeout = max(first_token, stall) if _is_thought(value) else stall
    finally:
        with state.lock:
            state.done.set()
        demand.set()
