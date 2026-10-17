"""Tests for the per-source retrieval Dispatcher (B1a) and the kill-switch."""

from unittest.mock import Mock, patch

import pytest

from docsgpt.core.settings import settings
from docsgpt.decisions import record
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.retriever.classic_rag import ClassicRAG
from docsgpt.retriever.dispatcher import Dispatcher, build_dispatcher
from docsgpt.retriever.stages.relevance import rollout_on
from docsgpt.storage.db.source_config import GraphRetrievalConfig, RetrievalConfig


@pytest.fixture
def _patch_llm_creator(mock_llm, monkeypatch):
    monkeypatch.setattr(
        "docsgpt.retriever.classic_rag.LLMCreator.create_llm",
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


    def test_source_stored_at_the_old_default_is_an_override(self, _patch_llm_creator):
        # Accepted when the default moved from 2 to 6: sources saved with the
        # full config store chunks=2 and keep it as their own setting, while a
        # new upload stores 6, the default, and takes the global path.
        sources = [
            {"id": "old", "retrieval": RetrievalConfig(chunks=2)},
            {"id": "new", "retrieval": RetrievalConfig(chunks=6)},
        ]
        d = Dispatcher(source={"question": "q", "active_docs": ["old", "new"]}, sources=sources)
        retrievals = d._groups[0]["retrievals"]
        assert retrievals["old"].chunks == 2
        assert "new" not in retrievals

    def test_default_budget_is_six(self, _patch_llm_creator):
        assert Dispatcher(source={"question": "q", "active_docs": ["a"]}).chunks == 6

    def test_graph_options_count_as_an_override(self, _patch_llm_creator):
        """A graph source that changes only its graph options still needs its
        config carried over: those options live on the per-source retrieval the
        Dispatcher hands the retriever, so without this the UI toggles are
        no-ops and every source runs the defaults."""
        sources = [
            {
                "id": "a",
                "retrieval": RetrievalConfig(
                    retriever="graphrag", graph={"seed_strategy": "relationships"}
                ),
            },
            {"id": "b", "retrieval": RetrievalConfig(retriever="graphrag")},
        ]
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b"]}, sources=sources)
        retrievals = d._groups[0]["retrievals"]
        assert "a" in retrievals
        assert retrievals["a"].graph.seed_strategy == "relationships"
        # A source on the defaults still takes the shared path.
        assert "b" not in retrievals

    def test_graph_options_on_a_classic_source_are_not_an_override(self, _patch_llm_creator):
        # They only mean anything to the graph retriever; treating them as an
        # override would hand a classic source its own chunk budget.
        sources = [{"id": "a", "retrieval": RetrievalConfig(graph={"blend_vector": False})}]
        d = Dispatcher(source={"question": "q", "active_docs": ["a"]}, sources=sources)
        assert d._groups[0]["retrievals"] == {}


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

    @patch("docsgpt.retriever.classic_rag.VectorCreator")
    @patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_single_group_matches_classic_rag(self, _tok, mock_vc, _patch_llm_creator):
        from docsgpt.retriever.classic_rag import ClassicRAG

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

    @patch("docsgpt.retriever.classic_rag.VectorCreator")
    @patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_no_sources_matches_classic_rag(self, _tok, mock_vc, _patch_llm_creator):
        from docsgpt.retriever.classic_rag import ClassicRAG

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
    @patch("docsgpt.retriever.classic_rag.VectorCreator")
    @patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10)
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

    @patch("docsgpt.retriever.classic_rag.VectorCreator")
    @patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10)
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

    @patch("docsgpt.retriever.classic_rag.VectorCreator")
    @patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10)
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

    @patch("docsgpt.retriever.classic_rag.VectorCreator")
    @patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10)
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
            "docsgpt.retriever.stages.prescreen.LLMCreator.create_llm",
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

    @patch("docsgpt.retriever.stages.prescreen.build_prescreen_stages")
    @patch("docsgpt.retriever.classic_rag.VectorCreator")
    @patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_prescreen_none_no_extra_llm_calls(
        self, _tok, mock_vc, mock_build, _patch_llm_creator
    ):
        docsearch = Mock()
        docsearch.search.return_value = [_make_doc("one"), _make_doc("two")]
        mock_vc.create_vectorstore.return_value = docsearch
        # The stage factory imports the symbol; patch where it's looked up.
        import docsgpt.retriever.stages as stages

        with patch.object(stages, "build_prescreen_stages", mock_build):
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
            "docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED",
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
            "docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED",
            True,
        )
        result = build_dispatcher(
            lambda: object(),
            source={"question": "q", "active_docs": ["a"]},
            sources=[],
        )
        assert isinstance(result, Dispatcher)


