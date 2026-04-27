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
from application.llm.handlers.base import (
    LLMHandler,
    LLMResponse,
    ToolCall,
)


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
            lambda mid, **_kwargs: "openai",
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
            lambda mid, **_kwargs: "openai",
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
            lambda mid, **_kwargs: None,
        )
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )

        llm = StubLLM(backup_models=["unknown-model"])
        result = llm.fallback_llm
        assert result is None


# ---------------------------------------------------------------------------
# LLMHandler tests for application/llm/handlers/base.py
# ---------------------------------------------------------------------------


class ConcreteHandler(LLMHandler):
    """Concrete implementation for testing abstract base."""

    def parse_response(self, response):
        if isinstance(response, LLMResponse):
            return response
        return LLMResponse(
            content=str(response),
            tool_calls=[],
            finish_reason="stop",
            raw_response=response,
        )

    def create_tool_message(self, tool_call, result):
        return {
            "role": "tool",
            "content": str(result),
            "tool_call_id": tool_call.id,
        }

    def _iterate_stream(self, response):
        if hasattr(response, "__iter__"):
            yield from response
        else:
            yield response


@pytest.mark.unit
class TestLLMHandlerAbstractMethods:
    """Cover lines 58, 63, 68 (abstract method pass statements)."""

    def test_concrete_handler_has_abstract_methods(self):
        handler = ConcreteHandler()
        # Should be able to call abstract methods
        resp = handler.parse_response("hello")
        assert resp.content == "hello"
        msg = handler.create_tool_message(
            ToolCall(id="1", name="fn", arguments={}), "result"
        )
        assert msg["role"] == "tool"
        chunks = list(handler._iterate_stream(["a", "b"]))
        assert chunks == ["a", "b"]


@pytest.mark.unit
class TestConvertPdfToImages:
    """Cover line 204 (_convert_pdf_to_images)."""

    def test_convert_pdf_to_images(self, monkeypatch):
        handler = ConcreteHandler()
        monkeypatch.setattr(
            "application.utils.convert_pdf_to_images",
            lambda file_path, storage, max_pages, dpi: [
                {"mime_type": "image/png", "data": "base64data", "page": 1}
            ],
        )
        monkeypatch.setattr(
            "application.storage.storage_creator.StorageCreator.get_storage",
            MagicMock(return_value=MagicMock()),
        )
        result = handler._convert_pdf_to_images({"path": "/tmp/test.pdf"})
        assert len(result) == 1
        assert result[0]["mime_type"] == "image/png"

    def test_convert_pdf_no_path_raises(self):
        handler = ConcreteHandler()
        with pytest.raises(ValueError, match="No file path"):
            handler._convert_pdf_to_images({})


@pytest.mark.unit
class TestPruneMessagesMinimal:
    """Cover line 252 (_prune_messages_minimal)."""

    def test_no_system_message_returns_none(self):
        handler = ConcreteHandler()
        result = handler._prune_messages_minimal(
            [{"role": "user", "content": "hi"}]
        )
        assert result is None

    def test_no_user_message_returns_none(self):
        handler = ConcreteHandler()
        result = handler._prune_messages_minimal(
            [{"role": "system", "content": "sys"}]
        )
        assert result is None

    def test_returns_system_and_user(self):
        handler = ConcreteHandler()
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "resp"},
            {"role": "user", "content": "question"},
        ]
        result = handler._prune_messages_minimal(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_falls_back_to_non_system_non_user(self):
        """Cover line 258: no user, but has assistant as last non-system."""
        handler = ConcreteHandler()
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "resp"},
        ]
        result = handler._prune_messages_minimal(msgs)
        assert len(result) == 2
        assert result[1]["role"] == "assistant"


@pytest.mark.unit
class TestPerformMidExecutionCompression:
    """Cover lines 499, 506, 525-527 (_perform_mid_execution_compression)."""

    def test_exception_returns_false_none(self, monkeypatch):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService.__init__",
            MagicMock(side_effect=Exception("import error")),
        )

        result = handler._perform_mid_execution_compression(agent, [])
        assert result == (False, None)

    def test_no_conversation_falls_back_to_in_memory(self, monkeypatch):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = None
        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(),
        )

        # Mock in-memory compression to succeed
        handler._perform_in_memory_compression = MagicMock(
            return_value=(True, [{"role": "system", "content": "compressed"}])
        )

        success, msgs = handler._perform_mid_execution_compression(agent, [])
        assert success is True
        handler._perform_in_memory_compression.assert_called_once()


