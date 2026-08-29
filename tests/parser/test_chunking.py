"""Comprehensive tests for application/parser/chunking.py

Covers: Chunker (init, separate_header_and_body, split_document,
classic_chunk, chunk), edge cases, token counting.
"""

import pytest

from application.parser.chunking import Chunker
from application.parser.schema.base import Document


# =====================================================================
# Chunker - Init
# =====================================================================


@pytest.mark.unit
class TestChunkerInit:

    def test_default_init(self):
        chunker = Chunker()
        assert chunker.chunking_strategy == "classic_chunk"
        assert chunker.max_tokens == 2000
        assert chunker.min_tokens == 150
        assert chunker.duplicate_headers is False

    def test_custom_init(self):
        chunker = Chunker(
            chunking_strategy="classic_chunk",
            max_tokens=1000,
            min_tokens=50,
            duplicate_headers=True,
        )
        assert chunker.max_tokens == 1000
        assert chunker.min_tokens == 50
        assert chunker.duplicate_headers is True

    def test_unknown_strategy_construction_no_longer_raises(self):
        # Strategy dispatch/whitelist moved to ChunkerCreator; the Chunker
        # constructor itself no longer rejects an unknown strategy string.
        chunker = Chunker(chunking_strategy="unknown_strategy")
        assert chunker.chunking_strategy == "unknown_strategy"


# =====================================================================
# Separate Header and Body
# =====================================================================


@pytest.mark.unit
class TestSeparateHeaderAndBody:

    def test_with_header(self):
        chunker = Chunker()
        text = "line1\nline2\nline3\nbody content here"
        header, body = chunker.separate_header_and_body(text)
        assert "line1" in header
        assert "line2" in header
        assert "line3" in header
        assert "body content here" in body

    def test_without_header(self):
        chunker = Chunker()
        text = "short"
        header, body = chunker.separate_header_and_body(text)
        assert header == ""
        assert body == "short"

    def test_empty_text(self):
        chunker = Chunker()
        header, body = chunker.separate_header_and_body("")
        assert header == ""
        assert body == ""

    def test_exactly_three_lines(self):
        chunker = Chunker()
        text = "line1\nline2\nline3\n"
        header, body = chunker.separate_header_and_body(text)
        assert header == "line1\nline2\nline3\n"
        assert body == ""


# =====================================================================
# Split Document
# =====================================================================


