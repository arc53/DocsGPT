import sys

import pytest

from application.usage import (
    _count_prompt_tokens,
    _count_tokens,
    _serialize_for_token_count,
    gen_token_usage,
    stream_token_usage,
    update_token_usage,
)


@pytest.mark.unit
def test_count_tokens_includes_tool_call_payloads():
    payload = [
        {
            "function_call": {
                "name": "search_docs",
                "args": {"query": "pricing limits"},
                "call_id": "call_1",
            }
        },
        {
            "function_response": {
                "name": "search_docs",
                "response": {"result": "Found 3 docs"},
                "call_id": "call_1",
            }
        },
    ]

    assert _count_tokens(payload) > 0


@pytest.mark.unit
def test_gen_token_usage_counts_structured_tool_content(monkeypatch):
    captured = {}

    def fake_update(decoded_token, user_api_key, token_usage, agent_id=None):
        captured["decoded_token"] = decoded_token
        captured["user_api_key"] = user_api_key
        captured["token_usage"] = token_usage.copy()
        captured["agent_id"] = agent_id

    monkeypatch.setattr("application.usage.update_token_usage", fake_update)

    class DummyLLM:
        decoded_token = {"sub": "user_123"}
        user_api_key = "api_key_123"
        agent_id = "agent_123"
        token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    @gen_token_usage
    def wrapped(self, model, messages, stream, tools, **kwargs):
        _ = (model, messages, stream, tools, kwargs)
        return {
            "tool_calls": [
                {"name": "read_webpage", "arguments": {"url": "https://example.com"}}
            ]
        }

    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "function_call": {
                        "name": "search_docs",
                        "args": {"query": "pricing"},
                        "call_id": "1",
                    }
                }
            ],
        },
        {
            "role": "tool",
            "content": [
                {
                    "function_response": {
                        "name": "search_docs",
                        "response": {"result": "Found docs"},
                        "call_id": "1",
                    }
                }
            ],
        },
    ]

    llm = DummyLLM()
    wrapped(llm, "gpt-4o", messages, False, None)

    assert captured["decoded_token"] == {"sub": "user_123"}
    assert captured["user_api_key"] == "api_key_123"
    assert captured["agent_id"] == "agent_123"
    assert captured["token_usage"]["prompt_tokens"] > 0
    assert captured["token_usage"]["generated_tokens"] > 0


@pytest.mark.unit
def test_stream_token_usage_counts_tool_call_chunks(monkeypatch):
    captured = {}

    def fake_update(decoded_token, user_api_key, token_usage, agent_id=None):
        captured["token_usage"] = token_usage.copy()
        captured["agent_id"] = agent_id

    monkeypatch.setattr("application.usage.update_token_usage", fake_update)

    class ToolChunk:
        def model_dump(self):
            return {
                "delta": {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location":"Seattle"}',
                            },
                        }
                    ]
                }
            }

    class DummyLLM:
        decoded_token = {"sub": "user_123"}
        user_api_key = "api_key_123"
        agent_id = "agent_123"
        token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    @stream_token_usage
    def wrapped(self, model, messages, stream, tools, **kwargs):
        _ = (model, messages, stream, tools, kwargs)
        yield ToolChunk()
        yield "done"

    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "function_call": {
                        "name": "get_weather",
                        "args": {"location": "Seattle"},
                        "call_id": "1",
                    }
                }
            ],
        }
    ]

    llm = DummyLLM()
    list(wrapped(llm, "gpt-4o", messages, True, None))

    assert captured["agent_id"] == "agent_123"
    assert captured["token_usage"]["prompt_tokens"] > 0
    assert captured["token_usage"]["generated_tokens"] > 0