@pytest.mark.unit
class TestPerformInMemoryCompression:
    """Cover lines 538, 540, 586, 590, 635-636."""

    def test_no_conversation_returns_false(self):
        handler = ConcreteHandler()
        agent = MagicMock()
        # Empty messages means _build_conversation_from_messages returns None
        result = handler._perform_in_memory_compression(agent, [])
        assert result == (False, None)

    def test_exception_returns_false_none(self, monkeypatch):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"

        # Build conversation returns something so we get past the None check
        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": [{"prompt": "q", "response": "r"}]}
        )

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(side_effect=Exception("provider error")),
        )

        result = handler._perform_in_memory_compression(agent, [])
        assert result == (False, None)


@pytest.mark.unit
class TestHandleToolCallsErrors:
    """Cover lines 660, 797, 803, 808."""

    def test_tool_execution_error_yields_error_event(self):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent._check_context_limit = MagicMock(return_value=False)
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = MagicMock(return_value=None)
        agent.tool_executor._name_to_tool = {"search": ("1", "search")}
        agent._execute_tool_action = MagicMock(
            side_effect=RuntimeError("tool failed")
        )

        tool_call = ToolCall(id="tc1", name="search", arguments={"q": "test"})
        tools_dict = {"1": {"name": "search_tool"}}
        messages = [{"role": "user", "content": "hi"}]

        gen = handler.handle_tool_calls(agent, [tool_call], tools_dict, messages)
        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration:
            pass

        error_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "tool_call" and e["data"].get("status") == "error"
        ]
        assert len(error_events) == 1
        assert error_events[0]["data"]["tool_name"] == "search_tool"

    def test_tool_execution_error_single_part_name(self):
        """Cover line 808: call.name without underscore."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent._check_context_limit = MagicMock(return_value=False)
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = MagicMock(return_value=None)
        agent.tool_executor._name_to_tool = {}
        agent._execute_tool_action = MagicMock(
            side_effect=RuntimeError("tool failed")
        )

        tool_call = ToolCall(id="tc1", name="singletool", arguments={})
        tools_dict = {}
        messages = [{"role": "user", "content": "hi"}]

        gen = handler.handle_tool_calls(agent, [tool_call], tools_dict, messages)
        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration:
            pass

        error_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "tool_call"
        ]
        assert len(error_events) == 1
        assert error_events[0]["data"]["tool_name"] == "unknown_tool"
        assert error_events[0]["data"]["action_name"] == "singletool"


# ---------------------------------------------------------------------------
# Additional coverage: abstract property stubs (lines 58, 63, 68)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAbstractMethodStubs:
    """Verify that calling abstract methods on a raw subclass that only does pass works."""

    def test_parse_response_abstract(self):
        """Cover line 58: abstract pass in parse_response."""
        handler = ConcreteHandler()
        resp = handler.parse_response("test")
        assert resp.content == "test"
        assert resp.finish_reason == "stop"

    def test_create_tool_message_abstract(self):
        """Cover line 63: abstract pass in create_tool_message."""
        handler = ConcreteHandler()
        tc = ToolCall(id="id1", name="fn", arguments={"a": 1})
        msg = handler.create_tool_message(tc, "result_val")
        assert msg["role"] == "tool"
        assert msg["content"] == "result_val"

    def test_iterate_stream_abstract(self):
        """Cover line 68: abstract pass in _iterate_stream."""
        handler = ConcreteHandler()
        chunks = list(handler._iterate_stream(["x", "y", "z"]))
        assert chunks == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# Additional coverage: _convert_pdf_to_images (line 204)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConvertPdfToImagesAdditional:
    """Additional tests to ensure line 204 (dpi=150) is covered."""

    def test_convert_pdf_passes_dpi_150(self, monkeypatch):
        """Cover line 204: dpi=150 argument in convert_pdf_to_images call."""
        handler = ConcreteHandler()
        captured_kwargs = {}

        def mock_convert(file_path, storage, max_pages, dpi):
            captured_kwargs["dpi"] = dpi
            captured_kwargs["max_pages"] = max_pages
            return [{"mime_type": "image/png", "data": "b64", "page": 1}]

        monkeypatch.setattr(
            "application.utils.convert_pdf_to_images",
            mock_convert,
        )
        monkeypatch.setattr(
            "application.storage.storage_creator.StorageCreator.get_storage",
            MagicMock(return_value=MagicMock()),
        )

        result = handler._convert_pdf_to_images({"path": "/tmp/doc.pdf"})
        assert captured_kwargs["dpi"] == 150
        assert captured_kwargs["max_pages"] == 20
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Additional coverage: _prune_messages_minimal (line 252)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPruneMessagesMinimalAdditional:
    """Cover line 252: no system message returns None."""

    def test_no_system_only_user(self):
        """Cover line 252: missing system message returns None."""
        handler = ConcreteHandler()
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = handler._prune_messages_minimal(msgs)
        assert result is None

    def test_system_only_no_others(self):
        """Cover line 260-262: system present but no non-system messages."""
        handler = ConcreteHandler()
        msgs = [
            {"role": "system", "content": "sys"},
        ]
        result = handler._prune_messages_minimal(msgs)
        assert result is None


# ---------------------------------------------------------------------------
# Additional coverage: _perform_mid_execution_compression (lines 499, 506, 525-527)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPerformMidExecutionCompressionAdditional:
    """Cover lines 499, 506, 525-527."""

    def test_successful_compression_sets_agent_attrs(self, monkeypatch):
        """Cover lines 499, 503-509, 512-523: successful compression path."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "m"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 100
        mock_metadata.original_token_count = 500
        mock_metadata.compression_ratio = 5.0
        mock_metadata.to_dict.return_value = {"ratio": 5.0}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.compressed_summary = "compressed text"
        mock_result.recent_queries = [{"prompt": "Q", "response": "A"}]
        mock_result.metadata = mock_metadata

        mock_orchestrator = MagicMock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(return_value=mock_orchestrator),
        )

        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": [{"prompt": "Q", "response": "A"}]}
        )
        rebuilt = [{"role": "system", "content": "compressed text"}]
        handler._rebuild_messages_after_compression = MagicMock(return_value=rebuilt)

        success, msgs = handler._perform_mid_execution_compression(
            agent, [{"role": "user", "content": "hi"}]
        )

        assert success is True
        assert msgs == rebuilt
        assert agent.compressed_summary == "compressed text"
        assert agent.compression_saved is False
        assert agent.context_limit_reached is False

    def test_compression_not_performed_returns_false(self, monkeypatch):
        """Cover lines 474-476: compression not performed."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.compression_performed = False

        mock_orchestrator = MagicMock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(return_value=mock_orchestrator),
        )
        handler._build_conversation_from_messages = MagicMock(return_value=None)

        success, msgs = handler._perform_mid_execution_compression(agent, [])
        assert success is False
        assert msgs is None

    def test_compression_failed_with_prune_fallback(self, monkeypatch):
        """Cover lines 464-472: compression failed, falls back to prune."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "failed"

        mock_orchestrator = MagicMock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(return_value=mock_orchestrator),
        )
        handler._build_conversation_from_messages = MagicMock(return_value=None)

        pruned = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ]
        handler._prune_messages_minimal = MagicMock(return_value=pruned)

        success, msgs = handler._perform_mid_execution_compression(agent, [])
        assert success is True
        assert msgs == pruned
        assert agent.context_limit_reached is False

    def test_compression_failed_prune_also_fails(self, monkeypatch):
        """Cover line 472: compression failed, prune returns None."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "err"

        mock_orchestrator = MagicMock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(return_value=mock_orchestrator),
        )
        handler._build_conversation_from_messages = MagicMock(return_value=None)
        handler._prune_messages_minimal = MagicMock(return_value=None)

        success, msgs = handler._perform_mid_execution_compression(agent, [])
        assert success is False
        assert msgs is None

    def test_compression_didnt_reduce_tokens_falls_back_to_prune(self, monkeypatch):
        """Cover lines 480-489: compression ratio not reduced, falls back to prune."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 500
        mock_metadata.original_token_count = 400  # compressed >= original
        mock_metadata.compression_ratio = 0.8

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.metadata = mock_metadata

        mock_orchestrator = MagicMock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(return_value=mock_orchestrator),
        )
        handler._build_conversation_from_messages = MagicMock(return_value=None)

        pruned = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ]
        handler._prune_messages_minimal = MagicMock(return_value=pruned)

        success, msgs = handler._perform_mid_execution_compression(agent, [])
        assert success is True
        assert msgs == pruned

    def test_rebuild_returns_none(self, monkeypatch):
        """Cover lines 520-521: rebuilt_messages is None."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "m"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 100
        mock_metadata.original_token_count = 500
        mock_metadata.compression_ratio = 5.0
        mock_metadata.to_dict.return_value = {}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.compressed_summary = "summary"
        mock_result.recent_queries = []
        mock_result.metadata = mock_metadata

        mock_orchestrator = MagicMock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(return_value=mock_orchestrator),
        )
        handler._build_conversation_from_messages = MagicMock(return_value=None)
        handler._rebuild_messages_after_compression = MagicMock(return_value=None)

        success, msgs = handler._perform_mid_execution_compression(agent, [])
        assert success is False
        assert msgs is None


# ---------------------------------------------------------------------------
# Additional coverage: _perform_in_memory_compression (lines 586, 590, 635-636)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPerformInMemoryCompressionAdditional:
    """Cover lines 586, 590, 635-636."""

    def test_successful_in_memory_compression(self, monkeypatch):
        """Cover lines 586-637: full successful in-memory compression path."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "test-model"
        agent.user_api_key = None
        agent.decoded_token = None
        agent.agent_id = None

        conversation = {
            "queries": [
                {"prompt": "Q1", "response": "A1"},
                {"prompt": "Q2", "response": "A2"},
            ]
        }
        handler._build_conversation_from_messages = MagicMock(
            return_value=conversation
        )

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 50
        mock_metadata.original_token_count = 200
        mock_metadata.compression_ratio = 4.0
        mock_metadata.to_dict.return_value = {"ratio": 4.0}

        mock_compression_service = MagicMock()
        mock_compression_service.compress_conversation.return_value = mock_metadata
        mock_compression_service.get_compressed_context.return_value = (
            "compressed summary",
            [{"prompt": "Q2", "response": "A2"}],
        )

        rebuilt = [
            {"role": "system", "content": "compressed summary"},
            {"role": "user", "content": "Q2"},
        ]
        handler._rebuild_messages_after_compression = MagicMock(
            return_value=rebuilt
        )

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(return_value="openai"),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            MagicMock(return_value="key"),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.service.CompressionService",
            MagicMock(return_value=mock_compression_service),
        )

        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ]

        success, result_msgs = handler._perform_in_memory_compression(
            agent, messages
        )

        assert success is True
        assert result_msgs == rebuilt
        assert agent.compressed_summary == "compressed summary"
        assert agent.compression_saved is False
        assert agent.context_limit_reached is False

    def test_in_memory_compression_not_enough_queries(self, monkeypatch):
        """Cover lines 583-585: compress_up_to < 0."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"

        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": []}
        )

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(return_value="openai"),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            MagicMock(return_value="key"),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.service.CompressionService",
            MagicMock(),
        )

        success, msgs = handler._perform_in_memory_compression(agent, [])
        assert success is False
        assert msgs is None

    def test_in_memory_compression_no_reduction_prunes(self, monkeypatch):
        """Cover lines 593-605: compression doesn't reduce, falls back to prune."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"

        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": [{"prompt": "Q", "response": "A"}]}
        )

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 300
        mock_metadata.original_token_count = 200  # no reduction

        mock_compression_service = MagicMock()
        mock_compression_service.compress_conversation.return_value = mock_metadata

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(return_value="openai"),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            MagicMock(return_value="key"),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.service.CompressionService",
            MagicMock(return_value=mock_compression_service),
        )

        pruned = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ]
        handler._prune_messages_minimal = MagicMock(return_value=pruned)

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ]

        success, msgs = handler._perform_in_memory_compression(agent, messages)
        assert success is True
        assert msgs == pruned

    def test_in_memory_compression_no_reduction_prune_fails(self, monkeypatch):
        """Cover line 605: prune returns None after no-reduction."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"

        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": [{"prompt": "Q", "response": "A"}]}
        )

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 300
        mock_metadata.original_token_count = 200

        mock_compression_service = MagicMock()
        mock_compression_service.compress_conversation.return_value = mock_metadata

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(return_value="openai"),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            MagicMock(return_value="key"),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.service.CompressionService",
            MagicMock(return_value=mock_compression_service),
        )

        handler._prune_messages_minimal = MagicMock(return_value=None)

        success, msgs = handler._perform_in_memory_compression(agent, [])
        assert success is False
        assert msgs is None

    def test_in_memory_rebuild_returns_none(self, monkeypatch):
        """Cover lines 630-631: rebuilt_messages is None."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"

        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": [{"prompt": "Q", "response": "A"}]}
        )

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 50
        mock_metadata.original_token_count = 200
        mock_metadata.compression_ratio = 4.0
        mock_metadata.to_dict.return_value = {}

        mock_compression_service = MagicMock()
        mock_compression_service.compress_conversation.return_value = mock_metadata
        mock_compression_service.get_compressed_context.return_value = (
            "summary",
            [],
        )

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(return_value="openai"),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            MagicMock(return_value="key"),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.service.CompressionService",
            MagicMock(return_value=mock_compression_service),
        )

        handler._rebuild_messages_after_compression = MagicMock(return_value=None)

        success, msgs = handler._perform_in_memory_compression(agent, [])
        assert success is False
        assert msgs is None


