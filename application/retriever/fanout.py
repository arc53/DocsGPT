"""Shared helpers for fanning one query out across several vector stores.

Attaching N sources used to cost N query embeddings and N serial round trips.
The pieces here collapse that to one embedding plus one bounded, order-
preserving thread pool, and are reused by :mod:`application.retriever.classic_rag`
and :mod:`application.services.search_service` so both paths behave the same.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, TypeVar

from application.core.settings import settings

logger = logging.getLogger(__name__)

# Fallback fan-out width when ``RETRIEVAL_MAX_PARALLEL_SOURCES`` is unset.
DEFAULT_MAX_PARALLEL_SOURCES = 4

# Attributes the vector stores keep their embeddings object on, in the order
# they are probed. Stores that build embeddings inline (elasticsearch, lancedb)
# expose none of them and are handled by the ``_get_embeddings`` fallback.
EMBEDDING_ATTRS = ("_embedding", "_embeddings", "embeddings")

Job = TypeVar("Job")
Result = TypeVar("Result")


def max_parallel_sources(n_sources: int, settings_obj: Any = None) -> int:
    """Worker count for the per-source fan-out, bounded by the source count.

    Args:
        n_sources: Number of sources about to be searched.
        settings_obj: Settings to read ``RETRIEVAL_MAX_PARALLEL_SOURCES`` from;
            defaults to the global settings.

    Returns:
        int: Worker count, at least 1 and never above ``n_sources``.
    """
    config = settings if settings_obj is None else settings_obj
    configured = getattr(
        config, "RETRIEVAL_MAX_PARALLEL_SOURCES", DEFAULT_MAX_PARALLEL_SOURCES
    )
    try:
        configured = int(configured)
    except (TypeError, ValueError):
        configured = DEFAULT_MAX_PARALLEL_SOURCES
    return max(1, min(configured, n_sources))


def store_embeddings(docsearch) -> Optional[Any]:
    """Return the embeddings object a vector store searches with, if any."""
    for attr in EMBEDDING_ATTRS:
        embedder = getattr(docsearch, attr, None)
        if embedder is not None and hasattr(embedder, "embed_query"):
            return embedder
    getter = getattr(docsearch, "_get_embeddings", None)
    if callable(getter):
        try:
            return getter(settings.EMBEDDINGS_NAME, settings.EMBEDDINGS_KEY)
        except Exception as e:
            logger.debug("Could not resolve store embeddings: %s", e)
    return None


def embed_questions(docsearch, questions: Iterable[str]) -> Dict[str, List[float]]:
    """Embed each distinct query once for the whole retrieval.

    Every source of one retrieval shares a single embeddings config
    (``settings.EMBEDDINGS_NAME`` is global — nothing per-source overrides it),
    so a vector computed with one store's embedder is valid for all of them.
    That turns N sources from N query embeddings into one.

    Args:
        docsearch: Any store of the retrieval; only its embedder is used.
        questions: Queries to embed (duplicates are embedded once).

    Returns:
        dict: ``{question: vector}``, or ``{}`` when no embedder is reachable
        or embedding fails — in which case every store embeds its own query,
        exactly as before.
    """
    embedder = store_embeddings(docsearch)
    if embedder is None:
        return {}
    try:
        return {
            question: embedder.embed_query(question)
            for question in dict.fromkeys(questions)
        }
    except Exception as e:
        logger.warning(
            "Query embedding failed (%s); each store will embed its own.", e
        )
        return {}


def run_source_jobs(
    fn: Callable[[Job], Result],
    jobs: Iterable[Job],
    workers: Optional[int] = None,
) -> List[Result]:
    """Run one job per source, concurrently when there are several.

    Args:
        fn: Per-source callable; it must swallow its own errors, since a raise
            here aborts the whole fan-out.
        jobs: Job payloads, in source order.
        workers: Pool size; defaults to :func:`max_parallel_sources`.

    Returns:
        list: ``fn`` results in the original job order, so the caller's merge
        stays deterministic no matter which source finishes first.
    """
    jobs = list(jobs)
    if not jobs:
        return []
    if workers is None:
        workers = max_parallel_sources(len(jobs))
    if workers == 1:
        return [fn(job) for job in jobs]
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="rag-source"
    ) as pool:
        return list(pool.map(fn, jobs))
