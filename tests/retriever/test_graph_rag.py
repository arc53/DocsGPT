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
        store.count_nodes.return_value = 0
        mock_store_cls.return_value = store

        rag = _make_retriever()
        classic_docs = [{"title": "c", "text": "classic", "source": "src1", "filename": "c"}]
        rag._classic._get_data = Mock(return_value=list(classic_docs))

        docs = rag._get_data()

        assert docs == classic_docs
        store.search_nodes_by_embedding.assert_not_called()
        store.get_subgraph.assert_not_called()

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
        store.count_nodes.return_value = 5
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
