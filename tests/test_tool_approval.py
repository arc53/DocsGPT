"""Tests for tool approval (Phase 3).

Covers require_approval flag, check_pause for approval, the handler
pause/resume flow, and gen_continuation with approved/denied actions.
"""

from unittest.mock import Mock

import pytest

from application.agents.tool_executor import ToolExecutor
from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


# ---------------------------------------------------------------------------
# check_pause with require_approval
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPauseApproval:

    def _make_call(self, name="action_0", call_id="c1"):
        call = Mock()
        call.name = name
        call.id = call_id
        call.arguments = "{}"
        call.thought_signature = None
        return call

    def test_approval_required_triggers_pause(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "telegram",
                "actions": [
                    {
                        "name": "send_msg",
                        "active": True,
                        "require_approval": True,
                        "parameters": {},
                    },
                ],
            }
        }
        call = self._make_call(name="send_msg_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")

        assert result is not None
        assert result["pause_type"] == "awaiting_approval"
        assert result["tool_name"] == "telegram"
        assert result["action_name"] == "send_msg"
        assert result["tool_id"] == "0"

    def test_approval_not_required_no_pause(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "brave",
                "actions": [
                    {
                        "name": "search",
                        "active": True,
                        "require_approval": False,
                        "parameters": {},
                    },
                ],
            }
        }
        call = self._make_call(name="search_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is None

    def test_approval_absent_defaults_to_false(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "brave",
                "actions": [
                    {
                        "name": "search",
                        "active": True,
                        "parameters": {},
                    },
                ],
            }
        }
        call = self._make_call(name="search_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is None

    def test_api_tool_approval(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "api_tool",
                "config": {
                    "actions": {
                        "delete_user": {
                            "name": "delete_user",
                            "require_approval": True,
                            "url": "http://example.com",
                            "method": "DELETE",
                            "active": True,
                        }
                    }
                },
            }
        }
        call = self._make_call(name="delete_user_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "awaiting_approval"

    def test_api_tool_no_approval(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "api_tool",
                "config": {
                    "actions": {
                        "list_users": {
                            "name": "list_users",
                            "url": "http://example.com",
                            "method": "GET",
                            "active": True,
                        }
                    }
                },
            }
        }
        call = self._make_call(name="list_users_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is None


# ---------------------------------------------------------------------------
# Handler: approval tool causes pause signal
# ---------------------------------------------------------------------------


class ConcreteHandler(LLMHandler):
    def parse_response(self, response):
        return LLMResponse(
            content=str(response), tool_calls=[], finish_reason="stop",
            raw_response=response,
        )

    def create_tool_message(self, tool_call, result):
        import json as _json
        content = _json.dumps(result) if not isinstance(result, str) else result
        return {"role": "tool", "tool_call_id": tool_call.id, "content": content}

    def _iterate_stream(self, response):
        for chunk in response:
            yield chunk


@pytest.mark.unit
class TestHandlerApprovalPause:

    def _make_agent(self, pause_return):
        agent = Mock()
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=pause_return)

        def fake_execute(tools_dict, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("tool result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)
        return agent

    def test_approval_tool_pauses(self):
        handler = ConcreteHandler()
        pause_info = {
            "call_id": "c1",
            "name": "send_msg_0",
            "tool_name": "telegram",
            "tool_id": "0",
            "action_name": "send_msg",
            "arguments": {"text": "hello"},
            "pause_type": "awaiting_approval",
            "thought_signature": None,
        }
        agent = self._make_agent(pause_info)

        call = ToolCall(id="c1", name="send_msg_0", arguments='{"text": "hello"}')
        gen = handler.handle_tool_calls(
            agent, [call], {"0": {"name": "telegram"}}, []
        )

        events = []
        pending = None
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            messages, pending = e.value

        assert pending is not None
        assert len(pending) == 1
        assert pending[0]["pause_type"] == "awaiting_approval"

        # Should NOT have executed the tool
        assert agent._execute_tool_action.call_count == 0

        # Should have yielded awaiting_approval status
        approval_events = [
            e for e in events
            if e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "awaiting_approval"
        ]
        assert len(approval_events) == 1

    def test_mixed_normal_and_approval(self):
        """First tool runs normally, second needs approval."""
        handler = ConcreteHandler()

        call_count = {"n": 0}

        def selective_pause(tools_dict, call, llm_class):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return {
                    "call_id": "c2",
                    "name": "send_msg_0",
                    "tool_name": "telegram",
                    "tool_id": "0",
                    "action_name": "send_msg",
                    "arguments": {},
                    "pause_type": "awaiting_approval",
                    "thought_signature": None,
                }
            return None

        agent = self._make_agent(None)
        agent.tool_executor.check_pause = Mock(side_effect=selective_pause)

        calls = [
            ToolCall(id="c1", name="search_0", arguments="{}"),
            ToolCall(id="c2", name="send_msg_0", arguments="{}"),
        ]

        gen = handler.handle_tool_calls(
            agent, calls, {"0": {"name": "multi"}}, []
        )

        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            messages, pending = e.value

        # First tool executed
        assert agent._execute_tool_action.call_count == 1
        # Second tool is pending
        assert pending is not None
        assert len(pending) == 1
        assert pending[0]["call_id"] == "c2"


# ---------------------------------------------------------------------------
# gen_continuation: approval and denial flows
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenContinuationApproval:

    def _make_agent(self):
        from application.agents.classic_agent import ClassicAgent

        mock_llm = Mock()
        mock_llm._supports_tools = True
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))
        mock_llm._supports_structured_output = Mock(return_value=False)
        mock_llm.__class__.__name__ = "MockLLM"

        mock_handler = Mock()
        mock_handler.process_message_flow = Mock(return_value=iter([]))
        mock_handler.create_tool_message = Mock(
            return_value={"role": "tool", "tool_call_id": "c1", "content": "result"}
        )

        mock_executor = Mock()
        mock_executor.tool_calls = []
        mock_executor.prepare_tools_for_llm = Mock(return_value=[])
        mock_executor.get_truncated_tool_calls = Mock(return_value=[])

        def fake_execute(tools_dict, call, llm_class):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("executed_result", "c1")

        mock_executor.execute = Mock(side_effect=fake_execute)

        agent = ClassicAgent(
            endpoint="stream",
            llm_name="openai",
            model_id="gpt-4",
            api_key="test",
            llm=mock_llm,
            llm_handler=mock_handler,
            tool_executor=mock_executor,
        )
        return agent, mock_executor, mock_handler

    def test_approved_tool_executes(self):
        agent, mock_executor, mock_handler = self._make_agent()

        messages = [{"role": "system", "content": "test"}]
        pending = [
            {
                "call_id": "c1",
                "name": "send_msg_0",
                "tool_name": "telegram",
                "tool_id": "0",
                "action_name": "send_msg",
                "arguments": {"text": "hello"},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            }
        ]
        tool_actions = [{"call_id": "c1", "decision": "approved"}]

        list(agent.gen_continuation(
            messages, {"0": {"name": "telegram"}}, pending, tool_actions
        ))

        # Tool should have been executed
        assert mock_executor.execute.called

    def test_denied_tool_sends_denial_to_llm(self):
        agent, mock_executor, mock_handler = self._make_agent()

        messages = [{"role": "system", "content": "test"}]
        pending = [
            {
                "call_id": "c1",
                "name": "send_msg_0",
                "tool_name": "telegram",
                "tool_id": "0",
                "action_name": "send_msg",
                "arguments": {},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            }
        ]
        tool_actions = [
            {"call_id": "c1", "decision": "denied", "comment": "not safe"},
        ]

        events = list(agent.gen_continuation(
            messages, {"0": {"name": "telegram"}}, pending, tool_actions
        ))

        # Tool should NOT have been executed
        assert not mock_executor.execute.called

        # Should have a denied event
        denied = [
            e for e in events
            if isinstance(e, dict)
            and e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "denied"
        ]
        assert len(denied) == 1

        # create_tool_message should have been called with denial text
        denial_text = mock_handler.create_tool_message.call_args[0][1]
        assert "denied" in denial_text.lower()
        assert "not safe" in denial_text

    def test_denied_without_comment(self):
        agent, mock_executor, mock_handler = self._make_agent()

        messages = [{"role": "system", "content": "test"}]
        pending = [
            {
                "call_id": "c1",
                "name": "act_0",
                "tool_name": "tool",
                "tool_id": "0",
                "action_name": "act",
                "arguments": {},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            }
        ]
        tool_actions = [{"call_id": "c1", "decision": "denied"}]

        list(agent.gen_continuation(
            messages, {"0": {"name": "tool"}}, pending, tool_actions
        ))

        denial_text = mock_handler.create_tool_message.call_args[0][1]
        assert "denied" in denial_text.lower()

    def test_mixed_approve_deny_batch(self):
        """Two tools: one approved, one denied."""
        agent, mock_executor, mock_handler = self._make_agent()

        messages = [{"role": "system", "content": "test"}]
        pending = [
            {
                "call_id": "c1",
                "name": "safe_0",
                "tool_name": "safe",
                "tool_id": "0",
                "action_name": "safe",
                "arguments": {},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            },
            {
                "call_id": "c2",
                "name": "danger_0",
                "tool_name": "danger",
                "tool_id": "0",
                "action_name": "danger",
                "arguments": {},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            },
        ]
        tool_actions = [
            {"call_id": "c1", "decision": "approved"},
            {"call_id": "c2", "decision": "denied", "comment": "too risky"},
        ]

        events = list(agent.gen_continuation(
            messages, {"0": {"name": "multi"}}, pending, tool_actions
        ))

        # First tool executed, second denied
        assert mock_executor.execute.call_count == 1

        denied = [
            e for e in events
            if isinstance(e, dict)
            and e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "denied"
        ]
        assert len(denied) == 1

    def test_missing_action_defaults_to_denial(self):
        """If client doesn't respond for a pending tool, treat as denied."""
        agent, mock_executor, mock_handler = self._make_agent()

        messages = [{"role": "system", "content": "test"}]
        pending = [
            {
                "call_id": "c1",
                "name": "act_0",
                "tool_name": "tool",
                "tool_id": "0",
                "action_name": "act",
                "arguments": {},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            }
        ]
        # Empty tool_actions — no response for c1
        tool_actions = []

        events = list(agent.gen_continuation(
            messages, {"0": {"name": "tool"}}, pending, tool_actions
        ))

        # Should have been treated as denied
        assert not mock_executor.execute.called
        denied = [
            e for e in events
            if isinstance(e, dict)
            and e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "denied"
        ]
        assert len(denied) == 1
