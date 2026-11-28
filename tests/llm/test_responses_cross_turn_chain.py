"""A turn chained onto the previous turn's answer sends no stale tool outputs.

Product ledger #89 / error ledger #94: a turn that compressed its context
mid-turn restarts the provider's stored transcript, so the transcript behind its
final answer no longer holds the turn's earlier tool calls (nor the rounds a
fallback model answered). The next turn replayed that turn in full and the trim
re-sent every one of its tool outputs as a bare ``function_call_output``; the
provider refused the first output whose call it did not hold ("No tool call
found for function call output"), and the turn fell back to another model.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.llm.test_openai_responses import _make_llm, _ns, _responses_caps


def _call(call_id: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": "read_record", "arguments": "{}"}}


def _replayed_tool_turn() -> list[dict]:
    """The previous turn as the next one replays it: two tool rounds, then the answer."""
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "read the records"},
        {"role": "assistant", "content": None, "tool_calls": [_call("call_pre")]},
        {"role": "tool", "tool_call_id": "call_pre", "content": "record 1"},
        {"role": "assistant", "content": None, "tool_calls": [_call("chatcmpl-tool-k1"), _call("call_post")]},
        {"role": "tool", "tool_call_id": "chatcmpl-tool-k1", "content": "record 2"},
        {"role": "tool", "tool_call_id": "call_post", "content": "record 3"},
        {"role": "assistant", "content": "Here is the table."},
        {"role": "user", "content": "now compare them"},
    ]


def _outputs(items: list[dict]) -> list[str]:
    return [item["call_id"] for item in items if item.get("type") == "function_call_output"]


@pytest.mark.unit
def test_trim_after_a_finished_answer_carries_no_tool_outputs(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)

    trimmed = llm._trim_for_previous_response(_replayed_tool_turn())

    assert trimmed == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "now compare them"},
    ]


@pytest.mark.unit
def test_chained_turn_start_sends_only_the_new_question(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)

    items, chained = llm._build_responses_input(_replayed_tool_turn(), "resp_answer")

    assert chained == "resp_answer"
    assert _outputs(items) == []
    assert [item.get("role") for item in items] == ["system", "user"]


@pytest.mark.unit
def test_known_empty_call_ids_drop_stray_outputs(monkeypatch):
    """The agent seeds the answered response's call ids (none) at turn start;
    the coverage guard then drops any output that response never asked for."""
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    llm._last_response_call_ids = set()
    llm._chain_call_ids_known = True
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "call_stray", "content": "late"},
        {"role": "user", "content": "next"},
    ]

    items, chained = llm._build_responses_input(messages, "resp_answer")

    assert chained == "resp_answer"
    assert _outputs(items) == []


@pytest.mark.unit
def test_unknown_call_ids_leave_the_guard_inert(monkeypatch):
    """Rows persisted before ``call_ids`` existed: nothing is known, nothing dropped."""
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "call_x", "content": "r"},
        {"role": "user", "content": "next"},
    ]

    items, _ = llm._build_responses_input(messages, "resp_prev")

    assert _outputs(items) == ["call_x"]


@pytest.mark.unit
def test_a_request_in_flight_forgets_whether_the_call_ids_were_known(monkeypatch):
    """After a failed call the guard must not filter against a response it never got."""
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    llm._chain_call_ids_known = True
    llm.client.responses.create = MagicMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        llm._responses_gen("m", [{"role": "user", "content": "hi"}], previous_response_id="resp_prev")

    assert llm._chain_call_ids_known is False


@pytest.mark.unit
def test_recorded_and_imported_call_ids_are_known(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    llm._record_responses_metadata(_ns(id="resp_1", usage=None, output=[]))
    assert llm._chain_call_ids_known is True

    llm.start_responses_turn()
    assert llm._chain_call_ids_known is False

    state = llm.export_responses_state()
    other = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    assert other.import_responses_state(state) is True
    assert other._chain_call_ids_known is True
    assert other.import_responses_state({**state, "call_ids": None}) is True
    legacy = {key: value for key, value in state.items() if key != "call_ids"}
    assert other.import_responses_state(legacy) is True
    assert other._chain_call_ids_known is False


class _RejectChainThenAccept:
    """``responses.create`` that refuses the chained request and takes the unchained one."""

    def __init__(self, result, message="Error code: 400 - No tool call found for function call output with call_id x."):
        self.result = result
        self.message = message
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("previous_response_id"):
            raise RuntimeError(self.message)
        return self.result


def _completed(text: str):
    return [
        _ns(type="response.output_text.delta", delta=text),
        _ns(type="response.completed", response=_ns(id="resp_new", usage=None, output=[])),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "message",
    [
        "Error code: 400 - No tool call found for function call output with call_id call_pre.",
        "Error code: 400 - No tool output found for function call call_9.",
        "Error code: 400 - Previous response with id 'resp_x' not found.",
    ],
)
def test_a_rejected_chain_is_retried_unchained_on_the_same_model(monkeypatch, message):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    llm._chain_turn_tracked = True
    create = _RejectChainThenAccept(_completed("answer"), message)
    llm.client.responses.create = create

    chunks = list(
        llm._raw_gen_stream(llm, "m", _replayed_tool_turn(), previous_response_id="resp_answer")
    )

    assert chunks == ["answer"]
    assert [bool(call.get("previous_response_id")) for call in create.calls] == [True, False]
    # The unchained retry carries the whole history, every call paired with its output.
    retry_items = create.calls[1]["input"]
    calls = [item["call_id"] for item in retry_items if item.get("type") == "function_call"]
    assert calls == ["call_pre", "chatcmpl-tool-k1", "call_post"]
    assert _outputs(retry_items) == calls
    assert llm._chain_reset_reason in ("chain_rejected", "not_found")


@pytest.mark.unit
def test_non_streaming_rejected_chain_is_retried_unchained(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    response = _ns(
        id="resp_new",
        usage=None,
        output=[_ns(type="message", content=[_ns(type="output_text", text="answer")])],
    )
    create = _RejectChainThenAccept(response)
    llm.client.responses.create = create

    result = llm._raw_gen(llm, "m", _replayed_tool_turn(), stream=False, previous_response_id="resp_answer")

    assert result == "answer"
    assert [bool(call.get("previous_response_id")) for call in create.calls] == [True, False]


@pytest.mark.unit
def test_other_errors_and_unchained_requests_are_not_retried(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    create = MagicMock(side_effect=RuntimeError("Error code: 500 - upstream"))
    llm.client.responses.create = create
    with pytest.raises(RuntimeError):
        list(llm._raw_gen_stream(llm, "m", _replayed_tool_turn(), previous_response_id="resp_answer"))
    assert create.call_count == 1

    # Unchained already: a rejection naming a call cannot be cured by unchaining.
    create = MagicMock(side_effect=RuntimeError("No tool call found for function call output with call_id x"))
    llm.client.responses.create = create
    with pytest.raises(RuntimeError):
        list(llm._raw_gen_stream(llm, "m", [{"role": "user", "content": "hi"}]))
    assert create.call_count == 1


@pytest.mark.unit
def test_a_rejection_after_output_was_streamed_is_not_retried(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)

    def stream(**kwargs):
        def events():
            yield _ns(type="response.output_text.delta", delta="partial")
            raise RuntimeError("Previous response with id 'resp_x' not found.")

        return events()

    create = MagicMock(side_effect=stream)
    llm.client.responses.create = create

    out = []
    with pytest.raises(RuntimeError):
        for chunk in llm._raw_gen_stream(llm, "m", _replayed_tool_turn(), previous_response_id="resp_answer"):
            out.append(chunk)
    assert out == ["partial"]
    assert create.call_count == 1


@pytest.mark.unit
def test_an_abandoned_read_does_not_reset_the_chain(monkeypatch):
    """A rejection that lands after the consumer gave up (a stalled first token)
    must not touch the chain state the next call relies on."""
    from docsgpt.llm import deadlines

    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    create = _RejectChainThenAccept(_completed("answer"))
    llm.client.responses.create = create
    state = deadlines._ReaderState()
    state.done.set()
    token = deadlines._reader.set(state)
    try:
        with pytest.raises(deadlines.StreamAbandoned):
            list(llm._raw_gen_stream(llm, "m", _replayed_tool_turn(), previous_response_id="resp_answer"))
    finally:
        deadlines._reader.reset(token)

    assert len(create.calls) == 1
    assert llm._request_chained is True
    assert llm._chain_reset_hint is None
