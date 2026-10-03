"""Tests for the Atlas Cloud LLM provider.

Atlas Cloud uses an OpenAI-compatible API, so AtlasCloudLLM extends OpenAILLM.
These tests verify the Atlas Cloud-specific configuration is applied correctly.
"""

import types
from unittest.mock import patch

import pytest
from docsgpt.llm.atlascloud import ATLASCLOUD_BASE_URL, AtlasCloudLLM


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
            return FakeChatCompletions._Response(choices=[FakeChatCompletions._Choice(content="atlascloud response")])
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
def test_atlascloud_base_url_constant():
    """Verify the Atlas Cloud base URL is correctly defined."""
    assert ATLASCLOUD_BASE_URL == "https://api.atlascloud.ai/v1"


@pytest.mark.unit
def test_atlascloud_llm_uses_atlascloud_base_url():
    """Verify AtlasCloudLLM uses the Atlas Cloud API endpoint."""
    llm = AtlasCloudLLM(api_key="test-key", user_api_key=None)
    # The client should be configured with Atlas Cloud's base URL
    assert str(llm.client.base_url) == ATLASCLOUD_BASE_URL + "/"


@pytest.mark.unit
def test_atlascloud_llm_uses_atlascloud_api_key():
    """Verify AtlasCloudLLM prioritizes ATLASCLOUD_API_KEY from settings."""
    with patch("docsgpt.llm.atlascloud.settings") as mock_settings:
        mock_settings.ATLASCLOUD_API_KEY = "atlascloud-test-key"
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = AtlasCloudLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "atlascloud-test-key"


@pytest.mark.unit
def test_atlascloud_llm_falls_back_to_api_key():
    """Verify AtlasCloudLLM falls back to API_KEY when ATLASCLOUD_API_KEY is not set."""
    with patch("docsgpt.llm.atlascloud.settings") as mock_settings:
        mock_settings.ATLASCLOUD_API_KEY = None
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = AtlasCloudLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "fallback-key"


@pytest.mark.unit
def test_atlascloud_llm_explicit_api_key_takes_precedence():
    """Verify explicitly passed API key takes precedence over settings."""
    with patch("docsgpt.llm.atlascloud.settings") as mock_settings:
        mock_settings.ATLASCLOUD_API_KEY = "settings-key"
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = AtlasCloudLLM(api_key="explicit-key", user_api_key=None)
        assert llm.api_key == "explicit-key"


@pytest.mark.unit
def test_atlascloud_llm_custom_base_url():
    """Verify custom base_url can override the default Atlas Cloud URL."""
    custom_url = "https://custom.atlascloud.endpoint/v1"
    llm = AtlasCloudLLM(api_key="test-key", user_api_key=None, base_url=custom_url)
    assert str(llm.client.base_url) == custom_url + "/"


@pytest.mark.unit
def test_atlascloud_llm_supports_tools():
    """Verify AtlasCloudLLM supports function calling/tools."""
    llm = AtlasCloudLLM(api_key="test-key", user_api_key=None)
    assert llm.supports_tools() is True


@pytest.mark.unit
def test_atlascloud_llm_supports_structured_output():
    """Verify AtlasCloudLLM supports structured output."""
    llm = AtlasCloudLLM(api_key="test-key", user_api_key=None)
    assert llm.supports_structured_output() is True


@pytest.mark.unit
def test_atlascloud_llm_gen_calls_client(monkeypatch):
    """Verify AtlasCloudLLM.gen calls the OpenAI-compatible client correctly."""
    llm = AtlasCloudLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hello"}]
    result = llm._raw_gen(llm, model="deepseek-ai/DeepSeek-V3.1-Terminus", messages=msgs, stream=False)

    assert result == "atlascloud response"
    assert llm.client.chat.completions.last_kwargs["model"] == "deepseek-ai/DeepSeek-V3.1-Terminus"


@pytest.mark.unit
def test_atlascloud_llm_gen_stream_yields_chunks(monkeypatch):
    """Verify AtlasCloudLLM streaming yields chunks correctly."""
    llm = AtlasCloudLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hi"}]
    gen = llm._raw_gen_stream(llm, model="deepseek-ai/DeepSeek-V3.1-Terminus", messages=msgs, stream=True)
    chunks = list(gen)

    assert "part1" in "".join(chunks)
    assert "part2" in "".join(chunks)
