"""GraphRAG local retriever — Personalized PageRank over a per-source graph.

Rephrased query -> entity-name NN seeds -> bounded 1-2-hop fetch -> Personalized
PageRank (IDF-down-weighted hubs) -> chunks ranked by landed PPR mass -> shared
token budget. No LLM call at query time beyond the (optional, reused) rephrase.

``networkx`` supplies the graph structure, but the ranking is the local power
iteration in :func:`_personalized_pagerank`: ``nx.pagerank`` delegates to scipy,
which DocsGPT does not depend on, so calling it turned every graph retrieval
into a silent ClassicRAG fallback.

Composes :class:`ClassicRAG` rather than subclassing: PPR doesn't fit the
``_fetch_candidates`` hook, but the composed instance supplies the rephrase, the
token-budget loop, and the fallback for sources that have no graph.

Per request the whole source group costs one node-count query, one query
embedding, and one ClassicRAG run for all the graphless sources together — all
over a single pooled connection shared with the vector store.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

import networkx as nx

from docsgpt.core.settings import settings
from docsgpt.graphrag import graphrag_available
from docsgpt.graphrag.store import GraphStore
from docsgpt.retriever.base import BaseRetriever
from docsgpt.retriever.classic_rag import ClassicRAG
from docsgpt.retriever.labels import labels_from_metadata
from docsgpt.storage.db.source_config import GraphRetrievalConfig
from docsgpt.utils import num_tokens_from_string
from docsgpt.vectorstore.base import get_embeddings

SEED_NODES = 10
SUBGRAPH_HOPS = 1


PASSAGE_NODE_WEIGHT = 0.05
FACT_SEED_FACTS = 5
RRF_K = 60

# PageRank damping per ranking mode — each is the value that mode was measured
# at. Lower keeps mass nearer the seeds; with passages in the walk 0.5 measured
# better, while entity-only ranking was measured at the conventional 0.85.
DAMPING_WITH_PASSAGES = 0.5
DAMPING_ENTITIES_ONLY = 0.85


def _idf(doc_freq: Any) -> float:
    """Node-specificity weight: rarer entities (low ``doc_freq``) score higher."""
    return 1.0 / math.log(1.0 + max(int(doc_freq or 0), 0) + 1.0)


def _nodes_by_chunk(chunk_links: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Invert ``node -> chunk ids`` into ``chunk id -> node ids``.

    Node order within a chunk follows the node order of ``chunk_links``, so the
    passage edges are added in the same order as before.
    """
    inverted: Dict[str, List[str]] = {}
    for node, chunks in chunk_links.items():
        for chunk_id in chunks or ():
            inverted.setdefault(chunk_id, []).append(node)
    return inverted


def _damping(passage_nodes: bool) -> float:
    """PageRank damping for a ranking mode: the value that mode was measured at."""
    return DAMPING_WITH_PASSAGES if passage_nodes else DAMPING_ENTITIES_ONLY


def _restart_vector(nodes: List[Any], personalization: Dict[Any, float] | None) -> Dict[Any, float]:
    """Normalized restart distribution over ``nodes``.

    Weights are clamped at zero (a cosine distance above 1 yields a negative
    seed weight) and normalized across the nodes actually present in the graph,
    so restart mass can never leak to a node the subgraph does not contain. An
    absent or all-zero personalization collapses to a uniform restart.
    """
    if personalization:
        weights = {
            node: max(float(personalization.get(node, 0.0) or 0.0), 0.0)
            for node in nodes
        }
        total = sum(weights.values())
        if total > 0:
            return {node: weight / total for node, weight in weights.items()}
    uniform = 1.0 / len(nodes)
    return {node: uniform for node in nodes}


