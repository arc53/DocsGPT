"""Which API key the OpenAI embeddings client authenticates with."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch

import pytest

from docsgpt.vectorstore import embeddings_openai
from docsgpt.vectorstore.embeddings_openai import NO_API_KEY, OpenAIEmbeddings


def _settings(**values: Optional[str]) -> SimpleNamespace:
    base = {
        "EMBEDDINGS_KEY": None,
        "OPENAI_API_KEY": None,
        "API_KEY": None,
        "LLM_PROVIDER": "docsgpt",
        "OPENAI_API_BASE": None,
        "OPENAI_API_VERSION": None,
        "AZURE_DEPLOYMENT_NAME": None,
        "OPENAI_BASE_URL": None,
    }
    base.update(values)
    return SimpleNamespace(**base)


def _key_used(settings: SimpleNamespace, passed: Optional[str] = None) -> str:
    with patch.object(embeddings_openai, "settings", settings), patch("openai.OpenAI") as client:
        OpenAIEmbeddings(openai_api_key=passed)
    return client.call_args.kwargs["api_key"]


@pytest.mark.unit
class TestKeyLookup:
    def test_the_llm_api_key_is_reused_for_openai(self):
        """The documented OpenAI .env sets only API_KEY; the setup scripts say it is reused."""
        assert _key_used(_settings(LLM_PROVIDER="openai", API_KEY="sk-llm")) == "sk-llm"

    def test_the_llm_api_key_is_not_sent_for_another_provider(self):
        """An Anthropic key must never be sent to OpenAI."""
        assert _key_used(_settings(LLM_PROVIDER="anthropic", API_KEY="sk-ant")) == NO_API_KEY

    def test_embeddings_key_comes_first(self):
        s = _settings(EMBEDDINGS_KEY="sk-emb", OPENAI_API_KEY="sk-oai", LLM_PROVIDER="openai", API_KEY="sk-llm")
        assert _key_used(s) == "sk-emb"

    def test_openai_api_key_comes_before_the_llm_key(self):
        s = _settings(OPENAI_API_KEY="sk-oai", LLM_PROVIDER="openai", API_KEY="sk-llm")
        assert _key_used(s) == "sk-oai"

    def test_a_passed_key_wins(self):
        assert _key_used(_settings(EMBEDDINGS_KEY="sk-emb"), passed="sk-passed") == "sk-passed"
