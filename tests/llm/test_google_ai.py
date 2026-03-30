"""Unit tests for application/llm/google_ai.py — GoogleLLM.

Extends coverage beyond test_google_llm.py:
  - _clean_messages_google: system instructions, function responses, errors
  - _clean_schema: field filtering, type uppercasing, required validation
  - _clean_tools_format: empty properties, required fields
  - _extract_preview_from_message: various message shapes
  - _summarize_messages_for_log
  - _get_text_value / _is_thought_part: dict vs object forms
  - _raw_gen with tools and response_schema
  - _raw_gen_stream: function_call parts, thought parts, error handling
  - prepare_structured_output_format: comprehensive type mapping
  - prepare_messages_with_attachments: error handling
  - _upload_file_to_google
  - get_supported_attachment_types
"""

import types

import pytest

from application.llm.google_ai import GoogleLLM


# ---------------------------------------------------------------------------
# Fake types module for Google AI
# ---------------------------------------------------------------------------


class _FakePart:
    def __init__(self, text=None, function_call=None, file_data=None, thought=False):
        self.text = text
        self.function_call = function_call
        self.file_data = file_data
        self.thought = thought

    @staticmethod
    def from_text(text):
        return _FakePart(text=text)

    @staticmethod
    def from_function_call(name, args):
        return _FakePart(function_call=types.SimpleNamespace(name=name, args=args))

    @staticmethod
    def from_function_response(name, response):
        return _FakePart(text=str(response))

    @staticmethod
    def from_uri(file_uri, mime_type):
        return _FakePart(
            file_data=types.SimpleNamespace(file_uri=file_uri, mime_type=mime_type)
        )


class _FakeContent:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts


class FakeTypesModule:
    Part = _FakePart
    Content = _FakeContent

    class GenerateContentConfig:
        def __init__(self):
            self.system_instruction = None
            self.tools = None
            self.thinking_config = None
            self.response_schema = None
            self.response_mime_type = None

    class Tool:
        def __init__(self, function_declarations=None):
            self.function_declarations = function_declarations or []

    class FunctionCall:
        def __init__(self, name=None, args=None):
            self.name = name
            self.args = args


class FakeModels:
    def __init__(self):
        self.last_kwargs = None

    class _Resp:
        def __init__(self, text=None, candidates=None):
            self.text = text
            self.candidates = candidates or []

    def generate_content(self, *args, **kwargs):
        self.last_kwargs = kwargs
        return FakeModels._Resp(text="ok")

    def generate_content_stream(self, *args, **kwargs):
        self.last_kwargs = kwargs
        return []


class FakeClientFiles:
    def upload(self, file=None):
        return types.SimpleNamespace(uri="gs://fake-uri")


class FakeClient:
    def __init__(self, *a, **kw):
        self.models = FakeModels()
        self.files = FakeClientFiles()


@pytest.fixture(autouse=True)
def patch_google(monkeypatch):
    import application.llm.google_ai as gmod

    monkeypatch.setattr(gmod, "types", FakeTypesModule)
    monkeypatch.setattr(gmod.genai, "Client", FakeClient)


@pytest.fixture
def llm():
    instance = GoogleLLM(api_key="test-key")
    instance.storage = types.SimpleNamespace(
        file_exists=lambda p: True,
        process_file=lambda path, fn, **kw: fn(path),
    )
    return instance