def _personalized_pagerank(
    graph: nx.Graph,
    personalization: Dict[Any, float] | None = None,
    *,
    weight: str = "weight",
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-6,
) -> Dict[Any, float]:
    """Personalized PageRank by power iteration — no scipy.

    ``networkx.pagerank`` delegates to a scipy implementation, and scipy is not
    a DocsGPT dependency: in a default install the import raises and every graph
    retrieval silently degrades to the ClassicRAG fallback. This is the same
    algorithm over the same row-normalized transition matrix, so the ranking is
    unchanged where scipy happens to be installed.

    Args:
        graph: Undirected graph whose edges may carry a ``weight`` attribute.
        personalization: Node -> restart weight; ``None`` means uniform.
        weight: Edge attribute holding the weight.
        alpha: Damping factor.
        max_iter: Iteration cap. The last iterate is returned if it is hit —
            retrieval degrades to a slightly less converged ranking rather than
            raising, which is what the library does.
        tol: Convergence tolerance; iteration stops below ``len(graph) * tol``.

    Returns:
        Node -> PageRank mass, summing to ~1.0. Empty dict for an empty graph.
    """
    nodes = list(graph.nodes)
    node_count = len(nodes)
    if node_count == 0:
        return {}

    restart = _restart_vector(nodes, personalization)

    # Row-normalized transitions. An undirected edge is traversable from both
    # endpoints, so each node normalizes over its own incident weights.
    transitions: Dict[Any, List[tuple[Any, float]]] = {}
    for node in nodes:
        neighbors = []
        total = 0.0
        for neighbor, data in graph[node].items():
            raw_weight = data.get(weight, 1.0)
            # Default only a missing or null weight. ``or 1.0`` would also
            # rewrite an explicit 0 — "these entities are not related" — into a
            # full-strength transition, which changes the ranking.
            edge_weight = 1.0 if raw_weight is None else float(raw_weight)
            if edge_weight <= 0:
                continue
            neighbors.append((neighbor, edge_weight))
            total += edge_weight
        transitions[node] = (
            [(n, w / total) for n, w in neighbors] if total > 0 else []
        )

    # A node with no usable edge is dangling: its mass would vanish each pass,
    # so it is redistributed along the restart vector instead.
    dangling = [node for node in nodes if not transitions[node]]

    ranks = {node: 1.0 / node_count for node in nodes}
    for _ in range(max_iter):
        previous = ranks
        ranks = dict.fromkeys(nodes, 0.0)
        leaked = alpha * sum(previous[node] for node in dangling)
        for node in nodes:
            share = alpha * previous[node]
            for neighbor, transition in transitions[node]:
                ranks[neighbor] += share * transition
        for node in nodes:
            ranks[node] += (leaked + 1.0 - alpha) * restart[node]
        if sum(abs(ranks[node] - previous[node]) for node in nodes) < node_count * tol:
            break
    else:
        logging.debug(
            "Personalized PageRank hit its %s-iteration cap on a %s-node "
            "subgraph; ranking with the last iterate.",
            max_iter,
            node_count,
        )
    return ranks


