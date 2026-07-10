"""Hybrid retriever fusing vector and keyword search via RRF.

Subclasses :class:`ClassicRAG` so the Dispatcher builds it with identical
ctor kwargs and it inherits rephrase + token-budgeting. Only the per-source
fetch is overridden: for each vector store it pulls vector hits and keyword
hits, then fuses them with Reciprocal Rank Fusion. Stores without keyword
support (``keyword_search`` returns ``[]``) reduce to exact vector-only
behaviour.
"""

from application.retriever.classic_rag import ClassicRAG

RRF_K = 60


def _doc_key(doc):
    """Stable identity for a hit so the same chunk fuses across both lists."""
    if hasattr(doc, "page_content") and hasattr(doc, "metadata"):
        content = doc.page_content
        metadata = doc.metadata or {}
    else:
        content = doc.get("text", doc.get("page_content", ""))
        metadata = doc.get("metadata") or {}
    source = metadata.get("source", "")
    return (source, content)


def reciprocal_rank_fusion(vector_hits, keyword_hits, k=RRF_K):
    """Fuse two ranked hit lists into one by Reciprocal Rank Fusion.

    Each list contributes ``1 / (k + rank)`` per document (rank 0-based);
    documents are returned ordered by summed score, highest first. A document
    present in only one list is ranked solely on that list's contribution, so
    an empty ``keyword_hits`` yields exactly the vector ordering.
    """
    scores = {}
    docs = {}
    for hits in (vector_hits, keyword_hits):
        for rank, doc in enumerate(hits):
            key = _doc_key(doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in docs:
                docs[key] = doc
    ordered = sorted(docs.keys(), key=lambda key: scores[key], reverse=True)
    return [docs[key] for key in ordered]


class HybridRetriever(ClassicRAG):
    """ClassicRAG variant that fuses vector + keyword search with RRF."""

    def _fetch_candidates(self, docsearch, question, src_k, score_threshold):
        """Return RRF-fused vector+keyword hits for one vector store.

        Inherits the per-source resolution and budgeting from
        :meth:`ClassicRAG._get_data`; only candidate sourcing differs.
        RRF scores are not cosine similarities, so ``score_threshold`` is
        intentionally not applied to the fused list.
        """
        candidate_k = min(max(src_k * 2, 20), 500)
        vector_hits = docsearch.search(question, k=candidate_k)
        keyword_hits = docsearch.keyword_search(question, k=candidate_k)
        return reciprocal_rank_fusion(vector_hits, keyword_hits)
