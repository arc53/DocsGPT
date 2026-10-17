"""Tests for replaying a finished trace as OpenTelemetry GenAI spans."""

from __future__ import annotations

import pytest
from opentelemetry import trace as ot_trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from docsgpt import tracing
from docsgpt.core.settings import settings
from docsgpt.tracing import otel as trace_otel


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_OTEL_EXPORT", True)
    monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", True)
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)


@pytest.fixture()
def provider():
    exporter = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    tp.exporter = exporter
    return tp


def _sample_trace(otel_context=None):
    trace = tracing.start_trace(
        source="stream",
        request_id="req-1",
        message_id="msg-1",
        conversation_id="conv-1",
        agent_id="agent-1",
        capture_otel_context=False,
    )
    trace.otel_context = otel_context
    with tracing.activate(trace):
        with tracing.span(
            tracing.KIND_AGENT,
            "invoke_agent Support",
            attributes={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "Support"},
        ):
            with tracing.span(
                tracing.KIND_LLM,
                "chat gpt-4o",
                attributes={
                    "gen_ai.operation.name": "chat",
                    "gen_ai.provider.name": "openai",
                    "gen_ai.request.model": "gpt-4o",
                    "gen_ai.usage.input_tokens": 12,
                    "gen_ai.usage.output_tokens": 3,
                    "docsgpt.sources": ["a", "b"],
                    "docsgpt.meta": {"nested": True},
                },
            ) as llm:
                llm.preview("output", "hello")
            with tracing.span(
                tracing.KIND_TOOL,
                "execute_tool search",
                attributes={"gen_ai.tool.name": "search"},
            ) as tool:
                tool.preview("arguments", {"q": "x"})
                tool.preview("result", "found")
                tool.end(error=RuntimeError("tool broke"))
    trace.finish()
    return trace


