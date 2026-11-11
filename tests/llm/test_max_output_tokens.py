"""A model's YAML ``max_output_tokens`` caps each request, and a length stop with no answer falls back."""

import types
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from docsgpt.core.model_settings import ModelCapabilities
from docsgpt.llm.base import BaseLLM
from docsgpt.llm.deadlines import StreamNoAnswerError


class StubLLM(BaseLLM):
    def _raw_gen(self, *args, **kwargs):
        return "answer"

    def _raw_gen_stream(self, *args, **kwargs):
        yield "backup answer"


def stream(llm, body):
    return llm._stream_with_fallback(body, "_raw_gen_stream", [], model="m", messages=[])


def _length_stop(llm, *chunks):
    """A provider stream that yields ``chunks`` and then reports a length stop."""

    def body():
        llm._last_finish_reason = None
        llm._stream_reached_finish = False
        yield from chunks
        llm._stream_reached_finish = True
        llm._last_finish_reason = "length"

    return body


# ── YAML ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_yaml_max_output_tokens_reaches_the_capabilities(tmp_path):
    from docsgpt.core.model_yaml import load_model_yamls

    (tmp_path / "test.yaml").write_text(
        "provider: openai\ndefaults:\n  max_output_tokens: 8192\nmodels:\n"
        "  - id: capped\n    max_output_tokens: 32768\n  - id: inherits\n  - id: other\n"
    )
    models = {m.id: m for m in load_model_yamls([tmp_path])[0].models}
    assert models["capped"].capabilities.max_output_tokens == 32768
    assert models["inherits"].capabilities.max_output_tokens == 8192


@pytest.mark.unit
def test_yaml_without_max_output_tokens_leaves_it_unset(tmp_path):
    from docsgpt.core.model_yaml import load_model_yamls

    (tmp_path / "test.yaml").write_text("provider: openai\nmodels:\n  - id: plain\n")
    assert load_model_yamls([tmp_path])[0].models[0].capabilities.max_output_tokens is None


@pytest.mark.unit
@pytest.mark.parametrize("value", [0, -5])
def test_yaml_rejects_a_non_positive_cap(tmp_path, value):
    from docsgpt.core.model_yaml import load_model_yamls

    (tmp_path / "test.yaml").write_text(f"provider: openai\nmodels:\n  - id: bad\n    max_output_tokens: {value}\n")
    with pytest.raises((ValidationError, ValueError)):
        load_model_yamls([tmp_path])


# ── the cap itself ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cap", "requested", "expected"),
    [
        (None, None, None),
        (None, 500, 500),
        (32768, None, 32768),
        (32768, 2000, 2000),
        (32768, 100000, 32768),
    ],
)
def test_a_request_never_exceeds_the_model_cap(cap, requested, expected):
    llm = StubLLM(capabilities=ModelCapabilities(max_output_tokens=cap))
    assert llm._capped_output_tokens(requested) == expected


@pytest.mark.unit
def test_a_cap_that_is_not_a_positive_int_is_ignored():
    llm = StubLLM(capabilities=MagicMock())
    assert llm._capped_output_tokens(700) == 700
    assert StubLLM()._capped_output_tokens(None) is None


# ── OpenAI chat completions ─────────────────────────────────────────────────


class _ChatCompletions:
    def __init__(self):
        self.sent = None

    def create(self, **kwargs):
        self.sent = kwargs
        if kwargs.get("stream"):
            return iter(())
        message = types.SimpleNamespace(content="ok", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=None)


def _openai_llm(capabilities):
    from docsgpt.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="sk-test")
    llm.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_ChatCompletions()))
    llm.capabilities = capabilities
    return llm


MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.mark.unit
@pytest.mark.parametrize("streaming", [False, True])
def test_chat_request_carries_the_cap(streaming):
    llm = _openai_llm(ModelCapabilities(max_output_tokens=32768))
    if streaming:
        list(llm._raw_gen_stream(llm, model="m", messages=MESSAGES))
    else:
        llm._raw_gen(llm, model="m", messages=MESSAGES)
    sent = llm.client.chat.completions.sent
    assert sent["max_completion_tokens"] == 32768
    assert "max_tokens" not in sent


@pytest.mark.unit
@pytest.mark.parametrize("streaming", [False, True])
def test_chat_request_without_a_cap_is_unchanged(streaming):
    llm = _openai_llm(ModelCapabilities())
    if streaming:
        list(llm._raw_gen_stream(llm, model="m", messages=MESSAGES))
    else:
        llm._raw_gen(llm, model="m", messages=MESSAGES)
    sent = llm.client.chat.completions.sent
    assert "max_completion_tokens" not in sent
    assert "max_tokens" not in sent


@pytest.mark.unit
def test_chat_request_keeps_a_lower_explicit_limit_and_lowers_a_higher_one():
    llm = _openai_llm(ModelCapabilities(max_output_tokens=32768))
    llm._raw_gen(llm, model="m", messages=MESSAGES, max_tokens=2000)
    assert llm.client.chat.completions.sent["max_completion_tokens"] == 2000
    llm._raw_gen(llm, model="m", messages=MESSAGES, max_completion_tokens=100000)
    assert llm.client.chat.completions.sent["max_completion_tokens"] == 32768


# ── OpenAI Responses ────────────────────────────────────────────────────────


