"""Unit tests for application/llm/llama_cpp.py — LlamaCpp and LlamaSingleton.

Covers:
  - LlamaSingleton: get_instance, query_model (thread-safe)
  - LlamaCpp constructor
  - _raw_gen: prompt format and result extraction
  - _raw_gen_stream: streaming iteration
"""

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Fake llama_cpp module
# ---------------------------------------------------------------------------


class FakeLlama:
    def __init__(self, model_path=None, n_ctx=None):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.last_call = None

    def __call__(self, prompt, **kwargs):
        self.last_call = {"prompt": prompt, **kwargs}
        if kwargs.get("stream"):
            return iter(
                [
                    {"choices": [{"text": "chunk1"}]},
                    {"choices": [{"text": "chunk2"}]},
                ]
            )
        return {"choices": [{"text": "prefix ### Answer \nthe answer"}]}


@pytest.fixture(autouse=True)
def patch_llama_cpp(monkeypatch):
    fake_mod = types.ModuleType("llama_cpp")
    fake_mod.Llama = FakeLlama
    sys.modules["llama_cpp"] = fake_mod

    # Clear any cached instances
    if "application.llm.llama_cpp" in sys.modules:
        del sys.modules["application.llm.llama_cpp"]

    yield

    sys.modules.pop("llama_cpp", None)
    if "application.llm.llama_cpp" in sys.modules:
        del sys.modules["application.llm.llama_cpp"]


@pytest.fixture
def fresh_singleton():
    from application.llm.llama_cpp import LlamaSingleton

    LlamaSingleton._instances = {}
    return LlamaSingleton


@pytest.fixture
def llm(fresh_singleton):
    from application.llm.llama_cpp import LlamaCpp

    instance = LlamaCpp(api_key="k", user_api_key=None, llm_name="/path/to/model")
    return instance


# ---------------------------------------------------------------------------
# LlamaSingleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLlamaSingleton:

    def test_get_instance_creates_llama(self, fresh_singleton):
        instance = fresh_singleton.get_instance("/model/path")
        assert isinstance(instance, FakeLlama)
        assert instance.model_path == "/model/path"

    def test_get_instance_caches(self, fresh_singleton):
        inst1 = fresh_singleton.get_instance("/model")
        inst2 = fresh_singleton.get_instance("/model")
        assert inst1 is inst2

    def test_different_names_different_instances(self, fresh_singleton):
        inst1 = fresh_singleton.get_instance("/model_a")
        inst2 = fresh_singleton.get_instance("/model_b")
        assert inst1 is not inst2

    def test_query_model_thread_safe(self, fresh_singleton):
        instance = fresh_singleton.get_instance("/model")
        result = fresh_singleton.query_model(instance, "prompt", max_tokens=10)
        assert "choices" in result

    def test_import_error_raised(self, fresh_singleton, monkeypatch):
        # Remove the fake module to simulate import failure
        sys.modules.pop("llama_cpp", None)
        fresh_singleton._instances = {}

        with pytest.raises(ImportError, match="llama_cpp"):
            fresh_singleton.get_instance("/new_model")


# ---------------------------------------------------------------------------
# LlamaCpp constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLlamaCppConstructor:

    def test_sets_api_key(self, llm):
        assert llm.api_key == "k"

    def test_sets_user_api_key(self):
        from application.llm.llama_cpp import LlamaCpp, LlamaSingleton

        LlamaSingleton._instances = {}
        instance = LlamaCpp(
            api_key="k", user_api_key="uk", llm_name="/path/model"
        )
        assert instance.user_api_key == "uk"

    def test_creates_llama_instance(self, llm):
        assert isinstance(llm.llama, FakeLlama)


# ---------------------------------------------------------------------------
# _raw_gen
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGen:

    def test_returns_answer(self, llm):
        msgs = [
            {"content": "context text"},
            {"content": "user question"},
        ]
        result = llm._raw_gen(llm, model="local", messages=msgs)
        assert result == "the answer"

    def test_prompt_contains_instruction_and_context(self, llm):
        msgs = [
            {"content": "my context"},
            {"content": "my question"},
        ]
        llm._raw_gen(llm, model="local", messages=msgs)
        prompt = llm.llama.last_call["prompt"]
        assert "### Instruction" in prompt
        assert "### Context" in prompt
        assert "my question" in prompt
        assert "my context" in prompt

    def test_max_tokens_passed(self, llm):
        msgs = [{"content": "c"}, {"content": "q"}]
        llm._raw_gen(llm, model="local", messages=msgs)
        assert llm.llama.last_call["max_tokens"] == 150
        assert llm.llama.last_call["echo"] is False


# ---------------------------------------------------------------------------
# _raw_gen_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGenStream:

    def test_yields_text_chunks(self, llm):
        msgs = [{"content": "c"}, {"content": "q"}]
        chunks = list(llm._raw_gen_stream(llm, model="local", messages=msgs))
        assert chunks == ["chunk1", "chunk2"]

    def test_prompt_format(self, llm):
        msgs = [{"content": "ctx"}, {"content": "question"}]
        list(llm._raw_gen_stream(llm, model="local", messages=msgs))
        prompt = llm.llama.last_call["prompt"]
        assert "### Instruction" in prompt
        assert "### Answer" in prompt

    def test_stream_flag_passed(self, llm):
        msgs = [{"content": "c"}, {"content": "q"}]
        list(
            llm._raw_gen_stream(llm, model="local", messages=msgs, stream=True)
        )
        assert llm.llama.last_call["stream"] is True