# ---------------------------------------------------------------------------
# _clean_messages_google
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanMessagesGoogle:

    def test_system_message_extracted_as_instruction(self, llm):
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ]
        cleaned, sys_instr = llm._clean_messages_google(msgs)
        assert sys_instr == "You are helpful"
        assert all(c.role != "system" for c in cleaned)

    def test_multiple_system_messages_joined(self, llm):
        msgs = [
            {"role": "system", "content": "Rule 1"},
            {"role": "system", "content": "Rule 2"},
            {"role": "user", "content": "hi"},
        ]
        _, sys_instr = llm._clean_messages_google(msgs)
        assert "Rule 1" in sys_instr
        assert "Rule 2" in sys_instr

    def test_system_list_content(self, llm):
        msgs = [
            {"role": "system", "content": [{"text": "A"}, {"text": "B"}]},
            {"role": "user", "content": "hi"},
        ]
        _, sys_instr = llm._clean_messages_google(msgs)
        assert "A" in sys_instr and "B" in sys_instr

    def test_assistant_role_becomes_model(self, llm):
        msgs = [{"role": "assistant", "content": "hi"}]
        cleaned, _ = llm._clean_messages_google(msgs)
        assert cleaned[0].role == "model"

    def test_tool_role_becomes_model(self, llm):
        msgs = [{"role": "tool", "content": "result"}]
        cleaned, _ = llm._clean_messages_google(msgs)
        assert cleaned[0].role == "model"

    def test_function_call_in_content_list(self, llm):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"function_call": {"name": "fn", "args": {"x": 1}}},
                ],
            }
        ]
        cleaned, _ = llm._clean_messages_google(msgs)
        assert len(cleaned) == 1
        assert any(
            hasattr(p, "function_call") and p.function_call is not None
            for p in cleaned[0].parts
        )

    def test_function_response_in_content_list(self, llm):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {
                        "function_response": {
                            "name": "fn",
                            "response": {"result": 42},
                        }
                    },
                ],
            }
        ]
        cleaned, _ = llm._clean_messages_google(msgs)
        assert len(cleaned) == 1

    def test_files_in_content_list(self, llm):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"files": [{"file_uri": "gs://f", "mime_type": "image/png"}]},
                ],
            }
        ]
        cleaned, _ = llm._clean_messages_google(msgs)
        assert len(cleaned) == 1
        assert any(
            hasattr(p, "file_data") and p.file_data is not None
            for p in cleaned[0].parts
        )

    def test_unexpected_list_item_raises(self, llm):
        msgs = [{"role": "user", "content": [{"unknown_key": "val"}]}]
        with pytest.raises(ValueError, match="Unexpected content dictionary"):
            llm._clean_messages_google(msgs)

    def test_unexpected_content_type_raises(self, llm):
        msgs = [{"role": "user", "content": 12345}]
        with pytest.raises(ValueError, match="Unexpected content type"):
            llm._clean_messages_google(msgs)

    def test_no_system_instruction_returns_none(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        _, sys_instr = llm._clean_messages_google(msgs)
        assert sys_instr is None

    def test_empty_parts_skipped(self, llm):
        msgs = [{"role": "user", "content": None}]
        cleaned, _ = llm._clean_messages_google(msgs)
        assert len(cleaned) == 0


# ---------------------------------------------------------------------------
# _clean_schema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanSchema:

    def test_type_uppercased(self, llm):
        result = llm._clean_schema({"type": "string"})
        assert result["type"] == "STRING"

    def test_unsupported_fields_removed(self, llm):
        result = llm._clean_schema({"type": "string", "title": "Name", "$ref": "#/x"})
        assert "title" not in result
        assert "$ref" not in result
        assert result["type"] == "STRING"

    def test_nested_properties_cleaned(self, llm):
        # _clean_schema recursively cleans the properties dict value.
        # Property names that happen to match allowed_fields survive.
        # This tests the recursive cleaning on schema values.
        schema = {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
            },
        }
        result = llm._clean_schema(schema)
        # "type" is in allowed_fields, so the property survives as a key
        # Its value gets uppercased since it's a type field
        assert "properties" in result
        assert result["properties"]["type"]["type"] == "STRING"

    def test_required_validated_against_properties(self, llm):
        # Property names must be in allowed_fields to survive _clean_schema
        # "type" is in allowed_fields so it survives as a property key
        schema = {
            "type": "object",
            "properties": {"type": {"type": "string"}},
            "required": ["type", "nonexistent"],
        }
        result = llm._clean_schema(schema)
        assert result["required"] == ["type"]

    def test_required_removed_when_no_valid_entries(self, llm):
        schema = {
            "type": "object",
            "properties": {"type": {"type": "string"}},
            "required": ["nonexistent"],
        }
        result = llm._clean_schema(schema)
        assert "required" not in result

    def test_required_removed_when_no_properties(self, llm):
        schema = {"type": "string", "required": ["x"]}
        result = llm._clean_schema(schema)
        assert "required" not in result

    def test_non_dict_passthrough(self, llm):
        assert llm._clean_schema("hello") == "hello"
        assert llm._clean_schema(42) == 42

    def test_list_items_cleaned(self, llm):
        schema = {
            "type": "array",
            "items": {"type": "string", "title": "ignored"},
        }
        result = llm._clean_schema(schema)
        assert "title" not in result["items"]


