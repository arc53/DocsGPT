"""A tool that fails after the user approved it is reported to the model, not raised.

The in-loop path (``handle_tool_calls``) already turns a failing tool into an
``Error executing tool: ...`` result. The approval-resume path ran the same
executor without a guard, so one failing MCP action (Stripe's ``stripe_analytics``
without a Sigma subscription) ended the whole answer with a stream error.
"""

from unittest.mock import Mock

import pytest


def _agent(tool_error):
    from docsgpt.agents.classic_agent import ClassicAgent

    llm = Mock()
    llm._supports_tools = True
    llm._supports_structured_output = Mock(return_value=False)
    llm.__class__.__name__ = "MockLLM"
    llm.gen_stream = Mock(side_effect=lambda *_a, **_k: iter(["Answer"]))
    llm.gen = Mock(side_effect=lambda *_a, **_k: iter(["Answer"]))

    handler = Mock()
    handler.process_message_flow = Mock(return_value=iter([]))
    handler.create_tool_message = Mock(
        side_effect=lambda call, content: {"role": "tool", "tool_call_id": call.id, "content": content}
    )

    executor = Mock()
    executor.tool_calls = []
    executor.prepare_tools_for_llm = Mock(return_value=[])
    executor.get_truncated_tool_calls = Mock(return_value=[])

    def _execute(_tools, _call, _llm_class):
        yield {"type": "tool_call", "data": {"status": "pending"}}
        raise tool_error

    executor.execute = Mock(side_effect=_execute)
    agent = ClassicAgent(
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
    return agent, llm, handler


def _resume(agent):
    pending = [
        {
            "call_id": "c1",
            "name": "stripe_analytics_0",
            "llm_name": "stripe_analytics",
            "tool_name": "mcp_tool",
            "tool_id": "0",
            "action_name": "stripe_analytics",
            "arguments": {"query": "revenue"},
            "pause_type": "awaiting_approval",
            "thought_signature": None,
        }
    ]
    actions = [{"call_id": "c1", "decision": "approved"}]
    return list(
        agent.gen_continuation(
            [{"role": "system", "content": "s"}], {"0": {"name": "mcp_tool"}}, pending, actions
        )
    )


@pytest.mark.unit
def test_a_failing_approved_tool_is_handed_to_the_model_as_an_error():
    agent, llm, handler = _agent(Exception("This action requires a Sigma subscription."))

    events = _resume(agent)

    tool_messages = [call.args[1] for call in handler.create_tool_message.call_args_list]
    assert tool_messages == ["Error executing tool: This action requires a Sigma subscription."]
    errors = [e["data"] for e in events if e.get("type") == "tool_call" and e["data"].get("status") == "error"]
    assert errors == [
        {
            "tool_name": "mcp_tool",
            "call_id": "c1",
            "action_name": "stripe_analytics",
            "arguments": {"query": "revenue"},
            "error": "Error executing tool: This action requires a Sigma subscription.",
            "status": "error",
        }
    ]
    assert llm.gen_stream.called or llm.gen.called, "the model should answer after the failed tool"
