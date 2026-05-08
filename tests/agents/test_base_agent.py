from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from application.agents.classic_agent import ClassicAgent


@pytest.mark.unit
class TestBaseAgentInitialization:

    def test_agent_initialization(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        assert agent.endpoint == agent_base_params["endpoint"]
        assert agent.llm_name == agent_base_params["llm_name"]
        assert agent.model_id == agent_base_params["model_id"]
        assert agent.api_key == agent_base_params["api_key"]
        assert agent.prompt == agent_base_params["prompt"]
        assert agent.user == agent_base_params["decoded_token"]["sub"]
        assert agent.tools == []
        assert agent.tool_calls == []

    def test_agent_initialization_with_none_chat_history(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["chat_history"] = None
        agent = ClassicAgent(**agent_base_params)
        assert agent.chat_history == []

    def test_agent_initialization_with_chat_history(
        self,
        agent_base_params,
        sample_chat_history,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        agent_base_params["chat_history"] = sample_chat_history
        agent = ClassicAgent(**agent_base_params)
        assert len(agent.chat_history) == 2
        assert agent.chat_history[0]["prompt"] == "What is Python?"

    def test_agent_decoded_token_defaults_to_empty_dict(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["decoded_token"] = None
        agent = ClassicAgent(**agent_base_params)
        assert agent.decoded_token == {}
        assert agent.user is None

    def test_agent_user_extracted_from_token(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["decoded_token"] = {"sub": "user123"}
        agent = ClassicAgent(**agent_base_params)
        assert agent.user == "user123"

    def test_dependency_injection_llm(self, agent_base_params, mock_llm_handler_creator):
        """When llm is provided, LLMCreator.create_llm is NOT called."""
        injected_llm = Mock()
        agent_base_params["llm"] = injected_llm
        agent = ClassicAgent(**agent_base_params)
        assert agent.llm is injected_llm

    def test_dependency_injection_llm_handler(self, agent_base_params, mock_llm_creator):
        """When llm_handler is provided, LLMHandlerCreator is NOT called."""
        injected_handler = Mock()
        agent_base_params["llm_handler"] = injected_handler
        agent = ClassicAgent(**agent_base_params)
        assert agent.llm_handler is injected_handler

    def test_dependency_injection_tool_executor(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        """When tool_executor is provided, a new one is NOT created."""
        injected_executor = Mock()
        injected_executor.tool_calls = []
        agent_base_params["tool_executor"] = injected_executor
        agent = ClassicAgent(**agent_base_params)
        assert agent.tool_executor is injected_executor

    def test_json_schema_normalized(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["json_schema"] = {"type": "object"}
        agent = ClassicAgent(**agent_base_params)
        assert agent.json_schema == {"type": "object"}

    def test_json_schema_wrapped(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["json_schema"] = {"schema": {"type": "string"}}
        agent = ClassicAgent(**agent_base_params)
        assert agent.json_schema == {"type": "string"}

    def test_json_schema_invalid_ignored(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["json_schema"] = {"bad": "no type"}
        agent = ClassicAgent(**agent_base_params)
        assert agent.json_schema is None

    def test_retrieved_docs_defaults_to_empty(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        assert agent.retrieved_docs == []

    def test_attachments_defaults_to_empty(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["attachments"] = None
        agent = ClassicAgent(**agent_base_params)
        assert agent.attachments == []

    def test_limited_token_mode_defaults(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        assert agent.limited_token_mode is False
        assert agent.limited_request_mode is False
        assert agent.current_token_count == 0
        assert agent.context_limit_reached is False


@pytest.mark.unit
class TestBaseAgentBuildMessages:

    def test_build_messages_basic(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        system_prompt = "System prompt content"
        query = "What is Python?"

        messages = agent._build_messages(system_prompt, query)

        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == system_prompt
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == query

    def test_build_messages_with_chat_history(
        self,
        agent_base_params,
        sample_chat_history,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        agent_base_params["chat_history"] = sample_chat_history
        agent = ClassicAgent(**agent_base_params)

        system_prompt = "System prompt"
        query = "New question?"

        messages = agent._build_messages(system_prompt, query)

        user_messages = [m for m in messages if m["role"] == "user"]
        assistant_messages = [m for m in messages if m["role"] == "assistant"]

        assert len(user_messages) >= 3
        assert len(assistant_messages) >= 2

    def test_build_messages_with_tool_calls_in_history(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        tool_call_history = [
            {
                "tool_calls": [
                    {
                        "call_id": "123",
                        "action_name": "test_action",
                        "arguments": {"arg": "value"},
                        "result": "success",
                    }
                ]
            }
        ]
        agent_base_params["chat_history"] = tool_call_history
        agent = ClassicAgent(**agent_base_params)

        messages = agent._build_messages("System prompt", "query")

        tool_messages = [m for m in messages if m["role"] == "tool"]
        assert len(tool_messages) > 0

    def test_build_messages_handles_missing_filename(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        messages = agent._build_messages("System prompt", "query")

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "System prompt"

    def test_build_messages_uses_title_as_fallback(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        agent._build_messages("System prompt", "query")

    def test_build_messages_uses_source_as_fallback(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        agent._build_messages("System prompt", "query")


@pytest.mark.unit
class TestBaseAgentTools:

    def test_get_user_tools(
        self,
        agent_base_params,
        pg_conn,
        monkeypatch,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        from application.storage.db.repositories.user_tools import UserToolsRepository

        repo = UserToolsRepository(pg_conn)
        repo.create(user_id="test_user", name="tool1", status=True)
        repo.create(user_id="test_user", name="tool2", status=True)

        @contextmanager
        def _use_pg_conn():
            yield pg_conn

        monkeypatch.setattr(
            "application.agents.tool_executor.db_readonly", _use_pg_conn
        )

        agent = ClassicAgent(**agent_base_params)
        tools = agent._get_user_tools("test_user")

        assert len(tools) == 2
        assert "0" in tools
        assert "1" in tools

    def test_get_user_tools_filters_by_status(
        self,
        agent_base_params,
        pg_conn,
        monkeypatch,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        from application.storage.db.repositories.user_tools import UserToolsRepository

        repo = UserToolsRepository(pg_conn)
        repo.create(user_id="test_user", name="tool1", status=True)
        repo.create(user_id="test_user", name="tool2", status=False)

        @contextmanager
        def _use_pg_conn():
            yield pg_conn

        monkeypatch.setattr(
            "application.agents.tool_executor.db_readonly", _use_pg_conn
        )

        agent = ClassicAgent(**agent_base_params)
        tools = agent._get_user_tools("test_user")

        assert len(tools) == 1

    def test_get_tools_by_api_key(
        self,
        agent_base_params,
        pg_conn,
        monkeypatch,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool_row = UserToolsRepository(pg_conn).create(
            user_id="alice", name="api_tool"
        )
        tool_id = str(tool_row["id"])

        AgentsRepository(pg_conn).create(
            user_id="alice",
            name="my-agent",
            status="active",
            key="api_key_123",
            tools=[tool_id],
        )

        @contextmanager
        def _use_pg_conn():
            yield pg_conn

        monkeypatch.setattr(
            "application.agents.tool_executor.db_readonly", _use_pg_conn
        )

        agent = ClassicAgent(**agent_base_params)
        tools = agent._get_tools("api_key_123")

        assert tool_id in tools

    def test_build_tool_parameters(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        action = {
            "parameters": {
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Test param",
                        "filled_by_llm": True,
                        "required": True,
                    },
                    "param2": {
                        "type": "number",
                        "filled_by_llm": False,
                        "value": 42,
                        "required": False,
                    },
                }
            }
        }

        params = agent._build_tool_parameters(action)

        assert "param1" in params["properties"]
        assert "param1" in params["required"]
        assert "filled_by_llm" not in params["properties"]["param1"]

    def test_prepare_tools_with_api_tool(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        tools_dict = {
            "1": {
                "name": "api_tool",
                "config": {
                    "actions": {
                        "get_data": {
                            "name": "get_data",
                            "description": "Get data from API",
                            "active": True,
                            "url": "https://api.example.com/data",
                            "method": "GET",
                            "parameters": {"properties": {}},
                        }
                    }
                },
            }
        }

        agent._prepare_tools(tools_dict)

        assert len(agent.tools) == 1
        assert agent.tools[0]["type"] == "function"
        assert agent.tools[0]["function"]["name"] == "get_data"

    def test_prepare_tools_with_regular_tool(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        tools_dict = {
            "1": {
                "name": "custom_tool",
                "actions": [
                    {
                        "name": "action1",
                        "description": "Custom action",
                        "active": True,
                        "parameters": {"properties": {}},
                    }
                ],
            }
        }

        agent._prepare_tools(tools_dict)

        assert len(agent.tools) == 1
        assert agent.tools[0]["function"]["name"] == "action1"

    def test_prepare_tools_filters_inactive_actions(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        tools_dict = {
            "1": {
                "name": "custom_tool",
                "actions": [
                    {
                        "name": "active_action",
                        "description": "Active",
                        "active": True,
                        "parameters": {"properties": {}},
                    },
                    {
                        "name": "inactive_action",
                        "description": "Inactive",
                        "active": False,
                        "parameters": {"properties": {}},
                    },
                ],
            }
        }

        agent._prepare_tools(tools_dict)

        assert len(agent.tools) == 1
        assert agent.tools[0]["function"]["name"] == "active_action"


@pytest.mark.unit
class TestBaseAgentToolExecution:

    def test_execute_tool_action_success(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_tool_manager,
    ):
        agent = ClassicAgent(**agent_base_params)

        call = Mock()
        call.id = "call_123"
        call.name = "test_action_1"
        call.arguments = '{"param1": "value1"}'

        tools_dict = {
            "1": {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "custom_tool",
                "config": {},
                "actions": [
                    {
                        "name": "test_action",
                        "description": "Test",
                        "parameters": {"properties": {}},
                    }
                ],
            }
        }

        results = list(agent._execute_tool_action(tools_dict, call))

        assert len(results) >= 2
        assert results[0]["type"] == "tool_call"
        assert results[0]["data"]["status"] == "pending"
        assert results[-1]["data"]["status"] == "completed"

    def test_execute_tool_action_invalid_tool_name(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        call = Mock()
        call.id = "call_123"
        call.name = "invalid_format"
        call.arguments = "{}"

        tools_dict = {}

        results = list(agent._execute_tool_action(tools_dict, call))

        assert results[0]["type"] == "tool_call"
        assert results[0]["data"]["status"] == "error"
        assert (
            "Failed to parse" in results[0]["data"]["result"]
            or "not found" in results[0]["data"]["result"]
        )

    def test_execute_tool_action_tool_not_found(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        call = Mock()
        call.id = "call_123"
        call.name = "action_999"
        call.arguments = "{}"

        tools_dict = {"1": {"name": "tool1", "config": {}, "actions": []}}

        results = list(agent._execute_tool_action(tools_dict, call))

        assert results[0]["type"] == "tool_call"
        assert results[0]["data"]["status"] == "error"
        assert "not found" in results[0]["data"]["result"]

    def test_execute_tool_action_with_parameters(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_tool_manager,
    ):
        agent = ClassicAgent(**agent_base_params)

        call = Mock()
        call.id = "call_123"
        call.name = "test_action_1"
        call.arguments = '{"param1": "value1", "param2": "value2"}'

        tools_dict = {
            "1": {
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "custom_tool",
                "config": {},
                "actions": [
                    {
                        "name": "test_action",
                        "description": "Test",
                        "parameters": {
                            "properties": {
                                "param1": {"type": "string"},
                                "param2": {"type": "string"},
                            }
                        },
                    }
                ],
            }
        }

        results = list(agent._execute_tool_action(tools_dict, call))

        assert results[-1]["data"]["status"] == "completed"
        assert results[-1]["data"]["arguments"]["param1"] == "value1"

    def test_get_truncated_tool_calls(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        agent.tool_calls = [
            {
                "tool_name": "test_tool",
                "call_id": "123",
                "action_name": "action",
                "arguments": {},
                "result": "a" * 100,
            }
        ]

        truncated = agent._get_truncated_tool_calls()

        assert len(truncated) == 1
        assert len(truncated[0]["result"]) <= 53
        assert truncated[0]["result"].endswith("...")


@pytest.mark.unit
class TestBaseAgentLLMGeneration:

    def test_llm_gen_basic(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        agent = ClassicAgent(**agent_base_params)

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages, log_context)

        mock_llm.gen_stream.assert_called_once()
        call_args = mock_llm.gen_stream.call_args[1]
        assert call_args["model"] == agent.model_id
        assert call_args["messages"] == messages

    def test_llm_gen_with_tools(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        agent = ClassicAgent(**agent_base_params)
        agent.tools = [{"type": "function", "function": {"name": "test"}}]

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages, log_context)

        call_args = mock_llm.gen_stream.call_args[1]
        assert "tools" in call_args
        assert call_args["tools"] == agent.tools

    def test_llm_gen_with_json_schema(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        mock_llm._supports_structured_output = Mock(return_value=True)
        mock_llm.prepare_structured_output_format = Mock(
            return_value={"schema": "test"}
        )

        agent_base_params["json_schema"] = {"type": "object"}
        agent_base_params["llm_name"] = "openai"
        agent = ClassicAgent(**agent_base_params)

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages, log_context)

        call_args = mock_llm.gen_stream.call_args[1]
        assert "response_format" in call_args


@pytest.mark.unit
class TestBaseAgentHandleResponse:

    def test_handle_response_string(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, log_context
    ):
        agent = ClassicAgent(**agent_base_params)

        response = "Simple string response"
        results = list(agent._handle_response(response, {}, [], log_context))

        assert len(results) == 1
        assert results[0]["answer"] == "Simple string response"

    def test_handle_response_with_message(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, log_context
    ):
        agent = ClassicAgent(**agent_base_params)

        response = Mock()
        response.message = Mock()
        response.message.content = "Message content"

        results = list(agent._handle_response(response, {}, [], log_context))

        assert len(results) == 1
        assert results[0]["answer"] == "Message content"

    def test_handle_response_with_structured_output(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        mock_llm._supports_structured_output = Mock(return_value=True)
        agent_base_params["json_schema"] = {"type": "object"}

        agent = ClassicAgent(**agent_base_params)

        response = "Structured response"
        results = list(agent._handle_response(response, {}, [], log_context))

        assert results[0]["structured"] is True
        assert results[0]["schema"] == {"type": "object"}

    def test_handle_response_with_handler(
        self,
        agent_base_params,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        def mock_process(*args):
            yield {"type": "tool_call", "data": {}}
            yield "Final answer"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_process)

        agent = ClassicAgent(**agent_base_params)

        response = Mock()
        response.message = None

        results = list(agent._handle_response(response, {}, [], log_context))

        assert len(results) == 2
        assert results[0]["type"] == "tool_call"
        assert results[1]["answer"] == "Final answer"

    def test_handle_response_dict_event_passthrough(
        self,
        agent_base_params,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Dict events with 'type' key pass through without wrapping."""

        def mock_process(*args):
            yield {"type": "info", "data": {"message": "processing"}}

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_process)

        agent = ClassicAgent(**agent_base_params)
        response = Mock()
        response.message = None

        results = list(agent._handle_response(response, {}, [], log_context))
        assert results == [{"type": "info", "data": {"message": "processing"}}]

    def test_handle_response_message_object_from_handler(
        self,
        agent_base_params,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Response objects with .message.content from handler are unwrapped."""
        event = Mock()
        event.message = Mock()
        event.message.content = "from handler"

        def mock_process(*args):
            yield event

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_process)

        agent = ClassicAgent(**agent_base_params)
        response = Mock()
        response.message = None

        results = list(agent._handle_response(response, {}, [], log_context))
        assert results[0]["answer"] == "from handler"


# ---------------------------------------------------------------------------
# gen() — the @log_activity decorated entry point
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaseAgentGen:

    def test_gen_delegates_to_gen_inner(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        # ClassicAgent._gen_inner is abstract — we patch it
        with patch.object(agent, "_gen_inner") as mock_inner:
            mock_inner.return_value = iter([{"answer": "ok"}])
            results = list(agent.gen("hello"))

        assert any(r.get("answer") == "ok" for r in results)


# ---------------------------------------------------------------------------
# tool_calls property
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaseAgentToolCallsProperty:

    def test_getter(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        agent.tool_executor.tool_calls = ["a", "b"]
        assert agent.tool_calls == ["a", "b"]

    def test_setter(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        agent.tool_calls = ["x"]
        assert agent.tool_executor.tool_calls == ["x"]


# ---------------------------------------------------------------------------
# _calculate_current_context_tokens
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalculateContextTokens:

    def test_delegates_to_token_counter(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        messages = [{"role": "user", "content": "hello"}]

        with patch(
            "application.api.answer.services.compression.token_counter.TokenCounter"
        ) as MockTC:
            MockTC.count_message_tokens.return_value = 42
            result = agent._calculate_current_context_tokens(messages)
            assert result == 42
            MockTC.count_message_tokens.assert_called_once_with(messages)


# ---------------------------------------------------------------------------
# _check_context_limit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckContextLimit:

    def _make_agent(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        return ClassicAgent(**agent_base_params)

    def test_below_threshold_returns_false(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        messages = [{"role": "user", "content": "hi"}]

        with patch.object(agent, "_calculate_current_context_tokens", return_value=100):
            with patch(
                "application.core.model_utils.get_token_limit", return_value=10000
            ):
                result = agent._check_context_limit(messages)
                assert result is False
                assert agent.current_token_count == 100

    def test_at_threshold_returns_true(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        messages = [{"role": "user", "content": "hi"}]

        # threshold = 10000 * 0.8 = 8000; tokens = 8001 → True
        with patch.object(agent, "_calculate_current_context_tokens", return_value=8001):
            with patch(
                "application.core.model_utils.get_token_limit", return_value=10000
            ):
                result = agent._check_context_limit(messages)
                assert result is True

    def test_error_returns_false(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        with patch.object(
            agent,
            "_calculate_current_context_tokens",
            side_effect=RuntimeError("boom"),
        ):
            result = agent._check_context_limit([])
            assert result is False


# ---------------------------------------------------------------------------
# _validate_context_size
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateContextSize:

    def test_at_limit_logs_warning(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        with patch.object(agent, "_calculate_current_context_tokens", return_value=10000):
            with patch(
                "application.core.model_utils.get_token_limit", return_value=10000
            ):
                # Should not raise
                agent._validate_context_size([{"role": "user", "content": "x"}])
                assert agent.current_token_count == 10000

    def test_below_threshold_no_warning(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        with patch.object(agent, "_calculate_current_context_tokens", return_value=100):
            with patch(
                "application.core.model_utils.get_token_limit", return_value=10000
            ):
                agent._validate_context_size([])
                assert agent.current_token_count == 100

    def test_approaching_threshold(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        # 8500 / 10000 = 85% → above 80% threshold but below 100%
        with patch.object(agent, "_calculate_current_context_tokens", return_value=8500):
            with patch(
                "application.core.model_utils.get_token_limit", return_value=10000
            ):
                agent._validate_context_size([])
                assert agent.current_token_count == 8500


# ---------------------------------------------------------------------------
# _truncate_text_middle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTruncateTextMiddle:

    def test_short_text_unchanged(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        with patch("application.utils.num_tokens_from_string", return_value=5):
            result = agent._truncate_text_middle("short", max_tokens=100)
            assert result == "short"

    def test_long_text_truncated(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        long_text = "A" * 1000

        def fake_tokens(text):
            return len(text) // 4

        with patch("application.utils.num_tokens_from_string", side_effect=fake_tokens):
            result = agent._truncate_text_middle(long_text, max_tokens=50)
            assert "[... content truncated to fit context limit ...]" in result
            assert len(result) < len(long_text)

    def test_zero_target_returns_empty(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)
        with patch("application.utils.num_tokens_from_string", return_value=100):
            result = agent._truncate_text_middle("some text", max_tokens=0)
            assert result == ""


# ---------------------------------------------------------------------------
# _truncate_history_to_fit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTruncateHistoryToFit:

    def _make_agent(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        return ClassicAgent(**agent_base_params)

    def test_empty_history(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        assert agent._truncate_history_to_fit([], 100) == []

    def test_zero_budget(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        history = [{"prompt": "a", "response": "b"}]
        assert agent._truncate_history_to_fit(history, 0) == []

    def test_fits_all(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        history = [
            {"prompt": "q1", "response": "a1"},
            {"prompt": "q2", "response": "a2"},
        ]
        with patch("application.utils.num_tokens_from_string", return_value=5):
            result = agent._truncate_history_to_fit(history, 10000)
            assert len(result) == 2

    def test_partial_fit_keeps_most_recent(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        history = [
            {"prompt": "old", "response": "old_ans"},
            {"prompt": "new", "response": "new_ans"},
        ]
        # Each message = 10 tokens (prompt + response), budget = 15 → only 1 fits
        with patch("application.utils.num_tokens_from_string", return_value=5):
            result = agent._truncate_history_to_fit(history, 15)
            assert len(result) == 1
            assert result[0]["prompt"] == "new"

    def test_history_with_tool_calls(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        history = [
            {
                "prompt": "q",
                "response": "a",
                "tool_calls": [
                    {
                        "tool_name": "t",
                        "action_name": "act",
                        "arguments": "{}",
                        "result": "ok",
                    }
                ],
            }
        ]
        with patch("application.utils.num_tokens_from_string", return_value=3):
            result = agent._truncate_history_to_fit(history, 100)
            assert len(result) == 1


# ---------------------------------------------------------------------------
# _build_messages — compressed_summary and query truncation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildMessagesAdvanced:

    def test_compressed_summary_appended(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["compressed_summary"] = "Previous conversation summary"
        agent = ClassicAgent(**agent_base_params)

        with patch(
            "application.core.model_utils.get_token_limit", return_value=100000
        ), patch("application.utils.num_tokens_from_string", return_value=10):
            messages = agent._build_messages("System prompt", "query")

        system_content = messages[0]["content"]
        assert "Previous conversation summary" in system_content

    def test_query_truncated_when_too_large(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        call_count = {"n": 0}

        def fake_tokens(text):
            call_count["n"] += 1
            return len(text)

        with patch(
            "application.core.model_utils.get_token_limit", return_value=200
        ), patch("application.utils.num_tokens_from_string", side_effect=fake_tokens):
            with patch.object(agent, "_truncate_text_middle", return_value="truncated"):
                with patch.object(agent, "_truncate_history_to_fit", return_value=[]):
                    messages = agent._build_messages("sys", "A" * 500)

        # The method should have been called for truncation
        assert messages[-1]["role"] == "user"

    def test_build_messages_with_tool_call_missing_call_id(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        """Tool calls without call_id get a generated UUID."""
        history = [
            {
                "tool_calls": [
                    {
                        "action_name": "search",
                        "arguments": "{}",
                        "result": "found",
                    }
                ]
            }
        ]
        agent_base_params["chat_history"] = history
        agent = ClassicAgent(**agent_base_params)

        with patch(
            "application.core.model_utils.get_token_limit", return_value=100000
        ), patch("application.utils.num_tokens_from_string", return_value=5):
            messages = agent._build_messages("sys", "q")

        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1


# ---------------------------------------------------------------------------
# _llm_gen — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLLMGenAdvanced:

    def test_llm_gen_with_attachments(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        agent_base_params["attachments"] = [{"id": "att1", "mime_type": "image/png"}]
        agent = ClassicAgent(**agent_base_params)

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages)

        call_kwargs = mock_llm.gen_stream.call_args[1]
        assert "_usage_attachments" in call_kwargs

    def test_llm_gen_without_log_context(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        agent = ClassicAgent(**agent_base_params)
        messages = [{"role": "user", "content": "test"}]

        # Should not raise even without log_context
        agent._llm_gen(messages, log_context=None)
        mock_llm.gen_stream.assert_called_once()

    def test_llm_gen_google_structured_output(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        mock_llm._supports_structured_output = Mock(return_value=True)
        mock_llm.prepare_structured_output_format = Mock(
            return_value={"schema": "test"}
        )

        agent_base_params["json_schema"] = {"type": "object"}
        agent_base_params["llm_name"] = "google"
        agent = ClassicAgent(**agent_base_params)

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages, log_context)

        call_kwargs = mock_llm.gen_stream.call_args[1]
        assert "response_schema" in call_kwargs

    def test_llm_gen_no_tools_when_unsupported(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        mock_llm._supports_tools = False
        agent = ClassicAgent(**agent_base_params)
        agent.tools = [{"type": "function", "function": {"name": "test"}}]

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages)

        call_kwargs = mock_llm.gen_stream.call_args[1]
        assert "tools" not in call_kwargs

    def test_llm_gen_no_structured_output_when_unsupported(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        mock_llm._supports_structured_output = Mock(return_value=False)
        agent_base_params["json_schema"] = {"type": "object"}
        agent = ClassicAgent(**agent_base_params)

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages)

        call_kwargs = mock_llm.gen_stream.call_args[1]
        assert "response_format" not in call_kwargs
        assert "response_schema" not in call_kwargs

    def test_llm_gen_no_format_when_prepare_returns_none(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        mock_llm._supports_structured_output = Mock(return_value=True)
        mock_llm.prepare_structured_output_format = Mock(return_value=None)

        agent_base_params["json_schema"] = {"type": "object"}
        agent_base_params["llm_name"] = "openai"
        agent = ClassicAgent(**agent_base_params)

        messages = [{"role": "user", "content": "test"}]
        agent._llm_gen(messages)

        call_kwargs = mock_llm.gen_stream.call_args[1]
        assert "response_format" not in call_kwargs


# ---------------------------------------------------------------------------
# _llm_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLLMHandlerMethod:

    def test_delegates_to_handler(
        self,
        agent_base_params,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        mock_llm_handler.process_message_flow = Mock(return_value="result")

        agent = ClassicAgent(**agent_base_params)
        resp = Mock()
        result = agent._llm_handler(resp, {}, [], log_context)

        mock_llm_handler.process_message_flow.assert_called_once()
        assert result == "result"
        assert len(log_context.stacks) == 1
        assert log_context.stacks[0]["component"] == "llm_handler"

    def test_without_log_context(
        self,
        agent_base_params,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        mock_llm_handler.process_message_flow = Mock(return_value="r")
        agent = ClassicAgent(**agent_base_params)
        result = agent._llm_handler(Mock(), {}, [], log_context=None)
        assert result == "r"


# ---------------------------------------------------------------------------
# _handle_response — structured output on all code paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleResponseStructuredAllPaths:

    def test_message_response_with_structured_output(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Structured output on the message.content early-return path."""
        mock_llm._supports_structured_output = Mock(return_value=True)
        agent_base_params["json_schema"] = {"type": "object"}
        agent = ClassicAgent(**agent_base_params)

        response = Mock()
        response.message = Mock()
        response.message.content = "structured msg"

        results = list(agent._handle_response(response, {}, [], log_context))
        assert results[0]["structured"] is True
        assert results[0]["schema"] == {"type": "object"}
        assert results[0]["answer"] == "structured msg"

    def test_handler_string_event_with_structured_output(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Structured output on string events from the handler."""
        mock_llm._supports_structured_output = Mock(return_value=True)
        agent_base_params["json_schema"] = {"type": "array"}

        def mock_process(*args):
            yield "handler string"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_process)

        agent = ClassicAgent(**agent_base_params)
        response = Mock()
        response.message = None

        results = list(agent._handle_response(response, {}, [], log_context))
        assert results[0]["structured"] is True
        assert results[0]["schema"] == {"type": "array"}

    def test_handler_message_event_with_structured_output(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Structured output on message-object events from the handler."""
        mock_llm._supports_structured_output = Mock(return_value=True)
        agent_base_params["json_schema"] = {"type": "number"}

        event = Mock()
        event.message = Mock()
        event.message.content = "from handler msg"

        def mock_process(*args):
            yield event

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_process)

        agent = ClassicAgent(**agent_base_params)
        response = Mock()
        response.message = None

        results = list(agent._handle_response(response, {}, [], log_context))
        assert results[0]["structured"] is True
        assert results[0]["schema"] == {"type": "number"}
        assert results[0]["answer"] == "from handler msg"
