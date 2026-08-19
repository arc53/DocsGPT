"""Tests for the GraphRAG local PPR retriever.

The GraphStore and embeddings are mocked (no DB, no model load); ``networkx``
runs for real on small crafted graphs. The composed ClassicRAG is mocked when
exercising the fallback path.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from application.retriever.graph_rag import GraphRAGRetriever
from application.retriever.retriever_creator import RetrieverCreator


@pytest.fixture
def _patch_llm_creator(mock_llm, monkeypatch):
    monkeypatch.setattr(
        "application.retriever.classic_rag.LLMCreator.create_llm",
        Mock(return_value=mock_llm),
    )
    return mock_llm


def _make_retriever(source=None, **overrides):
    defaults = dict(
        source=source or {"question": "q", "active_docs": ["src1"]},
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
    return GraphRAGRetriever(**defaults)


@pytest.fixture
def _patch_embed(monkeypatch):
    monkeypatch.setattr(
        GraphRAGRetriever, "_embed_query", lambda self, q: [0.1, 0.2, 0.3]
    )


# ── Fallback to ClassicRAG ────────────────────────────────────────────────────


@pytest.mark.unit
class TestGraphRAGFallback:
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_no_graph_delegates_to_classic(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        store = MagicMock()
        store.count_nodes_many.return_value = {"src1": 0}
        mock_store_cls.return_value = store

        rag = _make_retriever()
        classic_docs = [{"title": "c", "text": "classic", "source": "src1", "filename": "c"}]
        rag._classic._get_data = Mock(return_value=list(classic_docs))

        docs = rag._get_data()

        assert docs == classic_docs
        store.search_nodes_by_embedding.assert_not_called()
        store.get_subgraph.assert_not_called()
        store.close.assert_called_once()

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=False)
    def test_graphrag_unavailable_delegates_to_classic(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        rag = _make_retriever()
        classic_docs = [{"title": "c", "text": "classic", "source": "src1", "filename": "c"}]
        rag._classic._get_data = Mock(return_value=list(classic_docs))

        docs = rag._get_data()

        assert docs == classic_docs
        mock_store_cls.assert_not_called()


# ── Happy path: seed -> subgraph -> PPR -> rank ───────────────────────────────


def _as_chunk_data(chunk_texts, metadata_by_chunk=None):
    """Wrap plain ``{chunk_id: text}`` into the richer get_chunk_texts shape."""
    metadata_by_chunk = metadata_by_chunk or {}
    return {
        chunk_id: {"text": text, "metadata": metadata_by_chunk.get(chunk_id, {})}
        for chunk_id, text in chunk_texts.items()
    }


def _store_with_graph(
    nodes, edges, node_chunks, chunk_texts, seed_rows, metadata_by_chunk=None
):
    store = MagicMock()
    store.count_nodes.return_value = len(nodes)
    store.count_nodes_many.side_effect = lambda ids: {
        source_id: len(nodes) for source_id in ids
    }
    store.search_nodes_by_embedding.return_value = seed_rows
    store.get_subgraph.return_value = {"nodes": nodes, "edges": edges}
    store.get_chunk_ids_for_nodes.return_value = node_chunks
    store.get_chunk_texts.return_value = _as_chunk_data(chunk_texts, metadata_by_chunk)
    return store


@pytest.mark.unit
class TestGraphRAGHappyPath:
    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_ppr_ranks_near_seed_higher(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        # Chain: seed(n1) - n2 - n3. Personalization on n1 biases the walk toward
        # the seed neighborhood, so the far node n3 lands the least PPR mass and
        # must rank below the seed and its direct neighbor.
        nodes = [
            {"id": "n1", "doc_freq": 1},
            {"id": "n2", "doc_freq": 1},
            {"id": "n3", "doc_freq": 1},
        ]
        edges = [
            {"src_node_id": "n1", "dst_node_id": "n2", "weight": 1.0},
            {"src_node_id": "n2", "dst_node_id": "n3", "weight": 1.0},
        ]
        node_chunks = {"n1": ["c1"], "n2": ["c2"], "n3": ["c3"]}
        chunk_texts = {"c1": "near", "c2": "mid", "c3": "far"}
        seed_rows = [{"id": "n1", "distance": 0.0}]
        store = _store_with_graph(nodes, edges, node_chunks, chunk_texts, seed_rows)
        mock_store_cls.return_value = store

        rag = _make_retriever(chunks=3)
        docs = rag._get_data()

        texts = [d["text"] for d in docs]
        assert texts[-1] == "far"
        assert texts.index("near") < texts.index("far")
        assert docs[0].keys() == {"title", "text", "source", "filename"}

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_seed_distance_over_one_is_clamped(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        # One seed at cosine distance > 1 (negative similarity) => raw weight
        # 1 - 1.5 < 0. Paired with a positive seed the personalization sums to
        # ~0, which makes networkx pagerank raise ZeroDivisionError. Clamping
        # each weight to >= 0 keeps the personalization a valid distribution.
        nodes = [{"id": "n1", "doc_freq": 1}, {"id": "n2", "doc_freq": 1}]
        edges = [{"src_node_id": "n1", "dst_node_id": "n2", "weight": 1.0}]
        node_chunks = {"n1": ["c1"], "n2": ["c2"]}
        chunk_texts = {"c1": "a", "c2": "b"}
        seed_rows = [
            {"id": "n1", "distance": 0.5},
            {"id": "n2", "distance": 1.5},
        ]
        store = _store_with_graph(nodes, edges, node_chunks, chunk_texts, seed_rows)
        mock_store_cls.return_value = store

        rag = _make_retriever(chunks=2)
        # Call the PPR path directly: _get_data would swallow a raise and fall
        # back to ClassicRAG, hiding the regression.
        docs = rag._graph_docs_for_source(store, "src1", [0.1, 0.2, 0.3])

        assert len(docs) >= 1

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_topk_respected(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        nodes = [{"id": f"n{i}", "doc_freq": 1} for i in range(1, 5)]
        edges = [
            {"src_node_id": "n1", "dst_node_id": "n2", "weight": 1.0},
            {"src_node_id": "n1", "dst_node_id": "n3", "weight": 1.0},
            {"src_node_id": "n1", "dst_node_id": "n4", "weight": 1.0},
        ]
        node_chunks = {f"n{i}": [f"c{i}"] for i in range(1, 5)}
        chunk_texts = {f"c{i}": f"t{i}" for i in range(1, 5)}
        seed_rows = [{"id": "n1", "distance": 0.0}]
        store = _store_with_graph(nodes, edges, node_chunks, chunk_texts, seed_rows)
        mock_store_cls.return_value = store

        rag = _make_retriever(chunks=2)
        docs = rag._get_data()

        assert len(docs) == 2

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_token_budget_honored(
        self, _avail, mock_store_cls, _patch_llm_creator, _patch_embed
    ):
        nodes = [{"id": f"n{i}", "doc_freq": 1} for i in range(1, 4)]
        edges = [
            {"src_node_id": "n1", "dst_node_id": "n2", "weight": 1.0},
            {"src_node_id": "n2", "dst_node_id": "n3", "weight": 1.0},
        ]
        node_chunks = {f"n{i}": [f"c{i}"] for i in range(1, 4)}
        chunk_texts = {f"c{i}": f"t{i}" for i in range(1, 4)}
        seed_rows = [{"id": "n1", "distance": 0.0}]
        store = _store_with_graph(nodes, edges, node_chunks, chunk_texts, seed_rows)
        mock_store_cls.return_value = store

        # Tiny budget: 0.9 * 100 = 90; each chunk costs 50 tokens → only one fits.
        rag = _make_retriever(chunks=3, doc_token_limit=100)
        with patch(
            "application.retriever.graph_rag.num_tokens_from_string", return_value=50
        ):
            docs = rag._get_data()

        assert len(docs) == 1

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_labels_derived_from_metadata_not_source_id(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        nodes = [{"id": "n1", "doc_freq": 1}]
        edges = []
        node_chunks = {"n1": ["c1"]}
        chunk_texts = {"c1": "near"}
        metadata = {"c1": {"title": "My Title", "source": "/docs/report.pdf"}}
        seed_rows = [{"id": "n1", "distance": 0.0}]
        store = _store_with_graph(
            nodes, edges, node_chunks, chunk_texts, seed_rows, metadata
        )
        mock_store_cls.return_value = store

        rag = _make_retriever(chunks=1)
        docs = rag._get_data()

        assert len(docs) == 1
        doc = docs[0]
        assert doc["title"] == "My Title"
        assert doc["filename"] == "report.pdf"
        assert doc["source"] == "/docs/report.pdf"
        assert "src1" not in (doc["title"], doc["filename"])

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_overfetch_fills_when_some_text_missing(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        # n2 ranks above n3 but its chunk text is missing; over-fetching past
        # ``chunks`` lets c3 fill the gap so the result still reaches ``chunks``.
        nodes = [{"id": f"n{i}", "doc_freq": 1} for i in range(1, 4)]
        edges = [
            {"src_node_id": "n1", "dst_node_id": "n2", "weight": 2.0},
            {"src_node_id": "n2", "dst_node_id": "n3", "weight": 1.0},
        ]
        node_chunks = {"n1": ["c1"], "n2": ["c2"], "n3": ["c3"]}
        chunk_texts = {"c1": "first", "c3": "third"}  # c2 missing
        seed_rows = [{"id": "n1", "distance": 0.0}]
        store = _store_with_graph(nodes, edges, node_chunks, chunk_texts, seed_rows)
        mock_store_cls.return_value = store

        rag = _make_retriever(chunks=2)
        docs = rag._get_data()

        texts = [d["text"] for d in docs]
        assert len(docs) == 2
        assert texts == ["first", "third"]

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_no_seeds_returns_empty(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        store = _store_with_graph([], [], {}, {}, [])
        store.count_nodes_many.side_effect = lambda ids: {s: 5 for s in ids}
        mock_store_cls.return_value = store

        rag = _make_retriever()
        assert rag._get_data() == []


# ── IDF down-weighting ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGraphRAGIdf:
    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_hub_downweighted_below_specific_node(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        # Star: seed n1 links a hub node (huge doc_freq) and a specific node
        # (doc_freq=1). PPR mass is symmetric across the two leaves, so only IDF
        # can break the tie — the specific node must rank above the hub.
        nodes = [
            {"id": "n1", "doc_freq": 1},
            {"id": "hub", "doc_freq": 100000},
            {"id": "specific", "doc_freq": 1},
        ]
        edges = [
            {"src_node_id": "n1", "dst_node_id": "hub", "weight": 1.0},
            {"src_node_id": "n1", "dst_node_id": "specific", "weight": 1.0},
        ]
        node_chunks = {"hub": ["c_hub"], "specific": ["c_spec"]}
        chunk_texts = {"c_hub": "hub_text", "c_spec": "spec_text"}
        seed_rows = [{"id": "n1", "distance": 0.0}]
        store = _store_with_graph(nodes, edges, node_chunks, chunk_texts, seed_rows)
        mock_store_cls.return_value = store

        rag = _make_retriever(chunks=2)
        docs = rag._get_data()
        texts = [d["text"] for d in docs]

        assert texts.index("spec_text") < texts.index("hub_text")

    @pytest.mark.unit
    def test_idf_helper_monotonic(self):
        from application.retriever.graph_rag import _idf

        assert _idf(1) > _idf(10) > _idf(1000)


# ── Registry resolution ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestGraphRAGRegistration:
    def test_graphrag_resolves_via_creator(self):
        assert RetrieverCreator.retrievers["graphrag"] is GraphRAGRetriever

    def test_create_retriever_builds_graphrag(self, _patch_llm_creator):
        retriever = RetrieverCreator.create_retriever(
            "graphrag",
            source={"question": "q", "active_docs": ["src1"]},
            chunks=2,
            doc_token_limit=50000,
            model_id="m",
            llm_name="openai",
            api_key="fake",
            decoded_token={"sub": "u"},
        )
        assert isinstance(retriever, GraphRAGRetriever)


# ── get_chunk_texts parameterization ─────────────────────────────────────────


@pytest.mark.unit
class TestGetChunkTexts:
    def _store_with_mock_conn(self):
        from application.graphrag.store import GraphStore

        store = GraphStore.__new__(GraphStore)
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (1, "alpha", {"filename": "a.pdf"}),
            (2, "beta", None),
        ]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        store._connection = conn
        store._get_connection = lambda: conn
        return store, cursor

    def test_returns_text_and_metadata_shape(self):
        import uuid

        store, cursor = self._store_with_mock_conn()
        sid = str(uuid.uuid4())
        result = store.get_chunk_texts(sid, ["1", "2"])

        assert result == {
            "1": {"text": "alpha", "metadata": {"filename": "a.pdf"}},
            "2": {"text": "beta", "metadata": {}},
        }

    def test_uses_configured_identifiers_and_binds_params(self):
        import uuid

        from application.graphrag.store import _pgvector_identifiers

        table, text_col, metadata_col, source_col = _pgvector_identifiers()
        store, cursor = self._store_with_mock_conn()
        sid = str(uuid.uuid4())
        store.get_chunk_texts(sid, ["1", "2"])

        sql, params = cursor.execute.call_args.args[0], cursor.execute.call_args.args[1]
        assert f"FROM {table}" in sql
        assert text_col in sql
        assert metadata_col in sql
        assert f"{source_col} = %s" in sql
        assert "id::text = ANY(%s)" in sql
        assert sid not in sql
        assert params == (sid, ["1", "2"])

    def test_identifiers_match_pgvector_defaults(self):
        from application.graphrag.store import _pgvector_identifiers
        from application.vectorstore.pgvector import PGVectorStore
        import inspect

        params = inspect.signature(PGVectorStore.__init__).parameters
        table, text_col, metadata_col, source_col = _pgvector_identifiers()
        assert table == params["table_name"].default
        assert text_col == params["text_column"].default
        assert metadata_col == params["metadata_column"].default
        assert source_col == "source_id"

    def test_empty_chunk_ids_short_circuits(self):
        store, cursor = self._store_with_mock_conn()
        assert store.get_chunk_texts("sid", []) == {}
        cursor.execute.assert_not_called()


class TestGraphRAGTopK:
    """A prescreen source elsewhere in the group inflates ``chunks``; a graph
    source must still contribute only its own top-k."""

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_inflated_chunks_do_not_raise_a_graph_source_top_k(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        nodes = [{"id": f"n{i}", "doc_freq": 1} for i in range(1, 5)]
        edges = [
            {"src_node_id": "n1", "dst_node_id": "n2", "weight": 1.0},
            {"src_node_id": "n2", "dst_node_id": "n3", "weight": 1.0},
            {"src_node_id": "n3", "dst_node_id": "n4", "weight": 1.0},
        ]
        node_chunks = {f"n{i}": [f"c{i}"] for i in range(1, 5)}
        chunk_texts = {f"c{i}": f"text {i}" for i in range(1, 5)}
        seed_rows = [{"id": "n1", "distance": 0.0}]
        mock_store_cls.return_value = _store_with_graph(
            nodes, edges, node_chunks, chunk_texts, seed_rows
        )

        # What the Dispatcher does when another source in the group prescreens
        # at candidate_k=40: chunks inflated to 40, base_chunks left at the real 2.
        rag = _make_retriever(chunks=40)
        rag.base_chunks = 2

        docs = rag._get_data()

        assert len(docs) == 2


# ── Embeddings resolution ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestEmbedQueryResolution:
    def test_embed_query_uses_shared_resolver(self):
        """Query embedding must go through ``get_embeddings``.

        Only the resolver knows the bundled local-model path, so calling the
        singleton directly loads a second copy of the model (or crashes on the
        positional key).
        """
        fake = Mock()
        fake.embed_query.return_value = [0.1, 0.2, 0.3]

        with patch(
            "application.retriever.graph_rag.get_embeddings", return_value=fake
        ) as mock_resolver:
            result = GraphRAGRetriever._embed_query(object(), "a question")

        mock_resolver.assert_called_once_with()
        fake.embed_query.assert_called_once_with("a question")
        assert result == [0.1, 0.2, 0.3]


# ── Batched retrieval across sources ─────────────────────────────────────────


def _multi_source_retriever(sources, **overrides):
    """Retriever over several attached sources."""
    return _make_retriever(
        source={"question": "q", "active_docs": list(sources)}, **overrides
    )


def _recording_classic(rag, docs):
    """Stub ``ClassicRAG._get_data`` that records the sources it was handed."""
    seen = []

    def _run():
        seen.append(list(rag._classic.vectorstores))
        return [dict(doc) for doc in docs]

    rag._classic._get_data = Mock(side_effect=_run)
    return seen


def _single_node_store(counts):
    """Graph store whose every source yields one chunk, with ``counts`` shape."""
    store = _store_with_graph(
        [{"id": "n1", "doc_freq": 1}],
        [],
        {"n1": ["c1"]},
        {"c1": "graph text"},
        [{"id": "n1", "distance": 0.0}],
    )
    store.count_nodes_many.side_effect = lambda ids: {
        source_id: counts[source_id] for source_id in ids
    }
    return store


_CLASSIC_DOC = {"title": "cl", "text": "classic", "source": "a", "filename": "cl"}


class _SourceConfig:
    """Minimal stand-in for the Dispatcher's per-source RetrievalConfig."""

    def __init__(self, chunks: int):
        self.chunks = chunks


