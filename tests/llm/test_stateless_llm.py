"""A stateless LLM never chains Responses calls or keeps them on the provider.

One-shot helpers (graph extraction, titles, compression) reuse an instance
across unrelated calls. Chained, each call was billed for every earlier one.
"""

import types
from unittest.mock import MagicMock

import pytest

from docsgpt.core.model_settings import ModelCapabilities


def _noop_decorator(func):
    def wrapper(self_llm, model, messages, stream, tools=None, **kwargs):
        return func(self_llm, model, messages, stream, tools, **kwargs)

    return wrapper


@pytest.fixture(autouse=True)
def _no_cache_or_usage(monkeypatch):
    monkeypatch.setattr("docsgpt.llm.base.gen_cache", _noop_decorator)
    monkeypatch.setattr("docsgpt.llm.base.gen_token_usage", _noop_decorator)


def _responses_llm(monkeypatch):
    """An OpenAI LLM on the Responses API with server-side storage on."""
    monkeypatch.setattr("docsgpt.llm.openai.OpenAI", MagicMock())
    monkeypatch.setattr(
        "docsgpt.llm.openai.StorageCreator",
        types.SimpleNamespace(get_storage=lambda: None),
    )
    monkeypatch.setattr(
        "docsgpt.llm.openai.settings",
        types.SimpleNamespace(
            OPENAI_API_KEY="k",
            API_KEY="k",
            OPENAI_BASE_URL="",
            AZURE_DEPLOYMENT_NAME="dep",
            OPENAI_RESPONSES_STORE=True,
            OPENAI_REASONING_SUMMARY="auto",
            OPENAI_RESPONSES_TRUNCATION_AUTO=False,
            OPENAI_PROMPT_CACHE_KEY=False,
            OPENAI_PROMPT_CACHE_RETENTION=None,
        ),
    )
    from docsgpt.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = ModelCapabilities(api_flavor="responses")
    return llm


def _response(response_id, text):
    return types.SimpleNamespace(
        id=response_id,
        output=[
            types.SimpleNamespace(
                type="message", content=[types.SimpleNamespace(type="output_text", text=text)]
            )
        ],
    )


def _two_calls(llm):
    create = llm.client.responses.create = MagicMock(
        side_effect=[_response("resp_1", "one"), _response("resp_2", "two")]
    )
    for text in ("first", "second"):
        llm.gen(model="gpt-5.5", messages=[{"role": "user", "content": text}])
    return [call.kwargs for call in create.call_args_list]


@pytest.mark.unit
def test_stateless_calls_neither_chain_nor_store(monkeypatch):
    llm = _responses_llm(monkeypatch)
    llm.stateless = True

    first, second = _two_calls(llm)

    for params in (first, second):
        assert "previous_response_id" not in params
        assert params["store"] is False
    assert llm._last_response_id is None


@pytest.mark.unit
def test_a_stateful_llm_still_chains(monkeypatch):
    # The control: with storage on, an agent's instance chains its calls.
    llm = _responses_llm(monkeypatch)

    _, second = _two_calls(llm)

    assert second["previous_response_id"] == "resp_1"
    assert second["store"] is True


@pytest.mark.unit
def test_create_llm_sets_the_flag():
    from docsgpt.llm.llm_creator import LLMCreator

    def build(**kwargs):
        return LLMCreator.create_llm("openai", api_key="k", user_api_key=None, decoded_token=None, **kwargs)

    assert build(stateless=True).stateless is True
    assert build().stateless is False


@pytest.mark.unit
def test_the_fallback_of_a_stateless_llm_is_stateless(monkeypatch):
    built = {}

    def create(type, **kwargs):
        built.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("docsgpt.llm.llm_creator.LLMCreator.create_llm", create)
    monkeypatch.setattr("docsgpt.core.model_utils.get_provider_from_model_id", lambda model_id, **kw: "openai")
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda provider: "k")
    llm = _responses_llm(monkeypatch)
    llm.stateless = True
    llm._backup_models = ["backup-model"]

    assert llm.fallback_llm is not None
    assert built["stateless"] is True


@pytest.mark.unit
class TestCreateStatelessLLM:
    """``create_stateless_llm`` builds the one-shot LLM of the drafter, the monitor judge and graph extraction."""

    def _capture(self, monkeypatch, provider):
        from docsgpt.llm.llm_creator import LLMCreator

        captured = {}

        def create_llm(type_, **kwargs):
            captured.update(provider=type_, **kwargs)
            return types.SimpleNamespace()

        monkeypatch.setattr(LLMCreator, "create_llm", staticmethod(create_llm))
        monkeypatch.setattr("docsgpt.core.model_utils.get_provider_from_model_id", lambda m, user_id=None: provider)
        monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda p: f"key-{p}")
        return captured

    def test_runs_under_the_user_and_tags_its_usage(self, monkeypatch):
        from docsgpt.llm.llm_creator import create_stateless_llm

        captured = self._capture(monkeypatch, "anthropic")
        llm, provider = create_stateless_llm("claude-x", "alice", source="drafter", request_id="drafter:1")
        assert provider == "anthropic" and captured["api_key"] == "key-anthropic"
        assert captured["decoded_token"] == {"sub": "alice"} and captured["model_user_id"] == "alice"
        assert captured["stateless"] is True and captured["user_api_key"] is None
        assert (llm._token_usage_source, llm._request_id) == ("drafter", "drafter:1")

    def test_without_a_user_or_a_known_model_uses_the_default_provider(self, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.llm.llm_creator import create_stateless_llm

        monkeypatch.setattr(settings, "LLM_PROVIDER", "docsgpt")
        captured = self._capture(monkeypatch, None)
        _, provider = create_stateless_llm("mystery", None, source="graph_extraction", request_id=None)
        assert provider == "docsgpt" and captured["decoded_token"] is None
