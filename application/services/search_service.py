"""Shared retrieval service used by the HTTP search route and the MCP tool.

Flask-free. Raises domain exceptions (``InvalidAPIKey``, ``SearchFailed``)
that callers translate into their own wire protocol (HTTP status codes,
MCP error responses, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from application.core.settings import settings
from application.retriever.fanout import embed_questions, run_source_jobs
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.session import db_readonly
from application.vectorstore.vector_creator import VectorCreator

logger = logging.getLogger(__name__)


class InvalidAPIKey(Exception):
    """The supplied ``api_key`` does not resolve to an agent."""


class SearchFailed(Exception):
    """Unexpected error during retrieval (e.g. DB outage). Caller maps to 5xx."""


def _collect_source_ids(agent: Dict[str, Any]) -> List[str]:
    """Extract the ordered list of source UUIDs to search.

    Prefers ``extra_source_ids`` (PG ARRAY(UUID) of multi-source agents);
    falls back to the legacy single ``source_id`` field.
    """
    source_ids: List[str] = []
    extra = agent.get("extra_source_ids") or []
    for src in extra:
        if src:
            source_ids.append(str(src))
    if not source_ids:
        single = agent.get("source_id")
        if single:
            source_ids.append(str(single))
    return source_ids


def _authorized_source_ids(conn, agent: Dict[str, Any], source_ids: List[str]) -> List[str]:
    """Drop source ids the agent's owner may not read.

    ``_collect_source_ids`` trusts whatever the agent row carries, and this
    service searches those ids directly. That made it the second half of a
    real disclosure: ``/api/share`` resolved a client-supplied source with no
    ownership predicate and baked it into the agent it created, after which
    this path returned another tenant's documents. The share route is fixed,
    but a row written before that — or by any future write path with the same
    gap — is still live here, so re-resolve against the owner rather than
    trusting the stored value.

    Args:
        conn: Open read connection.
        agent: The agent row resolved from the API key.
        source_ids: Ids extracted from that row.

    Returns:
        list: The subset the agent's owner may read.
    """
    owner = agent.get("user_id")
    if not owner:
        logger.warning("Agent %s has no owner; refusing to search its sources.", agent.get("id"))
        return []

    from application.api.user.team_sharing import can_access

    allowed = []
    for sid in source_ids:
        try:
            permitted = can_access(conn, "source", str(sid), owner)
        except Exception:
            # Fail closed, matching the answer path.
            logger.warning("Access check failed for source %s; dropping it.", sid)
            continue
        if permitted:
            allowed.append(sid)
        else:
            logger.warning(
                "Agent %s references source %s its owner %s cannot read; dropping it.",
                agent.get("id"), sid, owner,
            )
    return allowed


def _search_one(
    source_id: str,
    docsearch: Any,
    query: str,
    k: int,
    query_vector: Optional[List[float]],
) -> Optional[List[Any]]:
    """Search one source, returning its hits or ``None`` when it fails.

    Builds the vector store when not supplied, so each worker thread owns its
    own store instance (and therefore its own DB connection). Errors are logged
    and reported as ``None`` so one broken index cannot take the rest down.
    """
    try:
        if docsearch is None:
            docsearch = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
            )
        search_kwargs: Dict[str, Any] = {"k": k}
        if query_vector is not None:
            search_kwargs["query_vector"] = query_vector
        return docsearch.search(query, **search_kwargs)
    except Exception as e:
        logger.error(
            f"Error searching vectorstore {source_id}: {e}",
            exc_info=True,
        )
        return None


def _fetch_sources(
    query: str, source_ids: List[str], k: int
) -> List[Optional[List[Any]]]:
    """Fetch every source's hits: one query embedding, one bounded fan-out.

    The first store is built on the calling thread because its embeddings
    object supplies the shared query vector — and priming the embeddings
    singleton there keeps the workers off a concurrent model load. Results come
    back in the original source order so the merge stays deterministic.
    """

    def _job(job) -> Optional[List[Any]]:
        source_id, docsearch, query_vector = job
        return _search_one(source_id, docsearch, query, k, query_vector)

    first_store = None
    try:
        first_store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE, source_ids[0], settings.EMBEDDINGS_KEY
        )
    except Exception as e:
        logger.error(
            f"Error searching vectorstore {source_ids[0]}: {e}",
            exc_info=True,
        )

    if first_store is None:
        # The first source is already a logged failure; the rest still run,
        # each embedding its own query (there is no store to borrow one from).
        return [None] + run_source_jobs(
            _job, [(sid, None, None) for sid in source_ids[1:]]
        )

    vector = embed_questions(first_store, [query]).get(query)
    return run_source_jobs(
        _job,
        [
            (sid, first_store if idx == 0 else None, vector)
            for idx, sid in enumerate(source_ids)
        ],
    )


def _search_sources(
    query: str, source_ids: List[str], chunks: int
) -> List[Dict[str, Any]]:
    """Search across each source's vectorstore and return up to ``chunks`` hits.

    Per-source errors are logged and skipped so one broken index doesn't
    take down the whole search. Results are de-duplicated by content hash.
    """
    if chunks <= 0 or not source_ids:
        return []

    results: List[Dict[str, Any]] = []
    # Blank ids build no store but still count here, so the per-source budget
    # matches what the serial implementation handed each real source.
    chunks_per_source = max(1, chunks // len(source_ids))
    seen_texts: set[int] = set()

    active_ids = [sid for sid in source_ids if sid and sid.strip()]
    if not active_ids:
        return []

    # Fetch every source up front, then merge serially in source order so the
    # dedupe / cap semantics are exactly what they were.
    fetched = _fetch_sources(query, active_ids, chunks_per_source * 2)

    for source_id, docs in zip(active_ids, fetched):
        if docs is None:
            continue

        try:
            for doc in docs:
                if len(results) >= chunks:
                    break

                if hasattr(doc, "page_content") and hasattr(doc, "metadata"):
                    page_content = doc.page_content
                    metadata = doc.metadata
                else:
                    page_content = doc.get("text", doc.get("page_content", ""))
                    metadata = doc.get("metadata", {})

                text_hash = hash(page_content[:200])
                if text_hash in seen_texts:
                    continue
                seen_texts.add(text_hash)

                title = metadata.get("title", metadata.get("post_title", ""))
                if not isinstance(title, str):
                    title = str(title) if title else ""

                if title:
                    title = title.split("/")[-1]
                else:
                    title = metadata.get("filename", page_content[:50] + "...")

                source = metadata.get("source", source_id)

                results.append(
                    {
                        "text": page_content,
                        "title": title,
                        "source": source,
                    }
                )

            if len(results) >= chunks:
                break

        except Exception as e:
            logger.error(
                f"Error searching vectorstore {source_id}: {e}",
                exc_info=True,
            )
            continue

    return results[:chunks]


def search(api_key: str, query: str, chunks: int = 5) -> List[Dict[str, Any]]:
    """Resolve an agent by API key and search its sources.

    Args:
        api_key: Agent API key (the opaque string stored on
            ``agents.key`` in Postgres).
        query: Free-text search query.
        chunks: Max number of hits to return.

    Returns:
        List of hit dicts with ``text``, ``title``, ``source`` keys.
        Empty list if the agent has no sources configured.

    Raises:
        InvalidAPIKey: if ``api_key`` does not resolve to an agent.
        SearchFailed: on unexpected DB / infrastructure errors.
    """
    if chunks <= 0:
        return []

    try:
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
            if not agent:
                raise InvalidAPIKey()
            # Authorize inside the same connection the agent was read on.
            source_ids = _authorized_source_ids(
                conn, agent, _collect_source_ids(agent)
            )
    except InvalidAPIKey:
        raise
    except Exception as e:
        raise SearchFailed("agent lookup failed") from e

    if not source_ids:
        return []

    return _search_sources(query, source_ids, chunks)
