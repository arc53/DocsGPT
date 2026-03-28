import types

import pytest
from application.llm.minimax import MiniMaxLLM


class FakeChatCompletions:
    def __init__(self):
        self.last_kwargs = None

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
            self.message = FakeChatCompletions._Msg(content=content)
            self.delta = FakeChatCompletions._Delta(
                content=delta,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
            )
            self.finish_reason = finish_reason

    class _StreamLine:
        def __init__(self, deltas):
            choices = []
            for delta in deltas:
                if isinstance(delta, dict):
                    choices.append(
                        FakeChatCompletions._Choice(
                            delta=delta.get("content"),
                            reasoning_content=delta.get("reasoning_content"),
                            tool_calls=delta.get("tool_calls"),
                            finish_reason=delta.get("finish_reason", "stop"),
                        )
                    )
                else:
                    choices.append(FakeChatCompletions._Choice(delta=delta))
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

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if not kwargs.get("stream"):
            return FakeChatCompletions._Response(
                choices=[FakeChatCompletions._Choice(content="hello from minimax")]
            )
        return FakeChatCompletions._Response(
            lines=[
                FakeChatCompletions._StreamLine(["chunk1"]),
                FakeChatCompletions._StreamLine(["chunk2"]),
            ]
        )


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())


@pytest.fixture
def minimax_llm(monkeypatch):
    llm = MiniMaxLLM(api_key="minimax-test-key", user_api_key=None)
    llm.storage = types.SimpleNamespace(
        get_file=lambda path: types.SimpleNamespace(read=lambda: b"img"),
        file_exists=lambda path: True,
        process_file=lambda path, processor_func, **kwargs: "file_id_123",
    )
    llm.client = FakeClient()
    return llm


@pytest.mark.unit
def test_minimax_uses_correct_base_url():
    from application.llm.minimax import MINIMAX_BASE_URL

    assert MINIMAX_BASE_URL == "https://api.minimax.io/v1"


@pytest.mark.unit
def test_raw_gen_returns_content(minimax_llm):
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    content = minimax_llm._raw_gen(
        minimax_llm, model="MiniMax-M2.7", messages=msgs, stream=False
    )
    assert content == "hello from minimax"

    passed = minimax_llm.client.chat.completions.last_kwargs
    assert passed["model"] == "MiniMax-M2.7"
    assert passed["stream"] is False


@pytest.mark.unit
def test_raw_gen_stream_yields_chunks(minimax_llm):
    msgs = [{"role": "user", "content": "hi"}]
    gen = minimax_llm._raw_gen_stream(
        minimax_llm, model="MiniMax-M2.7", messages=msgs, stream=True
    )
    chunks = list(gen)
    assert "chunk1" in "".join(chunks)
    assert "chunk2" in "".join(chunks)


@pytest.mark.unit
def test_temperature_clamped_to_minimum(minimax_llm):
    msgs = [{"role": "user", "content": "test"}]
    minimax_llm._raw_gen(
        minimax_llm,
        model="MiniMax-M2.7",
        messages=msgs,
        stream=False,
        temperature=0,
    )
    passed = minimax_llm.client.chat.completions.last_kwargs
    assert passed["temperature"] == 0.01


@pytest.mark.unit
def test_temperature_clamped_to_maximum(minimax_llm):
    msgs = [{"role": "user", "content": "test"}]
    minimax_llm._raw_gen(
        minimax_llm,
        model="MiniMax-M2.7",
        messages=msgs,
        stream=False,
        temperature=2.0,
    )
    passed = minimax_llm.client.chat.completions.last_kwargs
    assert passed["temperature"] == 1.0


@pytest.mark.unit
def test_valid_temperature_passed_through(minimax_llm):
    msgs = [{"role": "user", "content": "test"}]
    minimax_llm._raw_gen(
        minimax_llm,
        model="MiniMax-M2.7",
        messages=msgs,
        stream=False,
        temperature=0.7,
    )
    passed = minimax_llm.client.chat.completions.last_kwargs
    assert passed["temperature"] == 0.7


@pytest.mark.unit
def test_stream_temperature_clamped(minimax_llm):
    msgs = [{"role": "user", "content": "test"}]
    gen = minimax_llm._raw_gen_stream(
        minimax_llm,
        model="MiniMax-M2.7",
        messages=msgs,
        stream=True,
        temperature=0,
    )
    list(gen)  # consume the generator
    passed = minimax_llm.client.chat.completions.last_kwargs
    assert passed["temperature"] == 0.01


@pytest.mark.unit
def test_response_format_dropped(minimax_llm):
    msgs = [{"role": "user", "content": "test"}]
    minimax_llm._raw_gen(
        minimax_llm,
        model="MiniMax-M2.7",
        messages=msgs,
        stream=False,
        response_format={"type": "json_object"},
    )
    passed = minimax_llm.client.chat.completions.last_kwargs
    assert "response_format" not in passed


@pytest.mark.unit
def test_does_not_support_structured_output(minimax_llm):
    assert minimax_llm._supports_structured_output() is False


@pytest.mark.unit
def test_supports_tools(minimax_llm):
    assert minimax_llm._supports_tools() is True


@pytest.mark.unit
def test_model_list_contains_m27():
    from application.core.model_configs import MINIMAX_MODELS

    model_ids = [m.id for m in MINIMAX_MODELS]
    assert "MiniMax-M2.7" in model_ids
    assert "MiniMax-M2.7-highspeed" in model_ids


@pytest.mark.unit
def test_m27_is_first_in_model_list():
    from application.core.model_configs import MINIMAX_MODELS

    assert MINIMAX_MODELS[0].id == "MiniMax-M2.7"
    assert MINIMAX_MODELS[1].id == "MiniMax-M2.7-highspeed"


@pytest.mark.unit
def test_old_models_still_available():
    from application.core.model_configs import MINIMAX_MODELS

    model_ids = [m.id for m in MINIMAX_MODELS]
    assert "MiniMax-M2.5" in model_ids
    assert "MiniMax-M2.5-highspeed" in model_ids
