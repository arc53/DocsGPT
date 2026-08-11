"""Tests for the per-source retrieval Dispatcher (B1a) and the kill-switch."""

from unittest.mock import Mock, patch

import pytest

from application.retriever.dispatcher import Dispatcher, build_dispatcher
from application.storage.db.source_config import RetrievalConfig


@pytest.fixture
def _patch_llm_creator(mock_llm, monkeypatch):
    monkeypatch.setattr(
        "application.retriever.classic_rag.LLMCreator.create_llm",
        Mock(return_value=mock_llm),
    )
    return mock_llm


def _make_doc(page_content, title="t", source="s"):
    doc = Mock()
    doc.page_content = page_content
    doc.metadata = {"title": title, "source": source}
    return doc


@pytest.mark.unit
class TestDispatcherGrouping:
    def test_no_sources_single_classic_group(self, _patch_llm_creator):
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b"]})
        groups = d._groups
        assert len(groups) == 1
        assert groups[0]["retriever"] == "classic"
        assert groups[0]["doc_ids"] == ["a", "b"]
        assert groups[0]["retrievals"] == {}

    def test_all_classic_collapse_to_one_group(self, _patch_llm_creator):
        sources = [
            {"id": "a", "retrieval": RetrievalConfig()},
            {"id": "b", "retrieval": RetrievalConfig()},
        ]
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b"]}, sources=sources)
        assert len(d._groups) == 1
        assert d._groups[0]["retriever"] == "classic"
        # All-default sources record no override → byte-identical global path.
        assert d._groups[0]["retrievals"] == {}

    def test_default_and_alias_share_one_group(self, _patch_llm_creator):
        sources = [
            {"id": "a", "retrieval": RetrievalConfig(retriever="classic")},
            {"id": "b", "retrieval": RetrievalConfig(retriever="default")},
        ]
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b"]}, sources=sources)
        assert len(d._groups) == 1
        assert d._groups[0]["doc_ids"] == ["a", "b"]

    def test_non_classic_gets_own_group(self, _patch_llm_creator):
        sources = [
            {"id": "a", "retrieval": RetrievalConfig(retriever="classic")},
            {"id": "b", "retrieval": RetrievalConfig(retriever="graphrag")},
        ]
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b"]}, sources=sources)
        keys = sorted(g["retriever"] for g in d._groups)
        assert keys == ["classic", "graphrag"]

    def test_override_recorded_only_when_non_default(self, _patch_llm_creator):
        sources = [
            {"id": "a", "retrieval": RetrievalConfig(chunks=7)},
            {"id": "b", "retrieval": RetrievalConfig()},
        ]
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b"]}, sources=sources)
        retrievals = d._groups[0]["retrievals"]
        assert "a" in retrievals
        assert "b" not in retrievals


@pytest.mark.unit
class TestDispatcherSharedBudget:
    def test_single_group_full_budget(self, _patch_llm_creator):
        d = Dispatcher(source={"question": "q", "active_docs": ["a"]}, doc_token_limit=5000)
        assert d._budget_for_group(1, 0) == 5000

    def test_multi_group_budget_split_never_exceeds_total(self, _patch_llm_creator):
        d = Dispatcher(source={"question": "q", "active_docs": ["a"]}, doc_token_limit=1000)
        budgets = [d._budget_for_group(3, i) for i in range(3)]
        assert sum(budgets) == 1000
        # Remainder goes to the first groups.
        assert budgets == [334, 333, 333]


@pytest.mark.unit
class TestDispatcherParity:
    """All-classic sources through the Dispatcher == one ClassicRAG today."""

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_single_group_matches_classic_rag(self, _tok, mock_vc, _patch_llm_creator):
        from application.retriever.classic_rag import ClassicRAG

        docsearch = Mock()
        docsearch.search.return_value = [_make_doc("content one"), _make_doc("content two")]
        mock_vc.create_vectorstore.return_value = docsearch

        common = dict(
            source={"question": "q", "active_docs": ["a", "b"]},
            chat_history=[],
            chunks=2,
            doc_token_limit=50000,
            model_id="m",
            decoded_token={"sub": "u"},
        )

        baseline = ClassicRAG(**common).search("query")
        dispatched = Dispatcher(
            sources=[
                {"id": "a", "retrieval": RetrievalConfig()},
                {"id": "b", "retrieval": RetrievalConfig()},
            ],
            **common,
        ).search("query")

        assert dispatched == baseline

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_no_sources_matches_classic_rag(self, _tok, mock_vc, _patch_llm_creator):
        from application.retriever.classic_rag import ClassicRAG

        docsearch = Mock()
        docsearch.search.return_value = [_make_doc("a")]
        mock_vc.create_vectorstore.return_value = docsearch

        common = dict(
            source={"question": "q", "active_docs": ["a"]},
            chat_history=[],
            chunks=2,
            doc_token_limit=50000,
            decoded_token={"sub": "u"},
        )
        baseline = ClassicRAG(**common).search("query")
        dispatched = Dispatcher(**common).search("query")
        assert dispatched == baseline


@pytest.mark.unit
class TestDispatcherStageSeam:
    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_stage_applied_to_candidates(self, _tok, mock_vc, _patch_llm_creator):
        docsearch = Mock()
        docsearch.search.return_value = [_make_doc("keep"), _make_doc("drop")]
        mock_vc.create_vectorstore.return_value = docsearch

        def drop_stage(docs, context):
            return [d for d in docs if d["text"] == "keep"]

        d = Dispatcher(
            source={"question": "q", "active_docs": ["a"]},
            stages=[drop_stage],
        )
        out = d.search("query")
        assert [doc["text"] for doc in out] == ["keep"]

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_default_stages_passthrough(self, _tok, mock_vc, _patch_llm_creator):
        docsearch = Mock()
        docsearch.search.return_value = [_make_doc("a")]
        mock_vc.create_vectorstore.return_value = docsearch
        d = Dispatcher(source={"question": "q", "active_docs": ["a"]})
        assert len(d.search("query")) == 1


