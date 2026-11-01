"""A retrieval records which sources it searched and which of them failed.

A source whose search raised used to look exactly like one that matched
nothing: both contributed no documents, so the answer said "nothing relevant
was found" through a days-long embedding outage. ``last_outcome`` keeps the
two apart without changing what ``search()`` returns.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.retriever.base import SearchOutcome
from docsgpt.retriever.classic_rag import ClassicRAG
from docsgpt.retriever.dispatcher import Dispatcher
from docsgpt.retriever.graph_rag import GraphRAGRetriever
from docsgpt.retriever.hybrid_rag import HybridRetriever


@pytest.fixture
def _patch_llm_creator(mock_llm, monkeypatch):
    monkeypatch.setattr(
        "docsgpt.retriever.classic_rag.LLMCreator.create_llm",
        Mock(return_value=mock_llm),
    )
    return mock_llm


def _doc(text):
    doc = Mock()
    doc.page_content = text
    doc.metadata = {"title": "t", "source": "s"}
    return doc


def _store(embedder, hits=()):
    store = Mock()
    store._embedding = embedder
    store.score_kind = None
    store.search.return_value = list(hits)
    store.keyword_search.return_value = []
    return store


def _embedder():
    embedder = Mock()
    embedder.embed_query = Mock(return_value=[0.1, 0.2])
    return embedder


def _rag(cls=ClassicRAG, sources=("a", "b", "c")):
    return cls(
        source={"question": "q", "active_docs": list(sources)},
        chunks=6,
        model_id="test-model",
        llm_name="openai",
        api_key="fake",
        decoded_token={"sub": "user1"},
    )


def _search(rag, create):
    with patch(
        "docsgpt.retriever.classic_rag.VectorCreator.create_vectorstore", side_effect=create
    ), patch("docsgpt.retriever.classic_rag.num_tokens_from_string", return_value=10):
        return rag.search()


@pytest.mark.unit
class TestSearchOutcome:
    def test_of_keeps_source_order_and_drops_unknown_failures(self):
        outcome = SearchOutcome.of(["a", "b", "a", ""], failed=["b", "z"])

        assert outcome.searched == ("a", "b")
        assert outcome.failed == ("b",)
        assert outcome.answered == ("a",)

    def test_combine_merges_groups(self):
        merged = SearchOutcome.combine([SearchOutcome.of(["a"], ["a"]), SearchOutcome.of(["b"])])

        assert merged == SearchOutcome(("a", "b"), ("a",))


@pytest.mark.unit
class TestClassicRecordsFailures:
    def test_every_source_ok_records_none_failed(self, _patch_llm_creator):
        embedder = _embedder()
        stores = {s: _store(embedder, [_doc(f"hit {s}")]) for s in "abc"}
        rag = _rag()

        docs = _search(rag, lambda _t, sid, _k: stores[sid])

        assert [d["text"] for d in docs] == ["hit a", "hit b", "hit c"]
        assert rag.last_outcome == SearchOutcome(("a", "b", "c"), ())

    def test_a_search_that_raises_is_failed_not_empty(self, _patch_llm_creator):
        embedder = _embedder()
        stores = {"a": _store(embedder, [_doc("hit a")]), "b": _store(embedder), "c": _store(embedder)}
        stores["b"].search.side_effect = RuntimeError("store b is down")
        rag = _rag()

        docs = _search(rag, lambda _t, sid, _k: stores[sid])

        assert [d["text"] for d in docs] == ["hit a"]
        # ``c`` matched nothing; only ``b`` failed.
        assert rag.last_outcome.failed == ("b",)
        assert rag.last_outcome.searched == ("a", "b", "c")

    def test_a_store_that_cannot_be_built_is_failed(self, _patch_llm_creator):
        embedder = _embedder()
        stores = {s: _store(embedder) for s in "bc"}

        def create(_t, sid, _k):
            if sid == "a":
                raise RuntimeError("connection failed")
            return stores[sid]

        rag = _rag()
        _search(rag, create)

        assert rag.last_outcome.failed == ("a",)

    def test_embedder_outage_fails_every_source(self, _patch_llm_creator, caplog):
        """No worker answering the delegated embed: nothing was searched at all."""
        embedder = Mock()
        embedder.embed_query.side_effect = TimeoutError("no embeddings worker answered")
        stores = {s: _store(embedder) for s in "abc"}
        rag = _rag()

        with caplog.at_level("WARNING", logger="docsgpt.retriever.fanout"):
            docs = _search(rag, lambda _t, sid, _k: stores[sid])

        assert docs == []
        assert rag.last_outcome == SearchOutcome(("a", "b", "c"), ("a", "b", "c"))
        for store in stores.values():
            store.search.assert_not_called()
        # One warning per source that was not searched.
        unsearched = [r for r in caplog.records if r.levelname == "WARNING" and "was not searched" in r.message]
        assert len(unsearched) == 3

    def test_a_plan_that_cannot_be_resolved_is_failed(self, _patch_llm_creator):
        embedder = _embedder()
        stores = {s: _store(embedder) for s in "abc"}
        rag = _rag()
        real = rag._resolve_source

        def resolve(source_id, chunks):
            if source_id == "c":
                raise ValueError("bad override")
            return real(source_id, chunks)

        rag._resolve_source = resolve
        _search(rag, lambda _t, sid, _k: stores[sid])

        assert rag.last_outcome.failed == ("c",)

    def test_nothing_attached_searches_nothing(self, _patch_llm_creator):
        rag = _rag(sources=())

        assert rag.search() == []
        assert rag.last_outcome == SearchOutcome()

    def test_hybrid_records_failures_too(self, _patch_llm_creator):
        embedder = _embedder()
        stores = {s: _store(embedder) for s in "ab"}
        stores["a"].keyword_search.side_effect = RuntimeError("fts down")
        rag = _rag(HybridRetriever, sources=("a", "b"))

        _search(rag, lambda _t, sid, _k: stores[sid])

        assert rag.last_outcome == SearchOutcome(("a", "b"), ("a",))


def _graph(sources):
    return GraphRAGRetriever(
        source={"question": "q", "active_docs": list(sources)},
        chunks=4,
        model_id="test-model",
        llm_name="openai",
        api_key="fake",
        decoded_token={"sub": "user1"},
    )


@pytest.mark.unit
class TestGraphRecordsFailures:
    @patch("docsgpt.retriever.graph_rag.graphrag_available", return_value=False)
    def test_classic_fallback_failures_are_the_graph_retrievals(self, _avail, _patch_llm_creator):
        rag = _graph(["a", "b"])

        def classic():
            rag._classic.last_outcome = SearchOutcome.of(rag._classic.vectorstores, ["b"])
            return [{"text": "x", "source": "a"}]

        rag._classic._get_data = Mock(side_effect=classic)

        rag.search()

        assert rag.last_outcome == SearchOutcome(("a", "b"), ("b",))

    @patch("docsgpt.retriever.graph_rag.GraphStore")
    @patch("docsgpt.retriever.graph_rag.graphrag_available", return_value=True)
    def test_a_graph_failure_rescued_by_the_fallback_is_not_failed(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        store = MagicMock()
        store.count_nodes_many.return_value = {"a": 3, "b": 0}
        mock_store_cls.return_value = store
        rag = _graph(["a", "b"])
        rag._embed_query = Mock(side_effect=RuntimeError("embedder down"))
        batches = []

        def classic():
            batches.append(list(rag._classic.vectorstores))
            # The graphless batch ("b") searched fine; the fallback batch
            # ("a", after its graph embed failed) failed too.
            failed = ["a"] if rag._classic.vectorstores == ["a"] else []
            rag._classic.last_outcome = SearchOutcome.of(rag._classic.vectorstores, failed)
            return []

        rag._classic._get_data = Mock(side_effect=classic)

        rag.search()

        assert sorted(batches) == [["a"], ["b"]]
        assert rag.last_outcome == SearchOutcome(("a", "b"), ("a",))


@pytest.mark.unit
class TestDispatcherRecordsFailures:
    def _dispatcher(self, groups):
        """A Dispatcher with one group per entry of ``groups`` (each its own retriever key)."""
        keys = ["classic", "hybrid"]
        sources = [
            {"id": doc_id, "retrieval": {"retriever": keys[idx]}}
            for idx, ids in enumerate(groups)
            for doc_id in ids
        ]
        active = [doc_id for ids in groups for doc_id in ids]
        dispatcher = Dispatcher(source={"question": "q", "active_docs": active}, sources=sources)
        assert [group["doc_ids"] for group in dispatcher._groups] == groups
        return dispatcher

    def test_groups_merge_into_one_outcome(self):
        dispatcher = self._dispatcher([["a", "b"], ["c"]])
        first = MagicMock(last_outcome=SearchOutcome.of(["a", "b"], ["b"]))
        first.search.return_value = []
        second = MagicMock()
        second.search.side_effect = RuntimeError("group down")
        retrievers = iter([first, second])
        dispatcher._build_group_retriever = lambda group, budget: next(retrievers)

        assert dispatcher.search("q") == []
        assert dispatcher.last_outcome == SearchOutcome(("a", "b", "c"), ("b", "c"))

    def test_a_single_group_that_raises_records_every_source_failed(self):
        dispatcher = self._dispatcher([["a", "b"]])
        retriever = MagicMock()
        retriever.search.side_effect = RuntimeError("boom")
        dispatcher._build_group_retriever = lambda group, budget: retriever

        with pytest.raises(RuntimeError):
            dispatcher.search("q")
        assert dispatcher.last_outcome == SearchOutcome(("a", "b"), ("a", "b"))

    def test_a_retriever_without_an_outcome_counts_as_searched(self):
        dispatcher = self._dispatcher([["a"]])
        retriever = MagicMock(spec=["search"])
        retriever.search.return_value = []
        dispatcher._build_group_retriever = lambda group, budget: retriever

        dispatcher.search("q")

        assert dispatcher.last_outcome == SearchOutcome(("a",), ())