def _responses_llm(monkeypatch, **caps):
    monkeypatch.setattr("docsgpt.llm.openai.OpenAI", MagicMock())
    monkeypatch.setattr(
        "docsgpt.llm.openai.StorageCreator", types.SimpleNamespace(get_storage=lambda: None)
    )
    monkeypatch.setattr(
        "docsgpt.llm.openai.settings",
        types.SimpleNamespace(
            OPENAI_API_KEY="k",
            API_KEY="k",
            OPENAI_BASE_URL="",
            AZURE_DEPLOYMENT_NAME="dep",
            OPENAI_RESPONSES_STORE=False,
            OPENAI_REASONING_SUMMARY="auto",
            OPENAI_RESPONSES_TRUNCATION_AUTO=False,
            OPENAI_PROMPT_CACHE_KEY=False,
            OPENAI_PROMPT_CACHE_RETENTION=None,
        ),
    )
    from docsgpt.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = ModelCapabilities(api_flavor="responses", **caps)
    llm.client.responses.create = MagicMock(return_value=[])
    return llm


@pytest.mark.unit
def test_responses_request_carries_the_cap(monkeypatch):
    llm = _responses_llm(monkeypatch, max_output_tokens=32768)
    list(llm._raw_gen_stream(llm, model="gpt-5.5", messages=MESSAGES))
    sent = llm.client.responses.create.call_args.kwargs
    assert sent["max_output_tokens"] == 32768
    assert "max_completion_tokens" not in sent


@pytest.mark.unit
def test_responses_request_without_a_cap_is_unchanged(monkeypatch):
    llm = _responses_llm(monkeypatch)
    list(llm._raw_gen_stream(llm, model="gpt-5.5", messages=MESSAGES))
    assert "max_output_tokens" not in llm.client.responses.create.call_args.kwargs


# ── a length stop with no answer ────────────────────────────────────────────


@pytest.mark.unit
def test_length_stop_with_only_reasoning_falls_back(caplog):
    llm = StubLLM(model_id="thinker", capabilities=ModelCapabilities(max_output_tokens=64))
    llm._fallback_llm = StubLLM(model_id="backup")
    body = _length_stop(llm, {"type": "thought", "thought": "step 1"}, {"type": "thought", "thought": "step 2"})
    with caplog.at_level("WARNING", logger="docsgpt.llm.base"):
        chunks = list(stream(llm, body))
    assert chunks[-1] == "backup answer"
    assert all(isinstance(c, dict) and c["type"] == "thought" for c in chunks[:-1])
    assert llm.answered_by[-1] == {
        "model": "backup",
        "provider": "unknown",
        "fallback": True,
        "reason": "StreamLengthNoAnswerError",
    }
    assert "reason=length_no_answer" in caplog.text


@pytest.mark.unit
def test_length_stop_with_no_output_at_all_falls_back():
    llm = StubLLM()
    llm._fallback_llm = StubLLM(model_id="backup")
    assert list(stream(llm, _length_stop(llm))) == ["backup answer"]


@pytest.mark.unit
def test_length_stop_without_a_fallback_fails_as_no_answer():
    from docsgpt.error import user_facing_error
    from docsgpt.llm.deadlines import StreamLengthNoAnswerError

    llm = StubLLM()
    with pytest.raises(StreamLengthNoAnswerError) as raised:
        list(stream(llm, _length_stop(llm, {"type": "thought", "thought": "step"})))
    assert isinstance(raised.value, StreamNoAnswerError)
    # The finish signal belonged to an empty answer: the handler must not take the error for a trailing frame.
    assert llm._stream_reached_finish is False
    assert user_facing_error(raised.value).code == "no_answer"


@pytest.mark.unit
def test_length_stop_after_answer_text_keeps_the_partial_answer():
    llm = StubLLM()
    llm._fallback_llm = backup = MagicMock()
    chunks = list(stream(llm, _length_stop(llm, {"type": "thought", "thought": "plan"}, "partial")))
    assert chunks[-1] == "partial"
    backup._raw_gen_stream.assert_not_called()


@pytest.mark.unit
def test_responses_length_marker_alone_is_not_an_answer(monkeypatch):
    llm = _responses_llm(monkeypatch, max_output_tokens=64)
    llm.client.responses.create = MagicMock(
        return_value=[
            types.SimpleNamespace(type="response.reasoning_summary_text.delta", delta="thinking"),
            types.SimpleNamespace(
                type="response.incomplete",
                response=types.SimpleNamespace(
                    id="resp_1", usage=None, incomplete_details=types.SimpleNamespace(reason="max_output_tokens")
                ),
            ),
        ]
    )
    llm._fallback_llm = StubLLM(model_id="backup")
    chunks = list(stream(llm, lambda: llm._raw_gen_stream(llm, model="gpt-5.5", messages=MESSAGES)))
    assert chunks[-1] == "backup answer"
    assert llm.answered_by[-1]["fallback"] is True


@pytest.mark.unit
def test_chat_stream_length_stop_with_only_reasoning_falls_back():
    llm = _openai_llm(ModelCapabilities(max_output_tokens=64))

    def line(reasoning=None, finish_reason=None):
        delta = types.SimpleNamespace(content=None, reasoning_content=reasoning, tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(delta=delta, finish_reason=finish_reason)], usage=None
        )

    llm.client.chat.completions.create = lambda **kw: iter([line("thinking"), line(finish_reason="length")])
    llm._fallback_llm = StubLLM(model_id="backup")
    chunks = list(stream(llm, lambda: llm._raw_gen_stream(llm, model="m", messages=MESSAGES)))
    assert chunks == [{"type": "thought", "thought": "thinking"}, "backup answer"]
