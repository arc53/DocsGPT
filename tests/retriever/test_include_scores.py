"""Score passthrough (``include_scores``) across the retrievers.

The retrieval-test endpoint needs each chunk's raw store score; the answer
pipeline does not. These tests pin both halves of that: opted in, the score and
its kind ride on every doc; opted out (the default everywhere else), the doc
dicts are exactly what they were before the flag existed.
"""

from unittest.mock import Mock, patch

import pytest

from application.retriever.classic_rag import ClassicRAG
from application.retriever.hybrid_rag import HybridRetriever


@pytest.fixture
def _patch_llm_creator(mock_llm, monkeypatch):
    monkeypatch.setattr(
        "application.retriever.classic_rag.LLMCreator.create_llm",
        Mock(return_value=mock_llm),
    )
    return mock_llm


def _make_doc(page_content, source="s", title="t"):
    doc = Mock()
    doc.page_content = page_content
    doc.metadata = {"title": title, "source": source}
    return doc


def _make_store(score_kind="cosine_similarity"):
    store = Mock()
    store.score_kind = score_kind
    store.search.return_value = [_make_doc("hit one"), _make_doc("hit two")]
    store.search_with_scores.return_value = [
        (_make_doc("hit one"), 0.82),
        (_make_doc("hit two"), 0.71),
    ]
    store.keyword_search.return_value = []
    return store


def _retrieve(retriever_cls, store, **overrides):
    kwargs = dict(
        source={"question": "q", "active_docs": ["vs1"]},
        chat_history=None,
        prompt="",
        chunks=2,
        doc_token_limit=50000,
        model_id="test-model",
        llm_name="openai",
        api_key="fake",
        decoded_token={"sub": "user1"},
    )
    kwargs.update(overrides)
    retriever = retriever_cls(**kwargs)
    with patch(
        "application.retriever.classic_rag.VectorCreator.create_vectorstore",
        return_value=store,
    ):
        return retriever.search("q")


@pytest.mark.unit
class TestClassicRAGScores:
    def test_off_by_default_leaves_docs_untouched(self, _patch_llm_creator):
        """The answer pipeline must see exactly the doc dict it saw before."""
        store = _make_store()
        docs = _retrieve(ClassicRAG, store)

        assert docs
        assert set(docs[0]) == {"text", "title", "source", "filename"}
        store.search.assert_called_once()
        store.search_with_scores.assert_not_called()

    def test_include_scores_attaches_score_and_kind(self, _patch_llm_creator):
        store = _make_store()
        docs = _retrieve(ClassicRAG, store, include_scores=True)

        assert [d["score"] for d in docs] == [0.82, 0.71]
        assert {d["score_kind"] for d in docs} == {"cosine_similarity"}
        store.search_with_scores.assert_called_once()
        store.search.assert_not_called()

    def test_unscored_store_yields_null_scores(self, _patch_llm_creator):
        """A store with no score seam reports None rather than a fabricated 0."""
        store = _make_store(score_kind=None)
        store.search_with_scores.return_value = [
            (_make_doc("hit one"), None),
            (_make_doc("hit two"), None),
        ]
        docs = _retrieve(ClassicRAG, store, include_scores=True)

        assert [d["score"] for d in docs] == [None, None]
        assert [d["score_kind"] for d in docs] == [None, None]


@pytest.mark.unit
class TestTopK:
    """``chunks`` is the final top-k, not just a floor on the fetch size."""

    def test_returns_at_most_chunks_docs(self, _patch_llm_creator):
        store = Mock()
        store.score_kind = None
        store.search.return_value = [_make_doc(f"hit {i}") for i in range(20)]
        store.keyword_search.return_value = []

        docs = _retrieve(ClassicRAG, store, chunks=2)

        assert len(docs) == 2
        assert [d["text"] for d in docs] == ["hit 0", "hit 1"]
        # The over-fetch itself is intact — only the tail is dropped.
        assert store.search.call_args.kwargs["k"] == 20

    def test_token_budget_still_caps_below_top_k(self, _patch_llm_creator):
        """The budget remains the harder of the two limits."""
        store = Mock()
        store.score_kind = None
        store.search.return_value = [_make_doc("word " * 500) for _ in range(10)]
        store.keyword_search.return_value = []

        docs = _retrieve(ClassicRAG, store, chunks=10, doc_token_limit=600)

        assert 0 < len(docs) < 10

    def test_hybrid_respects_top_k_too(self, _patch_llm_creator):
        store = Mock()
        store.score_kind = None
        store.search.return_value = [_make_doc(f"hit {i}") for i in range(20)]
        store.keyword_search.return_value = []

        docs = _retrieve(HybridRetriever, store, chunks=3)

        assert len(docs) == 3