class GraphRAGRetriever(BaseRetriever):
    """Per-source PPR retriever; falls back to ClassicRAG when a source has no graph."""

    # Set by the Dispatcher (see ClassicRAG.base_chunks); forwarded to the inner
    # ClassicRAG on the fallback path.
    base_chunks = None

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
        include_scores=False,
    ):
        # Graph docs are ranked by PPR, which yields no per-chunk similarity, so
        # they stay unscored; the flag only matters to the classic fallback,
        # which retrieves the sources that have no graph.
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
            include_scores=include_scores,
        )
        self.original_question = self._classic.original_question
        self.chunks = self._classic.chunks
        self.doc_token_limit = doc_token_limit
        self.vectorstores = self._classic.vectorstores
        self.per_source_retrieval = {}

    def _embed_query(self, question: str) -> List[float]:
        embedding = get_embeddings()
        return embedding.embed_query(question)

    def _ppr_scores(self, subgraph, seeds) -> Dict[str, float]:
        """Run Personalized PageRank, then down-weight hub nodes by IDF.

        ``seeds`` maps seed node id -> personalization weight (seed similarity).
        After PPR, each node's mass is scaled by ``1/log(2 + doc_freq)`` so a
        high-degree hub contributes less than a specific entity at equal mass.
        """
        # Through the class, not ``self``: this method reads no instance state,
        # and callers (and tests) rely on being able to invoke it unbound.
        graph = GraphRAGRetriever._subgraph_graph(subgraph)
        if graph.number_of_nodes() == 0:
            return {}

        personalization = {n: seeds.get(n, 0.0) for n in graph.nodes}
        if not any(personalization.values()):
            personalization = None

        ranks = _personalized_pagerank(
            graph,
            personalization=personalization,
            weight="weight",
            alpha=_damping(passage_nodes=False),
        )
        return {
            node: rank * _idf(graph.nodes[node].get("doc_freq", 0))
            for node, rank in ranks.items()
        }

    @staticmethod
    def _subgraph_graph(subgraph) -> "nx.Graph":
        """The fetched subgraph as a weighted undirected graph."""
        graph = nx.Graph()
        for node in subgraph.get("nodes", []):
            graph.add_node(node["id"], doc_freq=node.get("doc_freq", 0))
        for edge in subgraph.get("edges", []):
            src, dst = edge["src_node_id"], edge["dst_node_id"]
            if src in graph and dst in graph:
                raw_weight = edge.get("weight")
                # Default only a missing or null weight. Coercing an explicit 0
                # to 1.0 would make "these entities are not related" the
                # strongest possible link.
                edge_weight = 1.0 if raw_weight is None else float(raw_weight)
                graph.add_edge(src, dst, weight=edge_weight)
        return graph

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

    def _rank_chunks_with_passages(
        self, store, source_id, subgraph, seeds, query_embedding
    ) -> List[str]:
        """Rank chunks by walking a graph that contains the chunks themselves.

        :meth:`_rank_chunks` reads a chunk's score *off* its entities, summing
        their PPR mass — so a chunk touching many mid-scoring generic entities
        outranks one touching the few entities the question is about. Putting
        the chunks in the walk instead, each joined to its own entities and
        carrying a small share of the restart mass proportional to its own
        vector similarity, makes a chunk reachable both ways: by being about the
        question, and by being connected to what is. Graph retrieval then
        contains vector retrieval rather than competing with it.

        Only an improvement when the seeds are good: measured across five
        corpora it helped alongside richer seed embeddings and *hurt* with
        bare-name seeds (0.73 -> 0.57 on one corpus). Graphs are now always
        built with the richer seed text; one built before that change should be
        rebuilt before this is relied on.
        """
        node_ids = [node["id"] for node in subgraph.get("nodes", [])]
        chunk_links = store.get_chunk_ids_for_nodes(source_id, node_ids)
        candidate_ids = sorted({c for chunks in chunk_links.values() for c in chunks})
        if not candidate_ids:
            return []

        graph = self._subgraph_graph(subgraph)
        similarities = store.chunk_similarities(
            source_id, candidate_ids, query_embedding
        )
        # Normalised so the passage share is a fixed fraction of the restart
        # mass rather than whatever absolute cosine this embedding model emits.
        scores = [similarities.get(c, 0.0) for c in candidate_ids]
        low, high = (min(scores), max(scores)) if scores else (0.0, 0.0)
        spread = high - low

        personalization = dict(seeds)
        passage_of: Dict[str, str] = {}
        # Inverted once: scanning every node's chunk list per candidate is
        # quadratic, and at the candidate cap it cost more than the walk it
        # feeds (76 ms against 0.5 ms measured).
        nodes_by_chunk = _nodes_by_chunk(chunk_links)
        for chunk_id in candidate_ids:
            linked = [n for n in nodes_by_chunk.get(chunk_id, ()) if n in graph]
            if not linked:
                continue
            passage_node = f"chunk::{chunk_id}"
            passage_of[passage_node] = chunk_id
            for node in linked:
                graph.add_edge(passage_node, node, weight=1.0)
            similarity = similarities.get(chunk_id, 0.0)
            normalized = (similarity - low) / spread if spread > 0 else 0.0
            personalization[passage_node] = normalized * PASSAGE_NODE_WEIGHT

        if graph.number_of_nodes() == 0 or not any(personalization.values()):
            return []

        ranks = _personalized_pagerank(
            graph,
            personalization=personalization,
            weight="weight",
            alpha=_damping(passage_nodes=True),
        )
        chunk_scores = {
            chunk_id: ranks.get(passage_node, 0.0)
            for passage_node, chunk_id in passage_of.items()
        }
        ranked = sorted(chunk_scores, key=lambda c: chunk_scores[c], reverse=True)
        candidates = max(self.chunks * 2, self.chunks + 5)
        return ranked[: max(1, candidates)]

    def _source_top_k(self, source_id) -> int:
        """How many chunks this source may contribute — its own top-k.

        Mirrors ClassicRAG's resolution: a per-source override wins (raised to
        candidate_k when it prescreens, so the stage has candidates to filter);
        otherwise the group's real top-k is split across the sources. Without
        this, a prescreen source elsewhere in the group inflates ``chunks`` and
        this source would return that inflated count.
        """
        cfg = self.per_source_retrieval.get(source_id)
        if cfg is not None:
            top_k = max(1, int(cfg.chunks))
            ps = cfg.prescreen_config() if hasattr(cfg, "prescreen_config") else None
            if ps is not None:
                top_k = max(top_k, int(ps.candidate_k))
            return top_k
        base = self.base_chunks if self.base_chunks is not None else self.chunks
        return max(1, base // max(1, len(self.vectorstores)))

    def _vector_ranking(self, source_id, query_embedding: List[float]) -> List[tuple]:
        """The source's own vector ranking, as ``(text, metadata)`` in score order.

        Used only by the hybrid path. Vector hits carry no row id, so the fused
        ranking is keyed on the chunk text itself — the one identifier both
        rankings share — and the metadata travels with it so a hit the graph
        never surfaced can still be emitted as a document.
        """
        from docsgpt.vectorstore.vector_creator import VectorCreator

        store = None
        try:
            store = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
            )
            hits = store.search(
                self._classic._get_rephrased_question(),
                k=max(self.chunks * 4, 20),
                query_vector=query_embedding,
            )
        except Exception as e:
            logging.error(
                "GraphRAG hybrid: vector ranking failed for %s: %s", source_id, e
            )
            return []
        finally:
            close = getattr(store, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as e:
                    logging.debug("Error closing hybrid vector store: %s", e)
        ranked = []
        for hit in hits:
            text = getattr(hit, "page_content", None)
            metadata = getattr(hit, "metadata", None)
            if text is None and isinstance(hit, dict):
                text = hit.get("text") or hit.get("page_content")
                metadata = hit.get("metadata")
            if text:
                ranked.append((text, metadata or {}))
        return ranked

    @staticmethod
    def _rrf_order(rankings: List[List[str]], k: int) -> Dict[str, float]:
        """Reciprocal rank fusion over ranked lists of the same key type.

        Rank-based on purpose: PPR mass and cosine similarity are not on
        comparable scales, and normalising either one invents a calibration
        that does not exist.
        """
        scores: Dict[str, float] = {}
        for ranking in rankings:
            for position, key in enumerate(ranking):
                scores[key] = scores.get(key, 0.0) + 1.0 / (k + position + 1)
        return scores

    def _graph_options(self, source_id) -> GraphRetrievalConfig:
        """This source's graph retrieval options, or the recommended defaults.

        Options travel on the per-source retrieval config the Dispatcher hands
        over. A request that carries no per-source detail gets the defaults,
        which are the measured-best configuration rather than a neutral one.
        """
        cfg = (getattr(self, "per_source_retrieval", None) or {}).get(source_id)
        options = cfg.get("graph") if isinstance(cfg, dict) else getattr(cfg, "graph", None)
        if isinstance(options, GraphRetrievalConfig):
            return options
        try:
            return GraphRetrievalConfig.model_validate(options or {})
        except Exception:
            return GraphRetrievalConfig()

    def _seed_rows(
        self, store, source_id, query_embedding: List[float]
    ) -> List[Dict[str, Any]]:
        """The nodes the walk restarts from, per the source's ``seed_strategy``.

        Seeding decides more than ranking does: a walk that starts on the wrong
        nodes cannot be rescued downstream.

        ``entities``
            Cosine NN over entity embeddings, built from each entity's name,
            type and description so a whole question has something to match.
            The default: best or tied-best on every corpus measured.
        ``relationships``
            Cosine NN over relationship sentences ("A streams_to B: ..."),
            seeding both endpoints of the best-matching facts. The only way to
            start on an entity the question never names; strongest on
            chain-structured content, weaker on ordinary prose.

        Relationship seeding falls back to entity matching for a source with no
        fact embeddings (one built before they were recorded), so it still
        retrieves rather than returning nothing.
        """
        if self._graph_options(source_id).seed_strategy == "relationships":
            by_fact = store.seed_nodes_from_facts(
                source_id, query_embedding, fact_limit=FACT_SEED_FACTS, limit=SEED_NODES
            )
            if by_fact:
                return by_fact
        return store.search_nodes_by_embedding(
            source_id, query_embedding, k=SEED_NODES
        )

    def _graph_docs_for_source(
        self, store, source_id, query_embedding: List[float]
    ) -> List[Dict[str, Any]]:
        """Local PPR retrieval for one source (caller guarantees it has a graph).

        Args:
            store: Open :class:`GraphStore` shared by every source of this run.
            source_id: Source to retrieve from.
            query_embedding: Embedding of the rephrased question, computed once
                by the caller for the whole retrieval.
        """
        seed_rows = self._seed_rows(store, source_id, query_embedding)
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

        options = self._graph_options(source_id)
        subgraph = store.get_subgraph(source_id, seed_ids, hops=SUBGRAPH_HOPS)
        if options.passage_nodes:
            chunk_ids = self._rank_chunks_with_passages(
                store, source_id, subgraph, seeds, query_embedding
            )
        else:
            node_scores = self._ppr_scores(subgraph, seeds)
            if not node_scores:
                return []
            chunk_ids = self._rank_chunks(store, source_id, node_scores)
        if not chunk_ids:
            return []

        chunk_data = store.get_chunk_texts(source_id, chunk_ids)

        # ``(text, metadata)`` in rank order. Chunk ids stop being the currency
        # here: a hit contributed by the vector ranking has no graph chunk id,
        # and keying on ids is what made an earlier version of this fusion able
        # only to reorder the graph's own candidates.
        candidates: List[tuple] = []
        for chunk_id in chunk_ids:
            chunk = chunk_data.get(chunk_id)
            text = chunk.get("text") if chunk else None
            if text:
                candidates.append((text, chunk.get("metadata")))

        if options.blend_vector:
            # The graph ranks by how much PPR mass landed on a chunk's
            # entities, which says nothing about whether the chunk is about the
            # question. Fusing with the source's own vector ranking keeps the
            # graph's reach while letting plain relevance back in — including
            # chunks the graph never surfaced, which is where most of the value
            # is: no reordering can rescue a question whose answer the graph
            # missed entirely.
            vector_hits = self._vector_ranking(source_id, query_embedding)
            if vector_hits:
                metadata_by_text = {text: meta for text, meta in candidates}
                for text, meta in vector_hits:
                    metadata_by_text.setdefault(text, meta)
                fused = self._rrf_order(
                    [[t for t, _ in candidates], [t for t, _ in vector_hits]],
                    RRF_K,
                )
                candidates = [
                    (text, metadata_by_text.get(text))
                    for text in sorted(fused, key=lambda t: fused[t], reverse=True)
                ]

        docs: List[Dict[str, Any]] = []
        token_budget = max(int(self.doc_token_limit * 0.9), 100)
        cumulative_tokens = 0
        source_top_k = self._source_top_k(source_id)
        for text, metadata in candidates:
            if len(docs) >= source_top_k:
                break
            labels = labels_from_metadata(metadata, text, source_id)
            doc_tokens = num_tokens_from_string(f"{labels['filename']}\n{text}")
            if cumulative_tokens + doc_tokens >= token_budget:
                break
            docs.append({"text": text, **labels})
            cumulative_tokens += doc_tokens
        return docs

    def _classic_for_sources(self, source_ids) -> List[Dict[str, Any]]:
        """Reuse the composed ClassicRAG to retrieve a whole batch of sources.

        One inner run for every graphless source instead of one run per source:
        ClassicRAG then embeds the query once and fans the sources out itself.
        The trade is that the per-source chunk split and the shared doc-token
        budget apply across the batch — i.e. exactly plain ClassicRAG semantics
        over those sources, rather than each source getting its own full budget.
        """
        source_ids = [source_id for source_id in source_ids if source_id]
        if not source_ids:
            return []
        wanted = set(source_ids)
        original = self._classic.vectorstores
        original_overrides = self._classic.per_source_retrieval
        original_base = self._classic.base_chunks
        try:
            self._classic.vectorstores = list(source_ids)
            self._classic.per_source_retrieval = {
                k: v for k, v in self.per_source_retrieval.items() if k in wanted
            }
            # The Dispatcher sets these on *this* object; the inner retriever is
            # the one that reads them.
            self._classic.base_chunks = self.base_chunks
            return self._classic._get_data()
        finally:
            self._classic.vectorstores = original
            self._classic.per_source_retrieval = original_overrides
            self._classic.base_chunks = original_base

    def _classic_for_source(self, source_id) -> List[Dict[str, Any]]:
        """Retrieve one source through the batched classic path."""
        return self._classic_for_sources([source_id])

    def _retrieve_with_store(self, store, sources) -> List[Dict[str, Any]]:
        """Split ``sources`` by graph presence, then batch each half.

        Graph sources keep their own slot in source order; every graphless
        source collapses into a single ClassicRAG run that occupies the slot of
        the first graphless source. Sources whose PPR retrieval raises, or
        answers nothing, are collected and retried as one more classic batch,
        appended at the end.
        """
        try:
            counts = store.count_nodes_many(sources)
        except Exception as e:
            logging.error(f"GraphRAG count_nodes failed for {sources}: {e}")
            counts = {}

        segments: List[List[Dict[str, Any]]] = []
        graph_slots: Dict[str, int] = {}
        graphed: List[str] = []
        graphless: List[str] = []
        classic_slot = None
        for source_id in sources:
            if counts.get(source_id, 0) > 0:
                if source_id in graph_slots:
                    continue
                graph_slots[source_id] = len(segments)
                segments.append([])
                graphed.append(source_id)
            else:
                if classic_slot is None:
                    classic_slot = len(segments)
                    segments.append([])
                graphless.append(source_id)

        fallback: List[str] = []
        query_embedding = None
        if graphed:
            # Embedded once for the whole retrieval, not once per graph source.
            try:
                query_embedding = self._embed_query(
                    self._classic._get_rephrased_question()
                )
            except Exception as e:
                logging.error(
                    f"GraphRAG query embedding failed, falling back: {e}",
                    exc_info=True,
                )
                fallback, graphed = list(graphed), []

        for source_id in graphed:
            try:
                docs = self._graph_docs_for_source(store, source_id, query_embedding)
            except Exception as e:
                logging.error(
                    f"GraphRAG retrieval failed for {source_id}, falling back: {e}",
                    exc_info=True,
                )
                fallback.append(source_id)
                continue
            if not docs:
                # Empty is not an answer. Every graph read reports its own
                # failure and returns nothing, so "no rows" covers a query that
                # broke or a half-built graph as much as a walk that found
                # nothing — and only a raise reaches the fallback, so the
                # source would otherwise contribute nothing at all. Searching
                # it classically is what a source with no graph already gets.
                logging.info(
                    "GraphRAG retrieval returned nothing for %s, falling back",
                    source_id,
                )
                fallback.append(source_id)
                continue
            segments[graph_slots[source_id]] = docs

        # Every remaining segment is a ClassicRAG fan-out, and each of its legs
        # checks out of the *same* per-DSN pool this store is holding. Hand the
        # graph connection back first, or concurrent GraphRAG retrievals occupy
        # every slot and then block on their own fallbacks until PoolTimeout.
        # ``close()`` nulls the connection, so ``_get_data``'s finally stays correct.
        if graphless or fallback:
            try:
                store.close()
            except Exception as e:
                logging.debug("Error releasing GraphRAG store before fallback: %s", e)

        if graphless:
            segments[classic_slot] = self._classic_for_sources(graphless)
        if fallback:
            segments.append(self._classic_for_sources(fallback))

        return [doc for segment in segments for doc in segment]

    def _get_data(self) -> List[Dict[str, Any]]:
        sources = [source_id for source_id in self.vectorstores if source_id]
        if not sources:
            return []

        store = None
        if graphrag_available():
            try:
                store = GraphStore()
            except Exception as e:
                logging.error(f"GraphRAG store unavailable, falling back: {e}")
                store = None

        if store is None:
            return self._classic_for_sources(sources)

        try:
            return self._retrieve_with_store(store, sources)
        finally:
            # Hand the pooled connection back; the store is per-request.
            try:
                store.close()
            except Exception as e:
                logging.debug("Error closing GraphRAG store: %s", e)

    def search(self, query: str = "") -> List[Dict[str, Any]]:
        if query:
            self.original_question = query
            self._classic.original_question = query
            self._classic._rephrased_question = None
            self._classic.question = self._classic._rephrase_query()
            self._classic._rephrased_question = self._classic.question
        return self._get_data()