@pytest.mark.unit
def test_gen_token_usage_counts_tools_and_image_inputs(monkeypatch):
    captured = []

    def fake_update(decoded_token, user_api_key, token_usage, agent_id=None):
        _ = (decoded_token, user_api_key, agent_id)
        captured.append(token_usage.copy())

    monkeypatch.setattr("application.usage.update_token_usage", fake_update)

    class DummyLLM:
        decoded_token = {"sub": "user_123"}
        user_api_key = "api_key_123"
        agent_id = "agent_123"
        token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    @gen_token_usage
    def wrapped(self, model, messages, stream, tools, **kwargs):
        _ = (model, messages, stream, tools, kwargs)
        return "ok"

    messages = [{"role": "user", "content": "What is in this image?"}]
    tools_payload = [
        {
            "type": "function",
            "function": {
                "name": "describe_image",
                "description": "Describe image content",
                "parameters": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            },
        }
    ]
    usage_attachments = [
        {
            "mime_type": "image/png",
            "path": "attachments/example.png",
            "data": "abc123",
        }
    ]

    llm = DummyLLM()
    wrapped(llm, "gpt-4o", messages, False, None)
    wrapped(
        llm,
        "gpt-4o",
        messages,
        False,
        tools_payload,
        _usage_attachments=usage_attachments,
    )

    assert len(captured) == 2
    assert captured[1]["prompt_tokens"] > captured[0]["prompt_tokens"]


@pytest.mark.unit
def test_stream_token_usage_counts_tools_and_image_inputs(monkeypatch):
    captured = []

    def fake_update(decoded_token, user_api_key, token_usage, agent_id=None):
        _ = (decoded_token, user_api_key, agent_id)
        captured.append(token_usage.copy())

    monkeypatch.setattr("application.usage.update_token_usage", fake_update)

    class DummyLLM:
        decoded_token = {"sub": "user_123"}
        user_api_key = "api_key_123"
        agent_id = "agent_123"
        token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    @stream_token_usage
    def wrapped(self, model, messages, stream, tools, **kwargs):
        _ = (model, messages, stream, tools, kwargs)
        yield "ok"

    messages = [{"role": "user", "content": "What is in this image?"}]
    tools_payload = [
        {
            "type": "function",
            "function": {
                "name": "describe_image",
                "description": "Describe image content",
                "parameters": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            },
        }
    ]
    usage_attachments = [
        {
            "mime_type": "image/png",
            "path": "attachments/example.png",
            "data": "abc123",
        }
    ]

    llm = DummyLLM()
    list(wrapped(llm, "gpt-4o", messages, True, None))
    list(
        wrapped(
            llm,
            "gpt-4o",
            messages,
            True,
            tools_payload,
            _usage_attachments=usage_attachments,
        )
    )

    assert len(captured) == 2
    assert captured[1]["prompt_tokens"] > captured[0]["prompt_tokens"]


@pytest.mark.unit
def test_update_token_usage_inserts_with_agent_id_only(monkeypatch):
    inserted_docs = []

    class FakeCollection:
        def insert_one(self, doc):
            inserted_docs.append(doc)

    modules_without_pytest = dict(sys.modules)
    modules_without_pytest.pop("pytest", None)

    monkeypatch.setattr("application.usage.sys.modules", modules_without_pytest)
    monkeypatch.setattr("application.usage.usage_collection", FakeCollection())

    update_token_usage(
        decoded_token=None,
        user_api_key=None,
        token_usage={"prompt_tokens": 10, "generated_tokens": 5},
        agent_id="agent_123",
    )

    assert len(inserted_docs) == 1
    assert inserted_docs[0]["agent_id"] == "agent_123"
    assert inserted_docs[0]["user_id"] is None
    assert inserted_docs[0]["api_key"] is None


@pytest.mark.unit
def test_update_token_usage_skips_when_all_ids_missing(monkeypatch):
    inserted_docs = []

    class FakeCollection:
        def insert_one(self, doc):
            inserted_docs.append(doc)

    modules_without_pytest = dict(sys.modules)
    modules_without_pytest.pop("pytest", None)

    monkeypatch.setattr("application.usage.sys.modules", modules_without_pytest)
    monkeypatch.setattr("application.usage.usage_collection", FakeCollection())

    update_token_usage(
        decoded_token=None,
        user_api_key=None,
        token_usage={"prompt_tokens": 10, "generated_tokens": 5},
        agent_id=None,
    )

    assert inserted_docs == []


