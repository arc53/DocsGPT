"""In-memory recording of one execution trace.

A :class:`Trace` collects spans for a single request (a chat turn, a
scheduled run, a search). Spans are recorded while the request runs and the
whole trace is written once, when its owner calls :func:`flush`.

Nesting is tracked with one span stack per thread. Only *container* spans
(agent, tool, retrieval, step) are pushed, so a leaf such as an LLM call can
never become the parent of a sibling that starts while it is still open --
which matters because DocsGPT's agent loop is a chain of suspended
generators. Ending a span pops anything left above it (marked
``cancelled``), and :meth:`Trace.finish` closes whatever is still open, so a
generator finalized late can never corrupt the tree or the stored record.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, List, Optional

from docsgpt.core.settings import settings
from docsgpt.tracing.preview import make_preview

logger = logging.getLogger(__name__)

KIND_AGENT = "agent"
KIND_LLM = "llm"
KIND_TOOL = "tool"
KIND_RETRIEVAL = "retrieval"
KIND_SEARCH = "search"
KIND_EMBEDDING = "embedding"
KIND_RERANK = "rerank"
KIND_GUARDRAIL = "guardrail"
KIND_STEP = "step"

#: Kinds that become the implicit parent of spans started while they are open.
CONTAINER_KINDS = frozenset({KIND_AGENT, KIND_TOOL, KIND_RETRIEVAL, KIND_RERANK, KIND_STEP})

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"
STATUS_PAUSED = "paused"
STATUS_PENDING = "pending"
STATUS_DENIED = "denied"
STATUS_SKIPPED = "skipped"

#: Trace ids ``bind`` may set; anything else is ignored.
BINDABLE_IDS = frozenset(
    {
        "request_id",
        "message_id",
        "conversation_id",
        "activity_id",
        "workflow_run_id",
        "user_id",
        "agent_id",
        "name",
    }
)

_current: ContextVar[Optional["Trace"]] = ContextVar("docsgpt_trace", default=None)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class Span:
    """One timed step inside a trace.

    Attribute keys follow the OTel GenAI conventions (``gen_ai.*``) where one
    exists and ``docsgpt.*`` otherwise, so the stored trace and the exported
    spans share a vocabulary.
    """

    __slots__ = (
        "trace",
        "id",
        "parent_id",
        "kind",
        "name",
        "attributes",
        "previews",
        "status",
        "error",
        "start_perf_ns",
        "end_perf_ns",
        "_thread",
        "_pushed",
    )

    def __init__(
        self,
        trace: "Trace",
        kind: str,
        name: str,
        parent_id: Optional[str],
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.trace = trace
        self.id = _new_id()
        self.parent_id = parent_id
        self.kind = kind
        self.name = name
        self.attributes: Dict[str, Any] = dict(attributes or {})
        self.previews: Dict[str, Any] = {}
        self.status: Optional[str] = None
        self.error: Optional[str] = None
        self.start_perf_ns = time.perf_counter_ns()
        self.end_perf_ns: Optional[int] = None
        self._thread: Optional[int] = None
        self._pushed = False

    @property
    def ended(self) -> bool:
        return self.end_perf_ns is not None

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_perf_ns is None:
            return None
        return (self.end_perf_ns - self.start_perf_ns) / 1e6

    def set(self, **attributes: Any) -> "Span":
        """Merge attributes; ``None`` values are ignored. Keys may contain dots via ``**{...}``."""
        if not self.ended:
            self.attributes.update({k: v for k, v in attributes.items() if v is not None})
        return self

    def preview(self, key: str, value: Any) -> "Span":
        """Attach a bounded, redacted content preview (skipped when capture is off)."""
        if self.ended or value is None or not settings.TRACES_CAPTURE_CONTENT:
            return self
        try:
            self.previews[key] = make_preview(value)
        except Exception:  # noqa: BLE001 - a preview must never break a request
            logger.debug("trace preview failed for %s", key, exc_info=True)
        return self

    def fail(self, exc: BaseException) -> "Span":
        """Record ``exc`` on the span without ending it."""
        self.status = STATUS_ERROR
        self.error = str(exc)[:500] or type(exc).__name__
        self.attributes["error.type"] = type(exc).__name__
        return self

    def end(
        self,
        status: Optional[str] = None,
        *,
        error: Optional[BaseException] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Close the span. A second end, or an end after the trace finished, is ignored."""
        if self.ended:
            return
        if attributes:
            self.set(**attributes)
        if error is not None:
            self.fail(error)
        if status is not None:
            self.status = status
        elif self.status is None:
            self.status = STATUS_OK
        self.end_perf_ns = time.perf_counter_ns()
        self.trace._on_end(self)

    def __enter__(self) -> "Span":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self.end()
        elif isinstance(exc, GeneratorExit):
            self.end(STATUS_CANCELLED)
        else:
            self.end(error=exc)
        return False


