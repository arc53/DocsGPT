"""Multi-source retrieval: one query embedding, concurrent per-source search.

Six attached sources used to cost six query embeddings and six serial round
trips. These tests pin the two halves of the fix: the query is embedded once
and the vector is handed to every store, and the per-source searches run
concurrently while the merged output keeps the original source order.
"""

import threading
import time
from types import SimpleNamespace
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


def _make_embedder(vector=(0.1, 0.2, 0.3)):
    embedder = Mock()
    embedder.embed_query = Mock(return_value=list(vector))
    return embedder


def _make_store(embedder, hits=None, keyword_hits=None):
    store = Mock()
    store._embedding = embedder
    store.score_kind = None
    store.search.return_value = list(hits or [])
    store.search_with_scores.return_value = [(doc, 0.5) for doc in (hits or [])]
    store.keyword_search.return_value = list(keyword_hits or [])
    return store


def _make_rag(cls=ClassicRAG, source=None, **overrides):
    kwargs = dict(
        source=source or {"question": "q", "active_docs": ["a", "b", "c"]},
        chat_history=None,
        prompt="",
        chunks=6,
        doc_token_limit=50000,
        model_id="test-model",
        llm_name="openai",
        api_key="fake",
        decoded_token={"sub": "user1"},
    )
    kwargs.update(overrides)
    return cls(**kwargs)


def _run(rag, stores):
    """Run ``_get_data`` with ``VectorCreator`` handing out ``stores`` by id."""
    with patch(
        "application.retriever.classic_rag.VectorCreator.create_vectorstore",
        side_effect=lambda _type, source_id, _key: stores[source_id],
    ), patch(
        "application.retriever.classic_rag.num_tokens_from_string", return_value=10
    ):
        return rag._get_data()


@pytest.mark.unit
class TestQueryEmbeddedOnce:
    def test_three_sources_embed_the_query_once(self, _patch_llm_creator):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b", "c")
        }

        docs = _run(_make_rag(), stores)

        assert len(docs) == 3
        assert embedder.embed_query.call_count == 1
        embedder.embed_query.assert_called_once_with("q")

    def test_every_store_receives_the_same_vector(self, _patch_llm_creator):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b", "c")
        }

        _run(_make_rag(), stores)

        vectors = [
            store.search.call_args.kwargs["query_vector"] for store in stores.values()
        ]
        assert vectors == [[0.1, 0.2, 0.3]] * 3

    def test_include_scores_path_passes_the_vector_too(self, _patch_llm_creator):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b")
        }

        _run(_make_rag(include_scores=True, source={
            "question": "q", "active_docs": ["a", "b"]
        }), stores)

        assert embedder.embed_query.call_count == 1
        for store in stores.values():
            kwargs = store.search_with_scores.call_args.kwargs
            assert kwargs["query_vector"] == [0.1, 0.2, 0.3]

    def test_hybrid_reuses_the_shared_vector(self, _patch_llm_creator):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b")
        }

        _run(
            _make_rag(
                cls=HybridRetriever,
                source={"question": "q", "active_docs": ["a", "b"]},
            ),
            stores,
        )

        assert embedder.embed_query.call_count == 1
        for store in stores.values():
            assert store.search.call_args.kwargs["query_vector"] == [0.1, 0.2, 0.3]

    def test_distinct_questions_are_embedded_once_each(
        self, _patch_llm_creator, mock_llm
    ):
        """Per-source rephrase means two queries — one embedding each, no more."""
        from application.storage.db.source_config import RetrievalConfig

        mock_llm.gen = Mock(return_value="REPHRASED")
        embedder = Mock()
        embedder.embed_query = Mock(side_effect=lambda q: [len(q)])
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b", "c")
        }

        rag = _make_rag(
            source={"question": "original", "active_docs": ["a", "b", "c"]},
            chat_history=[{"prompt": "hi", "response": "yo"}],
            defer_rephrase=True,
        )
        rag.per_source_retrieval = {
            "a": RetrievalConfig(rephrase_query=False),
            "b": RetrievalConfig(rephrase_query=True),
            "c": RetrievalConfig(rephrase_query=True),
        }
        _run(rag, stores)

        assert embedder.embed_query.call_count == 2
        assert stores["a"].search.call_args.kwargs["query_vector"] == [len("original")]
        assert stores["b"].search.call_args.kwargs["query_vector"] == [len("REPHRASED")]
        assert stores["c"].search.call_args.kwargs["query_vector"] == [len("REPHRASED")]

    def test_embedding_failure_falls_back_to_per_store_embedding(
        self, _patch_llm_creator
    ):
        """A broken embedder must not break retrieval — stores embed their own."""
        embedder = Mock()
        embedder.embed_query = Mock(side_effect=RuntimeError("model down"))
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b")
        }

        docs = _run(
            _make_rag(source={"question": "q", "active_docs": ["a", "b"]}), stores
        )

        assert len(docs) == 2
        for store in stores.values():
            assert "query_vector" not in store.search.call_args.kwargs

    def test_store_without_embedder_still_searches(self, _patch_llm_creator):
        """A store exposing no embeddings object keeps the old call shape."""
        store = _make_store(None, [_make_doc("hit")])
        store._embedding = None
        store._embeddings = None
        store.embeddings = None
        store._get_embeddings = Mock(side_effect=AttributeError("nope"))

        docs = _run(
            _make_rag(source={"question": "q", "active_docs": ["a"]}), {"a": store}
        )

        assert len(docs) == 1
        assert "query_vector" not in store.search.call_args.kwargs


