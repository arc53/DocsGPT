"""Unit tests for application/llm/premai.py — PremAILLM.

Covers:
  - Constructor
  - _raw_gen: API call and return value
  - _raw_gen_stream: streaming with delta content filtering
"""

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Fake premai module
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content):
        self.message = {"content": content}


class _FakeDelta:
    def __init__(self, content):
        self.delta = {"content": content}


class _FakeChoice:
    def __init__(self, content):
        self.message = {"content": content}


class _FakeStreamChoice:
    def __init__(self, content):
        self.delta = {"content": content}


class _FakeResponse:
    def __init__(self, content="result_text"):
        self.choices = [_FakeChoice(content)]


class _FakeStreamLine:
    def __init__(self, content):
        self.choices = [_FakeStreamChoice(content)]


class _FakeChatCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            return [
                _FakeStreamLine("chunk1"),
                _FakeStreamLine("chunk2"),
                _FakeStreamLine(None),  # None content should be filtered
            ]
        return _FakeResponse()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeChatCompletions()


class _FakePrem:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.chat = _FakeChat()


@pytest.fixture(autouse=True)
def patch_premai(monkeypatch):
    fake_mod = types.ModuleType("premai")
    fake_mod.Prem = _FakePrem
    sys.modules["premai"] = fake_mod

    if "application.llm.premai" in sys.modules:
        del sys.modules["application.llm.premai"]
    yield
    sys.modules.pop("premai", None)
    if "application.llm.premai" in sys.modules:
        del sys.modules["application.llm.premai"]


@pytest.fixture
def llm():
    from application.llm.premai import PremAILLM

    return PremAILLM(api_key="test-key")


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPremAIConstructor:

    def test_sets_api_key(self, llm):
        assert llm.api_key == "test-key"

    def test_sets_user_api_key_none(self, llm):
        assert llm.user_api_key is None

    def test_client_created(self, llm):
        assert isinstance(llm.client, _FakePrem)

    def test_project_id_from_settings(self, llm):
        from application.core.settings import settings

        assert llm.project_id == settings.PREMAI_PROJECT_ID


# ---------------------------------------------------------------------------
# _raw_gen
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGen:

    def test_returns_content(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        result = llm._raw_gen(llm, model="model-1", messages=msgs)
        assert result == "result_text"

    def test_passes_model_and_project_id(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        llm._raw_gen(llm, model="my-model", messages=msgs)
        kwargs = llm.client.chat.completions.last_kwargs
        assert kwargs["model"] == "my-model"
        assert kwargs["project_id"] == llm.project_id
        assert kwargs["stream"] is False

    def test_passes_messages(self, llm):
        msgs = [{"role": "user", "content": "hello"}]
        llm._raw_gen(llm, model="m", messages=msgs)
        kwargs = llm.client.chat.completions.last_kwargs
        assert kwargs["messages"] == msgs

    def test_extra_kwargs_forwarded(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        llm._raw_gen(llm, model="m", messages=msgs, temperature=0.5)
        kwargs = llm.client.chat.completions.last_kwargs
        assert kwargs["temperature"] == 0.5


# ---------------------------------------------------------------------------
# _raw_gen_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGenStream:

    def test_yields_non_none_content(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(
            llm._raw_gen_stream(llm, model="m", messages=msgs, stream=True)
        )
        assert chunks == ["chunk1", "chunk2"]

    def test_filters_none_content(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(
            llm._raw_gen_stream(llm, model="m", messages=msgs, stream=True)
        )
        assert None not in chunks

    def test_passes_stream_true(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        list(llm._raw_gen_stream(llm, model="m", messages=msgs))
        kwargs = llm.client.chat.completions.last_kwargs
        assert kwargs["stream"] is True

    def test_passes_extra_kwargs(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        list(
            llm._raw_gen_stream(
                llm, model="m", messages=msgs, max_tokens=100
            )
        )
        kwargs = llm.client.chat.completions.last_kwargs
        assert kwargs["max_tokens"] == 100
