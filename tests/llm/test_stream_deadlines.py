"""Stream deadlines bound blocking providers without swallowing worker time limits."""

import threading
import time
from unittest.mock import Mock

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from docsgpt.core.run_budget import RunDeadlineExceeded, run_budget
from docsgpt.core.model_settings import ModelCapabilities
from docsgpt.llm.base import BaseLLM
from docsgpt.llm.deadlines import StreamStalledError


class StubLLM(BaseLLM):
    def _raw_gen(self, *args, **kwargs):
        return "answer"

    def _raw_gen_stream(self, *args, **kwargs):
        yield "answer"


def stream(llm, body):
    return llm._stream_with_fallback(body, "_raw_gen_stream", [], model="m", messages=[])


def test_soft_limit_never_falls_back():
    llm = StubLLM()
    llm._fallback_llm = Mock()

    def body():
        yield "partial"
        raise SoftTimeLimitExceeded()

    output = stream(llm, body)
    assert next(output) == "partial"
    with pytest.raises(SoftTimeLimitExceeded):
        next(output)
    llm._fallback_llm._raw_gen_stream.assert_not_called()


def test_stall_before_output_falls_back():
    release = threading.Event()
    llm = StubLLM(capabilities=ModelCapabilities(first_token_timeout=0.03))
    llm._fallback_llm = StubLLM(model_id="backup")

    def body():
        release.wait(2)
        yield "late"

    try:
        assert list(stream(llm, body)) == ["answer"]
    finally:
        release.set()


def test_stall_after_output_does_not_repeat_it_and_abandoned_stream_does_no_more_work():
    release = threading.Event()
    closed = threading.Event()
    llm = StubLLM(capabilities=ModelCapabilities(stall_timeout=0.03))
    llm._fallback_llm = Mock()

    def body():
        try:
            yield "partial"
            release.wait(2)
            yield "late"
            pytest.fail("abandoned stream advanced again")
        finally:
            closed.set()

    output = stream(llm, body)
    try:
        assert next(output) == "partial"
        with pytest.raises(StreamStalledError):
            next(output)
    finally:
        release.set()
    assert closed.wait(1)
    llm._fallback_llm._raw_gen_stream.assert_not_called()


def test_slow_first_token_uses_model_override(monkeypatch):
    monkeypatch.setattr("docsgpt.llm.base.settings.LLM_FIRST_TOKEN_TIMEOUT", 0.01)
    llm = StubLLM(capabilities=ModelCapabilities(first_token_timeout=0.3, stall_timeout=0.01))

    def body():
        time.sleep(0.04)
        yield "answer"

    assert list(stream(llm, body)) == ["answer"]


def test_budget_caps_stream_and_prevents_fallback():
    release = threading.Event()
    llm = StubLLM()
    llm._fallback_llm = Mock()

    def body():
        release.wait(2)
        yield "late"

    try:
        with run_budget(0.03), pytest.raises(RunDeadlineExceeded):
            list(stream(llm, body))
    finally:
        release.set()
    llm._fallback_llm._raw_gen_stream.assert_not_called()


def test_first_token_timeout_without_fallback():
    release = threading.Event()
    llm = StubLLM(capabilities=ModelCapabilities(first_token_timeout=0.02))

    def body():
        release.wait(2)
        yield "late"

    try:
        with pytest.raises(StreamStalledError):
            list(stream(llm, body))
    finally:
        release.set()


def test_yaml_deadline_overrides_global_default(tmp_path):
    from docsgpt.core.model_yaml import load_model_yamls

    (tmp_path / "test.yaml").write_text(
        "provider: openai\ndefaults:\n  first_token_timeout: 400\nmodels:\n"
        "  - id: slow\n    first_token_timeout: 900\n    stall_timeout: 30\n"
    )
    catalog = load_model_yamls([tmp_path])[0]
    model = catalog.models[0]
    assert model.capabilities.first_token_timeout == 900
    assert model.capabilities.stall_timeout == 30


