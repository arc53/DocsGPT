"""Tests for client-side tools (Phase 2).

Covers merge_client_tools, prepare_tools_for_llm with client tools,
check_pause for client-side tools, and the full flow through the handler.
"""

from unittest.mock import Mock

import pytest

from application.agents.tool_executor import ToolExecutor
from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


# ---------------------------------------------------------------------------
# ToolExecutor.merge_client_tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeClientTools:

    def test_merge_single_tool(self):
        executor = ToolExecutor()
        tools_dict = {}
        client_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string", "description": "City name"}
                        },
                        "required": ["city"],
                    },
                },
            }
        ]

        result = executor.merge_client_tools(tools_dict, client_tools)

        assert "ct0" in result
        tool = result["ct0"]
        assert tool["name"] == "get_weather"
        assert tool["client_side"] is True
        assert len(tool["actions"]) == 1
        assert tool["actions"][0]["name"] == "get_weather"
        assert tool["actions"][0]["active"] is True
        assert "city" in tool["actions"][0]["parameters"]["properties"]

    def test_merge_multiple_tools(self):
        executor = ToolExecutor()
        tools_dict = {"0": {"name": "existing_tool", "actions": []}}
        client_tools = [
            {"type": "function", "function": {"name": "tool_a", "description": "A"}},
            {"type": "function", "function": {"name": "tool_b", "description": "B"}},
        ]

        result = executor.merge_client_tools(tools_dict, client_tools)

        # Original tool still present
        assert "0" in result
        # Client tools added
        assert "ct0" in result
        assert "ct1" in result
        assert result["ct0"]["name"] == "tool_a"
        assert result["ct1"]["name"] == "tool_b"

    def test_merge_bare_format(self):
        """Accept simplified format without the outer 'function' wrapper."""
        executor = ToolExecutor()
        tools_dict = {}
        client_tools = [
            {"name": "simple_tool", "description": "Simple", "parameters": {}},
        ]

        result = executor.merge_client_tools(tools_dict, client_tools)

        assert "ct0" in result
        assert result["ct0"]["name"] == "simple_tool"

    def test_merge_preserves_existing_tools(self):
        executor = ToolExecutor()
        tools_dict = {
            "abc123": {
                "name": "brave",
                "actions": [{"name": "search", "active": True}],
            }
        }
        client_tools = [
            {"type": "function", "function": {"name": "my_tool", "description": "D"}},
        ]

        executor.merge_client_tools(tools_dict, client_tools)

        assert "abc123" in tools_dict
        assert tools_dict["abc123"]["name"] == "brave"
        assert "ct0" in tools_dict

    def test_merge_empty_list(self):
        executor = ToolExecutor()
        tools_dict = {"0": {"name": "existing"}}

        executor.merge_client_tools(tools_dict, [])

        assert len(tools_dict) == 1