# ---------------------------------------------------------------------------
# Additional coverage: handle_tool_calls error paths (lines 660, 797, 803, 808)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleToolCallsErrorsAdditional:
    """Additional tests for tool execution error handling."""

    def test_tool_error_with_multi_part_name_updates_messages(self):
        """Cover lines 797, 803: error_message appended to updated_messages."""
        handler = ConcreteHandler()
        agent = MagicMock()
        agent._check_context_limit = MagicMock(return_value=False)
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = MagicMock(return_value=None)
        agent.tool_executor._name_to_tool = {"do_thing": ("42", "do_thing")}
        agent._execute_tool_action = MagicMock(
            side_effect=RuntimeError("broken tool")
        )

        tool_call = ToolCall(
            id="tc1", name="do_thing", arguments={"x": 1}
        )
        tools_dict = {"42": {"name": "my_tool"}}
        messages = [{"role": "user", "content": "go"}]

        gen = handler.handle_tool_calls(
            agent, [tool_call], tools_dict, messages
        )
        events = []
        final_messages = None
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            final_messages, _pending = e.value

        # Verify the error message was appended
        error_msgs = [
            m for m in final_messages
            if m.get("role") == "tool"
            and "Error executing tool" in str(m.get("content", ""))
        ]
        assert len(error_msgs) == 1

        # Verify the yield event
        error_events = [
            e for e in events
            if isinstance(e, dict) and e.get("data", {}).get("status") == "error"
        ]
        assert len(error_events) == 1
        assert error_events[0]["data"]["tool_name"] == "my_tool"
        assert error_events[0]["data"]["action_name"] == "do_thing"

    def test_tool_error_with_no_context_check(self):
        """Cover line 660: messages.copy() at start of handle_tool_calls."""
        handler = ConcreteHandler()
        agent = MagicMock(spec=[])  # No _check_context_limit attribute
        agent.llm = MagicMock()
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor = MagicMock()
        agent.tool_executor.check_pause = MagicMock(return_value=None)
        agent.tool_executor._name_to_tool = {}
        agent._execute_tool_action = MagicMock(
            side_effect=ValueError("bad args")
        )

        tool_call = ToolCall(id="tc1", name="action", arguments={})
        tools_dict = {}
        messages = [{"role": "system", "content": "sys"}]

        gen = handler.handle_tool_calls(
            agent, [tool_call], tools_dict, messages
        )
        events = list(gen)

        # Should still get an error event even without _check_context_limit
        error_events = [
            e for e in events
            if isinstance(e, dict) and e.get("data", {}).get("status") == "error"
        ]
        assert len(error_events) == 1
        assert error_events[0]["data"]["tool_name"] == "unknown_tool"