class TestReplay:
    def test_spans_are_parented_and_timed(self, provider):
        trace = _sample_trace()
        otel_trace_id = trace_otel.export_trace(trace, tracer_provider=provider)
        spans = {s.name: s for s in provider.exporter.get_finished_spans()}
        root = spans["docsgpt stream"]
        agent = spans["invoke_agent Support"]
        llm = spans["chat gpt-4o"]
        tool = spans["execute_tool search"]
        assert agent.parent.span_id == root.context.span_id
        assert llm.parent.span_id == agent.context.span_id
        assert tool.parent.span_id == agent.context.span_id
        assert otel_trace_id == format(root.context.trace_id, "032x")
        recorded = {s.name: s for s in trace.spans}
        assert llm.start_time == trace.span_start_ns(recorded["chat gpt-4o"])
        assert llm.end_time == trace.span_end_ns(recorded["chat gpt-4o"])
        assert root.start_time == trace.start_ns
        assert root.end_time >= agent.end_time

    def test_semconv_attributes_and_kinds(self, provider):
        trace_otel.export_trace(_sample_trace(), tracer_provider=provider)
        spans = {s.name: s for s in provider.exporter.get_finished_spans()}
        llm = spans["chat gpt-4o"]
        assert llm.kind == SpanKind.CLIENT
        assert llm.attributes["gen_ai.usage.input_tokens"] == 12
        assert llm.attributes["gen_ai.conversation.id"] == "conv-1"
        assert tuple(llm.attributes["docsgpt.sources"]) == ("a", "b")
        assert llm.attributes["docsgpt.meta"] == '{"nested": true}'
        root = spans["docsgpt stream"]
        assert root.attributes["docsgpt.request_id"] == "req-1"
        assert root.attributes["docsgpt.message_id"] == "msg-1"

    def test_error_status(self, provider):
        trace_otel.export_trace(_sample_trace(), tracer_provider=provider)
        tool = {s.name: s for s in provider.exporter.get_finished_spans()}["execute_tool search"]
        assert tool.status.status_code == StatusCode.ERROR
        assert tool.attributes["error.type"] == "RuntimeError"

    def test_no_content_by_default(self, provider):
        trace_otel.export_trace(_sample_trace(), tracer_provider=provider)
        for span in provider.exporter.get_finished_spans():
            assert not any("preview" in k or "call.arguments" in k for k in span.attributes)

    def test_content_when_opted_in(self, provider, monkeypatch):
        monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "span_only")
        trace_otel.export_trace(_sample_trace(), tracer_provider=provider)
        spans = {s.name: s for s in provider.exporter.get_finished_spans()}
        tool = spans["execute_tool search"]
        assert tool.attributes["gen_ai.tool.call.arguments"] == '{"q": "x"}'
        assert tool.attributes["gen_ai.tool.call.result"] == "found"
        assert spans["chat gpt-4o"].attributes["docsgpt.preview.output"] == "hello"

    def test_content_blocked_trace_never_exports_content(self, provider, monkeypatch):
        monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "SPAN_ONLY")
        trace = _sample_trace()
        trace.content_blocked = True
        trace_otel.export_trace(trace, tracer_provider=provider)
        for span in provider.exporter.get_finished_spans():
            assert not any("preview" in k or "call.result" in k for k in span.attributes)

    def test_root_is_parented_to_captured_context(self, provider):
        server = provider.get_tracer("test").start_span("GET /stream")
        context = ot_trace.set_span_in_context(server)
        server.end()
        trace_otel.export_trace(_sample_trace(otel_context=context), tracer_provider=provider)
        root = {s.name: s for s in provider.exporter.get_finished_spans()}["docsgpt stream"]
        assert root.parent.span_id == server.get_span_context().span_id
        assert root.context.trace_id == server.get_span_context().trace_id

    def test_skipped_without_sdk_provider(self):
        assert trace_otel.export_trace(_sample_trace(), tracer_provider=ot_trace.NoOpTracerProvider()) is None

    def test_skipped_when_disabled(self, provider, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_OTEL_EXPORT", False)
        assert trace_otel.export_trace(_sample_trace(), tracer_provider=provider) is None
        assert provider.exporter.get_finished_spans() == ()


class TestProviderName:
    @pytest.mark.parametrize(
        "internal, expected",
        [
            ("openai", "openai"),
            ("google", "gcp.gen_ai"),
            ("anthropic", "anthropic"),
            ("azure_openai", "azure.ai.openai"),
            ("groq", "groq"),
            (None, "unknown"),
        ],
    )
    def test_mapping(self, internal, expected):
        assert trace_otel.provider_name(internal) == expected


class TestMetrics:
    def test_llm_metrics_recorded(self):
        reader = InMemoryMetricReader()
        mp = MeterProvider(metric_readers=[reader])
        trace_otel.record_llm_metrics(
            provider="openai",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=5,
            duration_s=0.25,
            error_type=None,
            meter_provider=mp,
        )
        data = reader.get_metrics_data()
        metrics = {
            m.name: m
            for rm in data.resource_metrics
            for sm in rm.scope_metrics
            for m in sm.metrics
        }
        usage = metrics["gen_ai.client.token.usage"]
        by_type = {
            p.attributes["gen_ai.token.type"]: p.sum for p in usage.data.data_points
        }
        assert by_type == {"input": 10, "output": 5}
        point = usage.data.data_points[0]
        assert point.attributes["gen_ai.provider.name"] == "openai"
        assert point.attributes["gen_ai.request.model"] == "gpt-4o"
        assert point.attributes["gen_ai.operation.name"] == "chat"
        duration = metrics["gen_ai.client.operation.duration"].data.data_points[0]
        assert duration.sum == pytest.approx(0.25)

    def test_error_type_on_duration_only(self):
        reader = InMemoryMetricReader()
        mp = MeterProvider(metric_readers=[reader])
        trace_otel.record_llm_metrics(
            provider="openai",
            model="m",
            input_tokens=0,
            output_tokens=0,
            duration_s=0.1,
            error_type="Timeout",
            meter_provider=mp,
        )
        metrics = {
            m.name: m
            for rm in reader.get_metrics_data().resource_metrics
            for sm in rm.scope_metrics
            for m in sm.metrics
        }
        assert "gen_ai.client.token.usage" not in metrics
        point = metrics["gen_ai.client.operation.duration"].data.data_points[0]
        assert point.attributes["error.type"] == "Timeout"

    def test_metrics_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_OTEL_EXPORT", False)
        reader = InMemoryMetricReader()
        mp = MeterProvider(metric_readers=[reader])
        trace_otel.record_llm_metrics(
            provider="openai", model="m", input_tokens=1, output_tokens=1,
            duration_s=0.1, error_type=None, meter_provider=mp,
        )
        data = reader.get_metrics_data()
        assert data is None or not data.resource_metrics
