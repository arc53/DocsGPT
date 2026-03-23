"""Tests for the Novita LLM provider.

Novita uses an OpenAI-compatible API, so NovitaLLM extends OpenAILLM.
These tests verify the Novita-specific configuration is applied correctly.
"""

import types
from unittest.mock import MagicMock, patch

import pytest
from application.llm.novita import NOVITA_BASE_URL, NovitaLLM


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
            self.delta = FakeChatCompletions._Delta(delta=delta)

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
            return FakeChatCompletions._Response(choices=[FakeChatCompletions._Choice(content="novita response")])
        return FakeChatCompletions._Response(
            lines=[
                FakeChatCompletions._Choice(delta="part1"),
                FakeChatCompletions._Choice(delta="part2"),
            ]
        )


class FakeClient:
    """Fake OpenAI client for testing."""

    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())


@pytest.mark.unit
def test_novita_base_url_constant():
    """Verify the Novita base URL is correctly defined."""
    assert NOVITA_BASE_URL == "https://api.novita.ai/openai"


@pytest.mark.unit
def test_novita_llm_uses_novita_base_url():
    """Verify NovitaLLM uses the Novita API endpoint."""
    llm = NovitaLLM(api_key="test-key", user_api_key=None)
    # The client should be configured with Novita's base URL
    assert llm.client.base_url == NOVITA_BASE_URL


@pytest.mark.unit
def test_novita_llm_uses_novita_api_key():
    """Verify NovitaLLM prioritizes NOVITA_API_KEY from settings."""
    with patch("application.llm.novita.settings") as mock_settings:
        mock_settings.NOVITA_API_KEY = "novita-test-key"
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = NovitaLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "novita-test-key"


@pytest.mark.unit
def test_novita_llm_falls_back_to_api_key():
    """Verify NovitaLLM falls back to API_KEY when NOVITA_API_KEY is not set."""
    with patch("application.llm.novita.settings") as mock_settings:
        mock_settings.NOVITA_API_KEY = None
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = NovitaLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "fallback-key"


@pytest.mark.unit
def test_novita_llm_explicit_api_key_takes_precedence():
    """Verify explicitly passed API key takes precedence over settings."""
    with patch("application.llm.novita.settings") as mock_settings:
        mock_settings.NOVITA_API_KEY = "settings-key"
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = NovitaLLM(api_key="explicit-key", user_api_key=None)
        assert llm.api_key == "explicit-key"


@pytest.mark.unit
def test_novita_llm_custom_base_url():
    """Verify custom base_url can override the default Novita URL."""
    custom_url = "https://custom.novita.endpoint/v1"
    llm = NovitaLLM(api_key="test-key", user_api_key=None, base_url=custom_url)
    assert llm.client.base_url == custom_url


@pytest.mark.unit
def test_novita_llm_supports_tools():
    """Verify NovitaLLM supports function calling/tools."""
    llm = NovitaLLM(api_key="test-key", user_api_key=None)
    assert llm.supports_tools() is True


@pytest.mark.unit
def test_novita_llm_supports_structured_output():
    """Verify NovitaLLM supports structured output."""
    llm = NovitaLLM(api_key="test-key", user_api_key=None)
    assert llm.supports_structured_output() is True


@pytest.mark.unit
def test_novita_llm_gen_calls_client(monkeypatch):
    """Verify NovitaLLM.gen calls the OpenAI-compatible client correctly."""
    llm = NovitaLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hello"}]
    result = llm._raw_gen(llm, model="moonshotai/kimi-k2.5", messages=msgs, stream=False)

    assert result == "novita response"
    assert llm.client.chat.completions.last_kwargs["model"] == "moonshotai/kimi-k2.5"


@pytest.mark.unit
def test_novita_llm_gen_stream_yields_chunks(monkeypatch):
    """Verify NovitaLLM streaming yields chunks correctly."""
    llm = NovitaLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hi"}]
    gen = llm._raw_gen_stream(llm, model="moonshotai/kimi-k2.5", messages=msgs, stream=True)
    chunks = list(gen)

    assert "part1" in "".join(chunks)
    assert "part2" in "".join(chunks)
