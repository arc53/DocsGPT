"""Latency is measured by the usage wrappers and persisted with the call.

``duration_ms`` and ``ttft_ms`` were already computed for the finish log lines
and then discarded; these pin that they now reach ``token_usage``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docsgpt.usage import gen_token_usage, stream_token_usage


class _LLM:
    """Minimal stand-in for an LLM instance the wrappers decorate."""

    def __init__(self):
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        self.decoded_token = {"sub": "u1"}
        self.user_api_key = None
        self.agent_id = None


@pytest.fixture
def persisted():
    calls: list[dict] = []

    def _capture(llm, call_usage, *, duration_ms=None, ttft_ms=None):
        calls.append({"duration_ms": duration_ms, "ttft_ms": ttft_ms})

    with patch("docsgpt.usage._persist_call_usage", _capture):
        yield calls


@pytest.mark.unit
class TestNonStreaming:
    def test_records_a_duration_and_no_first_token(self, persisted):
        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            return "hello"

        assert _gen(_LLM(), "m", [], False, None) == "hello"
        assert persisted[0]["duration_ms"] >= 0
        # A non-streaming call has no first-token moment.
        assert persisted[0]["ttft_ms"] is None

    def test_a_failed_call_still_records_its_duration(self, persisted):
        @gen_token_usage
        def _gen(self, model, messages, stream, tools, **kwargs):
            raise RuntimeError("upstream down")

        with pytest.raises(RuntimeError):
            _gen(_LLM(), "m", [], False, None)
        assert persisted[0]["duration_ms"] >= 0


@pytest.mark.unit
class TestStreaming:
    def test_records_time_to_first_chunk(self, persisted):
        @stream_token_usage
        def _stream(self, model, messages, stream, tools, **kwargs):
            yield "a"
            yield "b"

        assert list(_stream(_LLM(), "m", [], True, None)) == ["a", "b"]
        row = persisted[0]
        assert row["ttft_ms"] is not None
        # First token cannot land after the call finished.
        assert row["ttft_ms"] <= row["duration_ms"]

    def test_a_stream_that_never_yields_has_no_first_token(self, persisted):
        """NULL, not 0 — an instant p50 would be a lie."""

        @stream_token_usage
        def _stream(self, model, messages, stream, tools, **kwargs):
            raise RuntimeError("refused")
            yield  # pragma: no cover - unreachable, makes this a generator

        with pytest.raises(RuntimeError):
            list(_stream(_LLM(), "m", [], True, None))
        assert persisted[0]["ttft_ms"] is None
        assert persisted[0]["duration_ms"] >= 0

    def test_duration_excludes_consumer_backpressure(self, persisted):
        """The clock must measure the provider, not a slow reader.

        ``stream_token_usage`` is a generator, so every yield suspends until
        the consumer comes back. Timing start-to-exhaustion would bill the
        agent loop's tool handling and the SSE client's pace to the model.
        """
        import time as _time

        @stream_token_usage
        def _stream(self, model, messages, stream, tools, **kwargs):
            yield "a"
            yield "b"

        for _ in _stream(_LLM(), "m", [], True, None):
            # A consumer that takes far longer than the provider did.
            _time.sleep(0.05)
        assert persisted[0]["duration_ms"] < 50

    def test_a_stream_cut_short_keeps_the_first_token_it_saw(self, persisted):
        @stream_token_usage
        def _stream(self, model, messages, stream, tools, **kwargs):
            yield "a"
            raise RuntimeError("dropped")

        with pytest.raises(RuntimeError):
            list(_stream(_LLM(), "m", [], True, None))
        assert persisted[0]["ttft_ms"] is not None
