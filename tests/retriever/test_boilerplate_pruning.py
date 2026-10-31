from __future__ import annotations

from unittest.mock import Mock

import pytest

from docsgpt.retriever.dispatcher import (
    CompressingDispatcher,
    CompressingRetriever,
    Dispatcher,
    build_dispatcher,
)
from docsgpt.retriever.stages.boilerplate_pruning import (
    prune_boilerplate,
    prune_chunk_text,
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

    def test_preserves_blank_lines_inside_fenced_code(self):
        raw = (
            "Home > Guides\n"
            "Here is the example code:\n"
            "```python\n"
            "def foo():\n"
            "\n"
            "\n"
            "    return 42\n"
            "```\n"
            "\n"
            "\n"
            "Summary text after code block."
        )
        cleaned = prune_chunk_text(raw, query="example")
        # Blank lines inside fence should be preserved
        assert "def foo():\n\n\n    return 42" in cleaned
        # Blank lines outside fence should be collapsed
        assert "\n\n\nSummary" not in cleaned
        assert "\n\nSummary text after code block." in cleaned

    def test_preserves_numeric_comparison_expressions(self):
        raw = (
            "Home > Security > Guidelines\n"
            "Password length > 8 characters\n"
            "Operating temperature >= -20 C\n"
            "Threshold offset <= +5 ms\n"
            "Error code != -1\n"
            "Other text here."
        )
        cleaned = prune_chunk_text(raw, query="How long should my passphrase be?")
        assert "Password length > 8 characters" in cleaned
        assert "Operating temperature >= -20 C" in cleaned
        assert "Threshold offset <= +5 ms" in cleaned
        assert "Error code != -1" in cleaned
        assert "Other text here." in cleaned
        assert "Home > Security > Guidelines" not in cleaned

    def test_breadcrumb_matching_variations_and_non_breadcrumbs(self):
        # Breadcrumbs should be pruned when they are purely navigation boilerplate
        assert prune_chunk_text("Home > API", query="database configuration") == ""
        assert prune_chunk_text("Home / Guides / Setup", query="database configuration") == ""
        assert prune_chunk_text("Docs » Reference", query="database configuration") == ""

        # Non-breadcrumbs (HTTP methods and tables) must be preserved
        assert "GET /api/v1/users" in prune_chunk_text("GET /api/v1/users", query="users")
        assert "POST /v1/chat/completions" in prune_chunk_text("POST /v1/chat/completions", query="chat")
        assert "| col1 | col2 |" in prune_chunk_text("| col1 | col2 |", query="col1")

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
            {"id": "doc2", "text": "DocsGPT Documentation v2.4\nFactual chunk 2 content."},
        ]
        pruned = prune_boilerplate(docs, query="content")
        assert "DocsGPT Documentation v2.4" in pruned[0]["text"]
        assert "DocsGPT Documentation v2.4" not in pruned[1]["text"]
        assert "Factual chunk 2 content." in pruned[1]["text"]

    def test_preserves_repeated_subheadings_within_same_chunk(self):
        text = (
            "# Authentication\n"
            "## Examples\n"
            "Auth example code here.\n"
            "# Authorization\n"
            "## Examples\n"
            "Rbac example code here."
        )
        cleaned = prune_chunk_text(text, query="")
        assert cleaned.count("## Examples") == 2

    def test_preserves_repeated_section_headings_across_chunks(self):
        docs = [
            {"id": "doc1", "text": "## Examples\ncurl https://api.docsgpt.cloud"},
            {"id": "doc2", "text": "## Examples\npython -m docsgpt"},
        ]
        pruned = prune_boilerplate(docs, query="")
        assert "## Examples" in pruned[0]["text"]
        assert "## Examples" in pruned[1]["text"]

    def test_preserves_repeated_factual_prose_across_chunks(self):
        docs = [
            {
                "id": "doc1",
                "text": (
                    "The primary service runs on port 8080.\n"
                    "API returns HTTP 401 for expired credentials.\n"
                    "Default timeout 30 seconds\n"
                    "Other details."
                ),
            },
            {
                "id": "doc2",
                "text": (
                    "The primary service runs on port 8080.\n"
                    "API returns HTTP 401 for expired credentials.\n"
                    "Default timeout 30 seconds\n"
                    "More information."
                ),
            },
        ]
        # Query does not contain keywords from those factual sentences
        pruned = prune_boilerplate(docs, query="Why do logins fail?")
        assert "The primary service runs on port 8080." in pruned[0]["text"]
        assert "The primary service runs on port 8080." in pruned[1]["text"]
        assert "API returns HTTP 401 for expired credentials." in pruned[0]["text"]
        assert "API returns HTTP 401 for expired credentials." in pruned[1]["text"]
        assert "Default timeout 30 seconds" in pruned[0]["text"]
        assert "Default timeout 30 seconds" in pruned[1]["text"]

    def test_prune_boilerplate_preserves_document_identity(self):
        doc1 = {"id": "doc1", "text": "Home > API\nFactual chunk 1 content."}
        doc2 = {"id": "doc2", "text": "Home > API\nFactual chunk 2 content."}
        docs = [doc1, doc2]
        pruned = prune_boilerplate(docs, query="content")
        assert pruned is docs
        assert pruned[0] is doc1
        assert pruned[1] is doc2
        assert "Home > API" not in doc1["text"]
        assert "Factual chunk 1 content." in doc1["text"]

    def test_prune_boilerplate_skips_duplicate_document_references(self):
        doc = {"id": "doc1", "text": "Server uses TLS."}
        docs = [doc, doc]
        pruned = prune_boilerplate(docs, query="TLS")
        assert pruned[0]["text"] == "Server uses TLS."
        assert pruned[1]["text"] == "Server uses TLS."

    def test_prune_boilerplate_does_not_leak_raw_text_attribute(self):
        doc = {"id": "doc1", "text": "Home > API\nFactual chunk."}
        prune_boilerplate([doc], query="Factual")
        assert "_raw_text" not in doc
        assert doc["text"] == "Factual chunk."


