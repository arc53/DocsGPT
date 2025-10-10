from unittest.mock import Mock

import pytest
from application.agents.tools.tool_action_parser import ToolActionParser


@pytest.mark.unit
class TestToolActionParser:

    def test_parser_initialization(self):
        parser = ToolActionParser("OpenAILLM")
        assert parser.llm_type == "OpenAILLM"
        assert "OpenAILLM" in parser.parsers
        assert "GoogleLLM" in parser.parsers

    def test_parse_openai_llm_valid_call(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "get_data_123"
        call.arguments = '{"param1": "value1", "param2": "value2"}'

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "123"
        assert action_name == "get_data"
        assert call_args == {"param1": "value1", "param2": "value2"}

    def test_parse_openai_llm_with_underscore_in_action(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "send_email_notification_456"
        call.arguments = '{"to": "user@example.com"}'

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "456"
        assert action_name == "send_email_notification"
        assert call_args == {"to": "user@example.com"}

    def test_parse_openai_llm_invalid_format_no_underscore(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "invalidtoolname"
        call.arguments = "{}"

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id is None
        assert action_name is None
        assert call_args is None

    def test_parse_openai_llm_non_numeric_tool_id(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "action_notanumber"
        call.arguments = "{}"

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "notanumber"
        assert action_name == "action"

    def test_parse_openai_llm_malformed_json(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "action_123"
        call.arguments = "invalid json"

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id is None
        assert action_name is None
        assert call_args is None

    def test_parse_openai_llm_missing_attributes(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock(spec=[])

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id is None
        assert action_name is None
        assert call_args is None

    def test_parse_google_llm_valid_call(self):
        parser = ToolActionParser("GoogleLLM")

        call = Mock()
        call.name = "search_documents_789"
        call.arguments = {"query": "test query", "limit": 10}

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "789"
        assert action_name == "search_documents"
        assert call_args == {"query": "test query", "limit": 10}

    def test_parse_google_llm_with_complex_action_name(self):
        parser = ToolActionParser("GoogleLLM")

        call = Mock()
        call.name = "create_new_user_account_999"
        call.arguments = {"username": "test"}

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "999"
        assert action_name == "create_new_user_account"

    def test_parse_google_llm_invalid_format(self):
        parser = ToolActionParser("GoogleLLM")

        call = Mock()
        call.name = "nounderscores"
        call.arguments = {}

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id is None
        assert action_name is None
        assert call_args is None

    def test_parse_google_llm_missing_attributes(self):
        parser = ToolActionParser("GoogleLLM")

        call = Mock(spec=[])

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id is None
        assert action_name is None
        assert call_args is None

    def test_parse_unknown_llm_type_defaults_to_openai(self):
        parser = ToolActionParser("UnknownLLM")

        call = Mock()
        call.name = "action_123"
        call.arguments = '{"key": "value"}'

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "123"
        assert action_name == "action"
        assert call_args == {"key": "value"}

    def test_parse_args_empty_arguments_openai(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "action_123"
        call.arguments = "{}"

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "123"
        assert action_name == "action"
        assert call_args == {}

    def test_parse_args_empty_arguments_google(self):
        parser = ToolActionParser("GoogleLLM")

        call = Mock()
        call.name = "action_456"
        call.arguments = {}

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "456"
        assert action_name == "action"
        assert call_args == {}

    def test_parse_args_with_special_characters(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "send_message_123"
        call.arguments = '{"message": "Hello, World! 你好"}'

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "123"
        assert action_name == "send_message"
        assert call_args["message"] == "Hello, World! 你好"

    def test_parse_args_with_nested_objects(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "create_record_123"
        call.arguments = '{"data": {"name": "John", "age": 30}}'

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "123"
        assert action_name == "create_record"
        assert call_args["data"]["name"] == "John"
        assert call_args["data"]["age"] == 30
