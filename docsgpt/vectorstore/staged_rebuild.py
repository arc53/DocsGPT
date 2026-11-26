"""Full rebuilds that never leave a source's index empty or half-built.

A sync that can't edit a source's index file by file rebuilds it whole. In
place, that deletes the source's chunks first and embeds the new ones under
the same id, so for the hours a large source takes, a search finds part of it
or nothing. Where the vector store can swap one id's chunks for another's in
one step (``BaseVectorStore.supports_staged_rebuild``: pgvector), the rebuild
embeds under a staging id instead (:func:`staging_id`), and the source's
chunks are replaced only once every new one is stored
(:func:`promote_staged_index`). Until then searches read the old index; a
rebuild that fails leaves it as it was.

The staged chunks of a rebuild that failed stay under the staging id: the
next rebuild of the same chunks resumes from them (``ingest_chunk_progress``),
and a rebuild of other chunks clears them first. Deleting the source clears
them too (:func:`discard_staged_index`).

Other stores keep the in-place rebuild: FAISS needs nothing more (a rebuild
writes a new index file, stored whole when it is done), while MongoDB,
Qdrant, Milvus and Elasticsearch can't move chunks to another id in one step.
"""

from __future__ import annotations

import logging
from typing import Optional

from docsgpt.core.settings import settings
from docsgpt.storage.db.session import db_session
from docsgpt.vectorstore.base import StagedIndexIncomplete
from docsgpt.vectorstore.vector_creator import VectorCreator

logger = logging.getLogger(__name__)


_STAGING_SUFFIX = ":staging"


def staging_id(source_id: str) -> str:
    """The id a full rebuild of ``source_id`` embeds under until it is swapped in."""
    return f"{source_id}{_STAGING_SUFFIX}"


def owner_of(index_id: str) -> str:
    """The source an id in the vector store belongs to: itself, or the source a staging id rebuilds."""
    index_id = str(index_id)
    return index_id[: -len(_STAGING_SUFFIX)] if index_id.endswith(_STAGING_SUFFIX) else index_id


def staged_index_id(source_id: str) -> Optional[str]:
    """The staging id a full rebuild of ``source_id`` should embed under, or ``None`` to rebuild in place.

    Args:
        source_id: The source being rebuilt.

    Returns:
        :func:`staging_id` when the configured store can swap a staged index
        in (``VectorCreator.supports_staged_rebuild``), else ``None``.
    """
    if not VectorCreator.supports_staged_rebuild(settings.VECTOR_STORE):
        return None
    return staging_id(str(source_id))


def _close(store: object) -> None:
    close = getattr(store, "close", None)
    if callable(close):
        close()


def promote_staged_index(source_id: str, staged_id: str, expected: int) -> int:
    """Replace a source's chunks with the ones its rebuild embedded under ``staged_id``.

    Args:
        source_id: The source.
        staged_id: Its staging id (:func:`staged_index_id`).
        expected: How many chunks the rebuild embedded.

    Returns:
        The number of chunks moved in.

    Raises:
        StagedIndexIncomplete: The staging id holds another number of chunks;
            the live index is kept, and the staged chunks and the source's
            checkpoint are dropped so the next rebuild starts afresh rather
            than resume from them.
        Exception: Whatever the store raised; the live index is kept.
    """
    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE, source_id=str(source_id), embeddings_key=settings.EMBEDDINGS_KEY,
    )
    try:
        moved = store.promote_staged(staged_id, expected=expected)
    except StagedIndexIncomplete:
        logger.error("Not swapping in the rebuilt index of source %s: it is incomplete", source_id, exc_info=True)
        discard_staged_index(str(source_id))
        _forget_checkpoint(str(source_id))
        raise
    finally:
        _close(store)
    logger.info("Swapped the rebuilt index of source %s in: %s chunks", source_id, moved)
    return moved


def _forget_checkpoint(source_id: str) -> None:
    """Delete a source's ``ingest_chunk_progress`` row, so no rebuild resumes chunks that are gone. Never raises."""
    from docsgpt.storage.db.repositories.ingest_chunk_progress import IngestChunkProgressRepository

    try:
        with db_session() as conn:
            IngestChunkProgressRepository(conn).delete(source_id)
    except Exception as err:  # noqa: BLE001 - a resume then fails the same check again
        logger.warning(f"Could not delete the checkpoint of source {source_id}: {err}")


def discard_staged_index(source_id: str) -> None:
    """Delete the chunks a rebuild of ``source_id`` left under its staging id. Best effort: never raises.

    Args:
        source_id: The source (not its staging id).
    """
    staged = staged_index_id(str(source_id))
    if staged is None:
        return
    try:
        store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE, source_id=staged, embeddings_key=settings.EMBEDDINGS_KEY,
        )
        try:
            store.purge_index()
        finally:
            _close(store)
    except Exception as err:  # noqa: BLE001 - the next rebuild of the source clears them anyway
        logger.warning(f"Could not delete the staged chunks {staged}: {err}")
