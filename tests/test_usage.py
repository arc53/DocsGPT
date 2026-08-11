from contextlib import contextmanager

import pytest

from application.usage import (
    _count_prompt_tokens,
    _count_tokens,
    _serialize_for_token_count,
    gen_token_usage,
    stream_token_usage,
)


class _FakeTokenUsageRepo:
    """In-memory stand-in for TokenUsageRepository used by the usage tests."""

    last_instance = None

    def __init__(self, conn=None):
        self.inserted = []
        _FakeTokenUsageRepo.last_instance = self

    def insert(self, **kwargs):
        self.inserted.append(kwargs)


@contextmanager
def _fake_db_session():
    yield None


def _install_fake_token_repo(monkeypatch):
    """Replace TokenUsageRepository + db_session with in-memory stubs."""
    _FakeTokenUsageRepo.last_instance = None
    monkeypatch.setattr(
        "application.usage.TokenUsageRepository", _FakeTokenUsageRepo
    )
    monkeypatch.setattr("application.usage.db_session", _fake_db_session)


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
def test_gen_token_usage_writes_row_per_call(monkeypatch):
    """Always-on persistence: every decorated ``gen`` call writes one row."""
    _install_fake_token_repo(monkeypatch)

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

    inserted = _FakeTokenUsageRepo.last_instance.inserted
    assert len(inserted) == 1
    assert inserted[0]["user_id"] == "user_123"
    assert inserted[0]["api_key"] == "api_key_123"
    assert inserted[0]["agent_id"] == "agent_123"
    assert inserted[0]["prompt_tokens"] > 0
    assert inserted[0]["generated_tokens"] > 0
    # Default source for unmarked LLMs.
    assert inserted[0]["source"] == "agent_stream"
    # Running totals also accumulate on the LLM instance.
    assert llm.token_usage["prompt_tokens"] > 0
    assert llm.token_usage["generated_tokens"] > 0


@pytest.mark.unit
def test_stream_token_usage_writes_row_per_call(monkeypatch):
    """Stream variant: same per-call write as ``gen``."""
    _install_fake_token_repo(monkeypatch)

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

    inserted = _FakeTokenUsageRepo.last_instance.inserted
    assert len(inserted) == 1
    assert inserted[0]["prompt_tokens"] > 0
    assert inserted[0]["generated_tokens"] > 0
    assert llm.token_usage["prompt_tokens"] > 0
    assert llm.token_usage["generated_tokens"] > 0


@pytest.mark.unit
def test_decorator_propagates_request_id_and_source(monkeypatch):
    """``_request_id`` + ``_token_usage_source`` on the LLM ride along
    with the row insert so DISTINCT counts and source filters work."""
    _install_fake_token_repo(monkeypatch)

    class TitleLLM:
        decoded_token = {"sub": "u"}
        user_api_key = "ak"
        agent_id = "agent"
        token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        _token_usage_source = "title"
        _request_id = "req-abc-123"

    @gen_token_usage
    def wrapped(self, model, messages, stream, tools, **kwargs):
        _ = (model, messages, stream, tools, kwargs)
        return "title"

    wrapped(TitleLLM(), "m", [{"role": "user", "content": "hi"}], False, None)

    inserted = _FakeTokenUsageRepo.last_instance.inserted
    assert len(inserted) == 1
    assert inserted[0]["source"] == "title"
    assert inserted[0]["request_id"] == "req-abc-123"


@pytest.mark.unit
def test_decorator_skips_zero_token_calls(monkeypatch):
    """Per-call write skipped when both counts are zero (e.g., empty result)."""
    _install_fake_token_repo(monkeypatch)

    class EmptyLLM:
        decoded_token = {"sub": "u"}
        user_api_key = "ak"
        agent_id = None
        token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    @gen_token_usage
    def wrapped(self, model, messages, stream, tools, **kwargs):
        _ = (model, messages, stream, tools, kwargs)
        return None  # Forces both counts to 0

    wrapped(EmptyLLM(), "m", [], False, None)

    # When zero-token short-circuits, the repo is never instantiated.
    assert (
        _FakeTokenUsageRepo.last_instance is None
        or _FakeTokenUsageRepo.last_instance.inserted == []
    )