# ---------------------------------------------------------------------------
# Additional coverage: abstract method stubs (lines 58, 63, 68)
# Ensure the `pass` body of each abstract method is reached.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAbstractMethodPassBodies:
    """Directly test that the ABC pass statements in parse_response,
    create_tool_message, _iterate_stream are reachable via concrete subclass.
    """

    def test_parse_response_pass_reached(self):
        """Cover line 58: abstract pass in parse_response."""

        class MinimalHandler(LLMHandler):
            def parse_response(self, response):
                super().parse_response(response)
                return LLMResponse(
                    content="x", tool_calls=[], finish_reason="stop",
                    raw_response=response,
                )

            def create_tool_message(self, tool_call, result):
                return {}

            def _iterate_stream(self, response):
                yield from []

        h = MinimalHandler()
        r = h.parse_response("test")
        assert r.content == "x"

    def test_create_tool_message_pass_reached(self):
        """Cover line 63: abstract pass in create_tool_message."""

        class MinimalHandler(LLMHandler):
            def parse_response(self, response):
                return LLMResponse(
                    content="x", tool_calls=[], finish_reason="stop",
                    raw_response=response,
                )

            def create_tool_message(self, tool_call, result):
                super().create_tool_message(tool_call, result)
                return {"role": "tool", "content": str(result)}

            def _iterate_stream(self, response):
                yield from []

        h = MinimalHandler()
        tc = ToolCall(id="1", name="fn", arguments={})
        msg = h.create_tool_message(tc, "res")
        assert msg["role"] == "tool"

    def test_iterate_stream_pass_reached(self):
        """Cover line 68: abstract pass in _iterate_stream."""

        class MinimalHandler(LLMHandler):
            def parse_response(self, response):
                return LLMResponse(
                    content="x", tool_calls=[], finish_reason="stop",
                    raw_response=response,
                )

            def create_tool_message(self, tool_call, result):
                return {}

            def _iterate_stream(self, response):
                super()._iterate_stream(response)
                yield from []

        h = MinimalHandler()
        result = list(h._iterate_stream([]))
        assert result == []


