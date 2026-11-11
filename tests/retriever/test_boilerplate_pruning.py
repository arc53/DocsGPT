from __future__ import annotations

import pytest

from docsgpt.retriever.stages.boilerplate_pruning import (
    _normalize_fence_state,
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
            "Error tolerance < 0.01 percent\n"
            "Next page"
        )
        cleaned = prune_chunk_text(raw, query="guidelines")
        assert "Password length > 8 characters" in cleaned
        assert "Operating temperature >= -20 C" in cleaned
        assert "Threshold offset <= +5 ms" in cleaned
        assert "Error tolerance < 0.01 percent" in cleaned
        assert "Next page" not in cleaned

    def test_preserves_prose_containing_slash_and_greater_than(self):
        raw = (
            "Home > Documentation\n"
            "The client connects to host:port/path and writes > 100 bytes/sec.\n"
            "Use the command: cat /etc/passwd > /dev/null\n"
            "Was this article helpful?"
        )
        cleaned = prune_chunk_text(raw, query="client")
        assert "The client connects to host:port/path and writes > 100 bytes/sec." in cleaned
        assert "Use the command: cat /etc/passwd > /dev/null" in cleaned
        assert "Home > Documentation" not in cleaned
        assert "Was this article helpful?" not in cleaned

    def test_preserves_fenced_code_context_across_chunk_boundaries_via_initial_fence(self):
        continuation_chunk = (
            "    # This is code continuing from previous chunk\n"
            "    x = 10\n"
            "    return x\n"
            "```\n"
            "Home > API\n"
            "Factual prose outside the code block."
        )
        cleaned = prune_chunk_text(continuation_chunk, query="", initial_active_fence=("`", 3))
        assert "    # This is code continuing from previous chunk\n    x = 10\n    return x\n```" in cleaned
        assert "Home > API" not in cleaned
        assert "Factual prose outside the code block." in cleaned

    def test_prune_boilerplate_carries_active_fence_from_metadata(self):
        docs = [
            {
                "id": "chunk1",
                "text": "```python\ndef run():\n    return 1",
                "metadata": {"active_fence": ("`", 3)},
            },
            {
                "id": "chunk2",
                "text": "    return 2\n```\nHome > API\nSummary info.",
                "metadata": {"active_fence": ("`", 3)},
            },
        ]
        pruned = prune_boilerplate(docs, query="python")
        assert "Home > API" not in pruned[1]["text"]
        assert "Summary info." in pruned[1]["text"]
        assert "return 2\n```" in pruned[1]["text"]

    def test_normalize_fence_state_handles_malformed_and_unexpected_values(self):
        # Valid tuple / list
        assert _normalize_fence_state(("`", 3)) == ("`", 3)
        assert _normalize_fence_state(["~", 4]) == ("~", 4)
        # Valid string
        assert _normalize_fence_state("```") == ("`", 3)
        assert _normalize_fence_state("~~~~") == ("~", 4)
        # Boolean True
        assert _normalize_fence_state(True) == ("`", 3)
        # Invalid / malformed inputs
        assert _normalize_fence_state(None) is None
        assert _normalize_fence_state(False) is None
        assert _normalize_fence_state("invalid") is None
        assert _normalize_fence_state(("`", "invalid")) is None

    def test_prune_boilerplate_handles_malformed_fence_metadata(self):
        docs = [
            {
                "id": "chunk1",
                "text": "Home > Guides\nFactual chunk with malformed fence.",
                "metadata": {"active_fence": "malformed_value"},
            },
            {
                "id": "chunk2",
                "text": "Home > Guides\nFactual chunk with non-dict metadata.",
                "metadata": "not-a-dict",
            },
            {
                "id": "chunk3",
                "text": "Home > Guides\nFactual chunk without metadata key.",
            },
        ]
        pruned = prune_boilerplate(docs, query="chunk")
        assert len(pruned) == 3
        for d in pruned:
            assert "Home > Guides" not in d["text"]
            assert "Factual chunk" in d["text"]

    def test_preserves_indentation_on_first_code_line(self):
        raw = "Home > Guides\n```python\n    def indented_func():\n        pass\n```\nNext page"
        cleaned = prune_chunk_text(raw, query="func")
        assert "```python\n    def indented_func():\n        pass\n```" in cleaned
        assert "Home > Guides" not in cleaned
        assert "Next page" not in cleaned

    def test_breadcrumb_matching_variations_and_non_breadcrumbs(self):
        # Breadcrumbs should be pruned when they are purely navigation boilerplate
        assert prune_chunk_text("Home > API", query="database configuration") == ""
        assert prune_chunk_text("Home / Guides / Setup", query="database configuration") == ""
        assert prune_chunk_text("Docs » Reference", query="database configuration") == ""

        # Multi-level breadcrumbs anchored by a navigation root must be pruned
        assert (
            prune_chunk_text(
                "Home > Documentation > API Reference > Endpoints",
                query="unrelated query",
            )
            == ""
        )
        assert (
            prune_chunk_text(
                "Reference > Authentication > OAuth",
                query="unrelated query",
            )
            == ""
        )

        # Non-breadcrumbs (HTTP methods, tables, and factual comparisons) must be preserved
        assert "GET /api/v1/users" in prune_chunk_text("GET /api/v1/users", query="users")
        assert "POST /v1/chat/completions" in prune_chunk_text("POST /v1/chat/completions", query="chat")
        assert "| col1 | col2 |" in prune_chunk_text("| col1 | col2 |", query="col1")
        assert "Cache size > memory budget" in prune_chunk_text(
            "Cache size > memory budget", query="unrelated search keywords"
        )

        # Factual comparison chains with 2+ '>' must NOT be pruned as breadcrumbs
        assert "Cache size > memory budget > disk capacity" in prune_chunk_text(
            "Cache size > memory budget > disk capacity", query="unrelated query"
        )
        assert "API latency > database latency" in prune_chunk_text(
            "API latency > database latency", query="unrelated query"
        )
        assert "Index size > cache size" in prune_chunk_text("Index size > cache size", query="unrelated query")
        assert "Reference latency > database latency" in prune_chunk_text(
            "Reference latency > database latency", query="unrelated query"
        )

    def test_preserves_code_blocks_and_inline_code(self):
        raw = (
            "Home > Documentation > API Reference > Endpoints\n"
            "Run the following command to initialize the server:\n"
            "```bash\n"
            "# Configure and start\n"
            "curl -X POST http://localhost:8080/init \\\n"
            "  -H 'Authorization: Bearer test-token'\n"
            "```\n"
            "Use the `GET /health` endpoint to verify status.\n"
            "Next page: Authentication"
        )
        cleaned = prune_chunk_text(raw, query="initialize")
        assert "```bash" in cleaned
        assert "curl -X POST http://localhost:8080/init" in cleaned
        assert "Use the `GET /health` endpoint to verify status." in cleaned
        assert "Home > Documentation" not in cleaned
        assert "Next page: Authentication" not in cleaned

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

    def test_preserves_apostrophe_negations_before_nav_pruning(self):
        """Straight and typographic apostrophe contractions must survive navigation pruning."""
        # Straight apostrophe form
        straight_cases = [
            ("Next page: Don't disable TLS verification", "database"),
            ("Don't use plain HTTP in production.", "security"),
            ("Won't retry on 4xx errors.", "config"),
            ("Can't authenticate without a token.", "auth"),
        ]
        for text, query in straight_cases:
            result = prune_chunk_text(text, query=query)
            assert result == text, (
                f"Straight-apostrophe negation incorrectly pruned.\n"
                f"  Input: {text!r}\n  Query: {query!r}\n  Got: {result!r}"
            )

        # Typographic / curly apostrophe (U+2019) — same words, different codepoint
        typographic_cases = [
            ("Next page: Don\u2019t disable TLS verification", "database"),
            ("Don\u2019t use plain HTTP in production.", "security"),
            ("Won\u2019t retry on 4xx errors.", "config"),
        ]
        for text, query in typographic_cases:
            result = prune_chunk_text(text, query=query)
            assert result == text, (
                f"Typographic-apostrophe negation incorrectly pruned.\n"
                f"  Input: {text!r}\n  Query: {query!r}\n  Got: {result!r}"
            )

    def test_preserves_possessives_matching_query_terms(self):
        """Possessives such as 'user's' must still match a query token 'user'."""
        result = prune_chunk_text("Next page: user's credentials expired", query="user login")
        assert result == "Next page: user's credentials expired", (
            f"Possessive 'user's' did not match query token 'user'; line removed.\n  Got: {result!r}"
        )

    def test_preserves_punctuation_bearing_query_terms(self):
        """Terms containing compounds or symbols like C++, C#, F# must survive navigation pruning."""
        cases = [
            ("Next page: C++ memory model", "C++", "Next page: C++ memory model"),
            ("Next page: C++20 memory model", "C++", "Next page: C++20 memory model"),
            ("Next page: C# async programming", "C#", "Next page: C# async programming"),
            ("Next page: F# pattern matching", "F#", "Next page: F# pattern matching"),
            ("Next page: Notepad++ configuration", "notepad++", "Next page: Notepad++ configuration"),
        ]
        for line, query, expected in cases:
            cleaned = prune_chunk_text(line, query=query)
            assert cleaned == expected, f"Failed for query {query!r}: got {cleaned!r}, expected {expected!r}"

    def test_preserves_one_character_query_terms(self):
        """Single-letter queries like 'C' or 'R' must protect matching navigation-like lines."""
        raw = "Next page: C memory model"
        cleaned = prune_chunk_text(raw, query="C")
        assert cleaned == raw

    def test_preserves_factual_sentences_with_nav_prefixes(self):
        """Lines starting with 'Next page:' containing full factual sentences or punctuation must not be pruned."""
        cases = [
            "Next page: The API returns 401 for expired credentials.",
            "Next page: What is the default timeout?",
            "Previous page: This requires administrative privileges!",
            "Next page: The API returns 401",
            "Next page The API returns 401",
            "Next page: [Administrators can access all records.]",
            "Next page [Administrators can access all records.]",
            "Next page token expires after 24 hours",
            "Next page: token expires after 24 hours",
        ]
        for line in cases:
            cleaned = prune_chunk_text(line, query="")
            assert cleaned == line, f"Factual line was pruned: {line!r}"

    def test_prunes_navigation_labels_with_or_without_colon_and_bracketed(self):
        cases = [
            "Next page Authentication",
            "previous page Overview",
            "Next page: API Reference Guide and Setup Overview",
            "Next page API Reference Guide and Setup Overview",
            "Next page: [Getting Started]",
            "Next page [Getting Started]",
            "Next page: [Getting Started](https://docs.example.com/start)",
        ]
        for line in cases:
            assert prune_chunk_text(line, query="") == "", f"Navigation line was not pruned: {line!r}"

    def test_nav_control_regex_preserves_factual_tokens_under_case_guard(self):
        """Regression test: uppercase-label guard in _NAV_CONTROL_RE must not match lowercase words."""
        cases = [
            "Next page token lifetime",
            "Next page token lifetime: 24 hours",
            "Next page token parameter: max 50 items",
            "Next page token expires after 24 hours",
            "Next page token is required for pagination",
            "Previous page cursor value: xyz123",
        ]
        for line in cases:
            cleaned = prune_chunk_text(line, query="unrelated search query")
            assert cleaned == line, f"Factual line with navigation prefix was pruned: {line!r}"

        # But true navigation labels with uppercase words should be pruned (including case-insensitive page)
        nav_cases = [
            "Next page Authentication",
            "Next page: Authentication",
            "NEXT PAGE: Authentication",
            "Previous page Overview",
            "Previous Page Overview",
            "Next PAGE Authentication",
            "Next page: User Profile Settings",
        ]
        for line in nav_cases:
            assert prune_chunk_text(line, query="unrelated search query") == "", (
                f"Navigation line was not pruned: {line!r}"
            )

    def test_preserves_indented_markdown_code_and_pipe_tables(self):
        """Four-space indented lines and tables without edge pipes must survive pruning."""
        raw = "Example code block:\n    Next page: Authentication\nSummary text."
        cleaned = prune_chunk_text(raw, query="")
        assert "    Next page: Authentication" in cleaned

        table_row = "Next page: Authentication | Description"
        assert prune_chunk_text(table_row, query="") == table_row

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

    def test_preserves_factual_comparison_without_numeric_operand(self):
        raw = "Home > API\nCache size > memory budget\nNext page: Settings"
        cleaned = prune_chunk_text(raw, query="unrelated query")
        assert "Cache size > memory budget" in cleaned
        assert "Home > API" not in cleaned
        assert "Next page" not in cleaned

        # Multi-level comparison chain must also be preserved
        raw2 = "Home > API\nCache size > memory budget > disk capacity\nNext page: Settings"
        cleaned2 = prune_chunk_text(raw2, query="unrelated query")
        assert "Cache size > memory budget > disk capacity" in cleaned2
        assert "Home > API" not in cleaned2

        # 'API latency > database latency' must be preserved (API is not a nav root)
        raw3 = "Home > API\nAPI latency > database latency\nNext page: Settings"
        cleaned3 = prune_chunk_text(raw3, query="unrelated query")
        assert "API latency > database latency" in cleaned3
        assert "Home > API" not in cleaned3

        # Exact navigation root check must not match root word prefixes in factual comparisons
        raw4 = "Home > API\nIndex size > cache size\nReference latency > database latency\nNext page: Settings"
        cleaned4 = prune_chunk_text(raw4, query="unrelated query")
        assert "Index size > cache size" in cleaned4
        assert "Reference latency > database latency" in cleaned4
        assert "Home > API" not in cleaned4
        assert "Next page" not in cleaned4

    def test_preserves_repeated_factual_license_statements_across_chunks(self):
        docs = [
            {
                "id": "doc1",
                "text": "Home > Reference\nThis library is licensed under MIT.\nCore module details.",
            },
            {
                "id": "doc2",
                "text": "Home > Reference\nThis library is licensed under MIT.\nPlugin module details.",
            },
        ]
        pruned = prune_boilerplate(docs, query="unrelated query terms")
        assert "This library is licensed under MIT." in pruned[0]["text"]
        assert "This library is licensed under MIT." in pruned[1]["text"]
        assert "Home > Reference" not in pruned[0]["text"]
        assert "Home > Reference" not in pruned[1]["text"]
