"""End-to-end smoke tests for AnthropicLLM against the Messages API.

Narrower than test_anthropic.py: these pin the request shape and the
streaming contract a caller sees, not the individual mapping rules.
"""

import sys
import types

import pytest


class _FakeUsage:
    def __init__(self, input_tokens=0, output_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class _FakeStream:
    def __init__(self, events):
        self._events = list(events)
        self.closed = False

    def __iter__(self):
        return iter(self._events)

    def close(self):
        self.closed = True


def _text_delta(text):
    return types.SimpleNamespace(
        type="content_block_delta",
        index=0,
        delta=types.SimpleNamespace(type="text_delta", text=text),
    )


class _FakeMessages:
    def __init__(self):
        self.last_kwargs = None
        self._stream = [
            _text_delta("s1"),
            _text_delta("s2"),
            types.SimpleNamespace(
                type="message_delta",
                delta=types.SimpleNamespace(stop_reason="end_turn"),
                usage=_FakeUsage(output_tokens=2),
            ),
        ]

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            return _FakeStream(self._stream)
        return types.SimpleNamespace(
            type="message",
            role="assistant",
            content=[types.SimpleNamespace(type="text", text="final")],
            stop_reason="end_turn",
            usage=_FakeUsage(7, 3),
        )


class _FakeAnthropic:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url
        self.messages = _FakeMessages()


@pytest.fixture(autouse=True)
def patch_anthropic():
    fake = types.ModuleType("anthropic")
    fake.Anthropic = _FakeAnthropic

    modules_to_remove = [key for key in sys.modules if key.startswith("anthropic")]
    for key in modules_to_remove:
        sys.modules.pop(key, None)
    sys.modules["anthropic"] = fake

    if "application.llm.anthropic" in sys.modules:
        del sys.modules["application.llm.anthropic"]
    yield

    sys.modules.pop("anthropic", None)
    if "application.llm.anthropic" in sys.modules:
        del sys.modules["application.llm.anthropic"]


def test_anthropic_raw_gen_uses_messages_api_and_returns_text():
    from application.llm.anthropic import AnthropicLLM

    llm = AnthropicLLM(api_key="k")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]
    out = llm._raw_gen(llm, model="claude-x", messages=msgs, stream=False, max_tokens=55)

    assert out == "final"
    last = llm.anthropic.messages.last_kwargs
    assert last["model"] == "claude-x"
    assert last["max_tokens"] == 55
    assert last["system"] == "sys"
    assert last["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "q"}]}
    ]
    # The retired Text Completions parameters are gone.
    assert "prompt" not in last
    assert "max_tokens_to_sample" not in last


def test_anthropic_raw_gen_stream_yields_text_chunks():
    from application.llm.anthropic import AnthropicLLM

    llm = AnthropicLLM(api_key="k")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]
    chunks = list(
        llm._raw_gen_stream(llm, model="claude", messages=msgs, stream=True, max_tokens=10)
    )

    assert [c for c in chunks if isinstance(c, str)] == ["s1", "s2"]
    assert llm.anthropic.messages.last_kwargs["stream"] is True
