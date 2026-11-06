"""Deleting the vectors of ingests that ended without a source, and reporting them.

An ingest writes chunks to the vector store as it goes and saves its
``sources`` row only at the end. One that fails, stalls past its resumes, or
stops between the last chunk and the save leaves vectors no query can reach.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import Connection, text

from docsgpt.core.settings import settings
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.engine import get_engine
from docsgpt.storage.db.repositories.ingest_chunk_progress import IngestChunkProgressRepository

logger = logging.getLogger(__name__)

# Orphans handled per run; the rest wait for the next hour.
ORPHAN_SWEEP_LIMIT = 100
# Vectors per delete, so a large orphan never holds one long transaction.
PURGE_BATCH_SIZE = 1000


def _purge_vectors(source_id: str) -> int:
    """Delete a source's vectors through the store; return how many, when the store says.

    FAISS writes an index to storage only with the source itself, so an
    orphan has none there.

    Args:
        source_id: The orphaned source id.

    Returns:
        Vectors deleted (``0`` when unknown or none).
    """
    if settings.VECTOR_STORE == "faiss":
        return 0
    from docsgpt.vectorstore.vector_creator import VectorCreator

    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE, source_id=source_id, embeddings_key=settings.EMBEDDINGS_KEY,
    )
    try:
        return int(store.purge_index(batch_size=PURGE_BATCH_SIZE) or 0)
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()


def sweep_orphaned_ingests(limit: int = ORPHAN_SWEEP_LIMIT) -> Dict[str, Any]:
    """Delete the vectors and progress row of each ingest orphaned past ``INGEST_ORPHAN_TTL_HOURS``.

    Each orphan is handled in its own transaction holding its progress row:
    the row is re-checked under the lock, its vectors deleted in batches,
    then the row deleted. A failure leaves the row for the next run. Only
    rows the reconciler is done with qualify (see ``list_orphans``), so a
    resumable ingest is never swept.

    Args:
        limit: Most orphans to handle in this run.

    Returns:
        Counts of orphans deleted, vectors deleted and failures.
    """
    summary: Dict[str, Any] = {"orphans_deleted": 0, "vectors_deleted": 0, "failed": 0}
    if not settings.POSTGRES_URI:
        return {**summary, "skipped": "POSTGRES_URI not set"}
    ttl = int(settings.INGEST_ORPHAN_TTL_HOURS)
    if ttl <= 0:
        return {**summary, "skipped": "INGEST_ORPHAN_TTL_HOURS is 0"}

    engine = get_engine()
    with engine.begin() as conn:
        candidates = IngestChunkProgressRepository(conn).list_orphans(ttl, limit)
    for candidate in candidates:
        source_id = str(candidate["source_id"])
        try:
            with engine.begin() as conn:
                repo = IngestChunkProgressRepository(conn)
                row = repo.lock_orphan(source_id, ttl)
                if row is None:
                    continue
                deleted = _purge_vectors(source_id)
                repo.delete(source_id)
        except Exception:
            summary["failed"] += 1
            logger.exception("Could not delete the vectors of orphaned ingest %s", source_id)
            continue
        summary["orphans_deleted"] += 1
        summary["vectors_deleted"] += deleted
        logger.info(
            "Deleted the vectors of orphaned ingest %s", source_id,
            extra={
                "source_id": source_id,
                "vectors_deleted": deleted,
                "status": row.get("status"),
                "last_updated": str(row.get("last_updated")),
            },
        )
    return summary


def _known_source_ids(conn: Connection, ids: List[str]) -> set[str]:
    """The ids among ``ids`` a ``sources`` row owns, by id or by legacy Mongo id."""
    if not ids:
        return set()
    result = conn.execute(
        text(
            """
            SELECT id::text FROM sources WHERE id = ANY(CAST(:uuids AS uuid[]))
            UNION
            SELECT legacy_mongo_id FROM sources WHERE legacy_mongo_id = ANY(:ids)
            """
        ),
        {"uuids": [i for i in ids if looks_like_uuid(i)], "ids": ids},
    )
    return {row[0] for row in result.fetchall()}


def _report_row(source_id: str, vectors: Optional[int], progress: Optional[dict]) -> Dict[str, Any]:
    """One report line: the source id, its vector count and its ingest's state."""
    return {
        "source_id": source_id,
        "vectors": vectors,
        "status": (progress or {}).get("status"),
        "last_updated": (progress or {}).get("last_updated"),
        "swept": bool((progress or {}).get("swept")),
    }


def orphan_report(conn: Connection) -> List[Dict[str, Any]]:
    """Sources with vectors but no ``sources`` row, and whether the sweep will delete them.

    On pgvector, every source id in the vectors table that no source owns,
    with its chunk count: those without a progress row are never swept and
    need deleting by hand. On other stores, counting is not cheap, so only
    the progress rows without a source are listed, with no count.

    Args:
        conn: A connection to the application database.

    Returns:
        Report rows: ``source_id``, ``vectors``, ``status``, ``last_updated``, ``swept``.
    """
    ttl = int(settings.INGEST_ORPHAN_TTL_HOURS)
    repo = IngestChunkProgressRepository(conn)
    if settings.VECTOR_STORE != "pgvector":
        return [_report_row(str(row["source_id"]), None, row) for row in repo.without_source(ttl)]

    from docsgpt.vectorstore import pgvector

    counts = pgvector.chunk_counts_by_source()
    known = _known_source_ids(conn, list(counts))
    orphans = [source_id for source_id in counts if source_id not in known]
    progress = {
        str(row["source_id"]): row
        for row in repo.without_source(ttl, [i for i in orphans if looks_like_uuid(i)])
    }
    return [_report_row(source_id, counts[source_id], progress.get(source_id)) for source_id in orphans]


def orphan_report_now() -> List[Dict[str, Any]]:
    """:func:`orphan_report` on a read-only connection of its own."""
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        return orphan_report(conn)
