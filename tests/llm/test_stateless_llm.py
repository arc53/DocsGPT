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
