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


def fetch_per_source(
    items: List[Job],
    build_store: Callable[[Job], Any],
    search: Callable[[Job, Optional[Any], Optional[List[float]]], Result],
    question_of: Callable[[Job], str],
    label_of: Callable[[Job], Any] = str,
    workers_for: Optional[Callable[[int], int]] = None,
) -> List[Optional[Result]]:
    """Search every source: one store built up front, one embedding, one fan-out.

    The first store is built on the calling thread because its embeddings
    object supplies the shared query vector — and priming the embeddings
    singleton there keeps the workers off a concurrent model load. The searches
    then run on a bounded pool, and results come back in the original source
    order so the caller's merge stays deterministic.

    Args:
        items: One entry per source, in the order results must come back.
        build_store: Builds the vector store for an item; may raise.
        search: ``(item, store_or_None, query_vector_or_None) -> result``. It
            must swallow its own errors and report failure as ``None``, since a
            raise here aborts the whole fan-out.
        question_of: The query for an item, used to look up its shared vector.
        label_of: Item identifier for the store-construction error log.
        workers_for: Pool size from the job count; defaults to
            :func:`max_parallel_sources`.

    Returns:
        list: One entry per item, in ``items`` order. ``None`` marks a source
        whose store could not be built or whose search reported failure.
    """
    items = list(items)
    if not items:
        return []

    def _dispatch(jobs: List[Any]) -> List[Optional[Result]]:
        if not jobs:
            return []
        workers = workers_for(len(jobs)) if workers_for is not None else None
        return run_source_jobs(lambda job: search(*job), jobs, workers=workers)

    first_store = None
    try:
        first_store = build_store(items[0])
    except Exception as e:
        logger.error(
            "Error searching vectorstore %s: %s", label_of(items[0]), e, exc_info=True
        )

    if first_store is None:
        # The first source is already a logged failure; the rest still run,
        # each embedding its own query (there is no store to borrow one from).
        return [None] + _dispatch([(item, None, None) for item in items[1:]])

    vectors = embed_questions(first_store, [question_of(item) for item in items])
    return _dispatch(
        [
            (item, first_store if idx == 0 else None, vectors.get(question_of(item)))
            for idx, item in enumerate(items)
        ]
    )
