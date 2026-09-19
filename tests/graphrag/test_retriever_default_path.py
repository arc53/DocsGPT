"""The graph retriever's default path, end to end through ``_graph_docs_for_source``.

The shipped defaults — seed from entities, walk the passages, blend with vector
search — are the configuration that measured best, so they are what most graph
sources run. This drives that whole path with a store that returns real values,
and checks each per-source option actually switches its stage off.
"""

from __future__ import annotations

from docsgpt.retriever.graph_rag import GraphRAGRetriever
from docsgpt.storage.db.source_config import RetrievalConfig

TEXTS = {
    "c-alder": "Alder streams audit events to Quill.",
    "c-quill": "Quill is compacted every six hours.",
}
VECTOR_ONLY = "A passage only plain vector search found."


class _Store:
    """A two-entity chain: the question matches Alder, the answer is on Quill."""

    def __init__(self):
        self.calls: list[str] = []

    def search_nodes_by_embedding(self, source_id, query_embedding, k=10):
        return [{"id": "alder", "name": "Alder", "distance": 0.1}]

    def get_subgraph(self, source_id, node_ids, hops=1):
        return {
            "nodes": [{"id": "alder", "doc_freq": 1}, {"id": "quill", "doc_freq": 1}],
            "edges": [{"src_node_id": "alder", "dst_node_id": "quill", "weight": 1.0}],
        }

    def get_chunk_ids_for_nodes(self, source_id, node_ids):
        return {"alder": ["c-alder"], "quill": ["c-quill"]}

    def chunk_similarities(self, source_id, chunk_ids, query_embedding):
        self.calls.append("chunk_similarities")
        return {"c-alder": 0.9, "c-quill": 0.2}

    def get_chunk_texts(self, source_id, chunk_ids):
        return {
            c: {"text": TEXTS[c], "metadata": {"title": c}}
            for c in chunk_ids
            if c in TEXTS
        }


def _retriever(per_source=None):
    """A retriever without its constructor (which builds a ClassicRAG)."""
    retriever = object.__new__(GraphRAGRetriever)
    retriever.chunks = 3
    retriever.base_chunks = None
    retriever.doc_token_limit = 50000
    retriever.vectorstores = ["src"]
    retriever.per_source_retrieval = per_source or {}
    retriever.vector_calls = 0

    def _vector_ranking(source_id, query_embedding):
        retriever.vector_calls += 1
        return [(VECTOR_ONLY, {"title": "vector"})]

    retriever._vector_ranking = _vector_ranking
    return retriever


def _texts(docs):
    return [doc["text"] for doc in docs]


class TestDefaultPath:
    def test_walks_passages_and_blends_in_vector_hits(self):
        store = _Store()
        retriever = _retriever()

        docs = retriever._graph_docs_for_source(store, "src", [0.1, 0.2])

        # The answer sits one edge away from the seed: the walk reached it.
        assert TEXTS["c-quill"] in _texts(docs)
        # A hit only vector search found is blended in, not lost.
        assert VECTOR_ONLY in _texts(docs)
        assert store.calls == ["chunk_similarities"]
        assert retriever.vector_calls == 1


class TestPerSourceOptions:
    def test_passage_walk_can_be_switched_off(self):
        store = _Store()
        retriever = _retriever(
            {"src": RetrievalConfig(chunks=3, graph={"passage_nodes": False})}
        )

        docs = retriever._graph_docs_for_source(store, "src", [0.1, 0.2])

        assert "chunk_similarities" not in store.calls
        assert TEXTS["c-quill"] in _texts(docs)

    def test_vector_blending_can_be_switched_off(self):
        store = _Store()
        retriever = _retriever(
            {"src": RetrievalConfig(chunks=3, graph={"blend_vector": False})}
        )

        docs = retriever._graph_docs_for_source(store, "src", [0.1, 0.2])

        assert retriever.vector_calls == 0
        assert VECTOR_ONLY not in _texts(docs)
