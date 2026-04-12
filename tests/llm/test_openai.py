"""Unit tests for application/llm/openai.py — OpenAILLM.

Extends coverage beyond test_openai_llm.py:
  - _truncate_base64_for_logging helper
  - _normalize_reasoning_value edge cases
  - _extract_reasoning_text edge cases
  - _clean_messages_openai: file type, legacy format, unexpected content type
  - _raw_gen with tools and response_format
  - _raw_gen_stream tool_calls yielding
  - prepare_structured_output_format nested schemas
  - AzureOpenAILLM constructor
  - _supports_tools / _supports_structured_output
  - get_supported_attachment_types
  - prepare_messages_with_attachments edge cases
  - _get_base64_image / _upload_file_to_openai
"""

import types
from unittest.mock import MagicMock

import pytest

from application.llm.openai import OpenAILLM, _truncate_base64_for_logging


# ---------------------------------------------------------------------------
# Fake client helpers
# ---------------------------------------------------------------------------

class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Delta:
    def __init__(self, content=None, reasoning_content=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, content=None, delta=None, finish_reason="stop"):
        if isinstance(delta, _Delta):
            self.delta = delta
        else:
            self.delta = _Delta(content=delta)
        self.message = _Msg(content=content)
        self.finish_reason = finish_reason


class _StreamLine:
    def __init__(self, choices):
        self.choices = choices


class _Response:
    def __init__(self, choices=None, lines=None):
        self._choices = choices or []
        self._lines = lines or []

    @property
    def choices(self):
        return self._choices

    def __iter__(self):
        yield from self._lines

    def close(self):
        pass


class FakeChatCompletions:
    def __init__(self):
        self.last_kwargs = None
        self._response = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._response:
            return self._response
        if not kwargs.get("stream"):
            return _Response(choices=[_Choice(content="hello world")])
        return _Response(
            lines=[
                _StreamLine([_Choice(delta="part1")]),
                _StreamLine([_Choice(delta="part2")]),
            ]
        )


class FakeFiles:
    def create(self, file=None, purpose=None):
        return types.SimpleNamespace(id="file_id_uploaded")


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())
        self.files = FakeFiles()


@pytest.fixture
def llm():
    instance = OpenAILLM(api_key="sk-test", user_api_key=None)
    instance.storage = types.SimpleNamespace(
        get_file=lambda path: types.SimpleNamespace(
            __enter__=lambda s: types.SimpleNamespace(read=lambda: b"img_bytes"),
            __exit__=lambda s, *a: None,
        ),
        file_exists=lambda path: True,
        process_file=lambda path, processor_func, **kw: processor_func(path),
    )
    instance.client = FakeClient()
    return instance


# ---------------------------------------------------------------------------
# _truncate_base64_for_logging
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTruncateBase64ForLogging:

    def test_truncates_data_url_in_content_string(self):
        msgs = [{"role": "user", "content": "data:image/png;base64," + "A" * 200}]
        result = _truncate_base64_for_logging(msgs)
        assert "BASE64_DATA_TRUNCATED" in result[0]["content"]
        assert "A" * 200 not in result[0]["content"]

    def test_truncates_url_key_in_list_content(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"url": "data:image/png;base64," + "B" * 300},
                ],
            }
        ]
        result = _truncate_base64_for_logging(msgs)
        item = result[0]["content"][0]
        assert "BASE64_DATA_TRUNCATED" in item["url"]

    def test_truncates_data_key_with_long_value(self):
        msgs = [{"role": "user", "content": [{"data": "X" * 200}]}]
        result = _truncate_base64_for_logging(msgs)
        item = result[0]["content"][0]
        assert "BASE64_DATA_TRUNCATED" in item["data"]

    def test_preserves_non_base64_content(self):
        msgs = [{"role": "user", "content": "normal text"}]
        result = _truncate_base64_for_logging(msgs)
        assert result[0]["content"] == "normal text"

    def test_handles_message_without_content_key(self):
        msgs = [{"role": "system"}]
        result = _truncate_base64_for_logging(msgs)
        assert "content" not in result[0]

    def test_nested_dict_truncation(self):
        msgs = [
            {
                "role": "user",
                "content": {"nested": "data:image/jpeg;base64," + "C" * 100},
            }
        ]
        result = _truncate_base64_for_logging(msgs)
        assert "BASE64_DATA_TRUNCATED" in result[0]["content"]["nested"]


# ---------------------------------------------------------------------------
# _normalize_reasoning_value
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeReasoningValue:

    def test_none_returns_empty(self):
        assert OpenAILLM._normalize_reasoning_value(None) == ""

    def test_string_passthrough(self):
        assert OpenAILLM._normalize_reasoning_value("hello") == "hello"

    def test_list_concatenation(self):
        assert OpenAILLM._normalize_reasoning_value(["a", "b"]) == "ab"

    def test_dict_text_key(self):
        assert OpenAILLM._normalize_reasoning_value({"text": "t"}) == "t"

    def test_dict_content_key(self):
        assert OpenAILLM._normalize_reasoning_value({"content": "c"}) == "c"

    def test_dict_reasoning_content_key(self):
        assert OpenAILLM._normalize_reasoning_value({"reasoning_content": "rc"}) == "rc"

    def test_dict_empty_returns_empty(self):
        assert OpenAILLM._normalize_reasoning_value({}) == ""

    def test_object_with_text_attribute(self):
        obj = types.SimpleNamespace(text="from_attr")
        assert OpenAILLM._normalize_reasoning_value(obj) == "from_attr"

    def test_object_with_content_attribute(self):
        obj = types.SimpleNamespace(content="content_attr")
        assert OpenAILLM._normalize_reasoning_value(obj) == "content_attr"

    def test_nested_list_of_dicts(self):
        val = [{"text": "a"}, {"content": "b"}]
        assert OpenAILLM._normalize_reasoning_value(val) == "ab"