# ---------------------------------------------------------------------------
# prepare_tools_for_llm with client tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareClientToolsForLlm:

    def test_client_tools_included_in_llm_schema(self):
        executor = ToolExecutor()
        tools_dict = {}
        client_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"}
                        },
                        "required": ["city"],
                    },
                },
            }
        ]
        executor.merge_client_tools(tools_dict, client_tools)

        schemas = executor.prepare_tools_for_llm(tools_dict)

        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "get_weather"
        assert schemas[0]["function"]["description"] == "Get weather"
        # Parameters passed through directly (not filtered by _build_tool_parameters)
        assert "city" in schemas[0]["function"]["parameters"]["properties"]
        assert schemas[0]["function"]["parameters"]["required"] == ["city"]

    def test_mixed_server_and_client_tools(self):
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "test_tool",
                "actions": [
                    {
                        "name": "do_thing",
                        "description": "Does a thing",
                        "active": True,
                        "parameters": {
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "filled_by_llm": True,
                                    "required": True,
                                }
                            }
                        },
                    }
                ],
            }
        }
        client_tools = [
            {
                "type": "function",
                "function": {
                    "name": "local_fn",
                    "description": "Local function",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        executor.merge_client_tools(tools_dict, client_tools)

        schemas = executor.prepare_tools_for_llm(tools_dict)

        assert len(schemas) == 2
        names = {s["function"]["name"] for s in schemas}
        assert "do_thing" in names
        assert "local_fn" in names


# ---------------------------------------------------------------------------
# get_tools auto-merges client_tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skip(reason="needs PG fixture rewrite — tracked as part of post-cutover test cleanup")
class TestGetToolsAutoMerge:

    def test_get_tools_merges_client_tools(self, monkeypatch):
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        mock_db.__getitem__.return_value.find.return_value = iter([])
        monkeypatch.setattr(
            "application.agents.tool_executor.MongoDB.get_client",
            lambda: mock_db,
        )
        executor = ToolExecutor(user="alice")
        executor.client_tools = [
            {
                "type": "function",
                "function": {"name": "my_fn", "description": "test"},
            }
        ]

        tools = executor.get_tools()

        assert any(
            t.get("client_side") is True for t in tools.values()
        ), "Client tools should be merged into tools_dict"

    def test_get_tools_no_client_tools(self, monkeypatch):
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        mock_db.__getitem__.return_value.find.return_value = iter([])
        monkeypatch.setattr(
            "application.agents.tool_executor.MongoDB.get_client",
            lambda: mock_db,
        )
        executor = ToolExecutor(user="alice")

        tools = executor.get_tools()

        assert not any(
            t.get("client_side") for t in tools.values()
        )


# ---------------------------------------------------------------------------
# check_pause for client-side tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPauseClientTools:

    def _make_call(self, name="action_0", call_id="c1"):
        call = Mock()
        call.name = name
        call.id = call_id
        call.arguments = "{}"
        call.thought_signature = None
        return call

    def test_client_tool_triggers_pause(self):
        executor = ToolExecutor()
        tools_dict = {
            "ct0": {
                "name": "get_weather",
                "client_side": True,
                "actions": [
                    {"name": "get_weather", "active": True, "parameters": {}},
                ],
            }
        }
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(name="get_weather")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")

        assert result is not None
        assert result["pause_type"] == "requires_client_execution"
        assert result["tool_name"] == "get_weather"
        assert result["tool_id"] == "ct0"

    def test_server_tool_no_pause(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "brave",
                "actions": [
                    {"name": "search", "active": True, "parameters": {}},
                ],
            }
        }
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(name="search")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")

        assert result is None


# ---------------------------------------------------------------------------
# Handler flow: client tool causes pause
# ---------------------------------------------------------------------------


class ConcreteHandler(LLMHandler):
    """Minimal concrete handler for testing."""

    def parse_response(self, response):
        return LLMResponse(
            content=str(response), tool_calls=[], finish_reason="stop",
            raw_response=response,
        )

    def create_tool_message(self, tool_call, result):
        return {"role": "tool", "content": str(result)}

    def _iterate_stream(self, response):
        for chunk in response:
            yield chunk


@pytest.mark.unit
class TestHandlerClientToolPause:

    def test_client_tool_pauses_stream(self):
        """When LLM calls a client-side tool, handler yields tool_calls_pending."""
        handler = ConcreteHandler()

        agent = Mock()
        agent.llm = Mock()
        agent.model_id = "test"
        agent.tools = []
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"

        # check_pause returns pause info for client tool
        agent.tool_executor.check_pause = Mock(return_value={
            "call_id": "c1",
            "name": "get_weather",
            "tool_name": "get_weather",
            "tool_id": "ct0",
            "action_name": "get_weather",
            "llm_name": "get_weather",
            "arguments": {"city": "SF"},
            "pause_type": "requires_client_execution",
            "thought_signature": None,
        })
        agent.tool_executor._name_to_tool = {"get_weather": ("ct0", "get_weather")}

        # Simulate streaming: one chunk with tool_calls finish_reason
        chunk = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="get_weather", arguments='{"city": "SF"}', index=0)],
            finish_reason="tool_calls",
            raw_response={},
        )
        handler.parse_response = lambda c: c
        handler._iterate_stream = lambda r: iter(r)

        gen = handler.handle_streaming(
            agent, [chunk], {"ct0": {"name": "get_weather", "client_side": True}}, []
        )
        events = list(gen)

        # Should have a requires_client_execution event
        client_events = [
            e for e in events
            if isinstance(e, dict)
            and e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "requires_client_execution"
        ]
        assert len(client_events) == 1

        # Should have a tool_calls_pending event
        pending_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "tool_calls_pending"
        ]
        assert len(pending_events) == 1

    def test_mixed_server_and_client_tools_in_batch(self):
        """Server tool executes, client tool pauses."""
        handler = ConcreteHandler()

        agent = Mock()
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"

        call_count = {"n": 0}

        def check_pause_fn(tools_dict, call, llm_class):
            call_count["n"] += 1
            if call_count["n"] == 2:  # Second tool is client-side
                return {
                    "call_id": "c2",
                    "name": "get_weather",
                    "tool_name": "get_weather",
                    "tool_id": "ct0",
                    "action_name": "get_weather",
                    "llm_name": "get_weather",
                    "arguments": {},
                    "pause_type": "requires_client_execution",
                    "thought_signature": None,
                }
            return None

        agent.tool_executor.check_pause = Mock(side_effect=check_pause_fn)
        agent.tool_executor._name_to_tool = {
            "search": ("0", "search"),
            "get_weather": ("ct0", "get_weather"),
        }

        def fake_execute(tools_dict, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("server result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)

        calls = [
            ToolCall(id="c1", name="search", arguments="{}"),
            ToolCall(id="c2", name="get_weather", arguments="{}"),
        ]

        gen = handler.handle_tool_calls(
            agent,
            calls,
            {
                "0": {"name": "search"},
                "ct0": {"name": "get_weather", "client_side": True},
            },
            [],
        )

        events = []
        messages = None
        pending = None
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            messages, pending = e.value

        # Server tool executed
        assert agent._execute_tool_action.call_count == 1
        # Client tool pending
        assert pending is not None
        assert len(pending) == 1
        assert pending[0]["pause_type"] == "requires_client_execution"