@pytest.mark.unit
def test_decorator_skips_when_no_attribution(monkeypatch, caplog):
    """No user_id and no api_key → warn and skip."""
    import logging

    _install_fake_token_repo(monkeypatch)

    class OrphanLLM:
        decoded_token = None
        user_api_key = None
        agent_id = None
        token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    @gen_token_usage
    def wrapped(self, model, messages, stream, tools, **kwargs):
        _ = (model, messages, stream, tools, kwargs)
        return "ok"

    with caplog.at_level(logging.WARNING, logger="application.usage"):
        wrapped(
            OrphanLLM(),
            "m",
            [{"role": "user", "content": "hello"}],
            False,
            None,
        )

    # The decorator short-circuits before constructing the repo.
    assert (
        _FakeTokenUsageRepo.last_instance is None
        or _FakeTokenUsageRepo.last_instance.inserted == []
    )
    assert any(
        "no user_id/api_key" in r.message
        for r in caplog.records
    )


@pytest.mark.unit
def test_gen_token_usage_counts_tools_and_image_inputs(monkeypatch):
    """Tools+attachments inflate the prompt-token count on the LLM's
    running totals.
    """
    _install_fake_token_repo(monkeypatch)

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
    after_first = llm.token_usage["prompt_tokens"]
    wrapped(
        llm,
        "gpt-4o",
        messages,
        False,
        tools_payload,
        _usage_attachments=usage_attachments,
    )
    after_second = llm.token_usage["prompt_tokens"]

    # Second call carries tools+attachments → strictly more prompt tokens.
    assert (after_second - after_first) > after_first


@pytest.mark.unit
def test_stream_token_usage_counts_tools_and_image_inputs(monkeypatch):
    """Stream variant of the prompt-inflation check."""
    _install_fake_token_repo(monkeypatch)

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
    after_first = llm.token_usage["prompt_tokens"]
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
    after_second = llm.token_usage["prompt_tokens"]

    assert (after_second - after_first) > after_first


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

    def test_bytes_returns_empty(self):
        # Regression: image/file attachments arrive as ``bytes`` from the
        # provider-specific message preparation. Without an explicit
        # branch they fell through to ``str(value)`` and inflated
        # ``prompt_tokens`` by millions per call.
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096
        assert _serialize_for_token_count(png_header) == ""
        assert _serialize_for_token_count(bytearray(png_header)) == ""
        assert _serialize_for_token_count(memoryview(png_header)) == ""

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

    def test_bytes_returns_zero(self):
        # Regression: a multi-megabyte ``bytes`` payload (image attachment)
        # used to be repr-stringified and counted as millions of tokens.
        assert _count_tokens(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100000) == 0

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

    def test_bytes_in_message_content_does_not_inflate_count(self):
        # Production regression: a single image attachment landed as bytes
        # inside ``content`` and the prior repr-fallback pushed
        # ``prompt_tokens`` past 2,000,000 on Axiom. Verify the bytes
        # branch keeps the count bounded by the surrounding text.
        text_only = [{"content": "Summarize this image."}]
        with_bytes = [
            {
                "content": [
                    {"type": "text", "text": "Summarize this image."},
                    {"type": "image", "data": b"\x89PNG\r\n" + b"\x00" * 200_000},
                ]
            }
        ]
        baseline = _count_prompt_tokens(text_only, tools=None)
        with_attachment = _count_prompt_tokens(with_bytes, tools=None)
        # 200KB of zero bytes used to register as ~200K tokens; cap the
        # acceptable inflation at a small constant for tool-format overhead.
        assert with_attachment - baseline < 50

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
