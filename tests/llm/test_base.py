"""Unit tests for application/llm/base.py — BaseLLM.

Extends coverage beyond test_base_llm.py:
  - gen / gen_stream: decorator application, argument forwarding
  - _execute_with_fallback: non-streaming fallback
  - _stream_with_fallback: mid-stream fallback
  - fallback_llm: backup model resolution, global fallback
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from application.llm.base import BaseLLM


# ---------------------------------------------------------------------------
# Concrete stubs
# ---------------------------------------------------------------------------


class StubLLM(BaseLLM):
    def __init__(self, raw_gen_return="gen_result", raw_gen_stream_items=None, **kwargs):
        super().__init__(**kwargs)
        self._raw_gen_return = raw_gen_return
        self._raw_gen_stream_items = raw_gen_stream_items or ["s1", "s2"]

    def _raw_gen(self, baseself, model, messages, stream=False, tools=None, **kw):
        return self._raw_gen_return

    def _raw_gen_stream(self, baseself, model, messages, stream=True, tools=None, **kw):
        yield from self._raw_gen_stream_items


class FailingLLM(BaseLLM):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _raw_gen(self, baseself, model, messages, stream=False, tools=None, **kw):
        raise RuntimeError("primary_failed")

    def _raw_gen_stream(self, baseself, model, messages, stream=True, tools=None, **kw):
        raise RuntimeError("primary_stream_failed")


class FallbackLLM(BaseLLM):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.gen_called = False
        self.gen_stream_called = False

    def _raw_gen(self, baseself, model, messages, stream=False, tools=None, **kw):
        self.gen_called = True
        return "fallback_result"

    def _raw_gen_stream(self, baseself, model, messages, stream=True, tools=None, **kw):
        self.gen_stream_called = True
        yield "fallback_chunk"

    def gen(self, *args, **kwargs):
        self.gen_called = True
        return "fallback_gen_result"

    def gen_stream(self, *args, **kwargs):
        self.gen_stream_called = True
        yield "fallback_stream_chunk"


# ---------------------------------------------------------------------------
# gen / gen_stream decorator application
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenMethods:

    @patch("application.llm.base.gen_cache", lambda f: f)
    @patch("application.llm.base.gen_token_usage", lambda f: f)
    def test_gen_returns_result(self):
        llm = StubLLM(raw_gen_return="hello")
        result = llm.gen(model="m", messages=[{"role": "user", "content": "hi"}])
        assert result == "hello"

    @patch("application.llm.base.stream_cache", lambda f: f)
    @patch("application.llm.base.stream_token_usage", lambda f: f)
    def test_gen_stream_yields_results(self):
        llm = StubLLM(raw_gen_stream_items=["a", "b"])
        result = list(
            llm.gen_stream(model="m", messages=[{"role": "user", "content": "hi"}])
        )
        assert result == ["a", "b"]

    @patch("application.llm.base.gen_cache", lambda f: f)
    @patch("application.llm.base.gen_token_usage", lambda f: f)
    def test_gen_passes_tools(self):
        tools = [{"type": "function", "function": {"name": "t"}}]

        class ToolCaptureLLM(BaseLLM):
            def __init__(self):
                super().__init__()
                self.captured_tools = None

            def _raw_gen(self, baseself, model, messages, stream=False, tools=None, **kw):
                self.captured_tools = tools
                return "ok"

            def _raw_gen_stream(self, baseself, model, messages, stream=True, tools=None, **kw):
                yield "x"

        llm = ToolCaptureLLM()
        llm.gen(model="m", messages=[], tools=tools)
        assert llm.captured_tools == tools


# ---------------------------------------------------------------------------
# _execute_with_fallback: non-streaming
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteWithFallbackNonStreaming:

    @patch("application.llm.base.gen_cache", lambda f: f)
    @patch("application.llm.base.gen_token_usage", lambda f: f)
    def test_no_fallback_raises(self):
        llm = FailingLLM()
        with pytest.raises(RuntimeError, match="primary_failed"):
            llm.gen(model="m", messages=[])

    @patch("application.llm.base.gen_cache", lambda f: f)
    @patch("application.llm.base.gen_token_usage", lambda f: f)
    def test_fallback_called_on_failure(self):
        fallback = FallbackLLM(model_id="fallback-model")
        llm = FailingLLM()
        llm._fallback_llm = fallback

        result = llm.gen(model="m", messages=[])
        assert result == "fallback_gen_result"
        assert fallback.gen_called


# ---------------------------------------------------------------------------
# _stream_with_fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStreamWithFallback:

    @patch("application.llm.base.stream_cache", lambda f: f)
    @patch("application.llm.base.stream_token_usage", lambda f: f)
    def test_no_fallback_raises(self):
        llm = FailingLLM()
        with pytest.raises(RuntimeError, match="primary_stream_failed"):
            list(llm.gen_stream(model="m", messages=[]))

    @patch("application.llm.base.stream_cache", lambda f: f)
    @patch("application.llm.base.stream_token_usage", lambda f: f)
    def test_fallback_called_on_stream_failure(self):
        fallback = FallbackLLM(model_id="fallback-model")
        llm = FailingLLM()
        llm._fallback_llm = fallback

        result = list(llm.gen_stream(model="m", messages=[]))
        assert "fallback_stream_chunk" in result
        assert fallback.gen_stream_called


# ---------------------------------------------------------------------------
# fallback_llm property: backup model resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFallbackLLMResolution:

    def test_returns_cached_fallback(self):
        sentinel = StubLLM()
        llm = StubLLM()
        llm._fallback_llm = sentinel
        assert llm.fallback_llm is sentinel

    def test_none_without_config(self, monkeypatch):
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )
        llm = StubLLM(backup_models=[])
        assert llm.fallback_llm is None

    def test_backup_model_resolved(self, monkeypatch):
        mock_fallback = StubLLM()
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda mid: "openai",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda p: "key",
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            Mock(return_value=mock_fallback),
        )

        llm = StubLLM(backup_models=["backup-model-id"])
        result = llm.fallback_llm
        assert result is mock_fallback

    def test_backup_model_failure_tries_next(self, monkeypatch):
        call_count = {"n": 0}

        def mock_create(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first fail")
            return StubLLM()

        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda mid: "openai",
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda p: "key",
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            mock_create,
        )

        llm = StubLLM(backup_models=["bad-model", "good-model"])
        result = llm.fallback_llm
        assert result is not None
        assert call_count["n"] == 2

    def test_global_fallback_used_when_no_backup(self, monkeypatch):
        mock_fallback = StubLLM()
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(
                FALLBACK_LLM_PROVIDER="openai",
                FALLBACK_LLM_NAME="gpt-4",
                FALLBACK_LLM_API_KEY="key",
                API_KEY="key",
            ),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            Mock(return_value=mock_fallback),
        )

        llm = StubLLM(backup_models=[])
        result = llm.fallback_llm
        assert result is mock_fallback

    def test_backup_provider_not_found_skipped(self, monkeypatch):
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            lambda mid: None,
        )
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )

        llm = StubLLM(backup_models=["unknown-model"])
        result = llm.fallback_llm
        assert result is None