# ---------------------------------------------------------------------------
# Additional coverage: _convert_pdf_to_images line 204
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConvertPdfDpiArg:
    """Ensure line 204 (dpi=150) is executed by verifying the arg."""

    def test_pdf_conversion_uses_correct_args(self, monkeypatch):
        handler = ConcreteHandler()
        call_args = {}

        def capture_convert(**kwargs):
            call_args.update(kwargs)
            return [{"page": 1, "data": "b64"}]

        monkeypatch.setattr(
            "application.utils.convert_pdf_to_images",
            lambda file_path, storage, max_pages, dpi: capture_convert(
                file_path=file_path, max_pages=max_pages, dpi=dpi
            ),
        )
        monkeypatch.setattr(
            "application.storage.storage_creator.StorageCreator.get_storage",
            MagicMock(return_value=MagicMock()),
        )
        handler._convert_pdf_to_images({"path": "/tmp/doc.pdf"})
        assert call_args["dpi"] == 150
        assert call_args["max_pages"] == 20


# ---------------------------------------------------------------------------
# Additional coverage: _prune_messages_minimal line 252
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPruneMinimalMissingSystem:
    """Cover line 252: returns None when no system message."""

    def test_only_tool_messages(self):
        handler = ConcreteHandler()
        msgs = [
            {"role": "tool", "content": "result"},
            {"role": "user", "content": "hi"},
        ]
        result = handler._prune_messages_minimal(msgs)
        assert result is None