@pytest.mark.unit
class TestCompressingRetrieverIntegration:
    def test_positional_and_keyword_query_handling(self):
        mock_inner = Mock()
        mock_inner.search.return_value = [{"id": "d1", "text": "Home > API\nThe primary endpoint is /v1/chat."}]
        retriever = CompressingRetriever(mock_inner)

        # Test positional query invocation (e.g. from headless_runner / internal_search)
        res_pos = retriever.search("endpoint")
        mock_inner.search.assert_called_with("endpoint")
        assert res_pos[0]["text"] == "The primary endpoint is /v1/chat."

        # Test keyword query invocation
        res_kw = retriever.search(query="endpoint")
        assert res_kw[0]["text"] == "The primary endpoint is /v1/chat."

    def test_build_dispatcher_disabled_returns_raw_retriever(self, monkeypatch):
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.CHUNK_COMPRESSION_ENABLED", False)
        # Test ClassicRAG path
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED", False)
        sentinel = object()
        retriever_classic = build_dispatcher(lambda: sentinel)
        assert retriever_classic is sentinel
        assert not isinstance(retriever_classic, CompressingRetriever)

        # Test Dispatcher path
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED", True)
        retriever_disp = build_dispatcher(lambda: object(), source={"question": "q"})
        assert not isinstance(retriever_disp, CompressingRetriever)

    def test_compressing_dispatcher_preserves_dispatcher_isinstance(self, monkeypatch):
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED", True)
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.CHUNK_COMPRESSION_ENABLED", True)
        retriever = build_dispatcher(
            lambda: object(),
            source={"question": "q", "active_docs": ["a"]},
            sources=[],
        )
        assert isinstance(retriever, Dispatcher)
        assert isinstance(retriever, CompressingDispatcher)
        assert isinstance(retriever, CompressingRetriever)

    def test_build_dispatcher_enabled_wraps_in_compressing_retriever(self, monkeypatch):
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED", False)
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.CHUNK_COMPRESSION_ENABLED", True)
        inner = Mock()
        inner.search.return_value = [{"id": "d1", "text": "Home > Guides\nSetup guide."}]
        retriever = build_dispatcher(lambda: inner)
        assert isinstance(retriever, CompressingRetriever)
        res = retriever.search("setup")
        assert res[0]["text"] == "Setup guide."

    def test_candidate_snapshot_preserves_pre_pruning_text_and_identity(self):
        doc1 = {"id": "doc1", "text": "Home > API\nFactual chunk 1."}
        mock_inner = Mock()
        mock_inner.search.return_value = [doc1]
        mock_inner.last_candidates = [
            {"doc": doc1, "snapshot": dict(doc1), "base": True, "relevance": 0.9}
        ]
        retriever = CompressingRetriever(mock_inner)
        res = retriever.search("chunk")
        assert res[0] is doc1
        assert res[0]["text"] == "Factual chunk 1."
        assert retriever.last_candidates[0]["doc"] is doc1
        assert retriever.last_candidates[0]["snapshot"]["text"] == "Home > API\nFactual chunk 1."
