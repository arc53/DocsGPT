import types

import pytest
from application.llm.openai import OpenAILLM


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
                choices=[FakeChatCompletions._Choice(content="hello world")]
            )
        return FakeChatCompletions._Response(
            lines=[
                FakeChatCompletions._StreamLine(["part1"]),
                FakeChatCompletions._StreamLine(["part2"]),
            ]
        )


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())


@pytest.fixture
def openai_llm(monkeypatch):
    llm = OpenAILLM(api_key="sk-test", user_api_key=None)
    llm.storage = types.SimpleNamespace(
        get_file=lambda path: types.SimpleNamespace(read=lambda: b"img"),
        file_exists=lambda path: True,
        process_file=lambda path, processor_func, **kwargs: "file_id_123",
    )
    llm.client = FakeClient()
    return llm


@pytest.mark.unit
def test_clean_messages_openai_variants(openai_llm):
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "model", "content": "asst"},
        {
            "role": "user",
            "content": [
                {"text": "hello"},
                {"function_call": {"call_id": "c1", "name": "fn", "args": {"a": 1}}},
                {
                    "function_response": {
                        "call_id": "c1",
                        "name": "fn",
                        "response": {"result": 42},
                    }
                },
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAA"},
                },
            ],
        },
    ]

    cleaned = openai_llm._clean_messages_openai(messages)

    roles = [m["role"] for m in cleaned]
    assert roles.count("assistant") >= 1
    assert any(m["role"] == "tool" for m in cleaned)

    assert any(
        isinstance(m["content"], list)
        and any(
            part.get("type") == "image_url"
            for part in m["content"]
            if isinstance(part, dict)
        )
        for m in cleaned
        if m["role"] == "user"
    )


@pytest.mark.unit
def test_raw_gen_calls_openai_client_and_returns_content(openai_llm):
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    content = openai_llm._raw_gen(
        openai_llm, model="gpt-4o", messages=msgs, stream=False
    )
    assert content == "hello world"

    passed = openai_llm.client.chat.completions.last_kwargs
    assert passed["model"] == "gpt-4o"
    assert isinstance(passed["messages"], list)
    assert passed["stream"] is False


@pytest.mark.unit
def test_raw_gen_stream_yields_chunks(openai_llm):
    msgs = [
        {"role": "user", "content": "hi"},
    ]
    gen = openai_llm._raw_gen_stream(
        openai_llm, model="gpt", messages=msgs, stream=True
    )
    chunks = list(gen)
    assert "part1" in "".join(chunks)
    assert "part2" in "".join(chunks)


@pytest.mark.unit
def test_raw_gen_stream_emits_thought_events(openai_llm):
    msgs = [{"role": "user", "content": "think first"}]

    openai_llm.client.chat.completions.create = lambda **kwargs: FakeChatCompletions._Response(
        lines=[
            FakeChatCompletions._StreamLine(
                [{"reasoning_content": "internal thought"}]
            ),
            FakeChatCompletions._StreamLine([{"content": "final answer"}]),
            FakeChatCompletions._StreamLine([{"finish_reason": "stop"}]),
        ]
    )

    chunks = list(openai_llm._raw_gen_stream(openai_llm, model="gpt", messages=msgs))

    assert {"type": "thought", "thought": "internal thought"} in chunks
    assert "final answer" in chunks


@pytest.mark.unit
def test_raw_gen_stream_keeps_prefix_like_text_as_answer(openai_llm):
    msgs = [{"role": "user", "content": "return literal marker"}]
    prefixed_answer = "[[DOCSGPT_OPENAI_REASONING]]this is answer text"

    openai_llm.client.chat.completions.create = lambda **kwargs: FakeChatCompletions._Response(
        lines=[
            FakeChatCompletions._StreamLine([{"content": prefixed_answer}]),
            FakeChatCompletions._StreamLine([{"finish_reason": "stop"}]),
        ]
    )

    chunks = list(openai_llm._raw_gen_stream(openai_llm, model="gpt", messages=msgs))

    assert prefixed_answer in chunks
    assert not any(isinstance(chunk, dict) and chunk.get("type") == "thought" for chunk in chunks)


@pytest.mark.unit
def test_prepare_structured_output_format_enforces_required_and_strict(openai_llm):
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "number"},
        },
    }
    result = openai_llm.prepare_structured_output_format(schema)
    assert result["type"] == "json_schema"
    js = result["json_schema"]
    assert js["strict"] is True
    assert set(js["schema"]["required"]) == {"a", "b"}
    assert js["schema"]["additionalProperties"] is False


@pytest.mark.unit
def test_prepare_messages_with_attachments_image_and_pdf(openai_llm, monkeypatch):
    monkeypatch.setattr(openai_llm, "_get_base64_image", lambda att: "AAA=")
    monkeypatch.setattr(openai_llm, "_upload_file_to_openai", lambda att: "file_xyz")

    messages = [{"role": "user", "content": "Hi"}]
    attachments = [
        {"path": "/tmp/img.png", "mime_type": "image/png"},
        {"path": "/tmp/doc.pdf", "mime_type": "application/pdf"},
    ]
    out = openai_llm.prepare_messages_with_attachments(messages, attachments)

    user_msg = next(m for m in out if m["role"] == "user")
    assert isinstance(user_msg["content"], list)
    types_in_content = [
        p.get("type") for p in user_msg["content"] if isinstance(p, dict)
    ]
    assert "image_url" in types_in_content or any(
        isinstance(p, dict) and p.get("image_url") for p in user_msg["content"]
    )
    assert any(
        isinstance(p, dict) and p.get("file", {}).get("file_id") == "file_xyz"
        for p in user_msg["content"]
    )