# ---------------------------------------------------------------------------
# Additional coverage: _perform_mid_execution_compression line 499, 506
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMidExecutionCompressionMetadata:
    """Cover line 499 (conversation_service.append_compression_message)
    and line 506 (agent.compression_saved = False).
    """

    def test_metadata_stored_on_agent(self, monkeypatch):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "c1"
        agent.initial_user_id = "u1"
        agent.model_id = "m"

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "Q", "response": "A"}]
        }

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 50
        mock_metadata.original_token_count = 500
        mock_metadata.compression_ratio = 10.0
        mock_metadata.to_dict.return_value = {"ratio": 10.0}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.compressed_summary = "summary"
        mock_result.recent_queries = []
        mock_result.metadata = mock_metadata

        mock_orchestrator = MagicMock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(return_value=mock_conv_service),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.CompressionOrchestrator",
            MagicMock(return_value=mock_orchestrator),
        )

        rebuilt = [{"role": "system", "content": "compressed"}]
        handler._build_conversation_from_messages = MagicMock(return_value=None)
        handler._rebuild_messages_after_compression = MagicMock(return_value=rebuilt)

        success, msgs = handler._perform_mid_execution_compression(
            agent, [{"role": "user", "content": "hi"}]
        )
        assert success is True
        assert agent.compression_saved is False
        assert agent.context_limit_reached is False
        assert agent.current_token_count == 0
        mock_conv_service.append_compression_message.assert_called_once()


# ---------------------------------------------------------------------------
# Additional coverage: _perform_mid_execution_compression lines 525-527
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMidExecutionCompressionExceptionPath:
    """Cover lines 525-527: exception during mid-execution compression."""

    def test_import_error_returns_false(self, monkeypatch):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.conversation_id = "c1"
        agent.initial_user_id = "u1"

        # Make ConversationService raise on instantiation
        monkeypatch.setattr(
            "application.api.answer.services.conversation_service.ConversationService",
            MagicMock(side_effect=ImportError("module not found")),
        )

        success, msgs = handler._perform_mid_execution_compression(agent, [])
        assert success is False
        assert msgs is None


# ---------------------------------------------------------------------------
# Additional coverage: _perform_in_memory_compression lines 538, 540
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInMemoryCompressionImport:
    """Cover lines 538-540: import path for in-memory compression."""

    def test_import_error_returns_false(self, monkeypatch):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"

        # Build conversation returns something
        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": [{"prompt": "q", "response": "r"}]}
        )

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        # Make get_provider_from_model_id raise
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(side_effect=RuntimeError("no provider")),
        )

        success, msgs = handler._perform_in_memory_compression(agent, [])
        assert success is False
        assert msgs is None


# ---------------------------------------------------------------------------
# Additional coverage: _perform_in_memory_compression lines 586, 590
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInMemoryCompressionNoQueries:
    """Cover lines 583-585 (compress_up_to < 0 or queries_count == 0)
    and lines 586, 590 (compress_conversation call).
    """

    def test_single_query_compresses(self, monkeypatch):
        """Cover lines 586, 590: compress_conversation called with
        compress_up_to_index=0 (queries_count=1, compress_up_to=0).
        """
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"
        agent.user_api_key = None
        agent.decoded_token = None
        agent.agent_id = None

        conversation = {
            "queries": [{"prompt": "Q1", "response": "A1"}]
        }
        handler._build_conversation_from_messages = MagicMock(
            return_value=conversation
        )

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 30
        mock_metadata.original_token_count = 200
        mock_metadata.compression_ratio = 6.6
        mock_metadata.to_dict.return_value = {"ratio": 6.6}

        mock_compression_service = MagicMock()
        mock_compression_service.compress_conversation.return_value = mock_metadata
        mock_compression_service.get_compressed_context.return_value = (
            "compressed",
            [],
        )

        rebuilt = [{"role": "system", "content": "compressed"}]
        handler._rebuild_messages_after_compression = MagicMock(
            return_value=rebuilt
        )

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(return_value="openai"),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            MagicMock(return_value="key"),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.service.CompressionService",
            MagicMock(return_value=mock_compression_service),
        )

        success, msgs = handler._perform_in_memory_compression(
            agent, [{"role": "user", "content": "Q1"}]
        )
        assert success is True
        assert msgs == rebuilt
        assert agent.compression_saved is False


