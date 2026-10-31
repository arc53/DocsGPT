"""Unit tests for DocsGPT boilerplate pruning stage and CompressingRetriever."""

import sys
from unittest.mock import Mock, MagicMock

for mod in ["anthropic", "openai", "groq", "cohere", "pytest_postgresql", "httpx2", "redis", "google.genai", "google.generativeai"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import types
if "google" not in sys.modules or not hasattr(sys.modules["google"], "genai"):
    gmod = types.ModuleType("google")
    gmod.genai = sys.modules["google.genai"]
    sys.modules["google"] = gmod

import pytest

from docsgpt.retriever.dispatcher import (
    CompressingRetriever,
    build_dispatcher,
)
from docsgpt.retriever.stages.boilerplate_pruning import (
    prune_chunk_text,
    prune_boilerplate,
)


@pytest.mark.unit
class TestBoilerplatePruningRules:
    def test_prunes_breadcrumbs_and_nav_headers(self):
        raw = (
            "Home > Documentation > API Reference > Endpoints\n"
            "# Table of Contents\n"
            "This service provides real-time transaction processing for payment requests.\n"
            "On this page\n"
            "Next page: Authentication\n"
            "Edit this page on GitHub"
        )
        cleaned = prune_chunk_text(raw, query="payment")
        expected = "This service provides real-time transaction processing for payment requests."
        assert cleaned == expected

    def test_preserves_code_blocks_and_inline_code(self):
        raw = (
            "Home / Guides / Setup\n"
            "To install the package, run:\n"
            "```bash\n"
            "npm install docsgpt-sdk\n"
            "```\n"
            "Use the `Client` class to configure authentication.\n"
            "Next page: Usage"
        )
        cleaned = prune_chunk_text(raw, query="install")
        assert "```bash\nnpm install docsgpt-sdk\n```" in cleaned
        assert "`Client`" in cleaned
        assert "Home / Guides / Setup" not in cleaned
        assert "Next page: Usage" not in cleaned

    def test_preserves_tables_and_factual_prose(self):
        raw = (
            "Docs > Tables\n"
            "| Parameter | Type | Required |\n"
            "| --- | --- | --- |\n"
            "| api_key | string | true |\n"
            "| timeout | integer | false |\n"
            "The client raises a TimeoutException if no response arrives within 30 seconds."
        )
        cleaned = prune_chunk_text(raw, query="timeout")
        assert "| Parameter | Type | Required |" in cleaned
        assert "| api_key | string | true |" in cleaned
        assert "The client raises a TimeoutException if no response arrives within 30 seconds." in cleaned
        assert "Docs > Tables" not in cleaned

    def test_preserves_negations_and_qualifiers(self):
        raw = (
            "Quick Links\n"
            "Users must not share authentication keys with third parties.\n"
            "This endpoint is deprecated and should never be used in production.\n"
            "Only valid admin tokens are accepted; invalid tokens will be rejected."
        )
        cleaned = prune_chunk_text(raw, query="tokens")
        assert "Users must not share authentication keys with third parties." in cleaned
        assert "This endpoint is deprecated and should never be used in production." in cleaned
        assert "Only valid admin tokens are accepted; invalid tokens will be rejected." in cleaned
        assert "Quick Links" not in cleaned

    def test_deduplicates_boilerplate_across_chunks(self):
        docs = [
            {"id": "doc1", "text": "DocsGPT Documentation v2.4\nFactual chunk 1 content."},
            {"id": "doc2", "text": "DocsGPT Documentation v2.4\nFactual chunk 2 content."}
        ]
        pruned = prune_boilerplate(docs, query="content")
        assert "DocsGPT Documentation v2.4" in pruned[0]["text"]
        assert "DocsGPT Documentation v2.4" not in pruned[1]["text"]
        assert "Factual chunk 2 content." in pruned[1]["text"]


@pytest.mark.unit
class TestCompressingRetrieverIntegration:
    def test_positional_and_keyword_query_handling(self):
        mock_inner = Mock()
        mock_inner.search.return_value = [
            {"id": "d1", "text": "Home > API\nThe primary endpoint is /v1/chat."}
        ]
        retriever = CompressingRetriever(mock_inner)

        # Test positional query invocation (e.g. from headless_runner / internal_search)
        res_pos = retriever.search("endpoint")
        mock_inner.search.assert_called_with("endpoint")
        assert res_pos[0]["text"] == "The primary endpoint is /v1/chat."

        # Test keyword query invocation
        res_kw = retriever.search(query="endpoint")
        assert res_kw[0]["text"] == "The primary endpoint is /v1/chat."

    def test_build_dispatcher_disabled_returns_raw_retriever(self, monkeypatch):
        monkeypatch.setattr(
            "docsgpt.retriever.dispatcher.settings.CHUNK_COMPRESSION_ENABLED",
            False
        )
        # Test ClassicRAG path
        monkeypatch.setattr(
            "docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED",
            False
        )
        sentinel = object()
        retriever_classic = build_dispatcher(lambda: sentinel)
        assert retriever_classic is sentinel
        assert not isinstance(retriever_classic, CompressingRetriever)

        # Test Dispatcher path
        monkeypatch.setattr(
            "docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED",
            True
        )
        retriever_disp = build_dispatcher(lambda: object(), source={"question": "q"})
        assert not isinstance(retriever_disp, CompressingRetriever)

    def test_build_dispatcher_enabled_wraps_in_compressing_retriever(self, monkeypatch):
        monkeypatch.setattr(
            "docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED",
            False
        )
        monkeypatch.setattr(
            "docsgpt.retriever.dispatcher.settings.CHUNK_COMPRESSION_ENABLED",
            True
        )
        inner = Mock()
        inner.search.return_value = [{"id": "d1", "text": "Home > Guides\nSetup guide."}]
        retriever = build_dispatcher(lambda: inner)
        assert isinstance(retriever, CompressingRetriever)
        res = retriever.search("setup")
        assert res[0]["text"] == "Setup guide."