def test_loop_at_margin_saves_without_starting_another_call(monkeypatch):
    from docsgpt.agents.base import BaseAgent
    from docsgpt.core import run_budget as budgets
    from types import SimpleNamespace

    clock = [0.0]
    monkeypatch.setattr(budgets, "monotonic", lambda: clock[0])
    agent = SimpleNamespace(tool_executor=SimpleNamespace(message_id=None))
    agent.bind_guardrail_log_context = lambda ctx: None
    agent.apply_input_guardrails = lambda q: (q, None)
    calls = []

    def gen(query, context):
        yield {"answer": "Progress"}
        clock[0] = 95
        budgets.check_round()
        calls.append("next LLM")

    agent._gen_inner = gen
    agent._get_truncated_tool_calls = lambda: [{"call_id": "done"}]
    # The last response may hold unanswered calls; chaining onto it would 400.
    agent._emit_responses_metadata = lambda: iter([{"metadata": {"response_id": "resp_unanswered"}}])
    with budgets.run_budget(100, margin=10):
        events = list(BaseAgent.gen.__wrapped__(agent, "q"))
    assert calls == []
    assert events[-1] == {"metadata": {"budget_deferred": True}}
    assert events[0] == {"answer": "Progress"}


def test_round_that_overran_its_deadline_defers_at_the_next_boundary(monkeypatch):
    from docsgpt.core import run_budget as budgets

    clock = [0.0]
    monkeypatch.setattr(budgets, "monotonic", lambda: clock[0])
    with budgets.run_budget(100, margin=10):
        clock[0] = 150  # a slow tool ran past the deadline
        with pytest.raises(budgets.RoundDeferred):
            budgets.check_round()


def test_cancel_key_stops_before_tool_execution(monkeypatch):
    from docsgpt.activity import flags
    from docsgpt.agents.tool_executor import ToolExecutor
    from docsgpt.core.run_budget import StreamCancelled
    from types import SimpleNamespace

    client = Mock()
    client.exists.return_value = True
    monkeypatch.setattr(flags, "_stop_redis", lambda: client)
    executor = SimpleNamespace(message_id="old", _execute=Mock())
    with pytest.raises(StreamCancelled):
        list(ToolExecutor.execute(executor, {}, Mock(), "llm"))
    executor._execute.assert_not_called()
    client.exists.assert_called_once_with("stream_cancel:old")


def test_shared_tool_loop_does_not_recover_a_soft_limit():
    from types import SimpleNamespace
    from docsgpt.llm.handlers.openai import OpenAILLMHandler
    from docsgpt.llm.handlers.base import ToolCall

    def execute(*args):
        raise SoftTimeLimitExceeded()
        yield

    agent = SimpleNamespace(
        llm=Mock(),
        _execute_tool_action=Mock(side_effect=execute),
        tool_executor=Mock(check_pause=Mock(return_value=None)),
    )
    handler = OpenAILLMHandler()
    with pytest.raises(SoftTimeLimitExceeded):
        list(handler.handle_tool_calls(agent, [ToolCall(id="c", name="tool", arguments={})], {}, []))
    agent._execute_tool_action.assert_called_once()


def test_deferral_before_input_checks_is_a_successful_round(monkeypatch):
    from types import SimpleNamespace
    from docsgpt.agents.base import BaseAgent
    from docsgpt.core import run_budget as budgets

    clock = [0.0]
    monkeypatch.setattr(budgets, "monotonic", lambda: clock[0])
    agent = SimpleNamespace(
        tool_executor=SimpleNamespace(message_id=None),
        bind_guardrail_log_context=Mock(), apply_input_guardrails=Mock(),
        _get_truncated_tool_calls=lambda: [], _emit_responses_metadata=lambda: iter([]),
    )
    with budgets.run_budget(100, margin=10):
        clock[0] = 95
        events = list(BaseAgent.gen.__wrapped__(agent, "q"))
    assert events[-1] == {"metadata": {"budget_deferred": True}}
    agent.apply_input_guardrails.assert_not_called()
