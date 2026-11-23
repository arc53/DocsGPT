"""``collect_stream``: one whole ``gen_stream`` read into the answer a non-streaming call returns."""

from types import SimpleNamespace

import pytest

from docsgpt.llm.handlers.base import collect_stream, LLMResponse, ToolCall


def _parsed(tool_calls=(), content="", finish_reason="", reasoning=""):
    """What a handler's ``parse_response`` returns for one chunk."""
    return LLMResponse(content=content, tool_calls=list(tool_calls), finish_reason=finish_reason,
                       raw_response=None, reasoning_content=reasoning)


def _parse(chunk):
    """Chunks in these tests are already parsed."""
    return chunk


def test_text_and_thoughts_are_joined():
    chunks = [{"type": "thought", "thought": "Let me "}, {"type": "thought", "thought": "think."},
              "Hello ", "world"]

    answer = collect_stream(chunks, _parse)

    assert answer.content == "Hello world"
    assert answer.reasoning_content == "Let me think."
    assert answer.tool_calls == []
    assert answer.finish_reason == "stop"


def test_argument_deltas_of_one_index_are_concatenated():
    chunks = [
        _parsed([ToolCall(id="call_1", name="submit_proposal", arguments='{"fields": ', index=0)]),
        _parsed([ToolCall(id="", name="", arguments='{"name": "Shipping"}}', index=0)]),
        _parsed(finish_reason="tool_calls"),
    ]

    answer = collect_stream(chunks, _parse)

    assert [(c.id, c.name, c.arguments) for c in answer.tool_calls] == [
        ("call_1", "submit_proposal", '{"fields": {"name": "Shipping"}}')
    ]
    assert answer.finish_reason == "tool_calls"


def test_complete_index_less_calls_stay_separate():
    chunks = [
        _parsed([ToolCall(id="a", name="read_prompt", arguments={"id": "p1"})]),
        _parsed([ToolCall(id="b", name="read_prompt", arguments={"id": "p2"})]),
    ]

    answer = collect_stream(chunks, _parse)

    assert [c.arguments for c in answer.tool_calls] == [{"id": "p1"}, {"id": "p2"}]


def test_a_restated_payload_replaces_rather_than_appends():
    chunks = [
        _parsed([ToolCall(id="call_1", name="ask_user", arguments='{"questions": []}', index=0)]),
        _parsed([ToolCall(id="", name="", arguments='{"questions": []}', index=0)]),
    ]

    answer = collect_stream(chunks, _parse)

    assert answer.tool_calls[0].arguments == '{"questions": []}'


def test_reasoning_on_a_parsed_chunk_is_kept():
    chunks = [_parsed([ToolCall(id="c", name="ask_user", arguments="{}", index=0)], reasoning="Because.")]

    assert collect_stream(chunks, _parse).reasoning_content == "Because."


def test_content_on_a_parsed_chunk_is_kept():
    assert collect_stream([_parsed(content="Hi")], _parse).content == "Hi"


def _failing(chunks, error):
    yield from chunks
    raise error


def test_a_failure_before_the_finish_is_raised():
    with pytest.raises(ConnectionError):
        collect_stream(_failing(["Hel"], ConnectionError("reset")), _parse)


def test_a_failure_after_a_tool_call_finish_keeps_the_answer():
    chunks = [_parsed([ToolCall(id="c", name="ask_user", arguments="{}", index=0)]),
              _parsed(finish_reason="tool_calls")]

    answer = collect_stream(_failing(chunks, ConnectionError("trailing frame")), _parse)

    assert [c.name for c in answer.tool_calls] == ["ask_user"]


def test_a_failure_after_the_provider_finished_keeps_the_answer():
    answer = collect_stream(_failing(["Done."], ConnectionError("trailing frame")), _parse,
                            finished=lambda: True)

    assert answer.content == "Done."


def test_the_stream_is_closed_when_reading_stops_early():
    closed = SimpleNamespace(value=False)

    def stream():
        try:
            yield "a"
            raise KeyError("boom")
        finally:
            closed.value = True

    with pytest.raises(KeyError):
        collect_stream(stream(), _parse)
    assert closed.value