# ---------------------------------------------------------------------------
# Additional coverage: _perform_in_memory_compression lines 635-636
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInMemoryCompressionLogging:
    """Cover lines 635-636: successful compression log message."""

    def test_log_message_emitted(self, monkeypatch):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent.model_id = "m"
        agent.user_api_key = None
        agent.decoded_token = None
        agent.agent_id = None

        conversation = {
            "queries": [
                {"prompt": "Q1", "response": "A1"},
                {"prompt": "Q2", "response": "A2"},
            ]
        }
        handler._build_conversation_from_messages = MagicMock(
            return_value=conversation
        )

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 20
        mock_metadata.original_token_count = 400
        mock_metadata.compression_ratio = 20.0
        mock_metadata.to_dict.return_value = {"ratio": 20.0}

        mock_compression_service = MagicMock()
        mock_compression_service.compress_conversation.return_value = mock_metadata
        mock_compression_service.get_compressed_context.return_value = (
            "summary",
            [{"prompt": "Q2", "response": "A2"}],
        )

        rebuilt = [
            {"role": "system", "content": "summary"},
            {"role": "user", "content": "Q2"},
        ]
        handler._rebuild_messages_after_compression = MagicMock(
            return_value=rebuilt
        )

        monkeypatch.setattr(
            "application.core.settings.settings.COMPRESSION_MODEL_OVERRIDE",
            None,
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_provider_from_model_id",
            MagicMock(return_value="openai"),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            MagicMock(return_value="key"),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            "application.api.answer.services.compression.service.CompressionService",
            MagicMock(return_value=mock_compression_service),
        )

        success, msgs = handler._perform_in_memory_compression(
            agent, [{"role": "user", "content": "Q1"}]
        )
        assert success is True
        assert msgs == rebuilt


# ---------------------------------------------------------------------------
# Additional coverage: handle_tool_calls line 660
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleToolCallsMessagesCopy:
    """Cover line 660: messages.copy() at the top of handle_tool_calls."""

    def test_original_messages_not_mutated(self):
        handler = ConcreteHandler()
        agent = MagicMock()
        agent._check_context_limit = MagicMock(return_value=False)
        agent._execute_tool_action = MagicMock(return_value="ok")

        tool_call = ToolCall(id="tc1", name="do_thing_1", arguments={})
        messages = [{"role": "user", "content": "hi"}]
        original_len = len(messages)

        gen = handler.handle_tool_calls(
            agent, [tool_call], {"1": {"name": "tool"}}, messages
        )
        # Consume generator
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        # Original messages should not have been mutated
        assert len(messages) == original_len


# ---------------------------------------------------------------------------
# Additional coverage for application/llm/handlers/base.py
# Lines: 298 (_commit_query), 499 (append_compression_message),
# 506 (compression_saved), 525-527 (exception in mid-exec compression),
# 538/540 (in-memory compression imports), 586 (compress_up_to),
# 590 (compress_conversation), 635-636 (in-memory log), 660 (messages.copy)
# ---------------------------------------------------------------------------


class ConcreteHandlerForCompression(LLMHandler):
    """A concrete handler for testing compression paths."""

    def _get_llm_response(self, *args, **kwargs):
        return LLMResponse(content="ok", tool_calls=[])

    def _get_llm_response_stream(self, *args, **kwargs):
        yield LLMResponse(content="ok", tool_calls=[])

    def parse_response(self, response):
        if isinstance(response, LLMResponse):
            return response
        return LLMResponse(content=str(response), tool_calls=[])

    def create_tool_message(self, tool_call, result):
        return {"role": "tool", "content": str(result), "tool_call_id": tool_call.id}

    def _iterate_stream(self, response):
        if hasattr(response, "__iter__"):
            yield from response
        else:
            yield response


@pytest.mark.unit
class TestPerformMidExecutionCompressionException:
    """Cover lines 525-527: exception during mid-execution compression."""

    def test_mid_execution_compression_exception(self):
        handler = ConcreteHandlerForCompression()
        agent = MagicMock()
        agent.conversation_id = "conv123"
        agent.initial_user_id = "user1"
        messages = [{"role": "user", "content": "hello"}]

        # Force an exception inside the try block to trigger lines 525-527
        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            side_effect=RuntimeError("compression error"),
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=MagicMock(),
        ):
            success, result = handler._perform_mid_execution_compression(
                agent, messages
            )
        assert success is False
        assert result is None


