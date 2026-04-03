"""Unit tests for application/llm/anthropic.py — AnthropicLLM.

Extends coverage beyond test_anthropic_llm.py:
  - Constructor: api_key priority, base_url support
  - get_supported_attachment_types
  - prepare_messages_with_attachments: various scenarios
  - _get_base64_image: error paths
  - _raw_gen_stream: close called on response
"""

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Fake anthropic module
# ---------------------------------------------------------------------------


class _FakeCompletion:
    def __init__(self, text):
        self.completion = text


class _FakeCompletions:
    def __init__(self):
        self.last_kwargs = None
        self._stream_items = [_FakeCompletion("s1"), _FakeCompletion("s2")]

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            return self._stream_items
        return _FakeCompletion("final")


class _FakeAnthropic:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url
        self.completions = _FakeCompletions()


@pytest.fixture(autouse=True)
def patch_anthropic(monkeypatch):
    fake = types.ModuleType("anthropic")
    fake.Anthropic = _FakeAnthropic
    fake.HUMAN_PROMPT = "<HUMAN>"
    fake.AI_PROMPT = "<AI>"

    modules_to_remove = [key for key in sys.modules if key.startswith("anthropic")]
    for key in modules_to_remove:
        sys.modules.pop(key, None)
    sys.modules["anthropic"] = fake

    if "application.llm.anthropic" in sys.modules:
        del sys.modules["application.llm.anthropic"]
    yield
    sys.modules.pop("anthropic", None)
    if "application.llm.anthropic" in sys.modules:
        del sys.modules["application.llm.anthropic"]


@pytest.fixture
def llm():
    from application.llm.anthropic import AnthropicLLM

    instance = AnthropicLLM(api_key="test-key")
    instance.storage = types.SimpleNamespace(
        get_file=lambda path: _ctx_manager(b"img_bytes"),
    )
    return instance


def _ctx_manager(data):
    """Create a simple context manager returning an object with .read()."""
    import contextlib

    @contextlib.contextmanager
    def cm():
        yield types.SimpleNamespace(read=lambda: data)

    return cm()


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnthropicConstructor:

    def test_api_key_set(self):
        from application.llm.anthropic import AnthropicLLM

        instance = AnthropicLLM(api_key="custom-key")
        assert instance.api_key == "custom-key"

    def test_base_url_passed(self):
        from application.llm.anthropic import AnthropicLLM

        instance = AnthropicLLM(api_key="k", base_url="https://custom.api")
        assert instance.anthropic.base_url == "https://custom.api"

    def test_no_base_url(self):
        from application.llm.anthropic import AnthropicLLM

        instance = AnthropicLLM(api_key="k")
        assert instance.anthropic.base_url is None

    def test_human_and_ai_prompts_set(self):
        from application.llm.anthropic import AnthropicLLM

        instance = AnthropicLLM(api_key="k")
        assert instance.HUMAN_PROMPT == "<HUMAN>"
        assert instance.AI_PROMPT == "<AI>"


# ---------------------------------------------------------------------------
# _raw_gen
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGen:

    def test_returns_completion(self, llm):
        msgs = [{"content": "context"}, {"content": "question"}]
        result = llm._raw_gen(llm, model="claude-2", messages=msgs)
        assert result == "final"

    def test_prompt_contains_context_and_question(self, llm):
        msgs = [{"content": "my context"}, {"content": "my question"}]
        llm._raw_gen(llm, model="claude-2", messages=msgs)
        prompt = llm.anthropic.completions.last_kwargs["prompt"]
        assert "my context" in prompt
        assert "my question" in prompt

    def test_max_tokens_passed(self, llm):
        msgs = [{"content": "c"}, {"content": "q"}]
        llm._raw_gen(llm, model="claude-2", messages=msgs, max_tokens=200)
        assert llm.anthropic.completions.last_kwargs["max_tokens_to_sample"] == 200