@pytest.mark.unit
class TestConcurrentSourceSearch:
    def test_sources_are_searched_concurrently(self, _patch_llm_creator):
        """Three sources must be in flight at once, not one after another.

        The barrier only clears if three searches overlap; a serial loop
        would trip its timeout and lose every source.
        """
        barrier = threading.Barrier(3, timeout=10)
        embedder = _make_embedder()

        def _search_factory(src):
            def _search(*_args, **_kwargs):
                barrier.wait()
                return [_make_doc(f"hit {src}", source=src)]

            return _search

        stores = {}
        for src in ("a", "b", "c"):
            store = _make_store(embedder)
            store.search.side_effect = _search_factory(src)
            stores[src] = store

        docs = _run(_make_rag(), stores)

        assert [d["text"] for d in docs] == ["hit a", "hit b", "hit c"]

    def test_results_keep_source_order_regardless_of_completion_order(
        self, _patch_llm_creator
    ):
        """The slowest source is first — it still leads the merged output."""
        embedder = _make_embedder()
        delays = {"a": 0.06, "b": 0.0, "c": 0.0}

        def _search_factory(src):
            def _search(*_args, **_kwargs):
                time.sleep(delays[src])
                return [_make_doc(f"hit {src}", source=src)]

            return _search

        stores = {}
        for src in ("a", "b", "c"):
            store = _make_store(embedder)
            store.search.side_effect = _search_factory(src)
            stores[src] = store

        docs = _run(_make_rag(), stores)

        assert [d["text"] for d in docs] == ["hit a", "hit b", "hit c"]
        assert [d["source"] for d in docs] == ["a", "b", "c"]

    def test_output_matches_the_serial_path_exactly(self, _patch_llm_creator):
        """Parity: one worker (serial) and four workers agree, doc for doc."""

        def _stores():
            embedder = _make_embedder()
            return {
                src: _make_store(
                    embedder,
                    [
                        _make_doc(f"{src}-0", source=src),
                        _make_doc(f"{src}-1", source=src),
                    ],
                )
                for src in ("a", "b", "c")
            }

        with patch(
            "application.retriever.classic_rag._max_parallel_sources",
            side_effect=lambda n: 1,
        ):
            serial = _run(_make_rag(), _stores())
        with patch(
            "application.retriever.classic_rag._max_parallel_sources",
            side_effect=lambda n: 4,
        ):
            parallel = _run(_make_rag(), _stores())

        assert serial == parallel
        assert len(serial) == 6

    def test_one_failing_source_does_not_kill_the_others(self, _patch_llm_creator):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b", "c")
        }
        stores["b"].search.side_effect = RuntimeError("store b is down")

        docs = _run(_make_rag(), stores)

        assert [d["text"] for d in docs] == ["hit a", "hit c"]

    def test_failing_store_construction_does_not_kill_the_others(
        self, _patch_llm_creator
    ):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [_make_doc(f"hit {src}", source=src)])
            for src in ("a", "b", "c")
        }

        def _create(_type, source_id, _key):
            if source_id == "a":
                raise RuntimeError("connection failed")
            return stores[source_id]

        rag = _make_rag()
        with patch(
            "application.retriever.classic_rag.VectorCreator.create_vectorstore",
            side_effect=_create,
        ), patch(
            "application.retriever.classic_rag.num_tokens_from_string", return_value=10
        ):
            docs = rag._get_data()

        assert [d["text"] for d in docs] == ["hit b", "hit c"]

    def test_single_source_skips_the_pool(self, _patch_llm_creator):
        """One source must not pay for a thread pool."""
        embedder = _make_embedder()
        store = _make_store(embedder, [_make_doc("only hit")])
        main_thread = threading.current_thread().name
        seen = []
        store.search.side_effect = lambda *_a, **_k: (
            seen.append(threading.current_thread().name),
            [_make_doc("only hit")],
        )[1]

        docs = _run(
            _make_rag(source={"question": "q", "active_docs": ["a"]}), {"a": store}
        )

        assert len(docs) == 1
        assert seen == [main_thread]


@pytest.mark.unit
class TestWorkerCap:
    """``RETRIEVAL_MAX_PARALLEL_SOURCES`` bounds the fan-out."""

    def _cap(self, monkeypatch, n_sources, configured=None):
        import application.retriever.classic_rag as classic_rag

        stub = SimpleNamespace()
        if configured is not None:
            stub.RETRIEVAL_MAX_PARALLEL_SOURCES = configured
        monkeypatch.setattr(classic_rag, "settings", stub)
        return classic_rag._max_parallel_sources(n_sources)

    def test_default_is_four(self, monkeypatch):
        assert self._cap(monkeypatch, 10) == 4

    def test_never_more_workers_than_sources(self, monkeypatch):
        assert self._cap(monkeypatch, 2) == 2

    def test_setting_is_honoured(self, monkeypatch):
        assert self._cap(monkeypatch, 10, configured=8) == 8

    def test_floor_is_one(self, monkeypatch):
        assert self._cap(monkeypatch, 10, configured=0) == 1

    def test_garbage_setting_falls_back_to_default(self, monkeypatch):
        assert self._cap(monkeypatch, 10, configured="lots") == 4