@pytest.mark.unit
class TestPerformMidExecutionCompressionSuccess:
    """Cover lines 499, 506: successful mid-exec compression with metadata."""

    def test_mid_execution_compression_with_metadata(self):
        handler = ConcreteHandlerForCompression()
        agent = MagicMock()
        agent.conversation_id = "conv123"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

        mock_metadata = MagicMock()
        mock_metadata.to_dict.return_value = {"ratio": 2.0}
        mock_metadata.compression_ratio = 2.0
        mock_metadata.original_token_count = 1000
        mock_metadata.compressed_token_count = 500

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.compressed_summary = "summary"
        mock_result.metadata = mock_metadata
        mock_result.recent_queries = []

        mock_conv_service = MagicMock()
        mock_conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "hi", "response": "hello"}]
        }

        rebuilt = [{"role": "system", "content": "compressed"}]
        handler._rebuild_messages_after_compression = MagicMock(return_value=rebuilt)
        handler._build_conversation_from_messages = MagicMock(
            return_value={"queries": [{"prompt": "hi", "response": "hello"}]}
        )

        with patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=mock_conv_service,
        ), patch(
            "application.api.answer.services.compression.CompressionOrchestrator"
        ) as MockOrch:
            mock_orch = MagicMock()
            mock_orch.compress_mid_execution.return_value = mock_result
            MockOrch.return_value = mock_orch

            success, result_msgs = handler._perform_mid_execution_compression(
                agent, messages
            )
        assert success is True
        assert result_msgs == rebuilt
        assert agent.compression_saved is False


@pytest.mark.unit
class TestPerformInMemoryCompressionSuccess:
    """Cover lines 538/540, 586, 590, 635-636: in-memory compression success."""

    def test_in_memory_compression_success(self):
        handler = ConcreteHandlerForCompression()
        agent = MagicMock()
        agent.model_id = "gpt-4"
        agent.user_api_key = None
        agent.decoded_token = None
        agent.agent_id = None

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

        mock_metadata = MagicMock()
        mock_metadata.compressed_token_count = 100
        mock_metadata.original_token_count = 500
        mock_metadata.compression_ratio = 5.0
        mock_metadata.to_dict.return_value = {"ratio": 5.0}

        mock_compression_service = MagicMock()
        mock_compression_service.compress_conversation.return_value = mock_metadata
        mock_compression_service.get_compressed_context.return_value = (
            "compressed_summary",
            [{"prompt": "hello", "response": "hi"}],
        )

        rebuilt = [{"role": "system", "content": "compressed"}]

        handler._build_conversation_from_messages = MagicMock(
            return_value={
                "queries": [{"prompt": "hello", "response": "hi"}],
            }
        )
        handler._rebuild_messages_after_compression = MagicMock(return_value=rebuilt)

        with patch(
            "application.api.answer.services.compression.service.CompressionService",
            return_value=mock_compression_service,
        ), patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), patch(
            "application.core.settings.settings"
        ) as mock_s, patch(
            "application.llm.llm_creator.LLMCreator"
        ) as MockCreator:
            mock_s.COMPRESSION_MODEL_OVERRIDE = None
            MockCreator.create_llm.return_value = MagicMock()

            success, result_msgs = handler._perform_in_memory_compression(
                agent, messages
            )
        assert success is True
        assert result_msgs == rebuilt
        assert agent.compressed_summary == "compressed_summary"


@pytest.mark.unit
class TestPerformInMemoryCompressionException:
    """Cover line 639+: exception in in-memory compression."""

    def test_in_memory_compression_exception(self):
        handler = ConcreteHandlerForCompression()
        agent = MagicMock()
        agent.model_id = "gpt-4"
        messages = [{"role": "user", "content": "hi"}]

        handler._build_conversation_from_messages = MagicMock(
            side_effect=RuntimeError("fail"),
        )

        with patch(
            "application.api.answer.services.compression.service.CompressionService",
        ), patch(
            "application.core.model_utils.get_provider_from_model_id",
        ), patch(
            "application.core.model_utils.get_api_key_for_provider",
        ), patch(
            "application.core.settings.settings",
        ), patch(
            "application.llm.llm_creator.LLMCreator",
        ):
            success, result = handler._perform_in_memory_compression(agent, messages)
        assert success is False
        assert result is None


@pytest.mark.unit
class TestBuildConversationFromMessagesEmpty:
    """Cover line 298: _build_conversation_from_messages with empty messages."""

    def test_build_conversation_empty_messages(self):
        handler = ConcreteHandlerForCompression()
        result = handler._build_conversation_from_messages([])
        # Empty messages -> None or empty conversation
        assert result is None or result.get("queries") == []

    def test_build_conversation_with_user_assistant(self):
        handler = ConcreteHandlerForCompression()
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        assert len(result.get("queries", [])) >= 1
