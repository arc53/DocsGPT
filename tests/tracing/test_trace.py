"""Tests for the execution-trace recorder in ``docsgpt.tracing``."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from docsgpt import tracing
from docsgpt.core.settings import settings


@pytest.fixture(autouse=True)
def _tracing_on(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", True)
    monkeypatch.setattr(settings, "TRACES_MAX_SPANS", 500)
    monkeypatch.setattr(settings, "TRACES_PREVIEW_CHARS", 2000)


def _by_name(trace):
    return {s.name: s for s in trace.spans}


class TestNoActiveTrace:
    def test_span_calls_are_noops_without_a_trace(self):
        assert tracing.current_trace() is None
        with tracing.span(tracing.KIND_LLM, "chat gpt") as s:
            s.set(foo=1)
            s.preview("output", "hi")
        handle = tracing.start_span(tracing.KIND_TOOL, "tool")
        handle.end(status="error")
        tracing.bind(message_id="m")

    def test_start_trace_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_ENABLED", False)
        assert tracing.start_trace(source="stream") is None
        with tracing.activate(None):
            assert tracing.current_trace() is None


class TestNesting:
    def test_containers_push_and_leaves_record_parent(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            with tracing.span(tracing.KIND_AGENT, "agent"):
                with tracing.span(tracing.KIND_LLM, "llm-1"):
                    pass
                with tracing.span(tracing.KIND_TOOL, "tool"):
                    with tracing.span(tracing.KIND_RETRIEVAL, "retrieval"):
                        with tracing.span(tracing.KIND_EMBEDDING, "embed"):
                            pass
                with tracing.span(tracing.KIND_LLM, "llm-2"):
                    pass
        spans = _by_name(trace)
        assert spans["agent"].parent_id is None
        assert spans["llm-1"].parent_id == spans["agent"].id
        assert spans["tool"].parent_id == spans["agent"].id
        assert spans["retrieval"].parent_id == spans["tool"].id
        assert spans["embed"].parent_id == spans["retrieval"].id
        assert spans["llm-2"].parent_id == spans["agent"].id
        assert all(s.status == "ok" for s in trace.spans)

    def test_leaf_span_does_not_become_a_parent(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            llm = tracing.start_span(tracing.KIND_LLM, "llm")
            with tracing.span(tracing.KIND_TOOL, "tool"):
                pass
            llm.end()
        spans = _by_name(trace)
        assert spans["tool"].parent_id is None

    def test_explicit_parent_wins(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            outer = tracing.start_span(tracing.KIND_RETRIEVAL, "outer")
            with tracing.span(tracing.KIND_AGENT, "agent"):
                child = tracing.start_span(tracing.KIND_SEARCH, "child", parent=outer)
                child.end()
            outer.end()
        assert _by_name(trace)["child"].parent_id == _by_name(trace)["outer"].id

    def test_interleaved_generators_nest_by_start_order(self):
        """An agent generator suspended at yield keeps its children nested."""
        trace = tracing.start_trace(source="stream")

        def llm_stream():
            handle = tracing.start_span(tracing.KIND_LLM, "llm")
            try:
                yield "a"
                yield "b"
            finally:
                handle.end()

        def agent_gen():
            handle = tracing.start_span(tracing.KIND_AGENT, "agent")
            try:
                yield from llm_stream()
                with tracing.span(tracing.KIND_TOOL, "tool"):
                    pass
                yield "c"
            finally:
                handle.end()

        with tracing.activate(trace):
            assert list(agent_gen()) == ["a", "b", "c"]
        spans = _by_name(trace)
        assert spans["llm"].parent_id == spans["agent"].id
        assert spans["tool"].parent_id == spans["agent"].id

    def test_out_of_order_end_cancels_abandoned_children(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            agent = tracing.start_span(tracing.KIND_AGENT, "agent")
            tool = tracing.start_span(tracing.KIND_TOOL, "tool")
            agent.end()
            after = tracing.start_span(tracing.KIND_LLM, "after")
            after.end()
            tool.end()  # late end is ignored
        spans = _by_name(trace)
        assert spans["tool"].status == "cancelled"
        assert spans["agent"].status == "ok"
        assert spans["after"].parent_id is None

    def test_exception_marks_span_error_and_propagates(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            with pytest.raises(ValueError):
                with tracing.span(tracing.KIND_TOOL, "tool"):
                    raise ValueError("boom")
        span = trace.spans[0]
        assert span.status == "error"
        assert span.attributes["error.type"] == "ValueError"
        assert span.error == "boom"

    def test_generator_exit_marks_span_cancelled(self):
        trace = tracing.start_trace(source="stream")

        def gen():
            with tracing.span(tracing.KIND_AGENT, "agent"):
                yield 1
                yield 2

        with tracing.activate(trace):
            g = gen()
            next(g)
            g.close()
        assert trace.spans[0].status == "cancelled"


class TestFinish:
    def test_finish_cancels_open_spans_and_ignores_late_ends(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            open_span = tracing.start_span(tracing.KIND_AGENT, "agent")
        trace.finish()
        assert open_span.status == "cancelled"
        duration = open_span.duration_ms
        open_span.end(status="ok")
        assert open_span.status == "cancelled"
        assert open_span.duration_ms == duration

    def test_finish_status_defaults_to_error_when_a_top_level_span_failed(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            tracing.start_span(tracing.KIND_AGENT, "agent").end(status="error")
        trace.finish()
        assert trace.status == "error"

    def test_explicit_finish_status(self):
        trace = tracing.start_trace(source="stream")
        trace.finish(status="paused")
        assert trace.status == "paused"

    def test_spans_after_finish_are_dropped(self):
        trace = tracing.start_trace(source="stream")
        trace.finish()
        with tracing.activate(trace):
            tracing.start_span(tracing.KIND_LLM, "late").end()
        assert trace.spans == []

    def test_summary_rolls_up_llm_tool_retrieval(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            with tracing.span(tracing.KIND_AGENT, "agent"):
                with tracing.span(
                    tracing.KIND_LLM,
                    "chat",
                    attributes={
                        "gen_ai.usage.input_tokens": 10,
                        "gen_ai.usage.output_tokens": 4,
                    },
                ):
                    pass
                with tracing.span(tracing.KIND_RETRIEVAL, "r"):
                    with tracing.span(tracing.KIND_RETRIEVAL, "inner"):
                        pass
                with tracing.span(tracing.KIND_TOOL, "t") as t:
                    t.end(status="error")
        trace.finish()
        summary = trace.summary()
        assert summary["llm_calls"] == 1
        assert summary["tool_calls"] == 1
        assert summary["input_tokens"] == 10
        assert summary["output_tokens"] == 4
        assert summary["retrieval_calls"] == 1
        assert summary["errors"] == 1
        assert summary["retrieval_ms"] >= 0


class TestCap:
    def test_span_cap_counts_dropped(self, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_MAX_SPANS", 10)
        trace = tracing.start_trace(source="graph_extraction")
        with tracing.activate(trace):
            for i in range(15):
                with tracing.span(tracing.KIND_LLM, f"llm-{i}"):
                    pass
        assert len(trace.spans) == 10
        assert trace.dropped_spans == 5


class TestThreads:
    def test_wrap_carries_trace_and_parent_into_pool_threads(self):
        trace = tracing.start_trace(source="stream")

        def work(i):
            with tracing.span(tracing.KIND_SEARCH, f"search-{i}"):
                with tracing.span(tracing.KIND_EMBEDDING, f"embed-{i}"):
                    pass
            return threading.get_ident()

        with tracing.activate(trace):
            with tracing.span(tracing.KIND_RETRIEVAL, "retrieval"):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    list(pool.map(tracing.wrap(work), range(3)))
        spans = _by_name(trace)
        for i in range(3):
            assert spans[f"search-{i}"].parent_id == spans["retrieval"].id
            assert spans[f"embed-{i}"].parent_id == spans["retrieval"].id

    def test_pool_threads_without_wrap_see_no_trace(self):
        trace = tracing.start_trace(source="stream")
        seen = []
        with tracing.activate(trace):
            t = threading.Thread(target=lambda: seen.append(tracing.current_trace()))
            t.start()
            t.join()
        assert seen == [None]

    def test_wrap_without_trace_is_passthrough(self):
        fn = tracing.wrap(lambda x: x + 1)
        assert fn(1) == 2


class TestBind:
    def test_bind_sets_ids_on_active_trace(self):
        trace = tracing.start_trace(source="stream", request_id="r1")
        with tracing.activate(trace):
            tracing.bind(message_id="m1", conversation_id="c1", unknown="x")
        assert trace.request_id == "r1"
        assert trace.message_id == "m1"
        assert trace.conversation_id == "c1"

    def test_bind_if_unset_keeps_first_value(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            tracing.bind_if_unset(activity_id="a1")
            tracing.bind_if_unset(activity_id="a2")
        assert trace.activity_id == "a1"


class TestPreviews:
    def test_preview_redacts_secrets_and_bounds_strings(self, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_PREVIEW_CHARS", 100)
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            with tracing.span(tracing.KIND_TOOL, "tool") as s:
                s.preview("arguments", {"api_key": "sk-123", "q": "x" * 500})
                s.preview("result", "y" * 500 + "\x00")
        preview = trace.spans[0].previews
        assert preview["arguments"]["api_key"] == "[REDACTED]"
        assert len(preview["arguments"]["q"]) < 200
        assert preview["result"].endswith("…")
        assert "\x00" not in preview["result"]

    def test_preview_skipped_when_capture_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", False)
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            with tracing.span(tracing.KIND_TOOL, "tool") as s:
                s.preview("result", "secret stuff")
        assert trace.spans[0].previews == {}

    def test_guardrail_trigger_strips_all_previews(self):
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            with tracing.span(tracing.KIND_TOOL, "tool") as s:
                s.preview("result", "leaked")
            tracing.mark_content_blocked()
        trace.finish()
        record = trace.to_record()
        assert all(not s.get("preview") for s in record["spans"])
        assert trace.content_blocked is True

    def test_huge_structures_collapse_to_a_string(self, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_PREVIEW_CHARS", 100)
        trace = tracing.start_trace(source="stream")
        with tracing.activate(trace):
            with tracing.span(tracing.KIND_TOOL, "tool") as s:
                s.preview("result", [{"k": "v" * 50} for _ in range(100)])
        value = trace.spans[0].previews["result"]
        assert isinstance(value, str)
        assert len(value) <= 101


class TestRecord:
    def test_to_record_shape(self):
        trace = tracing.start_trace(
            source="stream", request_id="r", user_id="u", agent_id="a"
        )
        with tracing.activate(trace):
            with tracing.span(
                tracing.KIND_LLM, "chat m", attributes={"gen_ai.request.model": "m"}
            ):
                pass
        trace.finish()
        record = trace.to_record()
        assert record["source"] == "stream"
        assert record["request_id"] == "r"
        assert record["status"] == "ok"
        assert record["span_count"] == 1
        span = record["spans"][0]
        assert set(span) >= {
            "id", "parent_id", "kind", "name", "status", "offset_ms",
            "duration_ms", "attributes",
        }
        assert span["attributes"]["gen_ai.request.model"] == "m"
        assert span["offset_ms"] >= 0


class TestOutcome:
    def test_outcome_is_used_when_no_status_given(self):
        trace = tracing.start_trace(source="stream")
        trace.outcome = "paused"
        trace.finish()
        assert trace.status == "paused"

    def test_explicit_status_beats_outcome(self):
        trace = tracing.start_trace(source="stream")
        trace.outcome = "paused"
        trace.finish(status="error")
        assert trace.status == "error"
