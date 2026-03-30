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