@pytest.mark.unit
class TestDispatcherLenientRead:
    """D7: a garbage/legacy per-source config still retrieves via classic."""

    def test_coerce_garbage_falls_back_to_default(self):
        assert Dispatcher._coerce_retrieval("not-a-dict") == RetrievalConfig()
        assert Dispatcher._coerce_retrieval(None) == RetrievalConfig()
        # An invalid dict that fails validation also falls back.
        assert Dispatcher._coerce_retrieval({"chunks": "abc"}) == RetrievalConfig()

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_garbage_config_retrieves_via_classic(self, _tok, mock_vc, _patch_llm_creator):
        docsearch = Mock()
        docsearch.search.return_value = [_make_doc("ok")]
        mock_vc.create_vectorstore.return_value = docsearch

        d = Dispatcher(
            source={"question": "q", "active_docs": ["a"]},
            sources=[{"id": "a", "retrieval": {"bogus": True, "chunks": "x"}}],
        )
        out = d.search("query")
        assert [doc["text"] for doc in out] == ["ok"]
        # Falls back to the global classic path (no override recorded).
        assert d._groups[0]["retriever"] == "classic"
        assert d._groups[0]["retrievals"] == {}


@pytest.mark.unit
class TestDispatcherPrescreen:
    """F1: prescreen bumps candidate_k, trims to max_keep, off == today."""

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_candidate_k_fetched_and_trimmed(self, _tok, mock_vc, _patch_llm_creator):
        docsearch = Mock()
        # Return 40 candidate docs; prescreen should trim to max_keep=3.
        docsearch.search.return_value = [
            _make_doc(f"c{i}") for i in range(40)
        ]
        mock_vc.create_vectorstore.return_value = docsearch

        prescreen_llm = Mock()
        # Keep the first index of each batch.
        prescreen_llm.gen = Mock(return_value='{"keep": [0]}')
        prescreen_llm.model_id = "m"

        with patch(
            "application.retriever.stages.prescreen.LLMCreator.create_llm",
            return_value=prescreen_llm,
        ):
            d = Dispatcher(
                source={"question": "q", "active_docs": ["a"]},
                doc_token_limit=500000,
                sources=[
                    {
                        "id": "a",
                        "retrieval": {
                            "chunks": 2,
                            "prescreen": {
                                "candidate_k": 40,
                                "batch_size": 10,
                                "max_keep": 3,
                            },
                        },
                    }
                ],
            )
            out = d.search("query")

        # Base retriever asked for >= candidate_k candidates.
        _, kwargs = docsearch.search.call_args
        assert kwargs["k"] >= 40
        # Prescreen ran (4 batches of 10) and trimmed to max_keep.
        assert prescreen_llm.gen.call_count == 4
        assert len(out) == 3

    @patch("application.retriever.stages.prescreen.build_prescreen_stages")
    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_prescreen_none_no_extra_llm_calls(
        self, _tok, mock_vc, mock_build, _patch_llm_creator
    ):
        docsearch = Mock()
        docsearch.search.return_value = [_make_doc("one"), _make_doc("two")]
        mock_vc.create_vectorstore.return_value = docsearch
        # The dispatcher imports the symbol; patch where it's looked up.
        import application.retriever.dispatcher as disp

        with patch.object(disp, "build_prescreen_stages", mock_build):
            mock_build.return_value = []
            d = Dispatcher(
                source={"question": "q", "active_docs": ["a"]},
                sources=[{"id": "a", "retrieval": RetrievalConfig()}],
            )
            out = d.search("query")

        # A default (non-prescreen) source records no override, so the prescreen
        # stage builder is invoked with an empty retrievals map and yields no
        # stages — i.e. zero extra screening calls — and output is unchanged.
        for call in mock_build.call_args_list:
            assert call.args[0] == {}
        assert [doc["text"] for doc in out] == ["one", "two"]

    def test_prescreen_only_source_records_override(self, _patch_llm_creator):
        d = Dispatcher(
            source={"question": "q", "active_docs": ["a"]},
            sources=[
                {
                    "id": "a",
                    "retrieval": {
                        "chunks": 2,
                        "prescreen": {"candidate_k": 20, "max_keep": 5},
                    },
                }
            ],
        )
        # A source that opts into prescreen only must still record an override
        # so the stage actually fires.
        assert "a" in d._groups[0]["retrievals"]


@pytest.mark.unit
class TestKillSwitch:
    def test_disabled_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setattr(
            "application.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED",
            False,
        )
        sentinel = object()
        result = build_dispatcher(
            lambda: sentinel,
            source={"question": "q", "active_docs": ["a"]},
            sources=[{"id": "a", "retrieval": RetrievalConfig(chunks=9)}],
        )
        assert result is sentinel

    def test_enabled_returns_dispatcher(self, monkeypatch, _patch_llm_creator):
        monkeypatch.setattr(
            "application.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED",
            True,
        )
        result = build_dispatcher(
            lambda: object(),
            source={"question": "q", "active_docs": ["a"]},
            sources=[],
        )
        assert isinstance(result, Dispatcher)