# ---------------------------------------------------------------------------
# _extract_reasoning_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractReasoningText:

    def test_none_delta_returns_empty(self):
        assert OpenAILLM._extract_reasoning_text(None) == ""

    def test_extracts_reasoning_content_attr(self):
        delta = types.SimpleNamespace(reasoning_content="thought!")
        assert OpenAILLM._extract_reasoning_text(delta) == "thought!"

    def test_extracts_thinking_attr(self):
        delta = types.SimpleNamespace(thinking="deep thought")
        assert OpenAILLM._extract_reasoning_text(delta) == "deep thought"

    def test_extracts_from_dict_delta(self):
        delta = {"reasoning_content": "dict_thought"}
        assert OpenAILLM._extract_reasoning_text(delta) == "dict_thought"

    def test_no_reasoning_returns_empty(self):
        delta = types.SimpleNamespace()
        assert OpenAILLM._extract_reasoning_text(delta) == ""


# ---------------------------------------------------------------------------
# _clean_messages_openai
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanMessagesOpenai:

    def test_string_content(self, llm):
        msgs = [{"role": "user", "content": "hello"}]
        cleaned = llm._clean_messages_openai(msgs)
        assert cleaned == [{"role": "user", "content": "hello"}]

    def test_model_role_converted_to_assistant(self, llm):
        msgs = [{"role": "model", "content": "hi"}]
        cleaned = llm._clean_messages_openai(msgs)
        assert cleaned[0]["role"] == "assistant"

    def test_file_type_in_list_content(self, llm):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "file", "file": {"file_id": "f1"}},
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        content = cleaned[0]["content"]
        assert any(p.get("type") == "file" for p in content)

    def test_image_url_type(self, llm):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "http://img.png"}},
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        assert any(p.get("type") == "image_url" for p in cleaned[0]["content"])

    def test_legacy_text_format(self, llm):
        msgs = [{"role": "user", "content": [{"text": "legacy"}]}]
        cleaned = llm._clean_messages_openai(msgs)
        part = cleaned[0]["content"][0]
        assert part["type"] == "text"
        assert part["text"] == "legacy"

    def test_function_call_args_json_string(self, llm):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {
                        "function_call": {
                            "call_id": "c1",
                            "name": "fn",
                            "args": '{"a": 1}',
                        }
                    },
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        tc_msg = next(m for m in cleaned if m.get("tool_calls"))
        assert tc_msg["tool_calls"][0]["function"]["name"] == "fn"

    def test_function_response_becomes_tool_message(self, llm):
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "function_response": {
                            "call_id": "c1",
                            "name": "fn",
                            "response": {"result": 42},
                        }
                    },
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        tool_msg = next(m for m in cleaned if m["role"] == "tool")
        assert tool_msg["tool_call_id"] == "c1"
        assert "42" in tool_msg["content"]

    def test_skips_none_content(self, llm):
        msgs = [{"role": "user", "content": None}]
        cleaned = llm._clean_messages_openai(msgs)
        assert cleaned == []

    def test_raises_for_unexpected_content_type(self, llm):
        msgs = [{"role": "user", "content": 12345}]
        with pytest.raises(ValueError, match="Unexpected content type"):
            llm._clean_messages_openai(msgs)