# ── Relevance: each source's reranker, under the operator's switch ────────────


def _ranked_store(texts, keyword_texts=None):
    """A store whose search returns ``texts`` in order, cut to ``k`` (as real stores rank)."""
    hits = [_make_doc(t, source=t.split("-")[0]) for t in texts]
    by_text = {h.page_content: h for h in hits}
    keyword = [by_text[t] for t in keyword_texts or []]
    store = Mock()
    store.search.side_effect = lambda question, k, **kwargs: hits[:k]
    store.keyword_search.side_effect = lambda question, k: keyword[:k]
    return store


def _corpus(source, n=40):
    # Lengths vary so token budgets cut at different places.
    return [f"{source}-{i}" + " w" * (i % 7) for i in range(n)]


def _scores_from_text(state, question):
    """Deterministic relevance from the passage: later and longer chunks score higher."""
    text = state["passage"]
    return (sum(map(ord, text)) % 97) / 100


@pytest.fixture
def stores():
    """Patch the vector store factory to per-source ranked stores; tokens are the text's length."""
    built = {}
    with patch("docsgpt.retriever.classic_rag.VectorCreator") as vc, patch(
        "docsgpt.retriever.classic_rag.num_tokens_from_string", side_effect=len
    ), patch("docsgpt.retriever.dispatcher.num_tokens_from_string", side_effect=len):
        vc.create_vectorstore.side_effect = lambda _kind, source_id, _key: built[source_id]
        yield built


@pytest.fixture
def relevance(monkeypatch):
    """Set ``DECISION_RELEVANCE_ENABLED`` (and any other settings) for the test."""

    def set_enabled(enabled, **values):
        monkeypatch.setattr(settings, "DECISION_RELEVANCE_ENABLED", enabled)
        for name, value in values.items():
            monkeypatch.setattr(settings, name, value)

    return set_enabled


def _on(**reranker):
    """A source config with relevance on."""
    return RetrievalConfig(reranker={"type": "decision", **reranker})


def _search(sources, *, chunks=6, doc_token_limit=50000, query="query", **kwargs):
    ids = [s["id"] for s in sources]
    d = Dispatcher(
        source={"question": "q", "active_docs": ids},
        chat_history=[],
        chunks=chunks,
        doc_token_limit=doc_token_limit,
        decoded_token={"sub": "u"},
        sources=sources,
        **kwargs,
    )
    return d, d.search(query)