@pytest.mark.unit
class TestHybridScores:
    def test_reports_rrf_not_the_store_kind(self, _patch_llm_creator):
        """RRF fuses two rankings — the fused number is not the store's cosine
        score, so it must not be labelled as one."""
        store = _make_store()
        store.keyword_search.return_value = [_make_doc("hit two")]

        docs = _retrieve(HybridRetriever, store, include_scores=True)

        assert {d["score_kind"] for d in docs} == {"rrf"}
        # A doc found by both searches outranks one found by vector search alone.
        assert docs[0]["text"] == "hit two"
        assert docs[0]["score"] > docs[1]["score"]

    def test_off_by_default_leaves_docs_untouched(self, _patch_llm_creator):
        store = _make_store()
        docs = _retrieve(HybridRetriever, store)

        assert docs
        assert set(docs[0]) == {"text", "title", "source", "filename"}


@pytest.mark.unit
class TestCandidateKDoesNotLeakAcrossSources:
    """A prescreen source's inflated fetch must not become its neighbour's top-k.

    The Dispatcher raises the group's ``chunks`` to the prescreen candidate_k so
    the fetch is big enough to screen. A source in that same group with no
    override still has to fall back to the group's *real* top-k.
    """

    def test_default_source_uses_base_chunks_not_the_inflated_fetch(
        self, _patch_llm_creator
    ):
        store = Mock()
        store.score_kind = None
        store.search.return_value = [_make_doc(f"hit {i}") for i in range(40)]
        store.keyword_search.return_value = []

        # What the Dispatcher does for a group whose other source prescreens at
        # candidate_k=40: chunks inflated to 40, base_chunks kept at the real 2.
        retriever = ClassicRAG(
            source={"question": "q", "active_docs": ["vs1", "vs2"]},
            chunks=40,
            doc_token_limit=50000,
            decoded_token={"sub": "u"},
        )
        retriever.base_chunks = 2

        with patch(
            "application.retriever.classic_rag.VectorCreator.create_vectorstore",
            return_value=store,
        ):
            docs = retriever.search("q")

        # 2 sources sharing a top-k of 2 → 1 chunk each, not 20 each.
        assert len(docs) == 2

    def test_absent_base_chunks_keeps_chunks_as_the_top_k(self, _patch_llm_creator):
        store = Mock()
        store.score_kind = None
        store.search.return_value = [_make_doc(f"hit {i}") for i in range(40)]
        store.keyword_search.return_value = []

        docs = _retrieve(ClassicRAG, store, chunks=4)

        assert len(docs) == 4


@pytest.mark.unit
class TestChunksCeiling:
    """``chunks`` is documented as a top-k but had a per-source floor of 1.

    Four sources at ``chunks=2`` returned four documents. The floor stays (no
    source should be starved), but the overshoot is now bounded by it.
    """

    def _rag(self, n_sources, chunks):
        from application.retriever.classic_rag import ClassicRAG

        rag = ClassicRAG.__new__(ClassicRAG)
        rag.vectorstores = [f"src-{i}" for i in range(n_sources)]
        rag.chunks = chunks
        rag.base_chunks = None
        rag.doc_token_limit = 100000
        rag.include_scores = False
        rag.question = "q"
        return rag

    @pytest.mark.parametrize(
        "n_sources,chunks,ceiling",
        [(4, 2, 4), (4, 10, 10), (1, 5, 5), (10, 2, 10)],
    )
    def test_ceiling_is_max_of_topk_and_source_count(self, n_sources, chunks, ceiling):
        rag = self._rag(n_sources, chunks)
        base = rag.base_chunks if rag.base_chunks is not None else rag.chunks
        assert max(base, len(rag.vectorstores)) == ceiling