@pytest.mark.unit
class TestGraphRAGBatching:
    """N attached sources cost one count query and one classic run, not N of each."""

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_node_counts_fetched_in_one_query(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        store = MagicMock()
        store.count_nodes_many.return_value = {"a": 0, "b": 0, "c": 0}
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a", "b", "c"])
        _recording_classic(rag, [])

        rag._get_data()

        store.count_nodes_many.assert_called_once_with(["a", "b", "c"])
        store.count_nodes.assert_not_called()

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_graphless_sources_share_one_classic_call(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        store = _single_node_store({"a": 0, "b": 3, "c": 0})
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a", "b", "c"], chunks=3)
        seen = _recording_classic(rag, [_CLASSIC_DOC])

        docs = rag._get_data()

        assert rag._classic._get_data.call_count == 1
        assert seen == [["a", "c"]]
        # The classic batch occupies the slot of the first graphless source, so
        # the graph source's docs still follow it in attachment order.
        assert [doc["text"] for doc in docs] == ["classic", "graph text"]

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_only_the_batched_sources_keep_their_overrides(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        store = _single_node_store({"a": 0, "b": 3, "c": 0})
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a", "b", "c"], chunks=3)
        configs = {sid: _SourceConfig(2) for sid in ("a", "b", "c")}
        rag.per_source_retrieval = dict(configs)
        captured = {}

        def _run():
            captured["overrides"] = dict(rag._classic.per_source_retrieval)
            return []

        rag._classic._get_data = Mock(side_effect=_run)

        rag._get_data()

        assert captured["overrides"] == {"a": configs["a"], "c": configs["c"]}
        # Restored afterwards, exactly as the per-source path did.
        assert rag._classic.per_source_retrieval == {}

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_query_is_embedded_once_for_several_graph_sources(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator
    ):
        store = _single_node_store({"a": 3, "b": 3})
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a", "b"], chunks=4)
        rag._embed_query = Mock(return_value=[0.1, 0.2, 0.3])

        docs = rag._get_data()

        assert rag._embed_query.call_count == 1
        assert store.search_nodes_by_embedding.call_count == 2
        # The one vector is what every source searches with.
        for call in store.search_nodes_by_embedding.call_args_list:
            assert call.args[1] == [0.1, 0.2, 0.3]
        assert [doc["text"] for doc in docs] == ["graph text", "graph text"]

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_failed_graph_sources_land_in_one_batched_fallback(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        store = _single_node_store({"a": 3, "b": 3, "c": 3})

        def _seed(source_id, embedding, k=10):
            if source_id in ("b", "c"):
                raise RuntimeError("graph exploded")
            return [{"id": "n1", "distance": 0.0}]

        store.search_nodes_by_embedding.side_effect = _seed
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a", "b", "c"], chunks=6)
        seen = _recording_classic(rag, [_CLASSIC_DOC])

        docs = rag._get_data()

        assert rag._classic._get_data.call_count == 1
        assert seen == [["b", "c"]]
        # The retried batch is appended after the graph results.
        assert [doc["text"] for doc in docs] == ["graph text", "classic"]

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_embedding_failure_falls_back_for_every_graph_source(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        store = _single_node_store({"a": 3, "b": 3})
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a", "b"])
        rag._embed_query = Mock(side_effect=RuntimeError("no embeddings"))
        seen = _recording_classic(rag, [_CLASSIC_DOC])

        docs = rag._get_data()

        assert seen == [["a", "b"]]
        assert [doc["text"] for doc in docs] == ["classic"]
        store.search_nodes_by_embedding.assert_not_called()

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_count_failure_falls_back_in_one_call(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        store = MagicMock()
        store.count_nodes_many.side_effect = RuntimeError("no graph tables")
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a", "b"])
        seen = _recording_classic(rag, [_CLASSIC_DOC])

        docs = rag._get_data()

        assert seen == [["a", "b"]]
        assert [doc["text"] for doc in docs] == ["classic"]

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_unbuildable_store_falls_back_in_one_call(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        mock_store_cls.side_effect = RuntimeError("no connection string")

        rag = _multi_source_retriever(["a", "b"])
        seen = _recording_classic(rag, [_CLASSIC_DOC])

        rag._get_data()

        assert seen == [["a", "b"]]

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=False)
    def test_unavailable_graphrag_makes_one_batched_classic_call(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        rag = _multi_source_retriever(["a", "b", "c"])
        seen = _recording_classic(rag, [_CLASSIC_DOC])

        rag._get_data()

        assert rag._classic._get_data.call_count == 1
        assert seen == [["a", "b", "c"]]
        mock_store_cls.assert_not_called()

    @patch("application.retriever.graph_rag.num_tokens_from_string", return_value=10)
    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_store_is_closed_on_the_success_path(
        self, _avail, mock_store_cls, _tok, _patch_llm_creator, _patch_embed
    ):
        store = _single_node_store({"a": 3})
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a"], chunks=2)
        rag._get_data()

        store.close.assert_called_once()

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_store_is_closed_when_retrieval_raises(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        store = MagicMock()
        store.count_nodes_many.return_value = {"a": 0}
        mock_store_cls.return_value = store

        rag = _multi_source_retriever(["a"])
        rag._classic._get_data = Mock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            rag._get_data()

        store.close.assert_called_once()

    @patch("application.retriever.graph_rag.GraphStore")
    @patch("application.retriever.graph_rag.graphrag_available", return_value=True)
    def test_empty_source_list_never_builds_a_store(
        self, _avail, mock_store_cls, _patch_llm_creator
    ):
        rag = _make_retriever(source={"question": "q", "active_docs": []})
        rag._classic._get_data = Mock(return_value=[])

        assert rag._get_data() == []
        mock_store_cls.assert_not_called()
        rag._classic._get_data.assert_not_called()
