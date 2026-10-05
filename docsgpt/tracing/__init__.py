"""Per-request execution traces.

Records agent runs, LLM calls, tool calls, retrieval and embeddings as a tree
of timed spans. A finished trace is stored in ``request_traces`` (rendered as
a waterfall in the Logs UI) and replayed as OpenTelemetry GenAI spans when an
OTel SDK is configured. See ``docs/content/Deploying/Observability.mdx``.

Typical use::

    trace = tracing.start_trace(source="stream", request_id=request_id)
    with tracing.activate(trace):
        with tracing.span(tracing.KIND_TOOL, "execute_tool search") as s:
            s.preview("arguments", args)
            ...
    tracing.flush(trace)

Every call is a no-op when no trace is active.
"""

from docsgpt.tracing.core import (
    BINDABLE_IDS,
    CONTAINER_KINDS,
    KIND_AGENT,
    KIND_EMBEDDING,
    KIND_GUARDRAIL,
    KIND_LLM,
    KIND_RERANK,
    KIND_RETRIEVAL,
    KIND_SEARCH,
    KIND_STEP,
    KIND_TOOL,
    NOOP_SPAN,
    STATUS_CANCELLED,
    STATUS_DENIED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PAUSED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    Span,
    Trace,
    activate,
    bind,
    bind_if_unset,
    current_trace,
    first_occurrence,
    mark_content_blocked,
    span,
    start_span,
    start_trace,
    wrap,
)
from docsgpt.tracing.sink import discard, flush

__all__ = [
    "BINDABLE_IDS",
    "CONTAINER_KINDS",
    "KIND_AGENT",
    "KIND_EMBEDDING",
    "KIND_GUARDRAIL",
    "KIND_LLM",
    "KIND_RERANK",
    "KIND_RETRIEVAL",
    "KIND_SEARCH",
    "KIND_STEP",
    "KIND_TOOL",
    "NOOP_SPAN",
    "STATUS_CANCELLED",
    "STATUS_DENIED",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_PAUSED",
    "STATUS_PENDING",
    "STATUS_SKIPPED",
    "Span",
    "Trace",
    "activate",
    "bind",
    "bind_if_unset",
    "current_trace",
    "discard",
    "first_occurrence",
    "flush",
    "mark_content_blocked",
    "span",
    "start_span",
    "start_trace",
    "wrap",
]
