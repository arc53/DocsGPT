"""Tests for the recursive / markdown / parent_child / semantic strategies."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.parser.chunking import Chunker
from docsgpt.parser.chunking_creator import ChunkerCreator
from docsgpt.parser.chunking_strategies import (
    MarkdownChunker,
    ParentChildChunker,
    RecursiveChunker,
    SemanticChunker,
)
from docsgpt.parser.schema.base import Document
from docsgpt.parser.tokenization import get_token_counter


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

    def test_chunk_overlap_creates_overlapping_chunks(self):
        """Ensure chunk_overlap creates ordered suffix/prefix overlap with full coverage."""
        sentences = [
            "antelope baboon cheetah dingo",
            "elephant falcon giraffe hyena",
            "iguana jaguar kangaroo lemur",
            "mongoose narwhal ocelot penguin",
        ]
        text = ". ".join(sentences) + "."
        chunker = RecursiveChunker(max_tokens=15, min_tokens=3, chunk_overlap=8)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) >= 2
        for c in out:
            assert _tok(c.text) <= 15

        # Assert ordered suffix/prefix overlap between adjacent chunks
        for k in range(len(out) - 1):
            words_a = [w.strip(".,") for w in out[k].text.split() if w.strip(".,")]
            words_b = [w.strip(".,") for w in out[k + 1].text.split() if w.strip(".,")]
            common = [w for w in words_a if w in words_b]
            assert len(common) > 0, f"Expected overlap between chunk {k} and {k+1}"
            assert words_a[-len(common):] == common
            assert words_b[:len(common)] == common

        # Full source coverage: all original distinct words present in output
        all_chunk_words = {w.strip(".,") for c in out for w in c.text.split()}
        for sentence in sentences:
            for word in sentence.split():
                assert word in all_chunk_words, f"Missing source word: {word}"

    def test_chunk_overlap_zero_produces_disjoint_chunks(self):
        """Ensure chunk_overlap=0 produces disjoint chunks without repeated content."""
        text = "\n\n".join([f"Paragraph {i} content text." for i in range(10)])
        chunker = RecursiveChunker(max_tokens=25, min_tokens=5, chunk_overlap=0)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) >= 2
        # Without overlap, paragraphs are disjoint
        for i in range(len(out) - 1):
            assert out[i].text.strip() not in out[i + 1].text

    def test_words_not_split_mid_word(self):
        """Ensure whitespace separator prevents slicing words mid-word."""
        # Text without newlines or periods: words must remain intact
        words = ["elephant", "hippopotamus", "rhinoceros", "chimpanzee", "crocodile"] * 6
        text = " ".join(words)
        chunker = RecursiveChunker(max_tokens=15, min_tokens=3, chunk_overlap=0)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) > 1
        for c in out:
            # Each chunk's words must be full words from our list
            chunk_words = c.text.strip().split()
            for w in chunk_words:
                assert w in words, f"Word '{w}' was sliced mid-word!"

    def test_multi_token_word_intact_with_small_positive_overlap(self):
        """Ensure multi-token words exceeding small chunk_overlap remain intact if <= max_tokens."""
        long_word = "antidisestablishmentarianism"
        assert _tok(long_word) > 3
        text = f"prefix intro words. {long_word}. trailing conclusion words."
        chunker = RecursiveChunker(max_tokens=15, min_tokens=1, chunk_overlap=3)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        combined = " ".join(c.text for c in out)
        assert long_word in combined
        for c in out:
            if "anti" in c.text:
                assert long_word in c.text

    def test_forward_progress_near_overlap_limit(self):
        """Ensure chunker makes forward progress without looping when overlap is max_tokens - 1."""
        sentences = [f"item_{i}" for i in range(20)]
        text = " ".join(sentences)
        chunker = RecursiveChunker(max_tokens=6, min_tokens=1, chunk_overlap=5)
        out = chunker.chunk([Document(text=text, doc_id="d")])
        assert len(out) > 1
        for k in range(len(out) - 1):
            curr_words = out[k].text.split()
            next_words = out[k + 1].text.split()
            assert next_words != curr_words
        assert "item_19" in out[-1].text

    def test_recursive_chunk_alias_is_registered(self):
        """Ensure recursive_chunk alias resolves to RecursiveChunker."""
        chunker = ChunkerCreator.create_chunker("recursive_chunk")
        assert isinstance(chunker, RecursiveChunker)

    def test_regression_max_10_min_5_overlap_9_avoids_undersized_chunk(self):
        """Regression: max_tokens=10, min_tokens=5, chunk_overlap=9 avoids undersized overlap chunk."""
        chunker = RecursiveChunker(max_tokens=10, min_tokens=5, chunk_overlap=9)
        token_map = {"f1": 6, "f2": 4, "f3": 9, "f1f2": 10, "f2f3": 13, "f1f2f3": 19}
        chunker._token_count = lambda text: token_map.get(text, len(text))

        chunks = chunker._merge_fragments(["f1", "f2", "f3"])
        # f1 + f2 = 10 tokens (chunk 1)
        # overlap would be f2 (4 tokens < min_tokens 5)
        # f2 + f3 = 13 tokens > max_tokens 10
        # Undersized overlap f2 is skipped so chunk 2 starts at f3
        assert chunks == ["f1f2", "f3"]
        for c in chunks:
            assert chunker._token_count(c) >= 5

    def test_overlap_skipped_when_overlap_cannot_fit_next_fragment(self):
        """Ensure overlap-only chunks are avoided even when overlap meets min_tokens."""
        chunker = RecursiveChunker(max_tokens=10, min_tokens=5, chunk_overlap=9)
        # Fragment sequence [4, 6, 9]: f2 (6) meets min_tokens (5), but f2 + f3 (15) > max_tokens (10)
        token_map = {"f1": 4, "f2": 6, "f3": 9, "f1f2": 10, "f2f3": 15, "f1f2f3": 19}
        chunker._token_count = lambda text: token_map.get(text, len(text))

        chunks = chunker._merge_fragments(["f1", "f2", "f3"])
        # Chunk 1: "f1f2" (10). Overlap "f2" (6) cannot combine with "f3" (9).
        # Must advance directly to "f3" rather than emitting redundant ["f1f2", "f2", "f3"].
        assert chunks == ["f1f2", "f3"]

    def test_overlap_is_trimmed_when_exceeding_max_tokens_with_next_fragment(self):
        """Ensure overlap is trimmed rather than dropped when overlap + next fragment exceeds max_tokens."""
        chunker = RecursiveChunker(max_tokens=15, min_tokens=1, chunk_overlap=8)
        # f1 (4) + f2 (4) + f3 (4) = 12 <= 15 (chunk 1)
        # target overlap up to 8 is f2 (4) + f3 (4) = 8
        # next fragment f4 has 9 tokens
        # full overlap (8) + f4 (9) = 17 > 15
        # Trimming reduces overlap to f3 (4 tokens) so f3 (4) + f4 (9) = 13 <= 15
        token_map = {"f1": 4, "f2": 4, "f3": 4, "f4": 9}
        chunker._token_count = lambda text: token_map.get(text, len(text))

        chunks = chunker._merge_fragments(["f1", "f2", "f3", "f4"])
        assert chunks == ["f1f2f3", "f3f4"]


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

    def test_semantic_fallback_passes_chunk_overlap(self, monkeypatch):
        """Ensure SemanticChunker._fallback preserves chunk_overlap when building RecursiveChunker."""
        chunker = SemanticChunker(max_tokens=100, min_tokens=10, chunk_overlap=30)
        captured = []

        def spy_chunker(*args, **kwargs):
            captured.append(kwargs)
            mock = MagicMock()
            mock.chunk.return_value = []
            return mock

        monkeypatch.setattr(
            "docsgpt.parser.chunking_strategies.RecursiveChunker", spy_chunker
        )
        chunker._fallback([Document(text="fallback test")])
        assert len(captured) == 1
        assert captured[0]["chunk_overlap"] == 30

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

    def test_explicit_classic_chunk_config_preserves_output(self):
        """Explicitly selecting classic_chunk preserves historical output."""
        from docsgpt.storage.db.source_config import ChunkingConfig

        cfg = ChunkingConfig(strategy="classic_chunk")
        chunker = ChunkerCreator.create_chunker(
            cfg.strategy,
            max_tokens=cfg.max_tokens,
            min_tokens=cfg.min_tokens,
            duplicate_headers=cfg.duplicate_headers,
        )
        assert isinstance(chunker, Chunker)

        docs = [Document(text="word " * 3000, doc_id="large")]
        direct = Chunker(max_tokens=1250, min_tokens=150).chunk(docs)
        via = chunker.chunk([Document(text="word " * 3000, doc_id="large")])
        assert [c.text for c in via] == [c.text for c in direct]

    def test_default_config_preserves_classic_output(self):
        """Default ChunkingConfig() preserves historical classic_chunk output."""
        from docsgpt.storage.db.source_config import ChunkingConfig

        cfg = ChunkingConfig()
        assert cfg.strategy == "classic_chunk"
        assert cfg.chunk_overlap == 0
        chunker = ChunkerCreator.create_chunker(
            cfg.strategy,
            max_tokens=cfg.max_tokens,
            min_tokens=cfg.min_tokens,
            chunk_overlap=cfg.chunk_overlap,
            duplicate_headers=cfg.duplicate_headers,
        )
        assert isinstance(chunker, Chunker)

        docs = [Document(text="word " * 3000, doc_id="large")]
        direct = Chunker(max_tokens=1250, min_tokens=150).chunk(docs)
        via = chunker.chunk([Document(text="word " * 3000, doc_id="large")])
        assert [c.text for c in via] == [c.text for c in direct]


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
