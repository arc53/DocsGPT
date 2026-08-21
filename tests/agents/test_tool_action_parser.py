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

    def test_parse_google_llm_string_arguments_from_resume(self):
        # Resume path stringifies dict args for the assistant message format
        # before re-invoking _execute_tool_action. The Google parser must
        # decode the JSON string back to a dict so the executor's
        # ``call_args.items()`` loop doesn't AttributeError.
        parser = ToolActionParser("GoogleLLM")

        call = Mock()
        call.name = "search_docs_42"
        call.arguments = '{"query": "workflows", "limit": 5}'

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "42"
        assert action_name == "search_docs"
        assert call_args == {"query": "workflows", "limit": 5}

    def test_parse_google_llm_non_json_string_arguments_fall_back_to_empty_dict(self):
        # Malformed string args fall back to ``{}`` so the executor's
        # ``call_args.items()`` walk doesn't crash. The executor still
        # journals the malformed call via its own type guard.
        parser = ToolActionParser("GoogleLLM")

        call = Mock()
        call.name = "act_7"
        call.arguments = "not json"

        tool_id, action_name, call_args = parser.parse_args(call)

        assert tool_id == "7"
        assert action_name == "act"
        assert call_args == {}

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


@pytest.mark.unit
class TestToolActionParserWithMapping:
    """Tests for the mapping-based lookup path."""

    def test_openai_mapping_resolves_clean_name(self):
        mapping = {"get_weather": ("ct0", "get_weather")}
        parser = ToolActionParser("OpenAILLM", name_mapping=mapping)

        call = Mock()
        call.name = "get_weather"
        call.arguments = '{"city": "SF"}'

        tool_id, action_name, call_args = parser.parse_args(call)
        assert tool_id == "ct0"
        assert action_name == "get_weather"
        assert call_args == {"city": "SF"}

    def test_openai_mapping_resolves_numbered_suffix(self):
        mapping = {"search_1": ("t1", "search"), "search_2": ("t2", "search")}
        parser = ToolActionParser("OpenAILLM", name_mapping=mapping)

        call = Mock()
        call.name = "search_1"
        call.arguments = '{"q": "test"}'

        tool_id, action_name, call_args = parser.parse_args(call)
        assert tool_id == "t1"
        assert action_name == "search"

    def test_google_mapping_resolves(self):
        mapping = {"get_weather": ("ct0", "get_weather")}
        parser = ToolActionParser("GoogleLLM", name_mapping=mapping)

        call = Mock()
        call.name = "get_weather"
        call.arguments = {"city": "SF"}

        tool_id, action_name, call_args = parser.parse_args(call)
        assert tool_id == "ct0"
        assert action_name == "get_weather"

    def test_fallback_to_split_when_not_in_mapping(self):
        mapping = {"get_weather": ("ct0", "get_weather")}
        parser = ToolActionParser("OpenAILLM", name_mapping=mapping)

        call = Mock()
        call.name = "unknown_action_99"
        call.arguments = "{}"

        tool_id, action_name, call_args = parser.parse_args(call)
        # Falls back to legacy split
        assert tool_id == "99"
        assert action_name == "unknown_action"

    def test_no_mapping_uses_legacy_split(self):
        parser = ToolActionParser("OpenAILLM", name_mapping=None)

        call = Mock()
        call.name = "action_123"
        call.arguments = '{"k": "v"}'

        tool_id, action_name, call_args = parser.parse_args(call)
        assert tool_id == "123"
        assert action_name == "action"


@pytest.mark.unit
class TestZeroArgumentToolCalls:
    """A registered tool with no parameters must survive an empty ``arguments``.

    Providers send ``arguments`` as ``""`` (or omit it) for a zero-parameter
    function. The parser decoded arguments *before* resolving the name, so the
    JSON error discarded a perfectly valid, registered tool name and the caller
    reported "Invalid tool name format" — a diagnosis that sent one production
    investigation down the wrong path and gave the model nothing to correct
    against. It then retried the same call 22 times in five minutes.
    """

    MAPPING = {"note_view": ("42", "note_view"), "memory_view": ("43", "memory_view")}

    @pytest.mark.parametrize("arguments", ["", "   ", None])
    def test_registered_zero_arg_call_resolves_with_empty_arguments(self, arguments):
        parser = ToolActionParser("OpenAILLM", name_mapping=self.MAPPING)

        call = Mock()
        call.name = "note_view"
        call.arguments = arguments

        tool_id, action_name, call_args = parser.parse_args(call)

        assert (tool_id, action_name) == ("42", "note_view")
        assert call_args == {}

    def test_legacy_split_also_survives_empty_arguments(self):
        parser = ToolActionParser("OpenAILLM")

        call = Mock()
        call.name = "action_123"
        call.arguments = ""

        tool_id, action_name, call_args = parser.parse_args(call)

        assert (tool_id, action_name, call_args) == ("123", "action", {})

    def test_google_zero_arg_call_resolves(self):
        parser = ToolActionParser("GoogleLLM", name_mapping=self.MAPPING)

        call = Mock()
        call.name = "note_view"
        call.arguments = ""

        assert parser.parse_args(call)[:2] == ("42", "note_view")

    def test_genuinely_malformed_arguments_still_fail(self):
        parser = ToolActionParser("OpenAILLM", name_mapping=self.MAPPING)

        call = Mock()
        call.name = "note_view"
        call.arguments = "invalid json"

        assert parser.parse_args(call) == (None, None, None)