# ── _serialize_for_token_count ──────────────────────────────────────────────


@pytest.mark.unit
class TestSerializeForTokenCount:

    def test_string_passthrough(self):
        assert _serialize_for_token_count("hello") == "hello"

    def test_data_url_returns_empty(self):
        data_url = "data:image/png;base64,iVBORw0KGgoAAAA..."
        assert _serialize_for_token_count(data_url) == ""

    def test_none_returns_empty(self):
        assert _serialize_for_token_count(None) == ""

    def test_list_recursion(self):
        result = _serialize_for_token_count(["hello", "world"])
        assert result == ["hello", "world"]

    def test_dict_skips_binary_fields(self):
        data = {
            "text": "hello",
            "data": "binary_stuff",
            "base64": "encoded_data",
            "image_data": "img_bytes",
        }
        result = _serialize_for_token_count(data)
        assert "text" in result
        assert "data" not in result
        assert "base64" not in result
        assert "image_data" not in result

    def test_dict_skips_base64_url(self):
        data = {"url": "data:image/png;base64,abc123"}
        result = _serialize_for_token_count(data)
        assert "url" not in result

    def test_dict_keeps_normal_url(self):
        data = {"url": "https://example.com/image.png"}
        result = _serialize_for_token_count(data)
        assert "url" in result

    def test_object_with_model_dump(self):
        class PydanticLike:
            def model_dump(self):
                return {"key": "value"}

        result = _serialize_for_token_count(PydanticLike())
        assert result == {"key": "value"}

    def test_object_with_to_dict(self):
        class DictLike:
            def to_dict(self):
                return {"key": "value"}

        result = _serialize_for_token_count(DictLike())
        assert result == {"key": "value"}

    def test_object_with_dict_attr(self):
        class SimpleObj:
            def __init__(self):
                self.name = "test"

        result = _serialize_for_token_count(SimpleObj())
        assert result == {"name": "test"}

    def test_number_to_string(self):
        assert _serialize_for_token_count(42) == "42"

    def test_nested_dict_with_list(self):
        data = {"items": ["a", "b"], "nested": {"key": "val"}}
        result = _serialize_for_token_count(data)
        assert result["items"] == ["a", "b"]
        assert result["nested"] == {"key": "val"}


# ── _count_tokens ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCountTokens:

    def test_none_returns_zero(self):
        assert _count_tokens(None) == 0

    def test_empty_string_returns_zero(self):
        assert _count_tokens("") == 0

    def test_data_url_returns_zero(self):
        data_url = "data:image/png;base64,iVBORw0KGgoAAAA..."
        assert _count_tokens(data_url) == 0

    def test_dict_counts(self):
        assert _count_tokens({"key": "some text here"}) > 0

    def test_list_counts(self):
        assert _count_tokens(["some text", "more text"]) > 0


# ── _count_prompt_tokens ────────────────────────────────────────────────────


