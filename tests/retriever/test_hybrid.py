"""Tests for the hybrid retriever (vector + keyword RRF fusion)."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from application.retriever.hybrid_rag import HybridRetriever, reciprocal_rank_fusion
from application.retriever.retriever_creator import RetrieverCreator


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


def _make_hybrid(source=None, **overrides):
    defaults = dict(
        source=source or {"question": "q", "active_docs": ["vs1"]},
        chat_history=None,
        prompt="",
        chunks=2,
        doc_token_limit=50000,
        model_id="test-model",
        llm_name="openai",
        api_key="fake",
        decoded_token={"sub": "user1"},
    )
    defaults.update(overrides)
    return HybridRetriever(**defaults)


# ── RRF fusion ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestReciprocalRankFusion:
    def test_doc_in_both_lists_outranks_singletons(self):
        shared = _make_doc("shared", source="x")
        only_vec = _make_doc("vec_only", source="v")
        only_kw = _make_doc("kw_only", source="k")
        # "shared" is rank-1 in vector and rank-0 in keyword → highest summed score.
        vector_hits = [only_vec, shared]
        keyword_hits = [shared, only_kw]

        fused = reciprocal_rank_fusion(vector_hits, keyword_hits)

        assert fused[0].page_content == "shared"
        assert {d.page_content for d in fused} == {"shared", "vec_only", "kw_only"}

    def test_empty_keyword_is_vector_only_order(self):
        vector_hits = [_make_doc("a", source="a"), _make_doc("b", source="b")]
        fused = reciprocal_rank_fusion(vector_hits, [])
        assert [d.page_content for d in fused] == ["a", "b"]

    def test_dedupes_same_doc(self):
        d_vec = _make_doc("same", source="same")
        d_kw = _make_doc("same", source="same")
        fused = reciprocal_rank_fusion([d_vec], [d_kw])
        assert len(fused) == 1

    def test_higher_keyword_rank_can_promote(self):
        # Vector top is "v0"; keyword strongly favours "kw" (rank 0 vs v0's rank 1).
        v0 = _make_doc("v0", source="v0")
        kw = _make_doc("kw", source="kw")
        fused = reciprocal_rank_fusion([v0, kw], [kw])
        assert fused[0].page_content == "kw"


# ── HybridRetriever._get_data ────────────────────────────────────────────────


@pytest.mark.unit
class TestHybridGetData:
    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_fuses_vector_and_keyword(self, _tok, mock_vc, _patch_llm_creator):
        docsearch = MagicMock()
        docsearch.search.return_value = [_make_doc("vec", source="vec")]
        docsearch.keyword_search.return_value = [_make_doc("kw", source="kw")]
        mock_vc.create_vectorstore.return_value = docsearch

        rag = _make_hybrid()
        docs = rag._get_data()

        docsearch.search.assert_called_once()
        docsearch.keyword_search.assert_called_once()
        assert {d["text"] for d in docs} == {"vec", "kw"}

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_keyword_empty_equals_vector_only(self, _tok, mock_vc, _patch_llm_creator):
        vec_docs = [_make_doc("a", source="a"), _make_doc("b", source="b")]

        # Hybrid with empty keyword results.
        ds_hybrid = MagicMock()
        ds_hybrid.search.return_value = list(vec_docs)
        ds_hybrid.keyword_search.return_value = []
        mock_vc.create_vectorstore.return_value = ds_hybrid
        hybrid_out = _make_hybrid().search("query")

        # Vector-only baseline: same vector hits, no keyword call.
        from application.retriever.classic_rag import ClassicRAG

        with patch(
            "application.retriever.classic_rag.VectorCreator"
        ) as mock_vc_classic, patch(
            "application.retriever.classic_rag.num_tokens_from_string", return_value=10
        ):
            ds_classic = MagicMock()
            ds_classic.search.return_value = list(vec_docs)
            mock_vc_classic.create_vectorstore.return_value = ds_classic
            classic_out = ClassicRAG(
                source={"question": "q", "active_docs": ["vs1"]},
                chat_history=None,
                chunks=2,
                doc_token_limit=50000,
                model_id="test-model",
                llm_name="openai",
                api_key="fake",
                decoded_token={"sub": "user1"},
            ).search("query")

        assert hybrid_out == classic_out

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_score_threshold_not_applied_to_fused(self, _tok, mock_vc, _patch_llm_creator):
        from application.storage.db.source_config import RetrievalConfig

        docsearch = MagicMock()
        docsearch.search.return_value = [_make_doc("a", source="a")]
        docsearch.keyword_search.return_value = []
        mock_vc.create_vectorstore.return_value = docsearch

        rag = _make_hybrid()
        rag.per_source_retrieval = {"vs1": RetrievalConfig(score_threshold=0.9)}
        rag._get_data()

        # RRF scores are not cosine — score_threshold must not reach the store.
        assert "score_threshold" not in docsearch.search.call_args.kwargs
        assert "score_threshold" not in docsearch.keyword_search.call_args.kwargs

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_chunks_zero_returns_empty(self, _tok, mock_vc, _patch_llm_creator):
        rag = _make_hybrid(chunks=0)
        assert rag._get_data() == []
        mock_vc.create_vectorstore.assert_not_called()

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_store_error_continues(self, _tok, mock_vc, _patch_llm_creator):
        mock_vc.create_vectorstore.side_effect = RuntimeError("boom")
        rag = _make_hybrid()
        assert rag._get_data() == []


# ── Registry resolution ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestHybridRegistration:
    def test_hybrid_resolves_via_creator(self):
        assert RetrieverCreator.retrievers["hybrid"] is HybridRetriever

    def test_create_retriever_builds_hybrid(self, _patch_llm_creator):
        retriever = RetrieverCreator.create_retriever(
            "hybrid",
            source={"question": "q", "active_docs": ["vs1"]},
            chunks=2,
            doc_token_limit=50000,
            model_id="m",
            llm_name="openai",
            api_key="fake",
            decoded_token={"sub": "u"},
        )
        assert isinstance(retriever, HybridRetriever)
