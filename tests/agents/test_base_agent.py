from unittest.mock import Mock

import pytest
from application.agents.classic_agent import ClassicAgent
from application.core.settings import settings


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
        mock_mongo_db,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        user_tools = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        user_tools.insert_one(
            {"_id": "1", "user": "test_user", "name": "tool1", "status": True}
        )
        user_tools.insert_one(
            {"_id": "2", "user": "test_user", "name": "tool2", "status": True}
        )

        agent = ClassicAgent(**agent_base_params)
        tools = agent._get_user_tools("test_user")

        assert len(tools) == 2
        assert "0" in tools
        assert "1" in tools

    def test_get_user_tools_filters_by_status(
        self,
        agent_base_params,
        mock_mongo_db,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        user_tools = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        user_tools.insert_one(
            {"_id": "1", "user": "test_user", "name": "tool1", "status": True}
        )
        user_tools.insert_one(
            {"_id": "2", "user": "test_user", "name": "tool2", "status": False}
        )

        agent = ClassicAgent(**agent_base_params)
        tools = agent._get_user_tools("test_user")

        assert len(tools) == 1

    def test_get_tools_by_api_key(
        self,
        agent_base_params,
        mock_mongo_db,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        from bson.objectid import ObjectId

        tool_id = str(ObjectId())
        tool_obj_id = ObjectId(tool_id)

        agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
        agents_collection.insert_one(
            {
                "key": "api_key_123",
                "tools": [tool_id],
            }
        )

        tools_collection = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        tools_collection.insert_one({"_id": tool_obj_id, "name": "api_tool"})

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
        assert agent.tools[0]["function"]["name"] == "get_data_1"

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
        assert agent.tools[0]["function"]["name"] == "action1_1"

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
        assert agent.tools[0]["function"]["name"] == "active_action_1"


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
