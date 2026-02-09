import types
import pytest

from application.llm.google_ai import GoogleLLM

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
        # not used in assertions but present for completeness
        return _FakePart(function_call=None, text=str(response))

    @staticmethod
    def from_uri(file_uri, mime_type):
        # mimic presence of file data for streaming detection
        return _FakePart(file_data=types.SimpleNamespace(file_uri=file_uri, mime_type=mime_type))


class _FakeContent:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts


class FakeTypesModule:
    Part = _FakePart
    Content = _FakeContent

    class ThinkingConfig:
        def __init__(
            self,
            include_thoughts=None,
            thinking_budget=None,
            thinking_level=None,
        ):
            self.include_thoughts = include_thoughts
            self.thinking_budget = thinking_budget
            self.thinking_level = thinking_level

    class GenerateContentConfig:
        def __init__(self):
            self.system_instruction = None
            self.tools = None
            self.thinking_config = None
            self.response_schema = None
            self.response_mime_type = None


class FakeModels:
    def __init__(self):
        self.last_args = None
        self.last_kwargs = None

    class _Resp:
        def __init__(self, text=None, candidates=None):
            self.text = text
            self.candidates = candidates or []

    def generate_content(self, *args, **kwargs):
        self.last_args, self.last_kwargs = args, kwargs
        return FakeModels._Resp(text="ok")

    def generate_content_stream(self, *args, **kwargs):
        self.last_args, self.last_kwargs = args, kwargs
        # Simulate stream of text parts
        part1 = types.SimpleNamespace(text="a", candidates=None)
        part2 = types.SimpleNamespace(text="b", candidates=None)
        return [part1, part2]


class FakeClient:
    def __init__(self, *_, **__):
        self.models = FakeModels()


@pytest.fixture(autouse=True)
def patch_google_modules(monkeypatch):
    # Patch the types module used by GoogleLLM
    import application.llm.google_ai as gmod
    monkeypatch.setattr(gmod, "types", FakeTypesModule)
    monkeypatch.setattr(gmod.genai, "Client", FakeClient)


def test_clean_messages_google_basic():
    llm = GoogleLLM(api_key="key")
    msgs = [
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": [
            {"text": "hello"},
            {"files": [{"file_uri": "gs://x", "mime_type": "image/png"}]},
            {"function_call": {"name": "fn", "args": {"a": 1}}},
        ]},
    ]
    cleaned, system_instruction = llm._clean_messages_google(msgs)

    assert all(hasattr(c, "role") and hasattr(c, "parts") for c in cleaned)
    assert any(c.role == "model" for c in cleaned)
    assert any(hasattr(p, "text") for c in cleaned for p in c.parts)


def test_raw_gen_calls_google_client_and_returns_text():
    llm = GoogleLLM(api_key="key")
    msgs = [{"role": "user", "content": "hello"}]
    out = llm._raw_gen(llm, model="gemini-2.0", messages=msgs, stream=False)
    assert out == "ok"


def test_raw_gen_stream_yields_chunks():
    llm = GoogleLLM(api_key="key")
    msgs = [{"role": "user", "content": "hello"}]
    gen = llm._raw_gen_stream(llm, model="gemini", messages=msgs, stream=True)
    assert list(gen) == ["a", "b"]


def test_raw_gen_stream_does_not_set_thinking_config_by_default(monkeypatch):
    captured = {}

    def fake_stream(self, *args, **kwargs):
        captured["config"] = kwargs.get("config")
        return [types.SimpleNamespace(text="a", candidates=None)]

    monkeypatch.setattr(FakeModels, "generate_content_stream", fake_stream)

    llm = GoogleLLM(api_key="key")
    msgs = [{"role": "user", "content": "hello"}]
    list(llm._raw_gen_stream(llm, model="gemini", messages=msgs, stream=True))

    assert captured["config"].thinking_config is None


def test_raw_gen_stream_emits_thought_events(monkeypatch):
    llm = GoogleLLM(api_key="key")
    msgs = [{"role": "user", "content": "hello"}]

    thought_part = types.SimpleNamespace(
        text="thinking token",
        function_call=None,
        thought=True,
    )
    answer_part = types.SimpleNamespace(
        text="answer token",
        function_call=None,
        thought=False,
    )
    chunk = types.SimpleNamespace(
        candidates=[
            types.SimpleNamespace(
                content=types.SimpleNamespace(parts=[thought_part, answer_part])
            )
        ]
    )

    monkeypatch.setattr(
        FakeModels,
        "generate_content_stream",
        lambda self, *args, **kwargs: [chunk],
    )

    out = list(llm._raw_gen_stream(llm, model="gemini", messages=msgs, stream=True))

    assert {"type": "thought", "thought": "thinking token"} in out
    assert "answer token" in out


def test_raw_gen_stream_keeps_prefix_like_text_as_answer(monkeypatch):
    llm = GoogleLLM(api_key="key")
    msgs = [{"role": "user", "content": "hello"}]
    prefixed_answer = "[[DOCSGPT_GOOGLE_REASONING]]this is answer text"

    answer_part = types.SimpleNamespace(
        text=prefixed_answer,
        function_call=None,
        thought=False,
    )
    chunk = types.SimpleNamespace(
        candidates=[
            types.SimpleNamespace(
                content=types.SimpleNamespace(parts=[answer_part])
            )
        ]
    )

    monkeypatch.setattr(
        FakeModels,
        "generate_content_stream",
        lambda self, *args, **kwargs: [chunk],
    )

    out = list(llm._raw_gen_stream(llm, model="gemini", messages=msgs, stream=True))

    assert prefixed_answer in out
    assert not any(isinstance(item, dict) and item.get("type") == "thought" for item in out)


def test_prepare_structured_output_format_type_mapping():
    llm = GoogleLLM(api_key="key")
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["a"],
    }
    out = llm.prepare_structured_output_format(schema)
    assert out["type"] == "OBJECT"
    assert out["properties"]["a"]["type"] == "STRING"
    assert out["properties"]["b"]["type"] == "ARRAY"


def test_prepare_messages_with_attachments_appends_files(monkeypatch):
    llm = GoogleLLM(api_key="key")
    llm.storage = types.SimpleNamespace(
        file_exists=lambda path: True,
        process_file=lambda path, processor_func, **kwargs: "gs://file_uri"
    )
    monkeypatch.setattr(llm, "_upload_file_to_google", lambda att: "gs://file_uri")

    messages = [{"role": "user", "content": "Hi"}]
    attachments = [
        {"path": "/tmp/img.png", "mime_type": "image/png"},
        {"path": "/tmp/doc.pdf", "mime_type": "application/pdf"},
    ]

    out = llm.prepare_messages_with_attachments(messages, attachments)
    user_msg = next(m for m in out if m["role"] == "user")
    assert isinstance(user_msg["content"], list)
    files_entry = next((p for p in user_msg["content"] if isinstance(p, dict) and "files" in p), None)
    assert files_entry is not None
    assert isinstance(files_entry["files"], list) and len(files_entry["files"]) == 2
