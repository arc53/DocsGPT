"""OpenTelemetry export for execution traces (GenAI semantic conventions).

A finished :class:`~docsgpt.tracing.core.Trace` is *replayed*: every recorded
span is re-created with its original start and end timestamps and explicit
parents, under the OTel context captured when the trace started (normally the
HTTP server span). Replaying after the fact means no OTel context is ever
attached across the agent loop's generator yields. The cost is that GenAI
spans reach the backend only when the request ends, and auto-instrumented
HTTP/DB spans made during a step do not nest under it.

Attribute names follow the (still incubating) ``gen_ai.*`` conventions and are
written as literals rather than imported from the semconv package. Prompt and
tool content is exported only when
``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`` opts in.

Nothing here runs unless an OTel SDK is installed as the global provider (for
example by launching under ``opentelemetry-instrument``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from docsgpt.core.settings import settings
from docsgpt.tracing.core import (
    KIND_EMBEDDING,
    KIND_LLM,
    KIND_TOOL,
    STATUS_ERROR,
    STATUS_OK,
    Trace,
)

logger = logging.getLogger(__name__)

_INSTRUMENTATION_NAME = "docsgpt.tracing"

#: DocsGPT provider names that differ from the ``gen_ai.provider.name`` values.
_PROVIDER_NAMES = {
    "google": "gcp.gen_ai",
    "azure_openai": "azure.ai.openai",
    "aws_bedrock": "aws.bedrock",
    "mistral": "mistral_ai",
}

#: Preview keys with a dedicated GenAI attribute; others export as ``docsgpt.preview.<key>``.
_TOOL_PREVIEW_ATTRIBUTES = {
    "arguments": "gen_ai.tool.call.arguments",
    "result": "gen_ai.tool.call.result",
}

_CAPTURE_VALUES = {"span_only", "span_and_event", "true"}

# Advisory buckets from the GenAI metrics conventions.
_DURATION_BUCKETS = [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]
_TOKEN_BUCKETS = [1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]


def provider_name(internal: Optional[str]) -> str:
    """Map a DocsGPT ``provider_name`` to the ``gen_ai.provider.name`` value."""
    if not internal:
        return "unknown"
    return _PROVIDER_NAMES.get(internal, internal)


def content_capture_enabled() -> bool:
    """Whether the standard GenAI content-capture variable opts into span content."""
    value = os.getenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "")
    return value.strip().lower() in _CAPTURE_VALUES


def _is_noop(provider: Any) -> bool:
    from opentelemetry import trace as ot_trace

    return isinstance(provider, (ot_trace.ProxyTracerProvider, ot_trace.NoOpTracerProvider))


def _attr_value(value: Any) -> Any:
    """Coerce a recorded attribute into an OTel-legal value (or ``None`` to skip)."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        items = [v for v in value if v is not None]
        if items and all(isinstance(v, str) for v in items):
            return list(items)
        if items and all(isinstance(v, bool) for v in items):
            return list(items)
        if items and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in items):
            return list(items)
        if not items:
            return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _attributes(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, value in raw.items():
        coerced = _attr_value(value)
        if coerced is not None:
            out[key] = coerced
    return out


def _preview_attributes(kind: str, previews: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, value in previews.items():
        name = _TOOL_PREVIEW_ATTRIBUTES.get(key) if kind == KIND_TOOL else None
        out[name or f"docsgpt.preview.{key}"] = value if isinstance(value, str) else _attr_value(value)
    return out


def _root_attributes(trace: Trace) -> Dict[str, Any]:
    return _attributes(
        {
            "docsgpt.trace.id": trace.id,
            "docsgpt.source": trace.source,
            "docsgpt.request_id": trace.request_id,
            "docsgpt.message_id": trace.message_id,
            "docsgpt.activity_id": trace.activity_id,
            "docsgpt.workflow_run_id": trace.workflow_run_id,
            "gen_ai.conversation.id": trace.conversation_id,
            "gen_ai.agent.id": trace.agent_id,
            "docsgpt.status": trace.status,
            "docsgpt.dropped_spans": trace.dropped_spans or None,
        }
    )


def export_trace(trace: Trace, tracer_provider: Any = None) -> Optional[str]:
    """Replay ``trace`` as OTel spans; returns the OTel trace id (hex) or ``None``.

    Args:
        trace: A finished trace.
        tracer_provider: Override the global provider (tests).

    Returns:
        The 32-char hex OTel trace id, or ``None`` when export is disabled,
        no SDK is configured, or the trace is empty.
    """
    if not settings.TRACES_OTEL_EXPORT or not trace.spans:
        return None
    from opentelemetry import trace as ot_trace
    from opentelemetry.trace import SpanKind, Status, StatusCode

    provider = tracer_provider or ot_trace.get_tracer_provider()
    if _is_noop(provider):
        return None
    tracer = provider.get_tracer(_INSTRUMENTATION_NAME)
    capture = content_capture_enabled() and not trace.content_blocked

    root = tracer.start_span(
        f"docsgpt {trace.source}",
        context=trace.otel_context,
        kind=SpanKind.INTERNAL,
        attributes=_root_attributes(trace),
        start_time=trace.start_ns,
    )
    if trace.status == STATUS_ERROR:
        root.set_status(Status(StatusCode.ERROR))
    exported: Dict[str, Any] = {}
    for span in trace.spans:
        parent = exported.get(span.parent_id, root)
        attributes = dict(span.attributes)
        if trace.conversation_id and span.kind in (KIND_LLM, KIND_TOOL):
            attributes.setdefault("gen_ai.conversation.id", trace.conversation_id)
        if span.status and span.status not in (STATUS_OK, STATUS_ERROR):
            attributes["docsgpt.status"] = span.status
        attributes = _attributes(attributes)
        if capture and span.previews:
            attributes.update(_preview_attributes(span.kind, span.previews))
        otel_span = tracer.start_span(
            span.name,
            context=ot_trace.set_span_in_context(parent),
            kind=SpanKind.CLIENT if span.kind in (KIND_LLM, KIND_EMBEDDING) else SpanKind.INTERNAL,
            attributes=attributes,
            start_time=trace.span_start_ns(span),
        )
        if span.status == STATUS_ERROR:
            otel_span.set_status(Status(StatusCode.ERROR, span.error))
        exported[span.id] = otel_span
    for span in trace.spans:
        exported[span.id].end(end_time=trace.span_end_ns(span))
    root.end(end_time=trace.start_ns + int((trace.duration_ms or 0) * 1e6))
    context = root.get_span_context()
    return format(context.trace_id, "032x") if context.trace_id else None


# -- metrics --------------------------------------------------------------------

_instruments_lock = threading.Lock()
_global_instruments: Optional[tuple] = None


def _make_instruments(meter_provider: Any = None) -> tuple:
    from opentelemetry import metrics

    meter = (
        meter_provider.get_meter(_INSTRUMENTATION_NAME)
        if meter_provider is not None
        else metrics.get_meter(_INSTRUMENTATION_NAME)
    )

    def _histogram(name: str, unit: str, description: str, buckets: list):
        try:
            return meter.create_histogram(
                name, unit=unit, description=description,
                explicit_bucket_boundaries_advisory=buckets,
            )
        except TypeError:  # API older than bucket advisories
            return meter.create_histogram(name, unit=unit, description=description)

    duration = _histogram(
        "gen_ai.client.operation.duration", "s", "GenAI operation duration.", _DURATION_BUCKETS
    )
    tokens = _histogram(
        "gen_ai.client.token.usage", "{token}", "Number of input and output tokens used.", _TOKEN_BUCKETS
    )
    return duration, tokens


def _instruments(meter_provider: Any = None) -> tuple:
    global _global_instruments
    if meter_provider is not None:
        return _make_instruments(meter_provider)
    with _instruments_lock:
        if _global_instruments is None:
            _global_instruments = _make_instruments()
        return _global_instruments


def record_llm_metrics(
    *,
    provider: Optional[str],
    model: Optional[str],
    input_tokens: int,
    output_tokens: int,
    duration_s: float,
    error_type: Optional[str],
    operation: str = "chat",
    meter_provider: Any = None,
) -> None:
    """Record the two GenAI client metrics for one model call.

    Token usage is recorded only for successful calls, as the conventions
    require; duration is recorded for every call, with ``error.type`` on
    failures. Without a configured SDK the meter is a no-op.
    """
    if not settings.TRACES_OTEL_EXPORT:
        return
    try:
        duration, tokens = _instruments(meter_provider)
        attributes = {
            "gen_ai.operation.name": operation,
            "gen_ai.provider.name": provider_name(provider),
        }
        if model:
            attributes["gen_ai.request.model"] = str(model)
        if error_type:
            duration.record(duration_s, {**attributes, "error.type": error_type})
            return
        duration.record(duration_s, attributes)
        tokens.record(int(input_tokens or 0), {**attributes, "gen_ai.token.type": "input"})
        tokens.record(int(output_tokens or 0), {**attributes, "gen_ai.token.type": "output"})
    except Exception:  # noqa: BLE001 - metrics must never break a call
        logger.debug("Failed to record GenAI metrics", exc_info=True)
