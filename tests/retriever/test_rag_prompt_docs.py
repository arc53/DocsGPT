"""Unit tests for RAG prompt excerpt formatting (no Flask / app deps)."""

import pytest

from application.retriever.rag_prompt_docs import (
    build_numbered_docs_together,
    format_rag_excerpt,
)


@pytest.mark.unit
def test_format_rag_excerpt_with_page():
    s = format_rag_excerpt(
        {"text": "hello", "filename": "a.pdf", "page": 3},
        1,
    )
    assert s.startswith("[1] p.3 a.pdf")
    assert "hello" in s


@pytest.mark.unit
def test_format_rag_excerpt_no_page():
    s = format_rag_excerpt({"text": "x", "title": "t.md"}, 2)
    assert s.startswith("[2] t.md")


@pytest.mark.unit
def test_build_numbered_docs_together_skips_non_string_text():
    assert build_numbered_docs_together([{"text": 123}]) is None


@pytest.mark.unit
def test_build_numbered_docs_together_numbers_and_note():
    body = build_numbered_docs_together(
        [
            {"text": "a", "filename": "f1.pdf", "page": 1},
            {"text": "b", "filename": "f1.pdf", "page": 2},
        ]
    )
    assert body is not None
    assert "cite excerpts" in body
    assert "[1] p.1 f1.pdf" in body
    assert "[2] p.2 f1.pdf" in body