@pytest.mark.unit
class TestSplitDocument:

    def test_split_large_document(self):
        chunker = Chunker(max_tokens=50, min_tokens=5)
        long_text = "word " * 200
        doc = Document(text=long_text, doc_id="doc1")

        result = chunker.split_document(doc)
        assert len(result) > 1
        for split_doc in result:
            assert split_doc.doc_id.startswith("doc1-")
            assert split_doc.extra_info is not None
            assert "token_count" in split_doc.extra_info

    def test_split_preserves_header_on_first(self):
        chunker = Chunker(max_tokens=50, min_tokens=5, duplicate_headers=False)
        text = "h1\nh2\nh3\n" + "word " * 200
        doc = Document(text=text, doc_id="doc1")

        result = chunker.split_document(doc)
        assert len(result) > 1
        assert "h1" in result[0].text
        # Only the first: this is what duplicate_headers=False means.
        assert all("h1" not in chunk.text for chunk in result[1:])

    def test_split_duplicates_header(self):
        """Every chunk carries the header when the flag is set.

        Asserting only the first chunk passed even while the flag did nothing:
        the implementation cleared the header after the first iteration, so
        duplicate_headers was unreachable.
        """
        chunker = Chunker(max_tokens=50, min_tokens=5, duplicate_headers=True)
        text = "h1\nh2\nh3\n" + "word " * 200
        doc = Document(text=text, doc_id="doc1")

        result = chunker.split_document(doc)
        assert len(result) > 1
        assert all("h1" in chunk.text for chunk in result)

    def test_oversized_header_does_not_multiply_chunks(self):
        """A header past the budget used to leave a one-token body budget.

        ``max(1, max_tokens - header_tokens)`` bottomed out at 1, so the body
        was cut into one chunk per token -- each still over ``max_tokens``,
        since the whole header was prepended to it.
        """
        chunker = Chunker(max_tokens=50, min_tokens=5, duplicate_headers=True)
        header = ("verylongheaderword " * 40) + "h2\nh3\n"
        body = "word " * 100
        doc = Document(text=f"{header}\n{body}", doc_id="doc1")

        result = chunker.split_document(doc)

        body_tokens = chunker.counter.count(body)
        assert len(result) <= body_tokens // 10, "chunk count must track the budget"
        for chunk in result:
            assert chunk.extra_info["token_count"] <= chunker.max_tokens
        assert "".join(chunk.text for chunk in result) == doc.text

    def test_header_taking_most_of_the_budget_is_not_duplicated(self):
        """Duplication is dropped when it would leave almost no room for body.

        Below a quarter of the budget every chunk is mostly repeated header,
        which multiplies the chunk count without adding retrievable text.
        """
        chunker = Chunker(max_tokens=50, min_tokens=5, duplicate_headers=True)
        header = ("headerword " * 20) + "h2\nh3\n"
        doc = Document(text=f"{header}\n" + "word " * 200, doc_id="doc1")

        result = chunker.split_document(doc)

        assert len(result) > 1
        assert "headerword" in result[0].text
        assert all("headerword" not in chunk.text for chunk in result[1:])

    def test_header_only_document_is_not_dropped(self):
        """The loop only ever emitted the header attached to a body piece.

        With no body there was no piece, so an entire document disappeared
        from the index with no error and no log line.
        """
        chunker = Chunker(max_tokens=50, min_tokens=1, duplicate_headers=False)
        text = "h1\nh2\nh3\n"
        doc = Document(text=text, doc_id="doc1")

        result = chunker.split_document(doc)

        assert len(result) == 1
        assert result[0].text == text

    def test_header_only_document_keeps_its_text_through_chunk(self):
        """The reachable shape: three lines that alone exceed the budget."""
        chunker = Chunker(max_tokens=5, min_tokens=1, duplicate_headers=False)
        text = "h1\nh2\nh3\n"

        result = chunker.chunk([Document(text=text, doc_id="doc1")])

        assert result, "the document must not vanish"
        assert "".join(chunk.text for chunk in result) == text

    def test_zero_max_tokens_does_not_split_per_token(self):
        chunker = Chunker(max_tokens=0, min_tokens=1)
        assert chunker.max_tokens == 1

    def test_split_preserves_embedding(self):
        chunker = Chunker(max_tokens=50, min_tokens=5)
        doc = Document(
            text="word " * 200,
            doc_id="doc1",
            embedding=[0.1, 0.2],
        )

        result = chunker.split_document(doc)
        for split_doc in result:
            assert split_doc.embedding == [0.1, 0.2]

    def test_split_preserves_extra_info(self):
        chunker = Chunker(max_tokens=50, min_tokens=5)
        doc = Document(
            text="word " * 200,
            doc_id="doc1",
            extra_info={"source": "test"},
        )

        result = chunker.split_document(doc)
        for split_doc in result:
            assert split_doc.extra_info["source"] == "test"
            assert "token_count" in split_doc.extra_info


# =====================================================================
# Classic Chunk
# =====================================================================


