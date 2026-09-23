"""Spans for RAG retrieval: the search itself, the query embedding, each source."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from docsgpt.tracing import core

#: Characters of each retrieved chunk kept in the stored preview.
_SNIPPET_CHARS = 240
#: Chunks listed in the preview; the count attribute still reports all of them.
_MAX_PREVIEW_CHUNKS = 20


def start_retrieval_span(name: str, *, sources: Optional[Iterable[Any]] = None, **attributes: Any):
    """Open a ``retrieval`` span (a container: embeddings and searches nest under it)."""
    source_ids = [str(s) for s in (sources or []) if s]
    base = {
        "gen_ai.operation.name": "retrieval",
        "docsgpt.source_ids": source_ids or None,
        "gen_ai.data_source.id": source_ids[0] if len(source_ids) == 1 else None,
    }
    base.update(attributes)
    return core.start_span(
        core.KIND_RETRIEVAL,
        name,
        attributes={k: v for k, v in base.items() if v is not None},
    )


def describe_documents(span: Any, docs: Optional[List[Dict[str, Any]]], *, query: Optional[str] = None) -> None:
    """Record what a retrieval returned: counts, sources, top scores and a chunk preview."""
    if not span:
        return
    docs = docs or []
    scores = [d.get("score") for d in docs if isinstance(d, dict) and isinstance(d.get("score"), (int, float))]
    score_kinds = {d.get("score_kind") for d in docs if isinstance(d, dict) and d.get("score_kind")}
    span.set(
        **{
            "docsgpt.chunk_count": len(docs),
            "docsgpt.top_score": max(scores) if scores else None,
            "docsgpt.score_kind": score_kinds.pop() if len(score_kinds) == 1 else None,
        }
    )
    if query:
        span.preview("query", query)
    if docs:
        span.preview(
            "chunks",
            [
                {
                    k: v
                    for k, v in {
                        "title": d.get("title") or d.get("filename"),
                        "source": d.get("source"),
                        "score": d.get("score"),
                        "text": str(d.get("text") or "")[:_SNIPPET_CHARS],
                    }.items()
                    if v not in (None, "")
                }
                for d in docs[:_MAX_PREVIEW_CHUNKS]
                if isinstance(d, dict)
            ],
        )


def start_embedding_span(model: Optional[str], *, inputs: int = 1, **attributes: Any):
    """Open an ``embeddings`` span for a query embedding (leaf)."""
    base = {
        "gen_ai.operation.name": "embeddings",
        "gen_ai.request.model": model,
        "docsgpt.input_count": inputs,
    }
    base.update(attributes)
    return core.start_span(
        core.KIND_EMBEDDING,
        f"embeddings {model}" if model else "embeddings",
        attributes={k: v for k, v in base.items() if v is not None},
    )


def start_source_search_span(source_id: Any, *, top_k: Optional[int] = None, **attributes: Any):
    """Open a per-source vector ``search`` span (leaf)."""
    base = {
        "gen_ai.operation.name": "search",
        "gen_ai.data_source.id": str(source_id) if source_id else None,
        "docsgpt.top_k": top_k,
    }
    base.update(attributes)
    return core.start_span(
        core.KIND_SEARCH,
        f"search {source_id}" if source_id else "search",
        attributes={k: v for k, v in base.items() if v is not None},
    )
