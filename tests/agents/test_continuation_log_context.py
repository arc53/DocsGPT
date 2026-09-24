"""A tool continuation stamps its log lines like the turn it resumes."""

from unittest.mock import Mock

import pytest

from docsgpt.core import log_context


def _agent(seen):
    from docsgpt.agents.classic_agent import ClassicAgent

    def _model_call(*_args, **_kwargs):
        seen.append(dict(log_context.snapshot()))
        return iter(["Answer"])

    llm = Mock()
    llm._supports_tools = True
    llm._supports_structured_output = Mock(return_value=False)
    llm.__class__.__name__ = "MockLLM"
    llm.gen_stream = Mock(side_effect=_model_call)
    llm.gen = Mock(side_effect=_model_call)

    handler = Mock()
    handler.process_message_flow = Mock(return_value=iter([]))
    handler.create_tool_message = Mock(return_value={"role": "tool", "tool_call_id": "c1", "content": "r"})

    executor = Mock()
    executor.tool_calls = []
    executor.prepare_tools_for_llm = Mock(return_value=[])
    executor.get_truncated_tool_calls = Mock(return_value=[])

    def _execute(_tools, _call, _llm_class):
        yield {"type": "tool_call", "data": {"status": "pending"}}
        return ("result", "c1")

    executor.execute = Mock(side_effect=_execute)
    return ClassicAgent(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4",
        api_key="test",
        agent_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        decoded_token={"sub": "user-cont"},
        llm=llm,
        llm_handler=handler,
        tool_executor=executor,
    )


def _resume(agent):
    pending = [
        {
            "call_id": "c1",
            "name": "search_0",
            "tool_name": "search",
            "tool_id": "0",
            "action_name": "search",
            "arguments": {"q": "x"},
            "pause_type": "requires_client_execution",
            "thought_signature": None,
        }
    ]
    actions = [{"call_id": "c1", "decision": "approved"}]
    return list(agent.gen_continuation([{"role": "system", "content": "s"}], {"0": {"name": "search"}}, pending, actions))


@pytest.mark.unit
def test_model_calls_in_a_continuation_carry_the_turns_identity():
    seen = []
    _resume(_agent(seen))

    assert seen, "the continuation should hand back to the model"
    assert seen[0]["user_id"] == "user-cont"
    assert seen[0]["agent_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert seen[0]["endpoint"] == "stream"
    assert "activity_id" not in seen[0], "a continuation is not an activity of its own"


@pytest.mark.unit
def test_the_binding_does_not_outlive_the_continuation():
    _resume(_agent([]))

    assert "user_id" not in log_context.snapshot()


@pytest.mark.unit
def test_an_enclosing_activity_keeps_its_id():
    seen = []
    token = log_context.bind(activity_id="act-1")
    try:
        _resume(_agent(seen))
    finally:
        log_context.reset(token)

    assert seen[0]["activity_id"] == "act-1"
    assert seen[0]["user_id"] == "user-cont"