# ---------------------------------------------------------------------------
# _clean_tools_format
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanToolsFormat:

    def test_basic_tool_conversion(self, llm):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ]
        result = llm._clean_tools_format(tools)
        assert len(result) == 1
        assert hasattr(result[0], "function_declarations")

    def test_tool_without_properties(self, llm):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "description": "Ping server",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = llm._clean_tools_format(tools)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _extract_preview_from_message / _summarize_messages_for_log
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMessagePreviewAndSummary:

    def test_preview_from_parts_text(self, llm):
        msg = types.SimpleNamespace(
            parts=[_FakePart(text="hello world")]
        )
        preview = llm._extract_preview_from_message(msg)
        assert preview == "hello world"

    def test_preview_from_function_call_part(self, llm):
        fc = types.SimpleNamespace(name="search")
        msg = types.SimpleNamespace(
            parts=[_FakePart(function_call=fc)]
        )
        preview = llm._extract_preview_from_message(msg)
        assert "search" in preview

    def test_preview_from_dict_string_content(self, llm):
        msg = {"content": "dict content"}
        preview = llm._extract_preview_from_message(msg)
        assert preview == "dict content"

    def test_preview_from_dict_list_content(self, llm):
        msg = {"content": [{"text": "list text"}]}
        preview = llm._extract_preview_from_message(msg)
        assert preview == "list text"

    def test_preview_from_dict_function_call(self, llm):
        msg = {"content": [{"function_call": {"name": "fn"}}]}
        preview = llm._extract_preview_from_message(msg)
        assert "fn" in preview

    def test_preview_from_dict_function_response(self, llm):
        msg = {"content": [{"function_response": {"name": "fn_resp"}}]}
        preview = llm._extract_preview_from_message(msg)
        assert "fn_resp" in preview

    def test_preview_fallback_to_str(self, llm):
        msg = 42
        preview = llm._extract_preview_from_message(msg)
        assert preview == "42"

    def test_summarize_messages_empty(self, llm):
        result = llm._summarize_messages_for_log([])
        assert "count=0" in result

    def test_summarize_messages_truncates(self, llm):
        msgs = [
            types.SimpleNamespace(parts=[_FakePart(text="a" * 100)])
        ]
        result = llm._summarize_messages_for_log(msgs, preview_chars=10)
        assert "..." in result


# ---------------------------------------------------------------------------
# _get_text_value / _is_thought_part
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStaticHelpers:

    def test_get_text_value_dict(self):
        assert GoogleLLM._get_text_value({"text": "hi"}) == "hi"

    def test_get_text_value_dict_no_text(self):
        assert GoogleLLM._get_text_value({"other": "x"}) == ""

    def test_get_text_value_dict_non_string(self):
        assert GoogleLLM._get_text_value({"text": 42}) == ""

    def test_get_text_value_object(self):
        obj = types.SimpleNamespace(text="obj_text")
        assert GoogleLLM._get_text_value(obj) == "obj_text"

    def test_get_text_value_object_no_text(self):
        obj = types.SimpleNamespace()
        assert GoogleLLM._get_text_value(obj) == ""

    def test_is_thought_part_dict_true(self):
        assert GoogleLLM._is_thought_part({"thought": True}) is True

    def test_is_thought_part_dict_false(self):
        assert GoogleLLM._is_thought_part({"thought": False}) is False

    def test_is_thought_part_object(self):
        obj = types.SimpleNamespace(thought=True)
        assert GoogleLLM._is_thought_part(obj) is True


