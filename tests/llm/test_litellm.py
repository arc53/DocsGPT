"""Tests for the LiteLLM provider."""

import types as builtin_types
from unittest import mock

import pytest

from application.llm.litellm import LiteLLM


# ---------------------------------------------------------------------------
# Fake response helpers (mirrors test_openai_llm.py style)
# ---------------------------------------------------------------------------


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Delta:
    def __init__(self, content=None, reasoning_content=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(
        self,
        content=None,
        delta=None,
        reasoning_content=None,
        tool_calls=None,
        finish_reason="stop",
    ):
        self.message = _Msg(content=content)
        self.delta = _Delta(
            content=delta,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
        )
        self.finish_reason = finish_reason


class _StreamLine:
    def __init__(self, deltas):
        choices = []
        for d in deltas:
            if isinstance(d, dict):
                choices.append(
                    _Choice(
                        delta=d.get("content"),
                        reasoning_content=d.get("reasoning_content"),
                        tool_calls=d.get("tool_calls"),
                        finish_reason=d.get("finish_reason", "stop"),
                    )
                )
            else:
                choices.append(_Choice(delta=d))
        self.choices = choices


class _Response:
    def __init__(self, choices=None, lines=None):
        self._choices = choices or []
        self._lines = lines or []

    @property
    def choices(self):
        return self._choices

    def __iter__(self):
        for line in self._lines:
            yield line


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def llm():
    """Return a LiteLLM instance with settings stubbed."""
    with mock.patch("application.llm.litellm.settings") as mock_settings:
        mock_settings.API_KEY = "test-key"
        return LiteLLM(api_key="test-key")


# ---------------------------------------------------------------------------
# _raw_gen tests
# ---------------------------------------------------------------------------


class TestRawGen:
    def test_basic_completion(self, llm):
        """Non-streaming call returns content string."""
        fake_response = _Response(
            choices=[_Choice(content="hello from litellm")]
        )
        import sys

        fake_mod = builtin_types.ModuleType("litellm")
        fake_mod.completion = mock.MagicMock(return_value=fake_response)
        sys.modules["litellm"] = fake_mod

        try:
            result = llm._raw_gen(
                llm,
                model="anthropic/claude-3-haiku",
                messages=[{"role": "user", "content": "hi"}],
                stream=False,
            )
            assert result == "hello from litellm"

            call_kwargs = fake_mod.completion.call_args[1]
            assert call_kwargs["model"] == "anthropic/claude-3-haiku"
            assert call_kwargs["drop_params"] is True
            assert call_kwargs["api_key"] == "test-key"
            assert call_kwargs["stream"] is False
        finally:
            del sys.modules["litellm"]

    def test_tool_call_returns_choice(self, llm):
        """When tools are provided, returns the Choice object."""
        fake_choice = _Choice(content=None, tool_calls=[{"id": "tc1"}])
        fake_response = _Response(choices=[fake_choice])

        import sys

        fake_mod = builtin_types.ModuleType("litellm")
        fake_mod.completion = mock.MagicMock(return_value=fake_response)
        sys.modules["litellm"] = fake_mod

        try:
            result = llm._raw_gen(
                llm,
                model="openai/gpt-4o",
                messages=[{"role": "user", "content": "use tool"}],
                stream=False,
                tools=[{"type": "function", "function": {"name": "test"}}],
            )
            assert result is fake_choice
        finally:
            del sys.modules["litellm"]


# ---------------------------------------------------------------------------
# _raw_gen_stream tests
# ---------------------------------------------------------------------------


class TestRawGenStream:
    def test_stream_yields_content(self, llm):
        """Streaming yields content strings."""
        fake_response = _Response(
            lines=[
                _StreamLine(["part1"]),
                _StreamLine(["part2"]),
            ]
        )

        import sys

        fake_mod = builtin_types.ModuleType("litellm")
        fake_mod.completion = mock.MagicMock(return_value=fake_response)
        sys.modules["litellm"] = fake_mod

        try:
            chunks = list(
                llm._raw_gen_stream(
                    llm,
                    model="anthropic/claude-3-haiku",
                    messages=[{"role": "user", "content": "hi"}],
                    stream=True,
                )
            )
            assert chunks == ["part1", "part2"]
        finally:
            del sys.modules["litellm"]

    def test_stream_yields_reasoning(self, llm):
        """Streaming yields reasoning tokens as dicts."""
        fake_response = _Response(
            lines=[
                _StreamLine(
                    [{"reasoning_content": "thinking...", "content": None}]
                ),
                _StreamLine(["answer"]),
            ]
        )

        import sys

        fake_mod = builtin_types.ModuleType("litellm")
        fake_mod.completion = mock.MagicMock(return_value=fake_response)
        sys.modules["litellm"] = fake_mod

        try:
            chunks = list(
                llm._raw_gen_stream(
                    llm,
                    model="openai/o3-mini",
                    messages=[{"role": "user", "content": "think"}],
                    stream=True,
                )
            )
            assert chunks[0] == {"type": "thought", "thought": "thinking..."}
            assert chunks[1] == "answer"
        finally:
            del sys.modules["litellm"]


# ---------------------------------------------------------------------------
# drop_params tests
# ---------------------------------------------------------------------------


class TestDropParams:
    def test_drop_params_default_true(self, llm):
        """drop_params=True is always passed by default."""
        fake_response = _Response(
            choices=[_Choice(content="ok")]
        )

        import sys

        fake_mod = builtin_types.ModuleType("litellm")
        fake_mod.completion = mock.MagicMock(return_value=fake_response)
        sys.modules["litellm"] = fake_mod

        try:
            llm._raw_gen(
                llm,
                model="openai/gpt-4o",
                messages=[{"role": "user", "content": "test"}],
            )
            call_kwargs = fake_mod.completion.call_args[1]
            assert call_kwargs["drop_params"] is True
        finally:
            del sys.modules["litellm"]


# ---------------------------------------------------------------------------
# Message cleaning tests
# ---------------------------------------------------------------------------


class TestCleanMessages:
    def test_model_role_becomes_assistant(self, llm):
        """'model' role is normalized to 'assistant'."""
        result = llm._clean_messages(
            [{"role": "model", "content": "hi"}]
        )
        assert result[0]["role"] == "assistant"

    def test_tool_message_passthrough(self, llm):
        """Tool messages with tool_call_id are passed through."""
        result = llm._clean_messages(
            [
                {
                    "role": "tool",
                    "tool_call_id": "tc1",
                    "content": '{"result": "ok"}',
                }
            ]
        )
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc1"

    def test_base_url_forwarded(self):
        """base_url is forwarded as api_base to litellm."""
        with mock.patch("application.llm.litellm.settings") as mock_settings:
            mock_settings.LITELLM_API_KEY = None
            mock_settings.API_KEY = None
            inst = LiteLLM(
                api_key="key",
                base_url="http://localhost:4000",
            )
            params = inst._build_completion_params(
                model="openai/gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=False,
            )
            assert params["api_base"] == "http://localhost:4000"


# ---------------------------------------------------------------------------
# supports_* tests
# ---------------------------------------------------------------------------


class TestSupports:
    def test_supports_tools(self, llm):
        assert llm._supports_tools() is True

    def test_supports_structured_output(self, llm):
        assert llm._supports_structured_output() is True