class _NoopSpan:
    """Stand-in returned when no trace is active or the span cap is reached."""

    id = None
    parent_id = None
    kind = None
    name = ""
    status = None
    ended = True
    duration_ms = None

    @property
    def attributes(self) -> Dict[str, Any]:
        return {}

    @property
    def previews(self) -> Dict[str, Any]:
        return {}

    def set(self, **attributes: Any) -> "_NoopSpan":
        return self

    def preview(self, key: str, value: Any) -> "_NoopSpan":
        return self

    def fail(self, exc: BaseException) -> "_NoopSpan":
        return self

    def end(self, status=None, *, error=None, attributes=None) -> None:
        return None

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __bool__(self) -> bool:
        return False


NOOP_SPAN = _NoopSpan()


class Trace:
    """All spans recorded for one execution, plus the ids that link it to logs."""

    def __init__(
        self,
        *,
        source: str,
        name: Optional[str] = None,
        request_id: Optional[str] = None,
        message_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        activity_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        otel_context: Any = None,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.source = source
        self.name = name or source
        self.request_id = request_id
        self.message_id = message_id
        self.conversation_id = conversation_id
        self.activity_id = activity_id
        self.workflow_run_id = workflow_run_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.otel_context = otel_context
        self.otel_trace_id: Optional[str] = None
        self.start_ns = time.time_ns()
        self.start_perf_ns = time.perf_counter_ns()
        self.end_perf_ns: Optional[int] = None
        self.status: Optional[str] = None
        self.spans: List[Span] = []
        self.dropped_spans = 0
        self.content_blocked = False
        self.attributes: Dict[str, Any] = {}
        self.finished = False
        self.flushed = False
        self._lock = threading.Lock()
        self._stacks: Dict[int, List[Any]] = {}

    # -- span lifecycle -------------------------------------------------

    def _parent_for_current_thread(self) -> Optional[str]:
        stack = self._stacks.get(threading.get_ident())
        return stack[-1].id if stack else None

    def start_span(
        self,
        kind: str,
        name: str,
        *,
        parent: Any = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Record a new span; returns :data:`NOOP_SPAN` once finished or over the cap."""
        with self._lock:
            if self.finished:
                return NOOP_SPAN
            if len(self.spans) >= settings.TRACES_MAX_SPANS:
                self.dropped_spans += 1
                return NOOP_SPAN
            if parent is not None:
                parent_id = getattr(parent, "id", None)
            else:
                parent_id = self._parent_for_current_thread()
            span = Span(self, kind, name, parent_id, attributes)
            self.spans.append(span)
            if kind in CONTAINER_KINDS:
                ident = threading.get_ident()
                self._stacks.setdefault(ident, []).append(span)
                span._thread = ident
                span._pushed = True
            return span

    def _on_end(self, span: Span) -> None:
        if not span._pushed:
            return
        with self._lock:
            stack = self._stacks.get(span._thread)
            if not stack or span not in stack:
                return
            index = stack.index(span)
            abandoned = stack[index + 1:]
            del stack[index:]
            if not stack:
                self._stacks.pop(span._thread, None)
        for child in reversed(abandoned):
            if isinstance(child, Span) and not child.ended:
                child.end(STATUS_CANCELLED)

    def _seed_thread(self, parent: Optional[Span]) -> Callable[[], None]:
        """Make ``parent`` the implicit parent in this thread; returns an undo callable."""
        if parent is None:
            return lambda: None
        ident = threading.get_ident()
        marker = _Seed(parent.id)
        with self._lock:
            self._stacks.setdefault(ident, []).append(marker)

        def _undo() -> None:
            with self._lock:
                stack = self._stacks.get(ident)
                if stack and marker in stack:
                    del stack[stack.index(marker):]
                if not stack:
                    self._stacks.pop(ident, None)

        return _undo

    def current_parent(self) -> Optional["_Seed | Span"]:
        stack = self._stacks.get(threading.get_ident())
        return stack[-1] if stack else None

    # -- ids --------------------------------------------------------------

    def bind(self, *, only_if_unset: bool = False, **ids: Any) -> None:
        for key, value in ids.items():
            if key not in BINDABLE_IDS or value is None:
                continue
            if only_if_unset and getattr(self, key, None):
                continue
            setattr(self, key, str(value))

    # -- completion ---------------------------------------------------------

    def finish(self, status: Optional[str] = None) -> None:
        """Freeze the trace: close open spans as ``cancelled`` and set the status."""
        with self._lock:
            if self.finished:
                return
            self.finished = True
            open_spans = [s for s in self.spans if not s.ended]
            self._stacks.clear()
        now = time.perf_counter_ns()
        for span in open_spans:
            span.status = STATUS_CANCELLED
            span.end_perf_ns = now
        self.end_perf_ns = now
        if status is not None:
            self.status = status
        else:
            failed = any(
                s.parent_id is None and s.status == STATUS_ERROR for s in self.spans
            )
            self.status = STATUS_ERROR if failed else STATUS_OK

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_perf_ns is None:
            return None
        return (self.end_perf_ns - self.start_perf_ns) / 1e6

    def span_start_ns(self, span: Span) -> int:
        """Wall-clock start of ``span`` in ns, derived from the monotonic offset."""
        return self.start_ns + (span.start_perf_ns - self.start_perf_ns)

    def span_end_ns(self, span: Span) -> int:
        end = span.end_perf_ns if span.end_perf_ns is not None else self.end_perf_ns
        return self.start_ns + ((end or span.start_perf_ns) - self.start_perf_ns)

    def summary(self) -> Dict[str, Any]:
        """Aggregate counts shown as chips in the Logs UI."""
        by_id = {s.id: s for s in self.spans}
        llm = [s for s in self.spans if s.kind == KIND_LLM]
        # Outermost retrieval spans only, so nested dispatcher/retriever
        # spans are not double-counted.
        retrieval = [
            s
            for s in self.spans
            if s.kind == KIND_RETRIEVAL
            and not (s.parent_id in by_id and by_id[s.parent_id].kind == KIND_RETRIEVAL)
        ]
        tools = [s for s in self.spans if s.kind == KIND_TOOL]

        def _tokens(key: str) -> int:
            total = 0
            for s in llm:
                value = s.attributes.get(key)
                if isinstance(value, (int, float)):
                    total += int(value)
            return total

        return {
            "llm_calls": len(llm),
            "tool_calls": len(tools),
            "retrieval_calls": len(retrieval),
            "retrieval_ms": round(sum(s.duration_ms or 0 for s in retrieval), 1),
            "input_tokens": _tokens("gen_ai.usage.input_tokens"),
            "output_tokens": _tokens("gen_ai.usage.output_tokens"),
            "errors": sum(1 for s in self.spans if s.status == STATUS_ERROR),
        }

    def to_record(self) -> Dict[str, Any]:
        """The ``request_traces`` row for this (finished) trace."""
        spans = []
        for s in self.spans:
            entry: Dict[str, Any] = {
                "id": s.id,
                "parent_id": s.parent_id,
                "kind": s.kind,
                "name": s.name,
                "status": s.status or STATUS_CANCELLED,
                "offset_ms": round((s.start_perf_ns - self.start_perf_ns) / 1e6, 2),
                "duration_ms": round(s.duration_ms or 0.0, 2),
                "attributes": s.attributes,
            }
            if s.error:
                entry["error"] = s.error
            if s.previews and not self.content_blocked:
                entry["preview"] = s.previews
            spans.append(entry)
        return {
            "id": self.id,
            "request_id": self.request_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "activity_id": self.activity_id,
            "workflow_run_id": self.workflow_run_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "source": self.source,
            "name": self.name,
            "status": self.status or STATUS_OK,
            "started_at_ns": self.start_ns,
            "duration_ms": int(round(self.duration_ms or 0)),
            "span_count": len(spans),
            "dropped_spans": self.dropped_spans,
            "summary": self.summary(),
            "spans": spans,
            "otel_trace_id": self.otel_trace_id,
        }


class _Seed:
    """Placeholder stack entry naming a parent span owned by another thread."""

    __slots__ = ("id",)

    def __init__(self, span_id: Optional[str]) -> None:
        self.id = span_id


# -- module-level API --------------------------------------------------------


def current_trace() -> Optional[Trace]:
    """The trace active in this context, or ``None``."""
    return _current.get()


def start_trace(*, source: str, capture_otel_context: bool = True, **ids: Any) -> Optional[Trace]:
    """Create a trace, or return ``None`` when ``TRACES_ENABLED`` is off.

    The OTel context current at this point (normally the HTTP server span) is
    captured so the exported GenAI spans hang off the request's own trace.
    """
    if not settings.TRACES_ENABLED:
        return None
    otel_context = None
    if capture_otel_context:
        try:
            from opentelemetry import context as otel_ctx

            otel_context = otel_ctx.get_current()
        except Exception:  # noqa: BLE001
            otel_context = None
    known = {k: v for k, v in ids.items() if k in BINDABLE_IDS}
    known = {k: (str(v) if v is not None else None) for k, v in known.items()}
    return Trace(source=source, otel_context=otel_context, **known)


@contextlib.contextmanager
def activate(trace: Optional[Trace]) -> Iterator[Optional[Trace]]:
    """Make ``trace`` current for the enclosed block (a no-op for ``None``)."""
    if trace is None:
        yield None
        return
    token = _current.set(trace)
    try:
        yield trace
    finally:
        try:
            _current.reset(token)
        except ValueError:
            # Reset from a different context (a generator finalized
            # elsewhere); clearing is the closest safe equivalent.
            _current.set(None)


def start_span(kind: str, name: str, *, parent: Any = None, attributes: Optional[Dict[str, Any]] = None):
    """Start a span in the current trace; returns :data:`NOOP_SPAN` without one."""
    trace = _current.get()
    if trace is None:
        return NOOP_SPAN
    try:
        return trace.start_span(kind, name, parent=parent, attributes=attributes)
    except Exception:  # noqa: BLE001 - tracing must never break a request
        logger.debug("trace start_span failed", exc_info=True)
        return NOOP_SPAN


def span(kind: str, name: str, *, parent: Any = None, attributes: Optional[Dict[str, Any]] = None):
    """Context-manager form of :func:`start_span` (errors mark the span and re-raise)."""
    return start_span(kind, name, parent=parent, attributes=attributes)


def bind(**ids: Any) -> None:
    """Set link ids (``message_id``, ``conversation_id``, ...) on the current trace."""
    trace = _current.get()
    if trace is not None:
        trace.bind(**ids)


def bind_if_unset(**ids: Any) -> None:
    """Like :func:`bind` but keeps any value already set."""
    trace = _current.get()
    if trace is not None:
        trace.bind(only_if_unset=True, **ids)


def mark_content_blocked() -> None:
    """A guardrail blocked or retracted content: drop every preview from the stored trace."""
    trace = _current.get()
    if trace is not None:
        trace.content_blocked = True


def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Bind the current trace and parent span into ``fn`` for another thread.

    Use around work handed to a thread pool or ``threading.Thread``; those do
    not inherit context variables. Without an active trace ``fn`` is returned
    unchanged.
    """
    trace = _current.get()
    if trace is None:
        return fn
    parent = trace.current_parent()

    @functools.wraps(fn)
    def _run(*args: Any, **kwargs: Any) -> Any:
        token = _current.set(trace)
        undo = trace._seed_thread(parent)
        try:
            return fn(*args, **kwargs)
        finally:
            undo()
            try:
                _current.reset(token)
            except ValueError:
                _current.set(None)

    return _run