# ---------------------------------------------------------------------------
# _raw_gen
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGen:

    def test_returns_text(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        result = llm._raw_gen(llm, model="gemini-2.0", messages=msgs)
        assert result == "ok"

    def test_with_tools_returns_response(self, llm):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "t",
                    "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        msgs = [{"role": "user", "content": "hi"}]
        result = llm._raw_gen(llm, model="gemini", messages=msgs, tools=tools)
        assert hasattr(result, "text")

    def test_with_response_schema(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        llm._raw_gen(
            llm,
            model="gemini",
            messages=msgs,
            response_schema={"type": "OBJECT"},
        )
        # Should not raise


# ---------------------------------------------------------------------------
# _raw_gen_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGenStream:

    def test_yields_text_from_candidates(self, llm, monkeypatch):
        part = types.SimpleNamespace(
            text="chunk1", function_call=None, thought=False
        )
        candidate = types.SimpleNamespace(
            content=types.SimpleNamespace(parts=[part])
        )
        chunk = types.SimpleNamespace(candidates=[candidate])

        monkeypatch.setattr(
            FakeModels,
            "generate_content_stream",
            lambda self, *a, **kw: [chunk],
        )

        msgs = [{"role": "user", "content": "hi"}]
        result = list(llm._raw_gen_stream(llm, model="gemini", messages=msgs))
        assert "chunk1" in result

    def test_yields_function_call_part(self, llm, monkeypatch):
        fc = types.SimpleNamespace(name="search")
        part = types.SimpleNamespace(
            text=None, function_call=fc, thought=False
        )
        candidate = types.SimpleNamespace(
            content=types.SimpleNamespace(parts=[part])
        )
        chunk = types.SimpleNamespace(candidates=[candidate])

        monkeypatch.setattr(
            FakeModels,
            "generate_content_stream",
            lambda self, *a, **kw: [chunk],
        )

        msgs = [{"role": "user", "content": "hi"}]
        result = list(llm._raw_gen_stream(llm, model="gemini", messages=msgs))
        assert any(hasattr(r, "function_call") for r in result)

    def test_yields_thought_event(self, llm, monkeypatch):
        part = types.SimpleNamespace(
            text="thinking", function_call=None, thought=True
        )
        candidate = types.SimpleNamespace(
            content=types.SimpleNamespace(parts=[part])
        )
        chunk = types.SimpleNamespace(candidates=[candidate])

        monkeypatch.setattr(
            FakeModels,
            "generate_content_stream",
            lambda self, *a, **kw: [chunk],
        )

        msgs = [{"role": "user", "content": "hi"}]
        result = list(llm._raw_gen_stream(llm, model="gemini", messages=msgs))
        assert {"type": "thought", "thought": "thinking"} in result

    def test_text_only_chunk_via_hasattr(self, llm, monkeypatch):
        chunk = types.SimpleNamespace(text="fallback", candidates=None, thought=False)

        monkeypatch.setattr(
            FakeModels,
            "generate_content_stream",
            lambda self, *a, **kw: [chunk],
        )

        msgs = [{"role": "user", "content": "hi"}]
        result = list(llm._raw_gen_stream(llm, model="gemini", messages=msgs))
        assert "fallback" in result

    def test_stream_error_propagates(self, llm, monkeypatch):
        def error_stream(self, *a, **kw):
            raise RuntimeError("stream_err")

        monkeypatch.setattr(FakeModels, "generate_content_stream", error_stream)

        msgs = [{"role": "user", "content": "hi"}]
        with pytest.raises(RuntimeError, match="stream_err"):
            list(llm._raw_gen_stream(llm, model="gemini", messages=msgs))

    def test_skips_empty_text_parts(self, llm, monkeypatch):
        part = types.SimpleNamespace(
            text="", function_call=None, thought=False
        )
        candidate = types.SimpleNamespace(
            content=types.SimpleNamespace(parts=[part])
        )
        chunk = types.SimpleNamespace(candidates=[candidate])

        monkeypatch.setattr(
            FakeModels,
            "generate_content_stream",
            lambda self, *a, **kw: [chunk],
        )

        msgs = [{"role": "user", "content": "hi"}]
        result = list(llm._raw_gen_stream(llm, model="gemini", messages=msgs))
        assert result == []


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

    def test_none_returns_none(self, llm):
        assert llm.prepare_structured_output_format(None) is None

    def test_type_mapping(self, llm):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
                "items": {"type": "array", "items": {"type": "string"}},
            },
        }
        result = llm.prepare_structured_output_format(schema)
        assert result["type"] == "OBJECT"
        assert result["properties"]["name"]["type"] == "STRING"
        assert result["properties"]["count"]["type"] == "INTEGER"
        assert result["properties"]["score"]["type"] == "NUMBER"
        assert result["properties"]["active"]["type"] == "BOOLEAN"
        assert result["properties"]["items"]["type"] == "ARRAY"

    def test_property_ordering_added(self, llm):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        }
        result = llm.prepare_structured_output_format(schema)
        assert "propertyOrdering" in result
        assert set(result["propertyOrdering"]) == {"a", "b"}

    def test_format_date_converted(self, llm):
        schema = {"type": "string", "format": "date"}
        result = llm.prepare_structured_output_format(schema)
        assert result["format"] == "date-time"

    def test_format_datetime_preserved(self, llm):
        schema = {"type": "string", "format": "date-time"}
        result = llm.prepare_structured_output_format(schema)
        assert result["format"] == "date-time"

    def test_anyof_processed(self, llm):
        schema = {
            "anyOf": [
                {"type": "string"},
                {"type": "integer"},
            ]
        }
        result = llm.prepare_structured_output_format(schema)
        assert len(result["anyOf"]) == 2
        assert result["anyOf"][0]["type"] == "STRING"


