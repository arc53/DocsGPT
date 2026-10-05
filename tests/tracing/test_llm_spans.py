"""LLM calls become ``chat`` spans through the token-usage wrappers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docsgpt import tracing
from docsgpt.cache import gen_cache, stream_cache
from docsgpt.core.settings import settings
from docsgpt.usage import gen_token_usage, stream_token_usage


class _LLM:
    provider_name = "openai"

    def __init__(self, source=None):
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        self.decoded_token = {"sub": "u1"}
        self.user_api_key = None
        self.agent_id = None
        if source:
            self._token_usage_source = source


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", True)
    with patch("docsgpt.usage._persist_call_usage", return_value=0.0012):
        yield


@pytest.fixture()
def trace():
    t = tracing.start_trace(source="stream", capture_otel_context=False)
    with tracing.activate(t):
        yield t


@pytest.fixture()
def metrics():
    with patch("docsgpt.tracing.llm.record_llm_metrics") as rec:
        yield rec


class TestNonStreaming:
    def test_span_with_usage_and_preview(self, trace, metrics):
        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            return "the answer"

        _gen(_LLM(), "gpt-4o", [{"role": "user", "content": "hi"}], False, None)
        (span,) = trace.spans
        assert span.kind == tracing.KIND_LLM
        assert span.name == "chat gpt-4o"
        assert span.status == "ok"
        attrs = span.attributes
        assert attrs["gen_ai.operation.name"] == "chat"
        assert attrs["gen_ai.provider.name"] == "openai"
        assert attrs["gen_ai.request.model"] == "gpt-4o"
        assert attrs["gen_ai.usage.input_tokens"] > 0
        assert attrs["gen_ai.usage.output_tokens"] > 0
        assert attrs["docsgpt.token_source"] == "agent_stream"
        assert attrs["docsgpt.cost_usd"] == 0.0012
        assert span.previews["output"] == "the answer"
        metrics.assert_called_once()
        assert metrics.call_args.kwargs["error_type"] is None

    def test_failure_marks_span_error(self, trace, metrics):
        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            raise TimeoutError("slow")

        with pytest.raises(TimeoutError):
            _gen(_LLM(source="fallback"), "m", [], False, None)
        (span,) = trace.spans
        assert span.status == "error"
        assert span.attributes["error.type"] == "TimeoutError"
        assert span.attributes["docsgpt.token_source"] == "fallback"
        assert metrics.call_args.kwargs["error_type"] == "TimeoutError"

    def test_provider_reported_usage_is_flagged(self, trace, metrics):
        llm = _LLM()

        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            self._last_usage = {
                "prompt_tokens": 100,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 40},
            }
            self._last_usage_claimed = False
            return "x"

        _gen(llm, "m", [], False, None)
        attrs = trace.spans[0].attributes
        assert attrs["gen_ai.usage.input_tokens"] == 100
        assert attrs["gen_ai.usage.output_tokens"] == 7
        assert attrs["gen_ai.usage.cache_read.input_tokens"] == 40
        assert attrs["docsgpt.usage_estimated"] is False

    def test_no_trace_no_span(self, metrics):
        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            return "x"

        assert _gen(_LLM(), "m", [], False, None) == "x"
        metrics.assert_called_once()


class TestDisabled:
    def test_no_metrics_when_tracing_is_off(self, metrics, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_ENABLED", False)

        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            return "x"

        _gen(_LLM(), "m", [], False, None)
        metrics.assert_not_called()


class TestStreaming:
    def test_span_starts_on_first_next_not_on_call(self, trace, metrics):
        @stream_token_usage
        def _stream(self, model, messages, stream, tools, **kwargs):
            yield "a"
            yield {"type": "thought", "thought": "hmm"}
            yield "b"

        gen = _stream(_LLM(), "m", [], True, None)
        assert trace.spans == []
        assert list(gen) == ["a", {"type": "thought", "thought": "hmm"}, "b"]
        (span,) = trace.spans
        assert span.status == "ok"
        assert span.attributes["docsgpt.ttft_ms"] is not None
        assert span.attributes["docsgpt.stream"] is True
        assert span.previews["output"] == "ab"

    def test_abandoned_stream_is_cancelled(self, trace, metrics):
        @stream_token_usage
        def _stream(self, model, messages, stream, tools, **kwargs):
            yield "a"
            yield "b"

        gen = _stream(_LLM(), "m", [], True, None)
        next(gen)
        gen.close()
        assert trace.spans[0].status == "cancelled"

    def test_failed_stream(self, trace, metrics):
        @stream_token_usage
        def _stream(self, model, messages, stream, tools, **kwargs):
            yield "a"
            raise ConnectionError("reset")

        with pytest.raises(ConnectionError):
            list(_stream(_LLM(), "m", [], True, None))
        assert trace.spans[0].status == "error"

    def test_primary_and_fallback_are_siblings(self, trace, metrics):
        @stream_token_usage
        def _primary(self, model, messages, stream, tools, **kwargs):
            raise ConnectionError("down")
            yield  # pragma: no cover

        @stream_token_usage
        def _fallback(self, model, messages, stream, tools, **kwargs):
            yield "ok"

        with tracing.span(tracing.KIND_AGENT, "agent"):
            with pytest.raises(ConnectionError):
                list(_primary(_LLM(), "m", [], True, None))
            list(_fallback(_LLM(source="fallback"), "m2", [], True, None))
        agent, primary, fallback = trace.spans
        assert primary.parent_id == agent.id == fallback.parent_id
        assert primary.status == "error"
        assert fallback.attributes["docsgpt.token_source"] == "fallback"


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value.encode("utf-8") if isinstance(value, str) else value

    def delete(self, key):
        self.store.pop(key, None)


class TestCacheHits:
    def test_gen_cache_hit_records_a_cached_span(self, trace, metrics):
        redis = _FakeRedis()

        @gen_cache
        @gen_token_usage
        def _gen(self, model, messages, stream, tools=None, **kwargs):
            return "fresh"

        with patch("docsgpt.cache.get_redis_instance", return_value=redis):
            _gen(_LLM(), "m", [{"role": "user", "content": "q"}], False)
            _gen(_LLM(), "m", [{"role": "user", "content": "q"}], False)
        first, second = trace.spans
        assert first.attributes.get("docsgpt.cache_hit") is None
        assert second.attributes["docsgpt.cache_hit"] is True
        assert second.status == "ok"

    def test_stream_cache_hit_flags_the_open_span(self, trace, metrics, monkeypatch):
        monkeypatch.setattr("docsgpt.cache.time.sleep", lambda _s: None)
        redis = _FakeRedis()

        @stream_token_usage
        @stream_cache
        def _stream(self, model, messages, stream, tools=None, **kwargs):
            yield "fresh"

        with patch("docsgpt.cache.get_redis_instance", return_value=redis):
            list(_stream(_LLM(), "m", [{"role": "user", "content": "q"}], True, None))
            list(_stream(_LLM(), "m", [{"role": "user", "content": "q"}], True, None))
        first, second = trace.spans
        assert first.attributes.get("docsgpt.cache_hit") is None
        assert second.attributes["docsgpt.cache_hit"] is True


class TestProviderResolution:
    """The span names the provider actually called, not the client class used."""

    @staticmethod
    def _llm(provider="openai", base_url=None, plugin=None):
        llm = _LLM()
        llm.provider_name = provider
        if base_url is not None:
            llm._effective_base_url = base_url
        if plugin is not None:
            llm._provider_plugin = plugin
        return llm

    @pytest.mark.parametrize(
        "base_url, plugin, expected",
        [
            ("https://api.deepseek.com/v1", "openai_compatible", "deepseek"),
            ("https://my-res.openai.azure.com/openai", "openai", "azure.ai.openai"),
            ("https://api.mistral.ai/v1", "openai_compatible", "mistral_ai"),
            ("https://api.x.ai/v1", "openai_compatible", "x_ai"),
            ("https://api.openai.com/v1", "openai", "openai"),
            ("http://10.0.0.5:8000/v1", "openai_compatible", "openai_compatible"),
            ("http://127.0.0.1:7899/v1", "openai", "openai_compatible"),
            (None, "openai", "openai"),
        ],
    )
    def test_provider_from_endpoint(self, base_url, plugin, expected):
        from docsgpt.tracing.llm import llm_provider

        assert llm_provider(self._llm(base_url=base_url, plugin=plugin)) == expected

    def test_native_providers_are_unchanged(self):
        from docsgpt.tracing.llm import llm_provider

        assert llm_provider(self._llm(provider="anthropic")) == "anthropic"
        assert llm_provider(self._llm(provider="google")) == "gcp.gen_ai"

    def test_span_and_metrics_use_it_and_record_server_address(self, trace, metrics):
        llm = self._llm(base_url="https://api.deepseek.com/v1", plugin="openai_compatible")

        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            return "x"

        _gen(llm, "deepseek-chat", [], False, None)
        attrs = trace.spans[0].attributes
        assert attrs["gen_ai.provider.name"] == "deepseek"
        assert attrs["server.address"] == "api.deepseek.com"
        assert metrics.call_args.kwargs["provider"] == "deepseek"