@pytest.mark.unit
class TestCountPromptTokens:

    def test_empty_messages(self):
        assert _count_prompt_tokens([], tools=None) == 0

    def test_none_messages(self):
        assert _count_prompt_tokens(None, tools=None) == 0

    def test_dict_messages(self):
        messages = [{"content": "Hello world"}]
        tokens = _count_prompt_tokens(messages, tools=None)
        assert tokens > 0

    def test_non_dict_messages(self):
        class MessageObj:
            def __init__(self):
                self.content = "Hello world"

        messages = [MessageObj()]
        tokens = _count_prompt_tokens(messages, tools=None)
        assert tokens > 0

    def test_with_tools(self):
        messages = [{"content": "Hello"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "parameters": {"type": "object"},
                },
            }
        ]
        tokens_without = _count_prompt_tokens(messages, tools=None)
        tokens_with = _count_prompt_tokens(messages, tools=tools)
        assert tokens_with > tokens_without

    def test_with_usage_attachments(self):
        messages = [{"content": "Hello"}]
        attachments = [{"mime_type": "text/plain", "content": "file data"}]
        tokens_without = _count_prompt_tokens(messages, tools=None)
        tokens_with = _count_prompt_tokens(
            messages, tools=None, usage_attachments=attachments
        )
        assert tokens_with > tokens_without

    def test_with_response_format(self):
        messages = [{"content": "Hello"}]
        tokens_without = _count_prompt_tokens(messages, tools=None)
        tokens_with = _count_prompt_tokens(
            messages, tools=None, response_format={"type": "json_object"}
        )
        assert tokens_with > tokens_without

    def test_message_with_tool_calls_field(self):
        messages = [
            {
                "content": "Hello",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "test", "arguments": "{}"}}
                ],
            }
        ]
        tokens = _count_prompt_tokens(messages, tools=None)
        assert tokens > 0

    def test_message_with_tool_call_id(self):
        messages = [
            {
                "content": "Result of tool",
                "tool_call_id": "call_1",
            }
        ]
        tokens = _count_prompt_tokens(messages, tools=None)
        assert tokens > 0


# ── update_token_usage edge cases ───────────────────────────────────────────


@pytest.mark.unit
def test_update_token_usage_with_user_api_key(monkeypatch):
    inserted_docs = []

    class FakeCollection:
        def insert_one(self, doc):
            inserted_docs.append(doc)

    modules_without_pytest = dict(sys.modules)
    modules_without_pytest.pop("pytest", None)

    monkeypatch.setattr("application.usage.sys.modules", modules_without_pytest)
    monkeypatch.setattr("application.usage.usage_collection", FakeCollection())

    update_token_usage(
        decoded_token=None,
        user_api_key="api-key-123",
        token_usage={"prompt_tokens": 10, "generated_tokens": 5},
        agent_id=None,
    )

    assert len(inserted_docs) == 1
    assert inserted_docs[0]["api_key"] == "api-key-123"
    assert inserted_docs[0]["user_id"] is None
    assert "agent_id" not in inserted_docs[0]


@pytest.mark.unit
def test_update_token_usage_with_decoded_token(monkeypatch):
    inserted_docs = []

    class FakeCollection:
        def insert_one(self, doc):
            inserted_docs.append(doc)

    modules_without_pytest = dict(sys.modules)
    modules_without_pytest.pop("pytest", None)

    monkeypatch.setattr("application.usage.sys.modules", modules_without_pytest)
    monkeypatch.setattr("application.usage.usage_collection", FakeCollection())

    update_token_usage(
        decoded_token={"sub": "user-abc"},
        user_api_key=None,
        token_usage={"prompt_tokens": 20, "generated_tokens": 10},
        agent_id=None,
    )

    assert len(inserted_docs) == 1
    assert inserted_docs[0]["user_id"] == "user-abc"


@pytest.mark.unit
def test_update_token_usage_non_dict_decoded_token(monkeypatch):
    inserted_docs = []

    class FakeCollection:
        def insert_one(self, doc):
            inserted_docs.append(doc)

    modules_without_pytest = dict(sys.modules)
    modules_without_pytest.pop("pytest", None)

    monkeypatch.setattr("application.usage.sys.modules", modules_without_pytest)
    monkeypatch.setattr("application.usage.usage_collection", FakeCollection())

    update_token_usage(
        decoded_token="not-a-dict",
        user_api_key="key",
        token_usage={"prompt_tokens": 5, "generated_tokens": 3},
        agent_id=None,
    )

    assert len(inserted_docs) == 1
    assert inserted_docs[0]["user_id"] is None