@pytest.mark.unit
class TestRelevanceParity:
    """Every fallback returns exactly what the retrieval returns with the stage off."""

    SCENARIOS = [
        # (retrievers per source, chunks, doc_token_limit)
        (["classic"], 6, 50000),
        (["classic", "classic", "classic"], 6, 50000),
        (["classic", "classic"], 6, 120),
        (["classic"] * 8, 6, 50000),
        (["hybrid"], 6, 50000),
        (["hybrid", "hybrid"], 4, 300),
        (["classic", "hybrid"], 6, 50000),
        (["classic", "hybrid"], 6, 160),
    ]

    @pytest.mark.parametrize("retrievers, chunks, limit", SCENARIOS)
    @pytest.mark.parametrize("failure", ["unavailable", "timeout", "decisions_off"])
    def test_fallback_equals_stage_off(self, stores, relevance, _patch_llm_creator, retrievers, chunks, limit,
                                       failure):
        sources = []
        for i, key in enumerate(retrievers):
            sid = f"src{i}"
            corpus = _corpus(sid)
            stores[sid] = _ranked_store(corpus, keyword_texts=list(reversed(corpus))[:25])
            sources.append({"id": sid, "retrieval": RetrievalConfig(retriever=key, reranker={"candidate_k": 30})})

        relevance(False)
        _, baseline = _search(sources, chunks=chunks, doc_token_limit=limit)
        assert baseline

        relevance(True)
        if failure == "decisions_off":
            _, out = _search(sources, chunks=chunks, doc_token_limit=limit)
        else:
            fake = FakeDecider(reasons={"*": failure})
            with installed(fake):
                d, out = _search(sources, chunks=chunks, doc_token_limit=limit)
            assert fake.calls, "the stage ran and failed"
            assert d.last_candidate_count > len(baseline)
            assert d.last_top_relevance is None
        assert out == baseline

    @pytest.mark.parametrize("sources_n", [1, 2])
    def test_graph_fallback_equals_stage_off(self, relevance, _patch_llm_creator, monkeypatch, sources_n):
        from docsgpt.retriever.graph_rag import GraphRAGRetriever

        nodes = [{"id": f"n{i}", "doc_freq": 1} for i in range(8)]
        edges = [{"src_node_id": f"n{i}", "dst_node_id": f"n{i + 1}", "weight": 1.0} for i in range(7)]
        store = Mock()
        store.count_nodes_many.side_effect = lambda ids: {sid: len(nodes) for sid in ids}
        store.search_nodes_by_embedding.return_value = [{"id": "n0", "distance": 0.0}]
        store.get_subgraph.return_value = {"nodes": nodes, "edges": edges}
        store.get_chunk_ids_for_nodes.return_value = {f"n{i}": [f"c{i}"] for i in range(8)}
        store.get_chunk_texts.return_value = {f"c{i}": {"text": f"chunk {i}", "metadata": {}} for i in range(8)}
        monkeypatch.setattr(GraphRAGRetriever, "_embed_query", lambda self, q: [0.1, 0.2])
        monkeypatch.setattr(
            GraphRAGRetriever, "_graph_options",
            lambda self, sid: GraphRetrievalConfig(passage_nodes=False, blend_vector=False),
        )
        monkeypatch.setattr("docsgpt.retriever.graph_rag.graphrag_available", lambda: True)
        monkeypatch.setattr("docsgpt.retriever.graph_rag.GraphStore", lambda: store)
        monkeypatch.setattr("docsgpt.retriever.graph_rag.num_tokens_from_string", lambda text: 10)
        relevance(True)

        def graph_sources(reranker):
            return [
                {"id": f"g{i}", "retrieval": RetrievalConfig(retriever="graphrag", reranker=reranker)}
                for i in range(sources_n)
            ]

        _, baseline = _search(graph_sources(None), chunks=2)
        assert baseline
        fake = FakeDecider(reasons={"*": "circuit_open"})
        with installed(fake):
            d, out = _search(graph_sources({"type": "decision"}), chunks=2)
        assert fake.calls and d.last_candidate_count > len(baseline)
        assert out == baseline


