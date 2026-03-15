import sys

import pytest

from application.usage import (
    _count_tokens,
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
