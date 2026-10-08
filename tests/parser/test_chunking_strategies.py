"""Tests for the recursive / markdown / parent_child / semantic strategies."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docsgpt.parser.chunking import Chunker
from docsgpt.parser.chunking_creator import ChunkerCreator
from docsgpt.parser.chunking_strategies import (
    MarkdownChunker,
    ParentChildChunker,
    RecursiveChunker,
    SemanticChunker,
)
from docsgpt.parser.limits import MAX_CHUNK_TOKENS
from docsgpt.parser.schema.base import Document
from docsgpt.parser.tokenization import HuggingFaceCounter, get_token_counter


def _tok(text: str) -> int:
    # Chunk budgets are enforced in the embedding model's tokenizer, so a
    # test that measures them in cl100k measures the wrong thing.
    return get_token_counter().count(text)


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
        ):
            assert ChunkerCreator.chunkers.get(key) is cls

    def test_worker_kwargs_accepted(self):
        # The worker builds every strategy with the classic kwarg set.
        for strat in ("recursive", "markdown", "parent_child", "semantic"):
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
        lc = out[0].to_vector_format()
        # parent_text must survive the langchain conversion into metadata.
        assert "parent_text" in lc.metadata
        assert lc.metadata["parent_text"]
        assert lc.page_content == out[0].text

    def test_child_size_defaults_when_min_zero(self):
        chunker = ParentChildChunker(max_tokens=200, min_tokens=0)
        out = chunker.chunk([Document(text="gamma " * 200, doc_id="d")])
        assert all("parent_text" in c.extra_info for c in out)


_EMB_TARGET = "docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance"


class _FakeEmbeddings:
    def __init__(self, vectors):
        self._vectors = vectors

    def embed_documents(self, sentences):
        return self._vectors


class _RecordingEmbeddings:
    def __init__(self):
        self.calls = []

    def embed_documents(self, sentences):
        self.calls.append(list(sentences))
        return [[1.0, 0.0] for _ in sentences]


class _CharacterCounter:
    """Deterministic counter where one character equals one token."""

    @staticmethod
    def count(text):
        return len(text)

    @staticmethod
    def split(text, max_tokens):
        return [text[i : i + max_tokens] for i in range(0, len(text), max_tokens)]


class _CollapsingEncoding:
    """WordPiece-like offsets: one token per word, including long unknowns."""

    def __init__(self, text):
        self.ids = []
        self.offsets = []
        cursor = 0
        for word in text.split(" "):
            if word:
                self.ids.append(0)
                self.offsets.append((cursor, cursor + len(word)))
            cursor += len(word) + 1


class _CollapsingTokenizer:
    def encode(self, text, add_special_tokens=False):
        return _CollapsingEncoding(text)


def _wordpiece_counter():
    return HuggingFaceCounter(_CollapsingTokenizer(), "wordpiece-stub")


@pytest.mark.unit
class TestSemantic:
    @pytest.fixture(autouse=True)
    def _no_remote_embeddings(self, monkeypatch):
        """The resolver short-circuits to the remote API when this is set."""
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "EMBEDDINGS_BASE_URL", None)

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
        embeddings = _RecordingEmbeddings()
        chunker = SemanticChunker(max_tokens=40, min_tokens=0)
        with patch(_EMB_TARGET, return_value=embeddings):
            out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) > 1
        assert embeddings.calls
        for c in out:
            assert _tok(c.text) <= 40

    def test_embedding_requests_bound_batch_and_input_tokens(self):
        short_sentences = " ".join(f"Sentence {i}." for i in range(70))
        oversized_sentence = "word " * 5000 + "."
        embeddings = _RecordingEmbeddings()
        # Exercise the hard ceiling even if a chunker is constructed directly
        # with a legacy value that bypasses SourceConfig validation.
        chunker = SemanticChunker(max_tokens=10_000, min_tokens=0)

        with patch(
            "docsgpt.vectorstore.base.get_embeddings", return_value=embeddings
        ):
            out = chunker.chunk(
                [Document(text=f"{short_sentences} {oversized_sentence}", doc_id="d")]
            )

        assert out
        assert len(embeddings.calls) > 1
        assert all(len(batch) <= 32 for batch in embeddings.calls)
        assert all(
            _tok(text) <= MAX_CHUNK_TOKENS
            for batch in embeddings.calls
            for text in batch
        )

    def test_wordpiece_collapsed_span_is_bounded_before_embedding(self):
        text = "a" * 32_000 + " b" * 3_000 + ". Tail sentence."
        embeddings = _RecordingEmbeddings()
        chunker = SemanticChunker(max_tokens=10_000, min_tokens=0)
        chunker.counter = _wordpiece_counter()

        with patch(
            "docsgpt.vectorstore.base.get_embeddings", return_value=embeddings
        ):
            chunker.chunk([Document(text=text, doc_id="d")])

        assert embeddings.calls
        assert all(
            chunker.counter.count(embedded) <= MAX_CHUNK_TOKENS
            for batch in embeddings.calls
            for embedded in batch
        )

    def test_sentence_fragments_preserve_exact_text(self):
        text = "identifierWithoutSpaces1234567890.  Tail sentence."
        embeddings = _RecordingEmbeddings()
        chunker = SemanticChunker(max_tokens=10, min_tokens=0)
        chunker.counter = _CharacterCounter()

        with patch(
            "docsgpt.vectorstore.base.get_embeddings", return_value=embeddings
        ):
            out = chunker.chunk([Document(text=text, doc_id="d")])

        assert "".join(chunk.text for chunk in out) == text

    def test_direct_oversized_limit_caps_final_chunks(self):
        text = "a" * 5_000 + ". Tail sentence."
        embeddings = _RecordingEmbeddings()
        chunker = SemanticChunker(max_tokens=10_000, min_tokens=0)
        chunker.counter = _CharacterCounter()

        with patch(
            "docsgpt.vectorstore.base.get_embeddings", return_value=embeddings
        ):
            out = chunker.chunk([Document(text=text, doc_id="d")])

        assert out
        assert all(chunker.counter.count(chunk.text) <= MAX_CHUNK_TOKENS for chunk in out)

    def test_direct_oversized_limit_caps_recursive_fallback(self):
        text = "x" * 5_000
        chunker = SemanticChunker(max_tokens=10_000, min_tokens=0)
        chunker.counter = _CharacterCounter()

        out = chunker.chunk([Document(text=text, doc_id="d")])

        assert len(out) > 1
        assert all(chunker.counter.count(chunk.text) <= MAX_CHUNK_TOKENS for chunk in out)

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


@pytest.mark.unit
class TestSemanticEmbeddingsResolution:
    def test_uses_shared_resolver(self):
        """Semantic chunking must resolve embeddings through ``get_embeddings``.

        Calling the singleton directly with the configured name skips the
        bundled local model and downloads a second copy from the hub.
        """
        vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]
        text = "Alpha one. Alpha two. Beta one. Beta two."
        chunker = SemanticChunker(max_tokens=2000, min_tokens=0)

        with patch(
            "docsgpt.vectorstore.base.get_embeddings",
            return_value=_FakeEmbeddings(vectors),
        ) as mock_resolver:
            out = chunker.chunk([Document(text=text, doc_id="d")])

        mock_resolver.assert_called_once_with()
        assert len(out) == 2