@pytest.mark.unit
class TestRelevanceRerank:
    def test_pool_is_fetched_and_tags_are_stripped(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True)
        fake = FakeDecider({"relevant": _scores_from_text})
        with installed(fake):
            d, out = _search([{"id": "a", "retrieval": _on(candidate_k=30)}])
        assert stores["a"].search.call_args.kwargs["k"] == 30
        assert len(fake.calls[0].requests) == 30
        assert len(out) == 6
        assert all("_base" not in doc for doc in out)
        relevance_values = [doc["relevance"] for doc in out]
        assert relevance_values == sorted(relevance_values, reverse=True)
        assert d.last_top_relevance == relevance_values[0]

    def test_an_unset_pool_is_twenty_within_the_passage_cap(self, relevance, _patch_llm_creator):
        relevance(True)
        sources = [{"id": "a", "retrieval": _on()}]
        with installed(FakeDecider()):
            d = Dispatcher(source={"question": "q", "active_docs": ["a"]}, chunks=4, sources=sources)
            retriever = d._build_group_retriever(d._groups[0], 1000)
        assert retriever.base_chunks == 4 and retriever.candidate_k == 20
        assert retriever.candidate_tokens == settings.DECISION_RELEVANCE_CANDIDATE_TOKENS
        assert retriever.chunks == 4
        relevance(True, DECISION_RELEVANCE_MAX_PASSAGES=12)
        sources = [{"id": "a", "retrieval": _on(candidate_k=80)}]
        with installed(FakeDecider()):
            d = Dispatcher(source={"question": "q", "active_docs": ["a"]}, sources=sources)
        assert d._groups[0]["relevance"]["candidate_k"] == 12

    def test_a_request_without_source_configs_is_never_judged(self, relevance, _patch_llm_creator):
        relevance(True)
        with installed(FakeDecider()):
            d = Dispatcher(source={"question": "q", "active_docs": ["a"]}, chunks=4)
            retriever = d._build_group_retriever(d._groups[0], 1000)
        assert d._groups[0]["relevance"]["mode"] == "off" and retriever.candidate_k is None

    def test_the_document_budget_applies_after_the_rerank(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True)
        with installed(FakeDecider({"relevant": _scores_from_text})):
            _, out = _search([{"id": "a", "retrieval": _on()}], doc_token_limit=120)
        # 90% of 120 tokens, counted with the filename header as the retriever counts them.
        assert sum(len(f"{d['filename']}\n{d['text']}") for d in out) < 108
        assert out and all("relevance" in d for d in out)

    def test_a_threshold_filters_and_keeps_min_keep(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True)
        with installed(FakeDecider({"relevant": 0.1})):
            _, out = _search([{"id": "a", "retrieval": _on(min_relevance=0.3)}])
        assert len(out) == settings.DECISION_RELEVANCE_MIN_KEEP
        with installed(FakeDecider({"relevant": 0.1})):
            _, out = _search([{"id": "a", "retrieval": _on(min_relevance=0)}])
        assert len(out) == 6, "0 reorders only"

    def test_a_reranker_alone_is_not_a_chunk_override(self, relevance, _patch_llm_creator):
        relevance(True)
        sources = [
            {"id": "a", "retrieval": _on(min_relevance=0.2)},
            {"id": "b", "retrieval": _on()},
        ]
        with installed(FakeDecider()):
            d = Dispatcher(source={"question": "q", "active_docs": ["a", "b"]}, sources=sources)
        (group,) = d._groups
        assert group["retrievals"] == {} and group["relevance"]["mode"] == "on"
        assert group["relevance"]["thresholds"] == {"a": 0.2}

    def test_sources_without_relevance_get_their_own_group(self, relevance, _patch_llm_creator):
        relevance(True)
        sources = [
            {"id": "a", "retrieval": _on()},
            {"id": "rows", "retrieval": RetrievalConfig()},
            {"id": "c", "retrieval": _on()},
        ]
        with installed(FakeDecider()):
            d = Dispatcher(source={"question": "q", "active_docs": ["a", "rows", "c", "stray"]}, sources=sources)
        assert [(g["retriever"], g["doc_ids"], g["relevance"]["mode"]) for g in d._groups] == [
            ("classic", ["a", "c"], "on"), ("classic", ["rows", "stray"], "off"),
        ]

    @pytest.mark.parametrize("retriever", ["classic", "hybrid", "graphrag"])
    def test_any_retriever_runs_its_sources_reranker(self, relevance, _patch_llm_creator, retriever):
        relevance(True)
        sources = [{"id": "g", "retrieval": RetrievalConfig(retriever=retriever, reranker={})}]
        with installed(FakeDecider()):
            d = Dispatcher(source={"question": "q", "active_docs": ["g"]}, sources=sources)
        assert d._groups[0]["relevance"]["mode"] == "on"

    def test_a_multi_group_merge_runs_best_first(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        stores["b"] = _ranked_store(_corpus("b"))
        relevance(True)
        sources = [
            {"id": "a", "retrieval": _on()},
            {"id": "b", "retrieval": RetrievalConfig(retriever="hybrid", reranker={})},
        ]
        with installed(FakeDecider({"relevant": _scores_from_text})):
            _, out = _search(sources, doc_token_limit=100)
        values = [doc["relevance"] for doc in out]
        assert values == sorted(values, reverse=True)
        assert {doc["source"] for doc in out} == {"a", "b"}

    def test_a_partly_scored_merge_keeps_group_order(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        stores["rows"] = _ranked_store(_corpus("rows"))
        relevance(True)
        sources = [
            {"id": "a", "retrieval": _on()},
            {"id": "rows", "retrieval": RetrievalConfig()},
        ]
        fake = FakeDecider({"relevant": _scores_from_text})
        with installed(fake):
            _, out = _search(sources)
        firsts = [doc["source"] for doc in out]
        assert firsts == sorted(firsts)  # every "a" doc, then every "rows" doc
        assert all("relevance" in d for d in out if d["source"] == "a")
        assert not any("relevance" in d for d in out if d["source"] == "rows")
        # Only the source that asked for it is sent to the model.
        assert {r.state["passage"].split("-")[0] for c in fake.calls for r in c.requests} == {"a"}

    def test_the_relevance_feature_label_can_be_set(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True)
        fake = FakeDecider({"relevant": 0.5})
        with installed(fake):
            _search([{"id": "a", "retrieval": _on()}], relevance_feature="retrieval_test")
        assert fake.calls[0].feature == "retrieval_test"


@pytest.mark.unit
class TestSearchQueryContext:
    def _recording(self, seen):
        def stage(docs, context):
            seen.append({k: context[k] for k in ("query", "search_query")})
            return docs

        return stage

    @pytest.mark.parametrize("multi", [False, True])
    def test_the_context_carries_the_rephrase(self, stores, _patch_llm_creator, multi):
        _patch_llm_creator.gen = Mock(return_value="how do I install it on Windows")
        stores["a"] = _ranked_store(_corpus("a"))
        stores["b"] = _ranked_store(_corpus("b"))
        sources = [{"id": "a", "retrieval": RetrievalConfig()}]
        if multi:
            sources.append({"id": "b", "retrieval": RetrievalConfig(retriever="hybrid")})
        seen = []
        d = Dispatcher(
            source={"question": "q", "active_docs": [s["id"] for s in sources]},
            chat_history=[{"prompt": "install docsgpt", "response": "..."}],
            sources=sources,
            stages=[self._recording(seen)],
        )
        d.search("and on Windows?")
        assert seen and all(
            c == {"query": "and on Windows?", "search_query": "how do I install it on Windows"} for c in seen
        )

    def test_without_history_the_search_query_is_the_raw_message(self, stores, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        seen = []
        Dispatcher(
            source={"question": "q", "active_docs": ["a"]}, stages=[self._recording(seen)]
        ).search("standalone question")
        assert seen == [{"query": "standalone question", "search_query": "standalone question"}]

    def test_a_retriever_without_the_property_gets_the_raw_query(self, _patch_llm_creator, monkeypatch):
        custom = Mock(spec=["search"])
        custom.search.return_value = [{"text": "t"}]
        monkeypatch.setattr(
            "docsgpt.retriever.dispatcher.RetrieverCreator.create_retriever", lambda key, **kwargs: custom
        )
        seen = []
        Dispatcher(
            source={"question": "q", "active_docs": ["a"]}, stages=[self._recording(seen)]
        ).search("raw")
        assert seen == [{"query": "raw", "search_query": "raw"}]

    def test_retrievers_expose_the_query_they_searched_with(self, _patch_llm_creator):
        from docsgpt.retriever.graph_rag import GraphRAGRetriever
        from docsgpt.retriever.hybrid_rag import HybridRetriever

        _patch_llm_creator.gen = Mock(return_value="rephrased")
        for cls in (ClassicRAG, HybridRetriever, GraphRAGRetriever):
            history = cls(source={"question": "raw", "active_docs": ["a"]}, chat_history=[{"prompt": "p"}])
            assert history.search_query == "rephrased"
            fresh = cls(source={"question": "raw", "active_docs": ["a"]}, chat_history=[])
            assert fresh.search_query == "raw"
            deferred = cls(
                source={"question": "raw", "active_docs": ["a"]}, chat_history=[{"prompt": "p"}], defer_rephrase=True
            )
            assert deferred.search_query == "raw", "no source asked for the rephrase yet"


@pytest.mark.unit
class TestRelevanceGating:
    def test_the_kill_switch_makes_no_calls(self, stores, relevance, monkeypatch, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True)
        monkeypatch.setattr("docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED", False)
        common = dict(source={"question": "q", "active_docs": ["a"]}, chat_history=[], decoded_token={"sub": "u"})
        fake = FakeDecider({"relevant": 0.9})
        with installed(fake):
            retriever = build_dispatcher(
                lambda: ClassicRAG(**common), sources=[{"id": "a", "retrieval": {"reranker": {}}}], **common
            )
            out = retriever.search("query")
        assert fake.calls == [] and len(out) == 6 and "relevance" not in out[0]

    def test_the_control_arm_asks_nothing_and_is_recorded(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True, DECISION_RELEVANCE_ROLLOUT_PERCENT=50)
        sources = [{"id": "a", "retrieval": _on()}]
        relevance(False)
        _, baseline = _search(sources)
        relevance(True)
        key = next(f"c{i}" for i in range(100) if not rollout_on(f"c{i}", 50))
        rec = record.DecisionRecord()
        fake = FakeDecider({"relevant": 0.9})
        with installed(fake), record.activate(rec):
            d, out = _search(sources, conversation_id=key)
        assert fake.calls == [] and out == baseline and d._groups[0]["relevance"]["arm"] == "control"
        (entry,) = rec._doc["entries"]
        assert (entry["feature"], entry["status"], entry["outcome"]) == ("rag_rerank", "skipped", {"arm": "control"})

    def test_the_rollout_arm_is_scored_and_recorded(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True, DECISION_RELEVANCE_ROLLOUT_PERCENT=50)
        key = next(f"c{i}" for i in range(100) if rollout_on(f"c{i}", 50))
        rec = record.DecisionRecord()
        with installed(FakeDecider({"relevant": 0.9})), record.activate(rec):
            _search([{"id": "a", "retrieval": _on()}], conversation_id=key)
        (entry,) = rec._doc["entries"]
        assert entry["outcome"]["arm"] == "on" and entry["applied"] is True

    def test_sources_without_relevance_have_no_arm(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True, DECISION_RELEVANCE_ROLLOUT_PERCENT=0)
        rec = record.DecisionRecord()
        with installed(FakeDecider()), record.activate(rec):
            _search([{"id": "a", "retrieval": RetrievalConfig()}], conversation_id="c1")
        assert rec._doc["entries"] == []


@pytest.mark.unit
class TestOperatorSwitch:
    """A source cannot make the process load the decision model: ``DECISION_RELEVANCE_ENABLED`` is the operator's."""

    @pytest.fixture
    def local_client(self, monkeypatch):
        """The real client in local mode, as a default install runs it; nothing may create its backend."""
        from docsgpt import decisions

        def refuse(**kwargs):
            raise AssertionError("a test tried to download the decision model")

        monkeypatch.setattr("huggingface_hub.snapshot_download", refuse)
        monkeypatch.setattr(settings, "DECISION_MODE", "local")
        monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: False)
        client = decisions.get_decider()
        yield client
        assert client._backend is None, "a source made the process build the decision model"

    def test_a_source_reranker_does_nothing_while_the_switch_is_off(self, stores, relevance, local_client,
                                                                     _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        stores["g"] = _ranked_store(_corpus("g"))
        relevance(False)

        def sources(reranker):
            return [
                {"id": "a", "retrieval": RetrievalConfig(reranker=reranker)},
                {"id": "g", "retrieval": RetrievalConfig(retriever="hybrid", reranker=reranker)},
            ]

        rec = record.DecisionRecord()
        with record.activate(rec):
            d, opted_in = _search(sources({"type": "decision", "min_relevance": 0.5, "candidate_k": 40}))
        _, without = _search(sources(None))
        assert opted_in == without
        assert all(g["relevance"]["mode"] == "off" for g in d._groups)
        assert d.last_candidate_count == len(without) and d.last_top_relevance is None
        # Nothing is recorded, as a failure or otherwise.
        assert rec._doc["entries"] == []

    def test_mode_none_never_judges(self, stores, relevance, _patch_llm_creator):
        stores["a"] = _ranked_store(_corpus("a"))
        relevance(True)
        rec = record.DecisionRecord()
        with record.activate(rec):
            d, out = _search([{"id": "a", "retrieval": _on()}])  # the tests run with DECISION_MODE=none
        assert d._groups[0]["relevance"]["mode"] == "off" and "relevance" not in out[0]
        assert rec._doc["entries"] == []


@pytest.mark.unit
class TestPrescreenScope:
    """An LLM prescreen judges only the sources that set it."""

    @staticmethod
    def _llm(max_keep, **extra):
        return RetrievalConfig(chunks=2, prescreen={"candidate_k": 4, "max_keep": max_keep, **extra})

    @staticmethod
    def _keep_all():
        screener = Mock(model_id="m")
        screener.gen = Mock(return_value='{"keep": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]}')
        return screener

    def test_an_llm_prescreen_leaves_a_plain_source_alone(self, stores, _patch_llm_creator):
        stores["screened"] = _ranked_store(_corpus("screened"))
        stores["plain"] = _ranked_store(_corpus("plain"))
        sources = [
            {"id": "screened", "retrieval": self._llm(1)},
            {"id": "plain", "retrieval": RetrievalConfig()},
        ]
        screener = self._keep_all()
        with patch("docsgpt.retriever.stages.prescreen.LLMCreator.create_llm", return_value=screener):
            d, out = _search(sources)
        assert [g["doc_ids"] for g in d._groups] == [["screened"], ["plain"]]
        assert sum(doc["source"] == "screened" for doc in out) == 1
        # The plain source's chunks survive the other source's max_keep of 1.
        assert sum(doc["source"] == "plain" for doc in out) == 6
        (call,) = screener.gen.call_args_list
        assert "plain-" not in call.kwargs["messages"][-1]["content"]

    def test_prescreens_with_different_settings_are_scoped_apart(self, stores, _patch_llm_creator):
        for sid in ("one", "two", "same"):
            stores[sid] = _ranked_store(_corpus(sid))
        sources = [
            {"id": "one", "retrieval": self._llm(1)},
            {"id": "two", "retrieval": self._llm(3)},
            # Same screening as "one" with another candidate_k: it shares that group and its one stage.
            {"id": "same", "retrieval": RetrievalConfig(chunks=2, prescreen={"candidate_k": 6, "max_keep": 1})},
        ]
        screener = self._keep_all()
        with patch("docsgpt.retriever.stages.prescreen.LLMCreator.create_llm", return_value=screener):
            d, out = _search(sources)
        assert [g["doc_ids"] for g in d._groups] == [["one", "same"], ["two"]]
        assert [len(d._group_stages(g)) for g in d._groups] == [1, 1]
        assert sum(doc["source"] in ("one", "same") for doc in out) == 1
        assert sum(doc["source"] == "two" for doc in out) == 3

    def test_a_stored_llm_backend_groups_with_the_matching_prescreen(self, _patch_llm_creator):
        sources = [
            {"id": "a", "retrieval": self._llm(2, backend="llm")},
            {"id": "b", "retrieval": self._llm(2)},
            {"id": "c", "retrieval": self._llm(2, batch_size=5)},
            {"id": "d", "retrieval": self._llm(2, model="other")},
        ]
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b", "c", "d"]}, sources=sources)
        assert [g["doc_ids"] for g in d._groups] == [["a", "b"], ["c"], ["d"]]

    def test_a_prescreened_group_and_a_relevance_group_stay_apart(self, stores, relevance, _patch_llm_creator):
        for sid in ("screened", "scored"):
            stores[sid] = _ranked_store(_corpus(sid))
        relevance(True)
        sources = [
            {"id": "screened", "retrieval": self._llm(2)},
            {"id": "scored", "retrieval": _on()},
        ]
        screener = self._keep_all()
        fake = FakeDecider({"relevant": _scores_from_text})
        with installed(fake), patch(
            "docsgpt.retriever.stages.prescreen.LLMCreator.create_llm", return_value=screener
        ):
            d, out = _search(sources)
        assert [(g["doc_ids"], g["relevance"]["mode"]) for g in d._groups] == [
            (["screened"], "off"), (["scored"], "on"),
        ]
        assert [type(stage).__name__ for g in d._groups for stage in d._group_stages(g)] == [
            "PreScreenStage", "RelevanceStage",
        ]
        # The model scores only the relevance source; the prescreen's max_keep cuts only its own.
        assert {r.state["passage"].split("-")[0] for c in fake.calls for r in c.requests} == {"scored"}
        assert sum(doc["source"] == "screened" for doc in out) == 2

    def test_grouping_is_unchanged_without_a_prescreen_or_relevance(self, _patch_llm_creator):
        sources = [
            {"id": "a", "retrieval": RetrievalConfig()},
            {"id": "b", "retrieval": RetrievalConfig(chunks=9, score_threshold=0.3, rephrase_query=False)},
            {"id": "c", "retrieval": RetrievalConfig(reranker={"type": "decision", "candidate_k": 30})},
            {"id": "h", "retrieval": RetrievalConfig(retriever="hybrid")},
            {"id": "g", "retrieval": RetrievalConfig(retriever="graphrag")},
        ]
        # The switch is off, so a stored reranker groups as no relevance at all.
        d = Dispatcher(source={"question": "q", "active_docs": ["a", "b", "c", "h", "g", "stray"]}, sources=sources)
        assert [(g["retriever"], g["doc_ids"]) for g in d._groups] == [
            ("classic", ["a", "b", "c", "stray"]), ("hybrid", ["h"]), ("graphrag", ["g"]),
        ]
        assert list(d._groups[0]["retrievals"]) == ["b"]
