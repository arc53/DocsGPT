"""Tests for the LLMTR LLM provider.

LLMTR uses an OpenAI-compatible API, so LLMTRLLM extends OpenAILLM.
These tests verify the LLMTR-specific configuration is applied correctly.
"""

import types
from unittest.mock import patch

import pytest
from docsgpt.llm.llmtr import LLMTR_BASE_URL, LLMTRLLM


class FakeChatCompletions:
    """Fake OpenAI chat completions for testing."""

    def __init__(self):
        self.last_kwargs = None

    class _Msg:
        def __init__(self, content=None):
            self.content = content

    class _Delta:
        def __init__(self, content=None):
            self.content = content

    class _Choice:
        def __init__(self, content=None, delta=None):
            self.message = FakeChatCompletions._Msg(content=content)
            self.delta = FakeChatCompletions._Delta(content=delta)

    class _StreamChunk:
        def __init__(self, choice):
            self.choices = [choice]

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

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if not kwargs.get("stream"):
            return FakeChatCompletions._Response(choices=[FakeChatCompletions._Choice(content="llmtr response")])
        return FakeChatCompletions._Response(
            lines=[
                FakeChatCompletions._StreamChunk(FakeChatCompletions._Choice(delta="part1")),
                FakeChatCompletions._StreamChunk(FakeChatCompletions._Choice(delta="part2")),
            ]
        )


class FakeClient:
    """Fake OpenAI client for testing."""

    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())


@pytest.mark.unit
def test_llmtr_base_url_constant():
    """Verify the LLMTR base URL is correctly defined."""
    assert LLMTR_BASE_URL == "https://llmtr.com/v1"


@pytest.mark.unit
def test_llmtr_llm_uses_llmtr_base_url():
    """Verify LLMTRLLM uses the LLMTR API endpoint."""
    llm = LLMTRLLM(api_key="test-key", user_api_key=None)
    # The client should be configured with LLMTR's base URL
    assert str(llm.client.base_url) == LLMTR_BASE_URL + "/"


@pytest.mark.unit
def test_llmtr_llm_uses_llmtr_api_key():
    """Verify LLMTRLLM prioritizes LLMTR_API_KEY from settings."""
    with patch("docsgpt.llm.llmtr.settings") as mock_settings:
        mock_settings.LLMTR_API_KEY = "llmtr-test-key"
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = LLMTRLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "llmtr-test-key"


@pytest.mark.unit
def test_llmtr_llm_falls_back_to_api_key():
    """Verify LLMTRLLM falls back to API_KEY when LLMTR_API_KEY is not set and LLMTR is LLM_PROVIDER."""
    with patch("docsgpt.llm.llmtr.settings") as mock_settings:
        mock_settings.LLMTR_API_KEY = None
        mock_settings.API_KEY = "fallback-key"
        mock_settings.LLM_PROVIDER = "llmtr"
        mock_settings.OPENAI_BASE_URL = None

        llm = LLMTRLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "fallback-key"


@pytest.mark.unit
def test_llmtr_llm_does_not_take_another_providers_api_key():
    """API_KEY belongs to LLM_PROVIDER; LLMTR must not send it to its own endpoint."""
    with patch("docsgpt.llm.llmtr.settings") as mock_settings:
        mock_settings.LLMTR_API_KEY = None
        mock_settings.API_KEY = "openai-key"
        mock_settings.LLM_PROVIDER = "openai"
        mock_settings.OPENAI_BASE_URL = None

        llm = LLMTRLLM(api_key=None, user_api_key=None)
        assert llm.api_key != "openai-key"


@pytest.mark.unit
def test_llmtr_llm_explicit_api_key_takes_precedence():
    """Verify explicitly passed API key takes precedence over settings."""
    with patch("docsgpt.llm.llmtr.settings") as mock_settings:
        mock_settings.LLMTR_API_KEY = "settings-key"
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = LLMTRLLM(api_key="explicit-key", user_api_key=None)
        assert llm.api_key == "explicit-key"


@pytest.mark.unit
def test_llmtr_llm_custom_base_url():
    """Verify custom base_url can override the default LLMTR URL."""
    custom_url = "https://custom.llmtr.endpoint/v1"
    llm = LLMTRLLM(api_key="test-key", user_api_key=None, base_url=custom_url)
    assert str(llm.client.base_url) == custom_url + "/"


@pytest.mark.unit
def test_llmtr_llm_supports_tools():
    """Verify LLMTRLLM supports function calling/tools."""
    llm = LLMTRLLM(api_key="test-key", user_api_key=None)
    assert llm.supports_tools() is True


@pytest.mark.unit
def test_llmtr_llm_supports_structured_output():
    """Verify LLMTRLLM supports structured output."""
    llm = LLMTRLLM(api_key="test-key", user_api_key=None)
    assert llm.supports_structured_output() is True


@pytest.mark.unit
def test_llmtr_llm_gen_calls_client(monkeypatch):
    """Verify LLMTRLLM.gen calls the OpenAI-compatible client correctly."""
    llm = LLMTRLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hello"}]
    result = llm._raw_gen(llm, model="qwen/qwen3.8-27b-free", messages=msgs, stream=False)

    assert result == "llmtr response"
    assert llm.client.chat.completions.last_kwargs["model"] == "qwen/qwen3.8-27b-free"


@pytest.mark.unit
def test_llmtr_llm_gen_stream_yields_chunks(monkeypatch):
    """Verify LLMTRLLM streaming yields chunks correctly."""
    llm = LLMTRLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hi"}]
    gen = llm._raw_gen_stream(llm, model="qwen/qwen3.8-27b-free", messages=msgs, stream=True)
    chunks = list(gen)

    assert "part1" in "".join(chunks)
    assert "part2" in "".join(chunks)