# ---------------------------------------------------------------------------
# _raw_gen_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGenStream:

    def test_yields_all_completions(self, llm):
        msgs = [{"content": "c"}, {"content": "q"}]
        chunks = list(
            llm._raw_gen_stream(llm, model="claude", messages=msgs, max_tokens=10)
        )
        assert chunks == ["s1", "s2"]

    def test_calls_close_on_response(self, llm):
        closed = {"called": False}
        original = llm.anthropic.completions._stream_items

        class ClosableList(list):
            def close(self):
                closed["called"] = True

        closable = ClosableList(original)
        llm.anthropic.completions._stream_items = closable
        llm.anthropic.completions.create = lambda **kw: closable

        msgs = [{"content": "c"}, {"content": "q"}]
        list(llm._raw_gen_stream(llm, model="claude", messages=msgs))
        assert closed["called"]

    def test_prompt_format(self, llm):
        msgs = [{"content": "ctx"}, {"content": "q"}]
        list(llm._raw_gen_stream(llm, model="claude", messages=msgs))
        prompt = llm.anthropic.completions.last_kwargs["prompt"]
        assert prompt.startswith("<HUMAN>")
        assert prompt.endswith("<AI>")


# ---------------------------------------------------------------------------
# get_supported_attachment_types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSupportedAttachmentTypes:

    def test_returns_image_types(self, llm):
        result = llm.get_supported_attachment_types()
        assert "image/png" in result
        assert "image/jpeg" in result
        assert "image/webp" in result
        assert "image/gif" in result

    def test_no_pdf_support(self, llm):
        result = llm.get_supported_attachment_types()
        assert "application/pdf" not in result


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
        msgs = [{"role": "user", "content": "look"}]
        attachments = [{"mime_type": "image/png", "data": "AABBCC"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        img_part = next(
            p for p in user_msg["content"] if p.get("type") == "image"
        )
        assert img_part["source"]["data"] == "AABBCC"
        assert img_part["source"]["type"] == "base64"
        assert img_part["source"]["media_type"] == "image/png"

    def test_image_from_storage(self, llm):
        llm.storage = types.SimpleNamespace(
            get_file=lambda p: _ctx_manager(b"raw_image_bytes"),
        )
        msgs = [{"role": "user", "content": "look"}]
        attachments = [{"mime_type": "image/jpeg", "path": "/tmp/img.jpg"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        img_part = next(
            p for p in user_msg["content"] if p.get("type") == "image"
        )
        assert img_part["source"]["media_type"] == "image/jpeg"
        assert len(img_part["source"]["data"]) > 0

    def test_no_user_message_creates_one(self, llm):
        msgs = [{"role": "system", "content": "sys"}]
        attachments = [{"mime_type": "image/png", "data": "AAA"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 1

    def test_image_error_adds_text_fallback(self, llm):
        def bad_storage(path):
            raise Exception("storage error")

        llm.storage = types.SimpleNamespace(get_file=bad_storage)
        msgs = [{"role": "user", "content": "look"}]
        attachments = [
            {"mime_type": "image/png", "path": "/bad.png", "content": "fb"},
        ]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        text_parts = [
            p for p in user_msg["content"]
            if p.get("type") == "text" and "could not" in p.get("text", "").lower()
        ]
        assert len(text_parts) == 1

    def test_non_image_attachment_ignored(self, llm):
        msgs = [{"role": "user", "content": "look"}]
        attachments = [{"mime_type": "application/pdf"}]
        result = llm.prepare_messages_with_attachments(msgs, attachments)
        user_msg = next(m for m in result if m["role"] == "user")
        # content becomes list with just original text
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) == 1

    def test_content_not_list_becomes_empty(self, llm):
        msgs = [{"role": "user", "content": 999}]
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
        def bad_file(path):
            raise FileNotFoundError("not found")

        llm.storage = types.SimpleNamespace(get_file=bad_file)
        with pytest.raises(FileNotFoundError):
            llm._get_base64_image({"path": "/nonexistent"})

    def test_returns_base64_encoded(self, llm):
        import base64

        llm.storage = types.SimpleNamespace(
            get_file=lambda p: _ctx_manager(b"test_data"),
        )
        result = llm._get_base64_image({"path": "/tmp/img.png"})
        decoded = base64.b64decode(result)
        assert decoded == b"test_data"
