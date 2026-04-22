"""Shared retrieval service used by the HTTP search route and the MCP tool.

Flask-free. Raises domain exceptions (``InvalidAPIKey``, ``SearchFailed``)
that callers translate into their own wire protocol (HTTP status codes,
MCP error responses, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from application.core.settings import settings
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


def _search_sources(
    query: str, source_ids: List[str], chunks: int
) -> List[Dict[str, Any]]:
    """Search across each source's vectorstore and return up to ``chunks`` hits.

    Per-source errors are logged and skipped so one broken index doesn't
    take down the whole search. Results are de-duplicated by content hash.
    """
    if not source_ids:
        return []

    results: List[Dict[str, Any]] = []
    chunks_per_source = max(1, chunks // len(source_ids))
    seen_texts: set[int] = set()

    for source_id in source_ids:
        if not source_id or not source_id.strip():
            continue

        try:
            docsearch = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
            )
            docs = docsearch.search(query, k=chunks_per_source * 2)

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
    try:
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
    except Exception as e:
        raise SearchFailed("agent lookup failed") from e

    if not agent:
        raise InvalidAPIKey()

    source_ids = _collect_source_ids(agent)
    if not source_ids:
        return []

    return _search_sources(query, source_ids, chunks)