# ---------------------------------------------------------------------------
# get_supported_attachment_types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSupportedAttachmentTypes:

    def test_returns_list_with_expected_types(self, llm):
        result = llm.get_supported_attachment_types()
        assert "application/pdf" in result
        assert "image/png" in result
        assert "image/jpeg" in result


# ---------------------------------------------------------------------------
# prepare_messages_with_attachments
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareMessagesWithAttachments:

    def test_no_attachments_returns_same(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        result = llm.prepare_messages_with_attachments(msgs)
        assert result == msgs

    def test_upload_error_adds_text_fallback(self, llm, monkeypatch):
        monkeypatch.setattr(
            llm, "_upload_file_to_google", lambda a: (_ for _ in ()).throw(Exception("fail"))
        )
        msgs = [{"role": "user", "content": "hi"}]
        attachments = [
            {"mime_type": "image/png", "path": "/tmp/img.png", "content": "fallback"},
        ]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        text_parts = [
            p for p in user_msg["content"]
            if isinstance(p, dict) and p.get("type") == "text" and "could not" in p.get("text", "").lower()
        ]
        assert len(text_parts) == 1

    def test_no_user_message_creates_one(self, llm, monkeypatch):
        monkeypatch.setattr(llm, "_upload_file_to_google", lambda a: "gs://uri")
        msgs = [{"role": "system", "content": "sys"}]
        attachments = [{"mime_type": "image/png", "path": "/img.png"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1


# ---------------------------------------------------------------------------
# _upload_file_to_google
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadFileToGoogle:

    def test_returns_cached_uri(self, llm):
        attachment = {"google_file_uri": "gs://cached"}
        result = llm._upload_file_to_google(attachment)
        assert result == "gs://cached"

    def test_raises_for_no_path(self, llm):
        with pytest.raises(ValueError, match="No file path"):
            llm._upload_file_to_google({})

    def test_raises_for_missing_file(self, llm):
        llm.storage = types.SimpleNamespace(file_exists=lambda p: False)
        with pytest.raises(FileNotFoundError):
            llm._upload_file_to_google({"path": "/nonexistent"})
