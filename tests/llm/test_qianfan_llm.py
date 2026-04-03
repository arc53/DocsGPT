"""Tests for the Qianfan LLM provider."""

import types
from unittest.mock import patch

import pytest

from application.llm.qianfan import QIANFAN_BASE_URL, QianfanLLM


class FakeChatCompletions:
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
            return FakeChatCompletions._Response(
                choices=[FakeChatCompletions._Choice(content="qianfan response")]
            )
        return FakeChatCompletions._Response(
            lines=[
                FakeChatCompletions._StreamChunk(
                    FakeChatCompletions._Choice(delta="part1")
                ),
                FakeChatCompletions._StreamChunk(
                    FakeChatCompletions._Choice(delta="part2")
                ),
            ]
        )


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())


@pytest.mark.unit
def test_qianfan_base_url_constant():
    assert QIANFAN_BASE_URL == "https://qianfan.baidubce.com/v2"


@pytest.mark.unit
def test_qianfan_llm_uses_qianfan_base_url():
    llm = QianfanLLM(api_key="test-key", user_api_key=None)
    assert str(llm.client.base_url) == QIANFAN_BASE_URL + "/"


@pytest.mark.unit
def test_qianfan_llm_uses_qianfan_api_key():
    with patch("application.llm.qianfan.settings") as mock_settings:
        mock_settings.QIANFAN_API_KEY = "qianfan-test-key"
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = QianfanLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "qianfan-test-key"


@pytest.mark.unit
def test_qianfan_llm_falls_back_to_api_key():
    with patch("application.llm.qianfan.settings") as mock_settings:
        mock_settings.QIANFAN_API_KEY = None
        mock_settings.API_KEY = "fallback-key"
        mock_settings.OPENAI_BASE_URL = None

        llm = QianfanLLM(api_key=None, user_api_key=None)
        assert llm.api_key == "fallback-key"


@pytest.mark.unit
def test_qianfan_llm_returns_no_attachment_types():
    llm = QianfanLLM(api_key="test-key", user_api_key=None)
    assert llm.get_supported_attachment_types() == []


@pytest.mark.unit
def test_qianfan_llm_disables_tools():
    llm = QianfanLLM(api_key="test-key", user_api_key=None)
    assert llm._supports_tools() is False


@pytest.mark.unit
def test_qianfan_llm_disables_structured_output():
    llm = QianfanLLM(api_key="test-key", user_api_key=None)
    assert llm._supports_structured_output() is False


@pytest.mark.unit
def test_qianfan_llm_gen_calls_client():
    llm = QianfanLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hello"}]
    result = llm._raw_gen(llm, model="ernie-5.0", messages=msgs, stream=False)

    assert result == "qianfan response"
    assert llm.client.chat.completions.last_kwargs["model"] == "ernie-5.0"


@pytest.mark.unit
def test_qianfan_llm_gen_stream_yields_chunks():
    llm = QianfanLLM(api_key="test-key", user_api_key=None)
    llm.client = FakeClient()

    msgs = [{"role": "user", "content": "hi"}]
    gen = llm._raw_gen_stream(llm, model="ernie-5.0", messages=msgs, stream=True)
    chunks = list(gen)

    assert "part1" in "".join(chunks)
    assert "part2" in "".join(chunks)