@pytest.mark.unit
class TestClassicChunk:

    def test_small_doc_passes_through(self):
        chunker = Chunker(max_tokens=2000, min_tokens=1)
        doc = Document(text="Short text", doc_id="d1")

        result = chunker.classic_chunk([doc])
        assert len(result) == 1
        assert result[0].extra_info is not None
        assert "token_count" in result[0].extra_info

    def test_large_doc_gets_split(self):
        chunker = Chunker(max_tokens=50, min_tokens=5)
        doc = Document(text="word " * 200, doc_id="d1")

        result = chunker.classic_chunk([doc])
        assert len(result) > 1

    def test_medium_doc_within_range(self):
        chunker = Chunker(max_tokens=2000, min_tokens=5)
        doc = Document(text="Hello " * 50, doc_id="d1")

        result = chunker.classic_chunk([doc])
        assert len(result) == 1

    def test_multiple_docs(self):
        chunker = Chunker(max_tokens=2000, min_tokens=1)
        docs = [
            Document(text="Doc 1 content", doc_id="d1"),
            Document(text="Doc 2 content", doc_id="d2"),
        ]

        result = chunker.classic_chunk(docs)
        assert len(result) == 2

    def test_empty_docs_list(self):
        chunker = Chunker()
        result = chunker.classic_chunk([])
        assert result == []

    def test_very_small_doc_below_min(self):
        chunker = Chunker(max_tokens=2000, min_tokens=500)
        doc = Document(text="tiny", doc_id="d1")

        result = chunker.classic_chunk([doc])
        assert len(result) == 1
        assert result[0].extra_info["token_count"] < 500

    def test_existing_extra_info_preserved(self):
        chunker = Chunker(max_tokens=2000, min_tokens=1)
        doc = Document(
            text="Hello world",
            doc_id="d1",
            extra_info={"source": "test"},
        )

        result = chunker.classic_chunk([doc])
        assert result[0].extra_info["source"] == "test"
        assert "token_count" in result[0].extra_info

    def test_none_extra_info_initialized(self):
        chunker = Chunker(max_tokens=2000, min_tokens=1)
        doc = Document(text="Hello", doc_id="d1", extra_info=None)

        result = chunker.classic_chunk([doc])
        assert result[0].extra_info is not None
        assert "token_count" in result[0].extra_info


# =====================================================================
# Chunk (dispatcher)
# =====================================================================


@pytest.mark.unit
class TestChunkDispatcher:

    def test_dispatch_classic_chunk(self):
        chunker = Chunker(chunking_strategy="classic_chunk")
        doc = Document(text="content", doc_id="d1")

        result = chunker.chunk([doc])
        assert len(result) == 1

    def test_chunk_runs_classic_regardless_of_strategy_attr(self):
        # Chunk() now always runs the classic implementation; strategy
        # selection happens at the ChunkerCreator level, not here.
        chunker = Chunker()
        chunker.chunking_strategy = "nonexistent"

        result = chunker.chunk([Document(text="x", doc_id="d")])
        assert len(result) == 1


# =====================================================================
# Integration-like test
# =====================================================================


@pytest.mark.unit
class TestChunkerIntegration:

    def test_mixed_document_sizes(self):
        chunker = Chunker(max_tokens=50, min_tokens=5)
        docs = [
            Document(text="small text", doc_id="small"),
            Document(text="word " * 200, doc_id="large"),
            Document(text="medium " * 20, doc_id="medium"),
        ]

        result = chunker.chunk(docs)
        # Small and medium should pass through, large should be split
        assert len(result) >= 3
        doc_ids = [d.doc_id for d in result]
        assert "small" in doc_ids

    def test_all_chunks_have_token_counts(self):
        chunker = Chunker(max_tokens=50, min_tokens=1)
        docs = [
            Document(text="word " * 200, doc_id="big"),
            Document(text="tiny", doc_id="small"),
        ]

        result = chunker.chunk(docs)
        for doc in result:
            assert doc.extra_info is not None
            assert "token_count" in doc.extra_info
            assert doc.extra_info["token_count"] > 0


# =====================================================================
# Special-token text must chunk as ordinary text, not raise
# =====================================================================


@pytest.mark.unit
class TestSpecialTokenText:

    def test_chunking_document_containing_special_token_markers(self):
        # A document ABOUT LLMs contains literal <|endoftext|>; plain
        # ``encode()`` raises ValueError on it and destroyed the ingest.
        chunker = Chunker(chunking_strategy="classic_chunk", max_tokens=50, min_tokens=0)
        doc = Document(
            text="The <|endoftext|> marker separates documents. " * 30,
            doc_id="d1",
        )
        chunks = chunker.chunk([doc])
        assert chunks
        assert all("<|endoftext|>" in c.text for c in chunks[:1])
