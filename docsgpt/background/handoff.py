"""Yield, then hand off: run a tool call in the pool and hand it to a background job if it is slow.

``ToolExecutor`` calls :func:`run_call` instead of ``tool.execute_action``
when its turn has a :class:`~docsgpt.background.context.BackgroundContext`.
The call runs on a pool thread; the request thread waits up to the yield
window. A call that finishes in time returns exactly what it returned before
(its exception propagates the same way). A call still running becomes a
``background_jobs`` row and the turn gets a ``running`` result; the pool
thread finishes the job when the call returns.

The hand-off decision is a small protocol between the two threads, guarded by
one lock: the pool thread, once the call returns, either finds it was handed
off (and finishes the job) or marks it finished (and returns normally). The
request thread hands off only a call not yet marked finished, so exactly one
side owns the result.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
import uuid
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from docsgpt.background import jobs, pool
from docsgpt.background.context import BackgroundContext
from docsgpt.background.results import running_payload

logger = logging.getLogger(__name__)

#: Tools never handed off: their result only means something inside the turn
#: that called them (``view_image`` shows this turn's model an image), or they
#: are the background machinery itself.
NEVER_BACKGROUND_TOOLS = frozenset({"check_job", "view_image", "attachments"})

#: Arguments the background layer reads and the tool never sees.
CONTROL_ARGS = ("background", "watch")

#: How long a finished pool thread waits for the request thread to write the job row.
_JOB_READY_TIMEOUT = 300.0

#: Returned by a tool whose work a background job's poller took over (a
#: detached sandbox run): the pool thread then has nothing left to finish.
DETACHED = object()

_current_call: contextvars.ContextVar[Optional["CallHandle"]] = contextvars.ContextVar(
    "docsgpt_background_call", default=None
)


def current_call() -> Optional["CallHandle"]:
    """The background call the running tool belongs to, or None outside a hand-off-able call."""
    return _current_call.get()


def split_controls(arguments: Any) -> Tuple[Any, Dict[str, Any]]:
    """Separate ``background`` / ``watch`` from the arguments the tool receives.

    Args:
        arguments: The model's arguments.

    Returns:
        ``(tool_arguments, controls)``; non-dict arguments pass through.
    """
    if not isinstance(arguments, dict) or not any(key in arguments for key in CONTROL_ARGS):
        return arguments, {}
    controls = {key: arguments[key] for key in CONTROL_ARGS if key in arguments}
    return {k: v for k, v in arguments.items() if k not in CONTROL_ARGS}, controls


def wants_background(controls: Dict[str, Any]) -> bool:
    """Whether the model asked for ``background=true`` (strings like ``"true"`` count)."""
    value = controls.get("background")
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def eligible(executor: Any, tool_data: Dict[str, Any]) -> bool:
    """Whether this call may be handed off at all.

    Args:
        executor: The turn's ``ToolExecutor``.
        tool_data: The tool row being called.

    Returns:
        True for a server-side call in a turn that has a background context.
    """
    context = getattr(executor, "background", None)
    if not isinstance(context, BackgroundContext):
        return False
    if getattr(executor, "headless", False) or getattr(executor, "workflow_run_id", None):
        return False
    if tool_data.get("client_side"):
        return False
    return tool_data.get("name") not in NEVER_BACKGROUND_TOOLS


@dataclass
class CallSpec:
    """The call being run, as the background layer records it.

    Attributes:
        tool_name: The tool's name.
        action_name: The action called.
        journal_key: The turn-scoped ``tool_call_attempts`` key.
        arguments: The model's arguments (stored redacted on the job).
        parameters: The resolved parameters the tool runs with.
        controls: ``background`` / ``watch`` as the model passed them.
        worker_payload: What a Celery worker needs to run the call itself
            (explicit ``background`` on a tool that can't detach).
    """

    tool_name: str
    action_name: str
    journal_key: str
    arguments: Any
    parameters: Dict[str, Any] = field(default_factory=dict)
    controls: Dict[str, Any] = field(default_factory=dict)
    worker_payload: Optional[Dict[str, Any]] = None


@dataclass
class Outcome:
    """How a call ended for the turn.

    Attributes:
        handed_off: True when the call became a background job.
        value: The tool's return value (not handed off).
        payload: The ``running`` result for the model (handed off).
        job: The job row (handed off).
    """

    handed_off: bool
    value: Any = None
    payload: Optional[Dict[str, Any]] = None
    job: Optional[Dict[str, Any]] = None


class _Flight:
    """The state the request thread and the pool thread share for one call."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.finished = False
        self.handed_off = False
        self.detached = False
        self.job_id: Optional[str] = None
        self.job_ready = threading.Event()
        self.started = time.monotonic()


class CallHandle:
    """What a running tool sees of its background call (``current_call()``).

    A tool that can run detached (``code_executor``) polls its run and, once
    the turn handed the call off, moves it to a poller with :meth:`detach`
    instead of holding a pool thread for the rest of the run.

    Attributes:
        key: A unique key for this call's detached run.
        explicit: The model asked for ``background=true``.
    """

    def __init__(self, flight: _Flight, *, explicit: bool, watch: Optional[dict]) -> None:
        self._flight = flight
        self.key = uuid.uuid4().hex[:12]
        self.explicit = explicit
        self.watch = watch

    def handoff_requested(self) -> bool:
        """True once the turn handed this call off and its job row exists."""
        return self._flight.job_ready.is_set() and self._flight.job_id is not None

    def wait(self, seconds: float) -> None:
        """Sleep up to ``seconds``, waking early when the call is handed off."""
        if self._flight.job_ready.is_set():
            time.sleep(seconds)
        else:
            self._flight.job_ready.wait(seconds)

    def detach(self, external: Dict[str, Any]) -> bool:
        """Hand the rest of the run to the sandbox poller; True when it took it.

        Args:
            external: Everything the poller needs (run handle, finish state).

        Returns:
            False when the job could not be moved (keep polling here).
        """
        job_id = self._flight.job_id
        if job_id is None:
            return False
        from docsgpt.background.sandbox_runner import detach_job

        if not detach_job(job_id, external):
            return False
        self._flight.detached = True
        return True


def _detaches(tool: Any) -> bool:
    """Whether the tool can move a running call to a sandbox poller (``code_executor``)."""
    supports = getattr(tool, "supports_detached", None)
    try:
        return bool(callable(supports) and supports())
    except Exception:
        return False


def run_call(
    context: BackgroundContext,
    spec: CallSpec,
    tool: Any,
    invoke: Callable[[], Any],
    *,
    yield_seconds: Optional[float] = None,
    explicit: bool = False,
) -> Outcome:
    """Run one tool call, handing it off to a background job if it outlives the yield window.

    Args:
        context: The turn's background context.
        spec: The call.
        tool: The loaded tool instance (finishes the job's result shaping).
        invoke: Runs the call: ``tool.execute_action(...)`` with its arguments.
        yield_seconds: Override of the yield window; 0 hands off at once.
        explicit: The model asked for ``background=true``. A tool that can't
            detach then runs in a Celery worker from the start.

    Returns:
        The outcome; ``Outcome.value`` carries the tool's result when it was not handed off.

    Raises:
        Exception: Whatever the tool raised, when the call was not handed off.
    """
    if explicit:
        if not _detaches(tool) and spec.worker_payload is not None:
            queued = _run_in_worker(context, spec)
            if queued is not None:
                return queued
        yield_seconds = 0

    flight = _Flight()
    watch = spec.controls.get("watch") if isinstance(spec.controls.get("watch"), dict) else None
    handle = CallHandle(flight, explicit=explicit, watch=watch)

    def _work() -> Any:
        token = _current_call.set(handle)
        value: Any = None
        error: Optional[BaseException] = None
        try:
            value = invoke()
        except BaseException as exc:  # noqa: BLE001 - re-raised or recorded on the job below
            error = exc
        finally:
            _current_call.reset(token)
        with flight.lock:
            handed_off = flight.handed_off
            if not handed_off:
                flight.finished = True
        if handed_off:
            flight.job_ready.wait(_JOB_READY_TIMEOUT)
        if not handed_off or flight.job_id is None:
            if error is not None:
                raise error
            return value
        if value is DETACHED and error is None:
            return None
        jobs.complete_from_tool(
            flight.job_id,
            tool=tool,
            action_name=spec.action_name,
            parameters=spec.parameters,
            value=value,
            error=error,
        )
        return None

    future = pool.try_submit(_work)
    if future is None:
        # Every pool slot is busy: run inline, exactly as before.
        return Outcome(False, value=invoke())
    return _await_or_hand_off(context, spec, flight, future, window_override=yield_seconds)


def _await_or_hand_off(
    context: BackgroundContext,
    spec: CallSpec,
    flight: _Flight,
    future: Any,
    *,
    window_override: Optional[float],
) -> Outcome:
    """Wait out the yield window, then hand the call off if it is still running."""
    yield_seconds = window_override
    window = context.yield_seconds if yield_seconds is None else max(0.0, float(yield_seconds))
    try:
        return Outcome(False, value=future.result(timeout=window))
    except FuturesTimeout:
        pass

    try:
        allowed = jobs.within_caps(context)
    except Exception:
        logger.exception("background job cap check failed; the call stays in the foreground")
        allowed = False
    if not allowed:
        return Outcome(False, value=future.result())

    with flight.lock:
        if flight.finished:
            finished_first = True
        else:
            flight.handed_off = True
            finished_first = False
    if finished_first:
        return Outcome(False, value=future.result())

    job: Optional[Dict[str, Any]] = None
    try:
        job, _created = jobs.create_job(
            context,
            tool_name=spec.tool_name,
            action_name=spec.action_name,
            journal_key=spec.journal_key,
            arguments=spec.arguments,
            watch=_watch_of(spec),
        )
    except Exception:
        logger.exception("background job could not be written; the call stays in the foreground")
    if not job:
        flight.job_ready.set()
        return Outcome(False, value=future.result())

    flight.job_id = str(job["id"])
    pool.hold(flight.job_id)
    flight.job_ready.set()
    payload = running_payload(
        flight.job_id,
        auto_resume=bool(job.get("auto_resume")),
        elapsed_s=time.monotonic() - flight.started,
    )
    logger.info(
        "tool call handed off to background job",
        extra={"job_id": flight.job_id, "tool_name": spec.tool_name, "action_name": spec.action_name},
    )
    return Outcome(True, payload=payload, job=job)


def _watch_of(spec: CallSpec) -> Optional[dict]:
    """The call's ``watch`` spec when it is a dict."""
    watch = spec.controls.get("watch")
    return watch if isinstance(watch, dict) else None


def _run_in_worker(context: BackgroundContext, spec: CallSpec) -> Optional[Outcome]:
    """Queue an explicit background call to a Celery worker; None to run it here instead.

    The job row is written first (runner ``celery``, no lease until a worker
    starts it); a call that can't be queued keeps the old behaviour.

    Args:
        context: The turn's background context.
        spec: The call; ``worker_payload`` says how to rebuild it in the worker.

    Returns:
        The hand-off outcome, or None (over the cap, or the queue refused it).
    """
    try:
        if not jobs.within_caps(context):
            return None
        job, created = jobs.create_job(
            context,
            tool_name=spec.tool_name,
            action_name=spec.action_name,
            journal_key=spec.journal_key,
            arguments=spec.arguments,
            runner="celery",
            watch=_watch_of(spec),
        )
    except Exception:
        logger.exception("background job could not be written; the call runs here")
        return None
    if created:
        from docsgpt.background.celery_runner import enqueue

        if not enqueue(str(job["id"]), spec.worker_payload or {}):
            return None
    payload = running_payload(str(job["id"]), auto_resume=bool(job.get("auto_resume")), elapsed_s=0)
    return Outcome(True, payload=payload, job=job)