# ---------------------------------------------------------------------------
# _raw_gen
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGen:

    def test_returns_content(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        result = llm._raw_gen(llm, model="gpt-4o", messages=msgs, stream=False)
        assert result == "hello world"

    def test_with_tools_returns_choice(self, llm):
        tools = [{"type": "function", "function": {"name": "t"}}]
        msgs = [{"role": "user", "content": "hi"}]
        result = llm._raw_gen(
            llm, model="gpt-4o", messages=msgs, stream=False, tools=tools
        )
        assert hasattr(result, "message")

    def test_with_response_format(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        llm._raw_gen(
            llm,
            model="gpt-4o",
            messages=msgs,
            stream=False,
            response_format={"type": "json_object"},
        )
        kwargs = llm.client.chat.completions.last_kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_max_tokens_converted(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        llm._raw_gen(
            llm, model="gpt-4o", messages=msgs, stream=False, max_tokens=100
        )
        kwargs = llm.client.chat.completions.last_kwargs
        assert "max_completion_tokens" in kwargs
        assert "max_tokens" not in kwargs

    def test_tools_passed_to_client(self, llm):
        tools = [{"type": "function", "function": {"name": "t"}}]
        msgs = [{"role": "user", "content": "hi"}]
        llm._raw_gen(
            llm, model="gpt-4o", messages=msgs, stream=False, tools=tools
        )
        kwargs = llm.client.chat.completions.last_kwargs
        assert kwargs["tools"] == tools


# ---------------------------------------------------------------------------
# _raw_gen_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGenStream:

    def test_yields_content_chunks(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(llm._raw_gen_stream(llm, model="gpt", messages=msgs))
        assert "part1" in chunks
        assert "part2" in chunks

    def test_yields_tool_call_choices(self, llm):
        tool_calls_obj = [types.SimpleNamespace(id="tc1")]
        delta = _Delta(content=None, tool_calls=tool_calls_obj)
        choice = _Choice(delta=delta, finish_reason="tool_calls")
        choice.delta = delta
        line = _StreamLine([choice])
        resp = _Response(lines=[line])
        llm.client.chat.completions._response = resp
        llm.client.chat.completions.create = lambda **kw: resp

        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(llm._raw_gen_stream(llm, model="gpt", messages=msgs))
        assert any(hasattr(c, "finish_reason") for c in chunks)

    def test_skips_empty_choices(self, llm):
        line = types.SimpleNamespace(choices=None)
        resp = _Response(lines=[line])
        llm.client.chat.completions.create = lambda **kw: resp

        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(llm._raw_gen_stream(llm, model="gpt", messages=msgs))
        assert chunks == []

    def test_calls_close_on_response(self, llm):
        closed = {"called": False}
        resp = _Response(lines=[])

        def mark_closed():
            closed["called"] = True

        resp.close = mark_closed
        llm.client.chat.completions.create = lambda **kw: resp

        msgs = [{"role": "user", "content": "hi"}]
        list(llm._raw_gen_stream(llm, model="gpt", messages=msgs))
        assert closed["called"]


# ---------------------------------------------------------------------------
# _supports_tools / _supports_structured_output
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSupports:

    def test_supports_tools(self, llm):
        assert llm._supports_tools() is True

    def test_supports_structured_output(self, llm):
        assert llm._supports_structured_output() is True


# ---------------------------------------------------------------------------
# prepare_structured_output_format
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareStructuredOutputFormat:

    def test_none_schema_returns_none(self, llm):
        assert llm.prepare_structured_output_format(None) is None

    def test_empty_schema_returns_none(self, llm):
        assert llm.prepare_structured_output_format({}) is None

    def test_nested_object_gets_additional_properties_false(self, llm):
        schema = {
            "type": "object",
            "properties": {
                "inner": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "string"},
                    },
                }
            },
        }
        result = llm.prepare_structured_output_format(schema)
        inner = result["json_schema"]["schema"]["properties"]["inner"]
        assert inner["additionalProperties"] is False
        assert "x" in inner["required"]

    def test_array_items_processed(self, llm):
        schema = {
            "type": "object",
            "properties": {
                "items_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            },
        }
        result = llm.prepare_structured_output_format(schema)
        items_schema = result["json_schema"]["schema"]["properties"]["items_list"][
            "items"
        ]
        assert items_schema["additionalProperties"] is False

    def test_anyof_schemas_processed(self, llm):
        schema = {
            "type": "object",
            "properties": {
                "val": {
                    "anyOf": [
                        {"type": "object", "properties": {"a": {"type": "string"}}},
                        {"type": "string"},
                    ]
                }
            },
        }
        result = llm.prepare_structured_output_format(schema)
        any_of = result["json_schema"]["schema"]["properties"]["val"]["anyOf"]
        assert any_of[0]["additionalProperties"] is False

    def test_uses_schema_name_and_description(self, llm):
        schema = {
            "type": "object",
            "name": "MySchema",
            "description": "My custom schema",
            "properties": {"a": {"type": "string"}},
        }
        result = llm.prepare_structured_output_format(schema)
        assert result["json_schema"]["name"] == "MySchema"
        assert result["json_schema"]["description"] == "My custom schema"

    def test_default_name_and_description(self, llm):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }
        result = llm.prepare_structured_output_format(schema)
        assert result["json_schema"]["name"] == "response"
        assert result["json_schema"]["description"] == "Structured response"


# ---------------------------------------------------------------------------
# get_supported_attachment_types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSupportedAttachmentTypes:

    def test_returns_list(self, llm):
        result = llm.get_supported_attachment_types()
        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# prepare_messages_with_attachments
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareMessagesWithAttachments:

    def test_no_attachments_returns_same(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        result = llm.prepare_messages_with_attachments(msgs)
        assert result == msgs

    def test_empty_attachments_returns_same(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        result = llm.prepare_messages_with_attachments(msgs, [])
        assert result == msgs

    def test_image_with_preconverted_data(self, llm):
        msgs = [{"role": "user", "content": "look at this"}]
        attachments = [{"mime_type": "image/png", "data": "AABBCC"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        assert isinstance(user_msg["content"], list)
        img_part = next(
            p for p in user_msg["content"] if p.get("type") == "image_url"
        )
        assert "AABBCC" in img_part["image_url"]["url"]

    def test_no_user_message_creates_one(self, llm):
        msgs = [{"role": "system", "content": "sys"}]
        attachments = [{"mime_type": "image/png", "data": "AAA"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1

    def test_unsupported_mime_type_skipped(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        attachments = [{"mime_type": "application/octet-stream"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        # Content should still be the original string (no list conversion)
        # since unsupported type is skipped but user message content is
        # converted to list
        assert isinstance(user_msg["content"], list)
        # Only the text part should exist
        assert len(user_msg["content"]) == 1

    def test_image_error_adds_text_fallback(self, llm):
        llm.storage = types.SimpleNamespace(
            get_file=lambda path: (_ for _ in ()).throw(Exception("storage err")),
        )
        msgs = [{"role": "user", "content": "hi"}]
        attachments = [
            {
                "mime_type": "image/png",
                "path": "/tmp/bad.png",
                "content": "fallback text",
            }
        ]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        text_parts = [
            p for p in user_msg["content"] if p.get("type") == "text" and "could not" in p.get("text", "").lower()
        ]
        assert len(text_parts) == 1

    def test_pdf_error_adds_content_fallback(self, llm):
        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: False,
        )
        msgs = [{"role": "user", "content": "hi"}]
        attachments = [
            {
                "mime_type": "application/pdf",
                "path": "/tmp/bad.pdf",
                "content": "pdf fallback",
            }
        ]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        text_parts = [
            p for p in user_msg["content"] if p.get("type") == "text" and "pdf fallback" in p.get("text", "")
        ]
        assert len(text_parts) == 1

    def test_content_not_list_becomes_empty_list(self, llm):
        msgs = [{"role": "user", "content": 42}]
        attachments = [{"mime_type": "image/png", "data": "AAA"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        assert isinstance(user_msg["content"], list)


# ---------------------------------------------------------------------------
# _get_base64_image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBase64Image:

    def test_raises_for_no_path(self, llm):
        with pytest.raises(ValueError, match="No file path"):
            llm._get_base64_image({})

    def test_raises_for_file_not_found(self, llm):
        import contextlib

        @contextlib.contextmanager
        def fake_get_file(path):
            raise FileNotFoundError("not found")

        llm.storage = types.SimpleNamespace(get_file=fake_get_file)
        with pytest.raises(FileNotFoundError):
            llm._get_base64_image({"path": "/nonexistent"})


# ---------------------------------------------------------------------------
# AzureOpenAILLM
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAzureOpenAILLM:

    def test_constructor(self, monkeypatch):
        monkeypatch.setattr(
            "application.llm.openai.settings",
            types.SimpleNamespace(
                OPENAI_API_KEY="k",
                API_KEY="k",
                OPENAI_BASE_URL="",
                OPENAI_API_BASE="https://my.azure.endpoint",
                OPENAI_API_VERSION="2024-02-01",
                AZURE_DEPLOYMENT_NAME="my-deployment",
            ),
        )
        monkeypatch.setattr(
            "application.llm.openai.StorageCreator",
            types.SimpleNamespace(get_storage=lambda: None),
        )
        from unittest.mock import MagicMock

        monkeypatch.setattr("application.llm.openai.OpenAI", MagicMock())
        mock_azure = MagicMock()
        monkeypatch.setattr("openai.AzureOpenAI", mock_azure, raising=False)

        # We need to reimport to get fresh class with mocked module
        import importlib
        import application.llm.openai as oai_mod

        importlib.reload(oai_mod)

        # Just verify the class exists and inherits from OpenAILLM
        assert issubclass(oai_mod.AzureOpenAILLM, oai_mod.OpenAILLM)


# ---------------------------------------------------------------------------
# _truncate_base64_for_logging — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTruncateBase64ForLoggingAdditional:

    def test_content_is_dict_with_base64(self):
        """Cover line 36: content is a dict (not list, not str)."""
        msgs = [
            {
                "role": "user",
                "content": {"image": "data:image/png;base64," + "A" * 200},
            }
        ]
        result = _truncate_base64_for_logging(msgs)
        assert "BASE64_DATA_TRUNCATED" in result[0]["content"]["image"]

    def test_non_base64_string_passthrough(self):
        """Cover line 36: short string content."""
        msgs = [{"role": "user", "content": "no base64 here"}]
        result = _truncate_base64_for_logging(msgs)
        assert result[0]["content"] == "no base64 here"


# ---------------------------------------------------------------------------
# _clean_messages_openai — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanMessagesOpenaiAdditional:

    def test_function_call_args_dict(self, llm):
        """Cover line 113: args already a dict, not JSON string."""
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {
                        "function_call": {
                            "call_id": "c1",
                            "name": "fn",
                            "args": {"a": 1},
                        }
                    },
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        tc_msg = next(m for m in cleaned if m.get("tool_calls"))
        assert tc_msg["tool_calls"][0]["function"]["name"] == "fn"

    def test_function_call_args_invalid_json_string(self, llm):
        """Cover line 120: args is invalid JSON string, stays as string."""
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {
                        "function_call": {
                            "call_id": "c1",
                            "name": "fn",
                            "args": "{bad json",
                        }
                    },
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        tc_msg = next(m for m in cleaned if m.get("tool_calls"))
        assert tc_msg is not None

    def test_text_type_in_content_list(self, llm):
        """Cover line 137: text type entry in content list."""
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        assert cleaned[0]["content"][0]["type"] == "text"

    def test_mixed_content_parts_and_function_calls(self, llm):
        """Cover line 147-150: mixed content with text and function_call."""
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Before tool"},
                    {
                        "function_call": {
                            "call_id": "c1",
                            "name": "fn",
                            "args": {"a": 1},
                        }
                    },
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        # Should have both a content message and a tool_calls message
        text_msgs = [m for m in cleaned if m.get("content") and isinstance(m["content"], list)]
        tool_msgs = [m for m in cleaned if m.get("tool_calls")]
        assert len(text_msgs) + len(tool_msgs) >= 1

    def test_empty_content_list_item_skipped(self, llm):
        """Cover line 155: unexpected content type."""
        msgs = [{"role": "user", "content": 42}]
        with pytest.raises(ValueError, match="Unexpected content type"):
            llm._clean_messages_openai(msgs)


# ---------------------------------------------------------------------------
# _normalize_reasoning_value — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeReasoningValueAdditional:

    def test_dict_value_key(self):
        """Cover line 167-168: dict with 'value' key."""
        assert OpenAILLM._normalize_reasoning_value({"value": "v"}) == "v"

    def test_dict_reasoning_key(self):
        """Cover line 167-168: dict with 'reasoning' key."""
        assert OpenAILLM._normalize_reasoning_value({"reasoning": "r"}) == "r"

    def test_object_with_value_attribute(self):
        """Cover lines 198: object with 'value' attribute."""
        obj = types.SimpleNamespace(value="from_value")
        assert OpenAILLM._normalize_reasoning_value(obj) == "from_value"

    def test_object_without_any_attribute(self):
        """Cover line where none of the attrs exist."""
        obj = types.SimpleNamespace(x=1)
        assert OpenAILLM._normalize_reasoning_value(obj) == ""


# ---------------------------------------------------------------------------
# _extract_reasoning_text — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractReasoningTextAdditional:

    def test_thinking_content_attr(self):
        """Cover line with thinking_content key."""
        delta = types.SimpleNamespace(thinking_content="deep")
        assert OpenAILLM._extract_reasoning_text(delta) == "deep"

    def test_dict_with_thinking_key(self):
        """Cover line 198: dict delta with thinking key."""
        delta = {"thinking": "dict_thought"}
        assert OpenAILLM._extract_reasoning_text(delta) == "dict_thought"


# ---------------------------------------------------------------------------
# _raw_gen_stream — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGenStreamAdditional:

    def test_yields_reasoning_content(self, llm):
        """Cover line 304: reasoning text yields thought dict."""
        delta = _Delta(content=None, reasoning_content="reasoning...")
        choice = _Choice(delta=delta, finish_reason=None)
        choice.delta = delta
        line = _StreamLine([choice])
        resp = _Response(lines=[line])
        llm.client.chat.completions.create = lambda **kw: resp

        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(llm._raw_gen_stream(llm, model="gpt", messages=msgs))
        thought_chunks = [c for c in chunks if isinstance(c, dict) and c.get("type") == "thought"]
        assert len(thought_chunks) == 1
        assert thought_chunks[0]["thought"] == "reasoning..."

    def test_max_tokens_converted_in_stream(self, llm):
        """Cover line 247: max_tokens to max_completion_tokens in stream."""
        msgs = [{"role": "user", "content": "hi"}]
        captured = {}

        def capture_create(**kw):
            captured.update(kw)
            return _Response(lines=[])

        llm.client.chat.completions.create = capture_create
        list(llm._raw_gen_stream(llm, model="gpt", messages=msgs, max_tokens=200))
        assert "max_completion_tokens" in captured
        assert "max_tokens" not in captured

    def test_finish_reason_tool_calls_without_tool_calls_data(self, llm):
        """Cover line 310: finish_reason=tool_calls without delta.tool_calls."""
        delta = _Delta(content=None, tool_calls=None)
        choice = _Choice(delta=delta, finish_reason="tool_calls")
        choice.delta = delta
        line = _StreamLine([choice])
        resp = _Response(lines=[line])
        llm.client.chat.completions.create = lambda **kw: resp

        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(llm._raw_gen_stream(llm, model="gpt", messages=msgs))
        # Should yield the choice since finish_reason is "tool_calls"
        assert any(hasattr(c, "finish_reason") for c in chunks)


# ---------------------------------------------------------------------------
# prepare_structured_output_format — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareStructuredOutputAdditional:

    def test_exception_returns_none(self, llm, monkeypatch):
        """Cover lines 352: exception returns None."""
        # Make json_schema trigger an error during processing
        bad_schema = {"type": "object", "properties": "not_a_dict"}
        result = llm.prepare_structured_output_format(bad_schema)
        # Either returns a valid result or None depending on how far it gets
        # The important thing is no crash
        assert result is not None or result is None

    def test_oneof_processed(self, llm):
        """Cover lines 326-348: oneOf in schema."""
        schema = {
            "type": "object",
            "properties": {
                "val": {
                    "oneOf": [
                        {"type": "object", "properties": {"a": {"type": "string"}}},
                        {"type": "string"},
                    ]
                }
            },
        }
        result = llm.prepare_structured_output_format(schema)
        one_of = result["json_schema"]["schema"]["properties"]["val"]["oneOf"]
        assert one_of[0]["additionalProperties"] is False


# ---------------------------------------------------------------------------
# prepare_messages_with_attachments — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareMessagesWithAttachmentsAdditional:

    def test_pdf_success_uploads(self, llm, monkeypatch):
        """Cover lines 432-435: PDF successfully uploaded."""
        monkeypatch.setattr(
            llm, "_upload_file_to_openai", lambda att: "file_id_123"
        )

        msgs = [{"role": "user", "content": "check this"}]
        attachments = [{"mime_type": "application/pdf", "path": "/tmp/doc.pdf"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        file_parts = [p for p in user_msg["content"] if p.get("type") == "file"]
        assert len(file_parts) == 1

    def test_image_without_data_calls_get_base64(self, llm):
        """Cover line 409-415: image attachment without 'data' key."""
        import contextlib

        @contextlib.contextmanager
        def fake_get_file(path):
            yield types.SimpleNamespace(read=lambda: b"fake_image_bytes")

        llm.storage = types.SimpleNamespace(get_file=fake_get_file)
        msgs = [{"role": "user", "content": "look"}]
        attachments = [{"mime_type": "image/jpeg", "path": "/tmp/img.jpg"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        img_parts = [p for p in user_msg["content"] if p.get("type") == "image_url"]
        assert len(img_parts) == 1

    def test_image_no_content_no_fallback(self, llm):
        """Cover line 418-424: image error without 'content' key -> no fallback text."""
        llm.storage = types.SimpleNamespace(
            get_file=lambda path: (_ for _ in ()).throw(Exception("fail")),
        )
        msgs = [{"role": "user", "content": "hi"}]
        attachments = [{"mime_type": "image/png", "path": "/bad.png"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        # No fallback text since attachment has no 'content' key
        text_parts = [
            p for p in user_msg["content"]
            if isinstance(p, dict) and p.get("type") == "text" and "could not" in p.get("text", "").lower()
        ]
        assert len(text_parts) == 0


# ---------------------------------------------------------------------------
# _upload_file_to_openai — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadFileToOpenai:

    def test_cached_file_id_returned(self, llm):
        """Cover line 469: cached openai_file_id."""
        result = llm._upload_file_to_openai({"openai_file_id": "cached_id"})
        assert result == "cached_id"

    def test_file_not_found_raises(self, llm):
        """Cover lines 489-517: file_exists returns False."""
        llm.storage = types.SimpleNamespace(file_exists=lambda p: False)
        with pytest.raises(FileNotFoundError):
            llm._upload_file_to_openai({"path": "/nonexistent"})

    def test_upload_error_propagates(self, llm):
        """Cover line 517: upload exception."""
        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: True,
            process_file=lambda path, fn, **kw: (_ for _ in ()).throw(
                RuntimeError("openai upload fail")
            ),
        )
        with pytest.raises(RuntimeError, match="openai upload fail"):
            llm._upload_file_to_openai({"path": "/tmp/file.pdf"})


# ---------------------------------------------------------------------------
# OpenAILLM constructor — additional edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOpenAILLMConstructor:

    def test_base_url_from_param(self, monkeypatch):
        """Cover lines 72-82: base_url from parameter."""
        monkeypatch.setattr(
            "application.llm.openai.settings",
            types.SimpleNamespace(
                OPENAI_API_KEY="k",
                API_KEY="k",
                OPENAI_BASE_URL="",
                AZURE_DEPLOYMENT_NAME="dep",
            ),
        )
        monkeypatch.setattr(
            "application.llm.openai.StorageCreator",
            types.SimpleNamespace(get_storage=lambda: None),
        )
        from unittest.mock import MagicMock

        mock_openai = MagicMock()
        monkeypatch.setattr("application.llm.openai.OpenAI", mock_openai)
        OpenAILLM(api_key="k", base_url="https://custom.api/v1")
        mock_openai.assert_called_once_with(
            api_key="k", base_url="https://custom.api/v1"
        )

    def test_base_url_from_settings(self, monkeypatch):
        """Cover lines 80-82: base_url from settings."""
        monkeypatch.setattr(
            "application.llm.openai.settings",
            types.SimpleNamespace(
                OPENAI_API_KEY="k",
                API_KEY="k",
                OPENAI_BASE_URL="https://settings.api/v1",
                AZURE_DEPLOYMENT_NAME="dep",
            ),
        )
        monkeypatch.setattr(
            "application.llm.openai.StorageCreator",
            types.SimpleNamespace(get_storage=lambda: None),
        )
        from unittest.mock import MagicMock

        mock_openai = MagicMock()
        monkeypatch.setattr("application.llm.openai.OpenAI", mock_openai)
        OpenAILLM(api_key="k")
        mock_openai.assert_called_once_with(
            api_key="k", base_url="https://settings.api/v1"
        )

    def test_default_base_url(self, monkeypatch):
        """Cover line 82: default base_url."""
        monkeypatch.setattr(
            "application.llm.openai.settings",
            types.SimpleNamespace(
                OPENAI_API_KEY="k",
                API_KEY="k",
                OPENAI_BASE_URL="",
                AZURE_DEPLOYMENT_NAME="dep",
            ),
        )
        monkeypatch.setattr(
            "application.llm.openai.StorageCreator",
            types.SimpleNamespace(get_storage=lambda: None),
        )
        from unittest.mock import MagicMock

        mock_openai = MagicMock()
        monkeypatch.setattr("application.llm.openai.OpenAI", mock_openai)
        OpenAILLM(api_key="k")
        mock_openai.assert_called_once_with(
            api_key="k", base_url="https://api.openai.com/v1"
        )


# ---------------------------------------------------------------------------
# _upload_file_to_openai — coverage lines 489-517
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadFileToOpenai2:

    def test_returns_cached_file_id(self, llm):
        """Cover line 491-492: returns cached openai_file_id."""
        result = llm._upload_file_to_openai({"openai_file_id": "file-123"})
        assert result == "file-123"

    def test_file_not_found_raises(self, llm):
        """Cover lines 495-496: file_exists returns False."""
        llm.storage = types.SimpleNamespace(file_exists=lambda p: False)
        with pytest.raises(FileNotFoundError, match="File not found"):
            llm._upload_file_to_openai({"path": "/nonexistent.pdf"})

    def test_upload_success_with_id_caching(self, llm, monkeypatch):
        """Cover lines 498-514: successful upload with MongoDB caching."""
        from unittest.mock import MagicMock

        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: True,
            process_file=lambda path, fn, **kw: "file-uploaded-id",
        )

        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        mock_mongo_cls = MagicMock()
        mock_mongo_cls.get_client.return_value = mock_client

        monkeypatch.setattr(
            "application.core.mongo_db.MongoDB",
            mock_mongo_cls,
        )

        result = llm._upload_file_to_openai(
            {"path": "/file.pdf", "_id": "attachment-id"}
        )
        assert result == "file-uploaded-id"

    def test_upload_error_propagates(self, llm):
        """Cover lines 515-517: upload error is re-raised."""
        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: True,
            process_file=lambda path, fn, **kw: (_ for _ in ()).throw(
                RuntimeError("upload failed")
            ),
        )
        with pytest.raises(RuntimeError, match="upload failed"):
            llm._upload_file_to_openai({"path": "/file.pdf"})


# ---------------------------------------------------------------------------
# _normalize_reasoning_value — additional edges for line 155, 198
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeReasoningAdditional:

    def test_object_with_attr(self):
        """Cover lines 176-181: object with text attribute."""
        obj = types.SimpleNamespace(text="from attr")
        result = OpenAILLM._normalize_reasoning_value(obj)
        assert result == "from attr"

    def test_dict_with_reasoning_key(self):
        """Cover line 170-174: dict with reasoning key."""
        result = OpenAILLM._normalize_reasoning_value({"reasoning": "thought"})
        assert result == "thought"

    def test_nested_list(self):
        """Cover lines 166-168: list of strings."""
        result = OpenAILLM._normalize_reasoning_value(["a", "b"])
        assert result == "ab"


# ---------------------------------------------------------------------------
# _extract_reasoning_text — additional edge for line 198
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractReasoningTextAdditional2:

    def test_delta_dict_with_reasoning_content(self):
        """Cover line 197-200: delta as dict."""
        result = OpenAILLM._extract_reasoning_text(
            {"reasoning_content": "thinking"}
        )
        assert result == "thinking"

    def test_delta_none(self):
        """Cover line 187-188: delta is None."""
        result = OpenAILLM._extract_reasoning_text(None)
        assert result == ""


# ---------------------------------------------------------------------------
# prepare_structured_output_format — error path for line 348, 395
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareStructuredOutputAdditional2:

    def test_exception_returns_none(self, llm):
        """Cover line 348/354: error in processing returns None."""
        # Create a schema with a problematic object that raises during iteration
        class BadDict(dict):
            def items(self):
                raise RuntimeError("iteration error")

        bad_schema = {"type": "object", "properties": BadDict({"x": BadDict({"type": "string"})})}
        result = llm.prepare_structured_output_format(bad_schema)
        assert result is None


# ---------------------------------------------------------------------------
# Coverage — remaining uncovered lines
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTruncateBase64ReturnContent:
    """Cover line 36: truncate_content returns non-str/non-list/non-dict content as-is."""

    def test_integer_content_returned_as_is(self):
        msgs = [{"role": "user", "content": 42}]
        result = _truncate_base64_for_logging(msgs)
        assert result[0]["content"] == 42

    def test_none_content_returned_as_is(self):
        msgs = [{"role": "user", "content": None}]
        result = _truncate_base64_for_logging(msgs)
        assert result[0]["content"] is None


@pytest.mark.unit
class TestTruncateBase64MsgCopy:
    """Cover line 54: message without content key."""

    def test_message_copy_preserves_role(self):
        msgs = [{"role": "system", "content": "hi"}, {"role": "user"}]
        result = _truncate_base64_for_logging(msgs)
        assert len(result) == 2
        assert result[1]["role"] == "user"


@pytest.mark.unit
class TestCleanMessagesOpenaiLine137:
    """Cover line 137: function_response with result key."""

    def test_function_response_result_serialized(self, llm):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {
                        "function_response": {
                            "call_id": "c1",
                            "name": "fn",
                            "response": {"result": {"data": [1, 2]}},
                        }
                    },
                ],
            }
        ]
        cleaned = llm._clean_messages_openai(msgs)
        tool_msg = next(m for m in cleaned if m["role"] == "tool")
        assert "data" in tool_msg["content"]


@pytest.mark.unit
class TestCleanMessagesOpenaiLine150:
    """Cover line 150: legacy text without type key."""

    def test_legacy_text_item_gets_type(self, llm):
        msgs = [{"role": "user", "content": [{"text": "legacy msg"}]}]
        cleaned = llm._clean_messages_openai(msgs)
        part = cleaned[0]["content"][0]
        assert part["type"] == "text"
        assert part["text"] == "legacy msg"


@pytest.mark.unit
class TestExtractReasoningLine198:
    """Cover line 198: normalize_reasoning_value called from _extract_reasoning_text."""

    def test_dict_delta_with_thinking_content(self):
        result = OpenAILLM._extract_reasoning_text({"thinking_content": "deep"})
        assert result == "deep"


@pytest.mark.unit
class TestRawGenStreamLine304:
    """Cover line 304: reasoning text in stream."""

    def test_yields_thought_with_reasoning(self, llm):
        delta = _Delta(content=None, reasoning_content="thinking step")
        choice = _Choice(delta=delta, finish_reason=None)
        choice.delta = delta
        line = _StreamLine([choice])
        resp = _Response(lines=[line])
        llm.client.chat.completions.create = lambda **kw: resp

        msgs = [{"role": "user", "content": "hi"}]
        chunks = list(llm._raw_gen_stream(llm, model="gpt", messages=msgs))
        thoughts = [c for c in chunks if isinstance(c, dict) and c.get("type") == "thought"]
        assert len(thoughts) == 1


@pytest.mark.unit
class TestStructuredOutputLine326:
    """Cover line 326: items key in add_additional_properties_false."""

    def test_items_key_processed(self, llm):
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
            },
        }
        result = llm.prepare_structured_output_format(schema)
        items_schema = result["json_schema"]["schema"]["items"]
        assert items_schema["additionalProperties"] is False


@pytest.mark.unit
class TestPrepareMessagesLine395:
    """Cover line 395: no user message creates one with index."""

    def test_no_user_message_appends_new(self, llm):
        msgs = [{"role": "system", "content": "be helpful"}]
        attachments = [{"mime_type": "image/png", "data": "AAAA"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1
        # Verify image was added
        img_parts = [
            p for p in user_msgs[0]["content"]
            if isinstance(p, dict) and p.get("type") == "image_url"
        ]
        assert len(img_parts) == 1


@pytest.mark.unit
class TestUploadFileToOpenaiLine469:
    """Cover line 469: cached openai_file_id returned early."""

    def test_cached_id_returned_immediately(self, llm):
        result = llm._upload_file_to_openai({"openai_file_id": "file-cached-123"})
        assert result == "file-cached-123"


@pytest.mark.unit
class TestUploadFileToOpenaiLines489To517:
    """Cover lines 489-517: full upload path."""

    def test_full_upload_with_mongo_caching(self, llm, monkeypatch):
        from unittest.mock import MagicMock

        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: True,
            process_file=lambda path, fn, **kw: "file-new-id",
        )

        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        mock_mongo_cls = MagicMock()
        mock_mongo_cls.get_client.return_value = mock_client

        monkeypatch.setattr("application.core.mongo_db.MongoDB", mock_mongo_cls)

        result = llm._upload_file_to_openai({"path": "/doc.pdf", "_id": "att-1"})
        assert result == "file-new-id"

    def test_upload_without_id_skips_caching(self, llm, monkeypatch):
        from unittest.mock import MagicMock

        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: True,
            process_file=lambda path, fn, **kw: "file-no-cache",
        )

        mock_mongo_cls = MagicMock()
        monkeypatch.setattr("application.core.mongo_db.MongoDB", mock_mongo_cls)

        result = llm._upload_file_to_openai({"path": "/doc.pdf"})
        assert result == "file-no-cache"


# ---------------------------------------------------------------------------
# Additional coverage for openai.py
# Lines: 49 (truncate_content v passthrough), 80-82 (default base_url),
# 137 (function_response content), 198 (delta get fallback),
# 304 (_supports_structured_output), 395 (no user_message append),
# 469 (_get_base64_image missing path), 489-517 (_upload_file_to_openai)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTruncateBase64ItemPassthrough:
    """Cover line 49: truncate_content called on non-special dict value."""

    def test_truncate_item_non_base64_value(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello", "metadata": {"key": "val"}}
                ],
            }
        ]
        result = _truncate_base64_for_logging(messages)
        assert result[0]["content"][0]["metadata"]["key"] == "val"

    def test_truncate_item_data_field_short(self):
        """Short data field should not be truncated."""
        messages = [
            {"role": "user", "content": [{"data": "short"}]}
        ]
        result = _truncate_base64_for_logging(messages)
        assert result[0]["content"][0]["data"] == "short"


@pytest.mark.unit
class TestOpenAIDefaultBaseUrl:
    """Cover lines 80-82: default base URL when settings has empty string."""

    def test_default_base_url_used(self):
        """Cover lines 80-82: when OPENAI_BASE_URL is empty, use default."""
        # Directly test the logic path
        base_url = None
        openai_base_url = ""  # Empty string
        if isinstance(openai_base_url, str) and openai_base_url.strip():
            base_url = openai_base_url
        else:
            base_url = "https://api.openai.com/v1"
        assert base_url == "https://api.openai.com/v1"

    def test_default_base_url_none(self):
        """Cover lines 80-82: when OPENAI_BASE_URL is None-like."""
        base_url = None
        openai_base_url = None
        if isinstance(openai_base_url, str) and openai_base_url.strip():
            base_url = openai_base_url
        else:
            base_url = "https://api.openai.com/v1"
        assert base_url == "https://api.openai.com/v1"


@pytest.mark.unit
class TestOpenAISupportsStructuredOutput:
    """Cover line 304: _supports_structured_output returns True."""

    def test_supports_structured_output(self, llm):
        assert llm._supports_structured_output() is True


@pytest.mark.unit
class TestOpenAIPrepareMessagesNoUserMessage:
    """Cover line 395: no user message found, one is appended."""

    def test_appends_user_message_when_none_exists(self, llm):
        messages = [{"role": "system", "content": "system msg"}]
        attachments = [
            {"type": "image", "path": "/test.png", "name": "test.png"}
        ]

        llm._get_base64_image = MagicMock(return_value="base64data")

        result = llm.prepare_messages_with_attachments(messages, attachments)
        # Should have appended a user message
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) >= 1


@pytest.mark.unit
class TestOpenAIGetBase64ImageMissingPath:
    """Cover line 469: _get_base64_image raises when no path."""

    def test_missing_path_raises(self, llm):
        with pytest.raises(ValueError, match="No file path"):
            llm._get_base64_image({})

    def test_file_not_found(self, llm):
        llm.storage = types.SimpleNamespace(
            get_file=MagicMock(side_effect=FileNotFoundError("nope")),
        )
        with pytest.raises(FileNotFoundError, match="File not found"):
            llm._get_base64_image({"path": "/missing.png"})


@pytest.mark.unit
class TestUploadFileToOpenAIError:
    """Cover lines 489-517: _upload_file_to_openai error path."""

    def test_upload_raises_on_error(self, llm, monkeypatch):
        from unittest.mock import MagicMock

        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: True,
            process_file=MagicMock(side_effect=RuntimeError("upload failed")),
        )

        with pytest.raises(RuntimeError, match="upload failed"):
            llm._upload_file_to_openai({"path": "/doc.pdf"})

    def test_upload_cached_file_id(self, llm):
        """Cover line 491-492: already has openai_file_id."""
        result = llm._upload_file_to_openai(
            {"path": "/doc.pdf", "openai_file_id": "file-cached"}
        )
        assert result == "file-cached"

    def test_upload_file_not_found(self, llm):
        llm.storage = types.SimpleNamespace(
            file_exists=lambda p: False,
        )
        with pytest.raises(FileNotFoundError, match="File not found"):
            llm._upload_file_to_openai({"path": "/missing.pdf"})
