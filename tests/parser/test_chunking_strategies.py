"""Tests for the recursive / markdown / parent_child / semantic / sentence_window strategies."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from application.parser.chunking import Chunker
from application.parser.chunking_creator import ChunkerCreator
from application.parser.chunking_strategies import (
    MarkdownChunker,
    ParentChildChunker,
    RecursiveChunker,
    SemanticChunker,
    SentenceWindowChunker,
)
from application.parser.schema.base import Document
from application.utils import get_encoding


def _tok(text: str) -> int:
    return len(get_encoding().encode(text))


@pytest.mark.unit
class TestRegistration:
    def test_strategies_registered(self):
        # create_chunker self-bootstraps the strategy module.
        ChunkerCreator.create_chunker("recursive")
        for key, cls in (
            ("recursive", RecursiveChunker),
            ("markdown", MarkdownChunker),
            ("parent_child", ParentChildChunker),
            ("semantic", SemanticChunker),
            ("sentence_window", SentenceWindowChunker),
        ):
            assert ChunkerCreator.chunkers.get(key) is cls

    def test_worker_kwargs_accepted(self):
        # The worker builds every strategy with the classic kwarg set.
        for strat in ("recursive", "markdown", "parent_child", "semantic", "sentence_window"):
            chunker = ChunkerCreator.create_chunker(
                strat,
                chunking_strategy=strat,
                max_tokens=200,
                min_tokens=20,
                duplicate_headers=False,
            )
            assert chunker.max_tokens == 200
            assert chunker.min_tokens == 20


@pytest.mark.unit
class TestRecursive:
    def test_caps_at_max_tokens(self):
        chunker = RecursiveChunker(max_tokens=40, min_tokens=5)
        docs = [Document(text="word " * 500, doc_id="d")]
        out = chunker.chunk(docs)
        assert len(out) > 1
        for c in out:
            assert _tok(c.text) <= 40
            assert c.extra_info["token_count"] == _tok(c.text)

    def test_splits_on_separator_hierarchy(self):
        # Paragraph boundaries should drive the split before token slicing.
        text = "\n\n".join(["para " * 30 for _ in range(5)])
        chunker = RecursiveChunker(max_tokens=60, min_tokens=5)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) >= 2
        for c in out:
            assert _tok(c.text) <= 60

    def test_small_doc_single_chunk(self):
        chunker = RecursiveChunker(max_tokens=2000, min_tokens=1)
        out = chunker.chunk([Document(text="short text here", doc_id="d")])
        assert len(out) == 1
        assert out[0].text.strip() == "short text here"


@pytest.mark.unit
class TestMarkdown:
    def test_splits_on_headings(self):
        text = "# A\nalpha\n\n## B\nbeta\n\n### C\ngamma"
        chunker = MarkdownChunker(max_tokens=2000, min_tokens=1)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        # One section per heading.
        assert len(out) == 3
        assert out[0].text.startswith("# A")
        assert out[1].text.startswith("## B")

    def test_oversized_section_token_capped(self):
        text = "# Big\n" + "word " * 400
        chunker = MarkdownChunker(max_tokens=50, min_tokens=5)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) > 1
        for c in out:
            assert _tok(c.text) <= 50

    def test_no_heading_falls_back_to_single_or_capped(self):
        chunker = MarkdownChunker(max_tokens=2000, min_tokens=1)
        out = chunker.chunk([Document(text="plain text no heading", doc_id="d")])
        assert len(out) == 1


@pytest.mark.unit
class TestParentChild:
    def test_children_smaller_than_parent(self):
        chunker = ParentChildChunker(max_tokens=60, min_tokens=15)
        out = chunker.chunk([Document(text="alpha " * 200, doc_id="d")])
        assert len(out) > 1
        for c in out:
            assert _tok(c.text) <= 15
            assert _tok(c.extra_info["parent_text"]) <= 60
            assert _tok(c.text) <= _tok(c.extra_info["parent_text"])

    def test_parent_text_reaches_vectorstore_metadata(self):
        chunker = ParentChildChunker(max_tokens=80, min_tokens=20)
        out = chunker.chunk([Document(text="beta " * 150, doc_id="d")])
        lc = out[0].to_langchain_format()
        # parent_text must survive the langchain conversion into metadata.
        assert "parent_text" in lc.metadata
        assert lc.metadata["parent_text"]
        assert lc.page_content == out[0].text

    def test_child_size_defaults_when_min_zero(self):
        chunker = ParentChildChunker(max_tokens=200, min_tokens=0)
        out = chunker.chunk([Document(text="gamma " * 200, doc_id="d")])
        assert all("parent_text" in c.extra_info for c in out)


_EMB_TARGET = "application.vectorstore.base.EmbeddingsSingleton.get_instance"


class _FakeEmbeddings:
    def __init__(self, vectors):
        self._vectors = vectors

    def embed_documents(self, sentences):
        return self._vectors


@pytest.mark.unit
class TestSemantic:
    def test_breakpoint_forces_split(self):
        # Two topics: sentences 0-1 vs 2-3, orthogonal embeddings between.
        text = "Alpha one. Alpha two. Beta one. Beta two."
        vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]
        chunker = SemanticChunker(max_tokens=2000, min_tokens=0)
        with patch(_EMB_TARGET, return_value=_FakeEmbeddings(vectors)):
            out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) == 2
        assert "Alpha" in out[0].text and "Beta" not in out[0].text
        assert "Beta" in out[1].text and "Alpha" not in out[1].text

    def test_no_breakpoint_single_chunk(self):
        # Identical embeddings -> zero distances -> no split.
        text = "Same one. Same two. Same three. Same four."
        vectors = [[1.0, 0.0]] * 4
        chunker = SemanticChunker(max_tokens=2000, min_tokens=0)
        with patch(_EMB_TARGET, return_value=_FakeEmbeddings(vectors)):
            out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) == 1
        assert out[0].extra_info["token_count"] == _tok(out[0].text)

    def test_max_tokens_enforced(self):
        # A single semantic group larger than max_tokens is hard-split.
        long_sentence = "word " * 300 + "."
        text = f"{long_sentence} {long_sentence}"
        vectors = [[1.0, 0.0], [1.0, 0.0]]
        chunker = SemanticChunker(max_tokens=40, min_tokens=0)
        with patch(_EMB_TARGET, return_value=_FakeEmbeddings(vectors)):
            out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) > 1
        for c in out:
            assert _tok(c.text) <= 40

    def test_min_tokens_merges_neighbours(self):
        # Non-uniform distances yield several breakpoints and tiny groups,
        # which must merge until they clear min_tokens.
        text = "A. B. C. D. E. F."
        vectors = [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
        ]
        chunker = SemanticChunker(max_tokens=2000, min_tokens=8)
        with patch(_EMB_TARGET, return_value=_FakeEmbeddings(vectors)):
            out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) < 6
        assert _tok(out[0].text) >= 8

    def test_embeddings_error_falls_back_to_recursive(self):
        text = "First sentence here. Second sentence here. Third one."

        def _boom(*args, **kwargs):
            raise RuntimeError("model unavailable")

        chunker = SemanticChunker(max_tokens=2000, min_tokens=0)
        with patch(_EMB_TARGET, side_effect=_boom):
            out = chunker.chunk([Document(text=text, doc_id="d")])
        recursive = RecursiveChunker(max_tokens=2000, min_tokens=0)
        expected = recursive.chunk([Document(text=text, doc_id="d")])
        assert [c.text for c in out] == [c.text for c in expected]

    def test_too_few_sentences_falls_back(self):
        # A single sentence cannot be semantically split.
        chunker = SemanticChunker(max_tokens=2000, min_tokens=0)
        with patch(_EMB_TARGET, side_effect=AssertionError("must not embed")):
            out = chunker.chunk([Document(text="just one sentence", doc_id="d")])
        assert len(out) == 1
        assert out[0].text.strip() == "just one sentence"

    def test_source_and_extra_info_preserved(self):
        text = "Alpha one. Alpha two. Beta one. Beta two."
        vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]
        doc = Document(
            text=text,
            doc_id="d",
            extra_info={"source": "file.md", "title": "T"},
        )
        chunker = SemanticChunker(max_tokens=2000, min_tokens=0)
        with patch(_EMB_TARGET, return_value=_FakeEmbeddings(vectors)):
            out = chunker.chunk([doc])
        assert len(out) == 2
        for c in out:
            assert c.extra_info["source"] == "file.md"
            assert c.extra_info["title"] == "T"
            assert c.extra_info["token_count"] == _tok(c.text)
            assert c.doc_id.startswith("d-")


@pytest.mark.unit
class TestSentenceWindow:
    def test_single_sentence_per_chunk(self):
        text = "Alpha one. Beta two. Gamma three. Delta four. Epsilon five."
        chunker = SentenceWindowChunker(max_tokens=2000, min_tokens=0, window_size=1)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        # 5 sentences → 5 chunks, each containing a single sentence.
        assert len(out) == 5
        assert out[0].text == "Alpha one."
        assert out[1].text == "Beta two."
        assert out[4].text == "Epsilon five."
        # Each chunk's window_text includes surrounding context.
        for c in out:
            assert "window_text" in c.extra_info
            assert c.extra_info["token_count"] == _tok(c.text)

    def test_window_size_boundaries(self):
        """First and last sentences have truncated windows; no IndexError."""
        text = "First. Second. Third. Fourth. Fifth."
        chunker = SentenceWindowChunker(max_tokens=2000, min_tokens=0, window_size=2)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        # Window for first sentence: sentences [0, 1, 2]
        assert "First." in out[0].extra_info["window_text"]
        assert "Second." in out[0].extra_info["window_text"]
        assert "Third." in out[0].extra_info["window_text"]
        # Window for last sentence: sentences [2, 3, 4]
        assert "Third." in out[4].extra_info["window_text"]
        assert "Fourth." in out[4].extra_info["window_text"]
        assert "Fifth." in out[4].extra_info["window_text"]
        # Middle sentence gets the full window.
        assert "First." in out[2].extra_info["window_text"]
        assert "Fifth." in out[2].extra_info["window_text"]

    def test_window_text_in_metadata(self):
        """window_text survives to_langchain_format()."""
        text = "One. Two. Three."
        chunker = SentenceWindowChunker(max_tokens=2000, min_tokens=0, window_size=1)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        lc = out[0].to_langchain_format()
        assert "window_text" in lc.metadata
        assert lc.metadata["window_text"]
        assert lc.page_content == out[0].text

    def test_too_few_sentences_fallback(self):
        """A single-sentence doc falls back to RecursiveChunker."""
        chunker = SentenceWindowChunker(max_tokens=2000, min_tokens=0)
        out = chunker.chunk([Document(text="only one sentence", doc_id="d")])
        assert len(out) == 1
        assert out[0].text.strip() == "only one sentence"
        # No window_text on fallback chunks.
        assert "window_text" not in out[0].extra_info

    def test_oversized_sentence_token_capped(self):
        """A sentence exceeding max_tokens is hard-split."""
        long_sent = "word " * 300 + "."
        text = f"{long_sent} Short."
        chunker = SentenceWindowChunker(max_tokens=40, min_tokens=0, window_size=1)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        # More than 2 chunks: the oversized sentence is split.
        assert len(out) > 2
        for c in out:
            assert _tok(c.text) <= 40
            assert "window_text" in c.extra_info

    def test_source_extra_info_preserved(self):
        """Inherited extra_info (source, title) is preserved."""
        text = "Alpha one. Beta two. Gamma three."
        doc = Document(
            text=text,
            doc_id="d",
            extra_info={"source": "file.md", "title": "T"},
        )
        chunker = SentenceWindowChunker(max_tokens=2000, min_tokens=0)
        out = chunker.chunk([doc])
        assert len(out) == 3
        for c in out:
            assert c.extra_info["source"] == "file.md"
            assert c.extra_info["title"] == "T"
            assert c.extra_info["token_count"] == _tok(c.text)
            assert c.doc_id.startswith("d-")

    def test_default_window_size(self):
        """Default window_size=2 produces a 5-sentence window for middle."""
        text = "A. B. C. D. E. F. G."
        chunker = SentenceWindowChunker(max_tokens=2000, min_tokens=0)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        # For sentence "D." (index 3), window should span [1..5] = B C D E F
        d_chunk = out[3]
        assert d_chunk.text == "D."
        window = d_chunk.extra_info["window_text"]
        assert "B." in window
        assert "C." in window
        assert "D." in window
        assert "E." in window
        assert "F." in window


@pytest.mark.unit
class TestClassicByteIdentical:
    def test_classic_chunk_unchanged(self):
        # The new strategies must not perturb the classic baseline.
        docs = [
            Document(text="A short paragraph.", doc_id="small"),
            Document(text="word " * 4000, doc_id="large"),
        ]
        params = dict(max_tokens=1250, min_tokens=150, duplicate_headers=False)
        direct = Chunker(chunking_strategy="classic_chunk", **params).chunk(docs)
        via = ChunkerCreator.create_chunker("classic_chunk", **params).chunk(
            [
                Document(text="A short paragraph.", doc_id="small"),
                Document(text="word " * 4000, doc_id="large"),
            ]
        )
        assert [(c.doc_id, c.text, c.extra_info) for c in via] == [
            (c.doc_id, c.text, c.extra_info) for c in direct
        ]
