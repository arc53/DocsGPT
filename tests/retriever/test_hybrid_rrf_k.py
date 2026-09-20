"""Per-source RRF constant for the hybrid retriever.

``RetrievalConfig.rrf_k`` overrides the module-level ``RRF_K`` for one source;
``None`` (the default) keeps today's behaviour byte-identical.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.retriever.hybrid_rag import RRF_K, HybridRetriever, fuse_with_scores


@pytest.fixture
def _patch_llm_creator(mock_llm, monkeypatch):
    monkeypatch.setattr(
        "docsgpt.retriever.classic_rag.LLMCreator.create_llm",
        Mock(return_value=mock_llm),
    )
    return mock_llm


def _make_doc(page_content, source="s"):
    doc = Mock()
    doc.page_content = page_content
    doc.metadata = {"source": source}
    return doc


def _make_hybrid(**overrides):
    defaults = dict(
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
    defaults.update(overrides)
    return HybridRetriever(**defaults)


@pytest.mark.unit
class TestRrfKConfig:
    def test_default_is_none(self):
        from docsgpt.storage.db.source_config import RetrievalConfig

        assert RetrievalConfig().rrf_k is None

    def test_rejects_out_of_range(self):
        from docsgpt.storage.db.source_config import RetrievalConfig

        with pytest.raises(ValueError):
            RetrievalConfig(rrf_k=0)
        with pytest.raises(ValueError):
            RetrievalConfig(rrf_k=501)

    def test_overrides_dispatcher_parity_check(self, _patch_llm_creator):
        from docsgpt.retriever.dispatcher import Dispatcher
        from docsgpt.storage.db.source_config import RetrievalConfig

        assert not Dispatcher._is_override(RetrievalConfig())
        assert Dispatcher._is_override(RetrievalConfig(rrf_k=10))


@pytest.mark.unit
class TestRrfKPlumbing:
    def test_resolve_source_carries_rrf_k(self, _patch_llm_creator):
        from docsgpt.storage.db.source_config import RetrievalConfig

        rag = _make_hybrid()
        assert rag._resolve_source("vs1", 2)["rrf_k"] is None

        rag.per_source_retrieval = {"vs1": RetrievalConfig(rrf_k=10)}
        assert rag._resolve_source("vs1", 2)["rrf_k"] == 10

    @patch("docsgpt.retriever.hybrid_rag.fuse_with_scores")
    def test_fetch_candidates_uses_configured_k(self, fuse_spy, _patch_llm_creator):
        fuse_spy.side_effect = lambda v, kh, **kw: fuse_with_scores(v, kh)
        docsearch = MagicMock()
        docsearch.search.return_value = [_make_doc("vec", source="v")]
        docsearch.keyword_search.return_value = [_make_doc("kw", source="k")]

        rag = _make_hybrid()
        rag._fetch_candidates(docsearch, "q", 2, None, rrf_k=10)
        assert fuse_spy.call_args.kwargs["k"] == 10

    @patch("docsgpt.retriever.hybrid_rag.fuse_with_scores")
    def test_fetch_candidates_defaults_to_rrf_k(self, fuse_spy, _patch_llm_creator):
        fuse_spy.side_effect = lambda v, kh, **kw: fuse_with_scores(v, kh)
        docsearch = MagicMock()
        docsearch.search.return_value = [_make_doc("vec", source="v")]
        docsearch.keyword_search.return_value = [_make_doc("kw", source="k")]

        _make_hybrid()._fetch_candidates(docsearch, "q", 2, None)
        assert fuse_spy.call_args.kwargs["k"] == RRF_K
