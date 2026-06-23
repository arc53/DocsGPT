"""GraphRAG local retriever — Personalized PageRank over a per-source graph.

Rephrased query -> entity-name NN seeds -> bounded 1-2-hop fetch -> networkx
Personalized PageRank (IDF-down-weighted hubs) -> chunks ranked by landed PPR
mass -> shared token budget. No LLM call at query time beyond the (optional,
reused) rephrase.

Composes :class:`ClassicRAG` rather than subclassing: PPR doesn't fit the
``_fetch_candidates`` hook, but the composed instance supplies the rephrase, the
token-budget loop, and the per-source fallback when a source has no graph.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

import networkx as nx

from application.core.settings import settings
from application.graphrag import graphrag_available
from application.graphrag.store import GraphStore
from application.retriever.base import BaseRetriever
from application.retriever.classic_rag import ClassicRAG
from application.retriever.labels import labels_from_metadata
from application.utils import num_tokens_from_string
from application.vectorstore.base import EmbeddingsSingleton

SEED_NODES = 10
SUBGRAPH_HOPS = 1


def _idf(doc_freq: Any) -> float:
    """Node-specificity weight: rarer entities (low ``doc_freq``) score higher."""
    return 1.0 / math.log(1.0 + max(int(doc_freq or 0), 0) + 1.0)


class GraphRAGRetriever(BaseRetriever):
    """Per-source PPR retriever; falls back to ClassicRAG when a source has no graph."""

    def __init__(
        self,
        source,
        chat_history=None,
        prompt="",
        chunks=2,
        doc_token_limit=50000,
        model_id="docsgpt-local",
        user_api_key=None,
        agent_id=None,
        llm_name=settings.LLM_PROVIDER,
        api_key=settings.API_KEY,
        decoded_token=None,
        model_user_id=None,
        defer_rephrase=False,
        request_id=None,
    ):
        self._classic = ClassicRAG(
            source=source,
            chat_history=chat_history,
            prompt=prompt,
            chunks=chunks,
            doc_token_limit=doc_token_limit,
            model_id=model_id,
            user_api_key=user_api_key,
            agent_id=agent_id,
            llm_name=llm_name,
            api_key=api_key,
            decoded_token=decoded_token,
            model_user_id=model_user_id,
            defer_rephrase=defer_rephrase,
            request_id=request_id,
        )
        self.original_question = self._classic.original_question
        self.chunks = self._classic.chunks
        self.doc_token_limit = doc_token_limit
        self.vectorstores = self._classic.vectorstores
        self.per_source_retrieval = {}

    def _embed_query(self, question: str) -> List[float]:
        embedding = EmbeddingsSingleton.get_instance(
            settings.EMBEDDINGS_NAME, settings.EMBEDDINGS_KEY
        )
        return embedding.embed_query(question)

    def _ppr_scores(self, subgraph, seeds) -> Dict[str, float]:
        """Run Personalized PageRank, then down-weight hub nodes by IDF.

        ``seeds`` maps seed node id -> personalization weight (seed similarity).
        After PPR, each node's mass is scaled by ``1/log(2 + doc_freq)`` so a
        high-degree hub contributes less than a specific entity at equal mass.
        """
        graph = nx.Graph()
        for node in subgraph.get("nodes", []):
            graph.add_node(node["id"], doc_freq=node.get("doc_freq", 0))
        for edge in subgraph.get("edges", []):
            src, dst = edge["src_node_id"], edge["dst_node_id"]
            if src in graph and dst in graph:
                weight = float(edge.get("weight") or 1.0)
                graph.add_edge(src, dst, weight=weight)
        if graph.number_of_nodes() == 0:
            return {}

        personalization = {n: seeds.get(n, 0.0) for n in graph.nodes}
        if not any(personalization.values()):
            personalization = None

        ranks = nx.pagerank(graph, personalization=personalization, weight="weight")
        return {
            node: rank * _idf(graph.nodes[node].get("doc_freq", 0))
            for node, rank in ranks.items()
        }

    def _rank_chunks(self, store, source_id, node_scores) -> List[str]:
        """Score chunks by summed (PPR mass x IDF) of their linked nodes; top candidates.

        Over-fetches beyond ``self.chunks`` so chunks with missing text don't drop
        the final count below the budget; the budget loop caps the real total.
        """
        node_ids = list(node_scores.keys())
        chunk_links = store.get_chunk_ids_for_nodes(source_id, node_ids)
        chunk_scores: Dict[str, float] = {}
        for node_id, chunk_ids in chunk_links.items():
            node_score = node_scores.get(node_id, 0.0)
            for chunk_id in chunk_ids:
                chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0.0) + node_score
        ranked = sorted(chunk_scores, key=lambda c: chunk_scores[c], reverse=True)
        candidates = max(self.chunks * 2, self.chunks + 5)
        return ranked[: max(1, candidates)]

    def _graph_docs_for_source(self, store, source_id) -> List[Dict[str, Any]]:
        """Local PPR retrieval for one source (caller guarantees it has a graph)."""
        question = self._classic._get_rephrased_question()
        query_embedding = self._embed_query(question)
        seed_rows = store.search_nodes_by_embedding(
            source_id, query_embedding, k=SEED_NODES
        )
        if not seed_rows:
            return []

        seed_ids = [row["id"] for row in seed_rows]
        # Clamp to >= 0: cosine distance can exceed 1 (negative similarity) for
        # some embedding backends, and networkx pagerank produces garbage on
        # negative personalization (and ZeroDivisionError when the weights sum
        # to ~0). All-zero collapses to uniform PPR via the None guard below.
        seeds = {
            row["id"]: max(0.0, 1.0 - float(row.get("distance") or 0.0))
            for row in seed_rows
        }

        subgraph = store.get_subgraph(source_id, seed_ids, hops=SUBGRAPH_HOPS)
        node_scores = self._ppr_scores(subgraph, seeds)
        if not node_scores:
            return []

        chunk_ids = self._rank_chunks(store, source_id, node_scores)
        chunk_data = store.get_chunk_texts(source_id, chunk_ids)

        docs: List[Dict[str, Any]] = []
        token_budget = max(int(self.doc_token_limit * 0.9), 100)
        cumulative_tokens = 0
        for chunk_id in chunk_ids:
            if len(docs) >= self.chunks:
                break
            chunk = chunk_data.get(chunk_id)
            text = chunk.get("text") if chunk else None
            if not text:
                continue
            labels = labels_from_metadata(chunk.get("metadata"), text, source_id)
            doc_tokens = num_tokens_from_string(f"{labels['filename']}\n{text}")
            if cumulative_tokens + doc_tokens >= token_budget:
                break
            docs.append({"text": text, **labels})
            cumulative_tokens += doc_tokens
        return docs

    def _classic_for_source(self, source_id) -> List[Dict[str, Any]]:
        """Reuse the composed ClassicRAG to retrieve one source's chunks."""
        original = self._classic.vectorstores
        original_overrides = self._classic.per_source_retrieval
        try:
            self._classic.vectorstores = [source_id]
            self._classic.per_source_retrieval = {
                k: v for k, v in self.per_source_retrieval.items() if k == source_id
            }
            return self._classic._get_data()
        finally:
            self._classic.vectorstores = original
            self._classic.per_source_retrieval = original_overrides

    def _get_data(self) -> List[Dict[str, Any]]:
        if not self.vectorstores:
            return []

        store = None
        if graphrag_available():
            try:
                store = GraphStore()
            except Exception as e:
                logging.error(f"GraphRAG store unavailable, falling back: {e}")
                store = None

        all_docs: List[Dict[str, Any]] = []
        for source_id in self.vectorstores:
            if not source_id:
                continue
            has_graph = False
            if store is not None:
                try:
                    has_graph = store.count_nodes(source_id) > 0
                except Exception as e:
                    logging.error(f"GraphRAG count_nodes failed for {source_id}: {e}")
                    has_graph = False

            if not has_graph:
                all_docs.extend(self._classic_for_source(source_id))
                continue

            try:
                all_docs.extend(self._graph_docs_for_source(store, source_id))
            except Exception as e:
                logging.error(
                    f"GraphRAG retrieval failed for {source_id}, falling back: {e}",
                    exc_info=True,
                )
                all_docs.extend(self._classic_for_source(source_id))
        return all_docs

    def search(self, query: str = "") -> List[Dict[str, Any]]:
        if query:
            self.original_question = query
            self._classic.original_question = query
            self._classic._rephrased_question = None
            self._classic.question = self._classic._rephrase_query()
            self._classic._rephrased_question = self._classic.question
        return self._get_data()
