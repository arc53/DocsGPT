import os
import logging
from typing import Any, List, Optional
from retry import retry
from tqdm import tqdm
from application.core.settings import settings
from application.events.publisher import publish_user_event
from application.storage.db.repositories.ingest_chunk_progress import (
    IngestChunkProgressRepository,
)
from application.storage.db.session import db_session
from application.vectorstore.vector_creator import VectorCreator


class EmbeddingPipelineError(Exception):
    """Raised when the per-chunk embed loop produces a partial index.

    Escapes into Celery's ``autoretry_for`` so a transient cause (rate
    limit, network blip) gets another shot. The chunk-progress
    checkpoint makes retries cheap — only the failed-and-after chunks
    re-run. After ``MAX_TASK_ATTEMPTS`` the poison-loop guard in
    ``with_idempotency`` finalises the row as ``failed``.
    """


def sanitize_content(content: str) -> str:
    """
    Remove NUL characters that can cause vector store ingestion to fail.
    
    Args:
        content (str): Raw content that may contain NUL characters
        
    Returns:
        str: Sanitized content with NUL characters removed
    """
    if not content:
        return content
    return content.replace('\x00', '')


# Per-chunk inline retry. Aggressive defaults (tries=10, delay=60) blocked
# the loop for up to 9 min per chunk and wedged the heartbeat: lower the
# tail so a transient failure fails-fast and the chunk-progress checkpoint
# resumes cleanly on next dispatch.
@retry(tries=3, delay=5, backoff=2)
def add_text_to_store_with_retry(store: Any, doc: Any, source_id: str) -> None:
    """Add a document's text and metadata to the vector store with retry logic.
    
    Args:
        store: The vector store object.
        doc: The document to be added.
        source_id: Unique identifier for the source.
        
    Raises:
        Exception: If document addition fails after all retry attempts.
    """
    try:
        # Sanitize content to remove NUL characters that cause ingestion failures
        doc.page_content = sanitize_content(doc.page_content)
        
        doc.metadata["source_id"] = str(source_id)
        store.add_texts([doc.page_content], metadatas=[doc.metadata])
    except Exception as e:
        logging.error(f"Failed to add document with retry: {e}", exc_info=True)
        raise


def _init_progress_and_resume_index(
    source_id: str, total_chunks: int, attempt_id: Optional[str],
) -> int:
    """Upsert the progress row and return the next chunk index to embed.

    The repository's upsert preserves ``last_index`` only when the
    incoming ``attempt_id`` matches the stored one (a Celery autoretry
    of the same task). On a fresh attempt — including any caller that
    doesn't pass an ``attempt_id``, e.g. legacy code or tests — the
    row's checkpoint is reset so the loop starts from chunk 0. This
    is what prevents a completed checkpoint from any prior run
    silently no-op'ing the next sync/reingest.

    Best-effort: a DB outage falls back to ``0`` (fresh run from
    chunk 0). The embed loop's own re-raise still ensures partial
    runs don't get cached as complete.
    """
    try:
        with db_session() as conn:
            progress = IngestChunkProgressRepository(conn).init_progress(
                source_id, total_chunks, attempt_id,
            )
    except Exception as e:
        logging.warning(
            f"Could not init ingest progress for {source_id}: {e}",
            exc_info=True,
        )
        return 0
    if not progress:
        return 0
    last_index = progress.get("last_index", -1)
    if last_index is None or last_index < 0:
        return 0
    return int(last_index) + 1


def _record_progress(source_id: str, last_index: int, embedded_chunks: int) -> None:
    """Best-effort checkpoint after each chunk; logged but never raised."""
    try:
        with db_session() as conn:
            IngestChunkProgressRepository(conn).record_chunk(
                source_id, last_index=last_index, embedded_chunks=embedded_chunks
            )
    except Exception as e:
        logging.warning(
            f"Could not record ingest progress for {source_id}: {e}", exc_info=True
        )


def assert_index_complete(source_id: str) -> None:
    """Raise ``EmbeddingPipelineError`` if ``ingest_chunk_progress``
    shows a partial embed for ``source_id``.

    Defense-in-depth tripwire that workers run after
    ``embed_and_store_documents`` to catch any future swallow path
    that bypasses the function's own re-raise — the chunk-progress
    row is the authoritative record of how many chunks landed.
    No-op when no row exists (zero-doc validation raised before init,
    or progress repo was unreachable).
    """
    try:
        with db_session() as conn:
            progress = IngestChunkProgressRepository(conn).get_progress(source_id)
    except Exception as e:
        logging.warning(
            f"assert_index_complete: progress lookup failed for "
            f"{source_id}: {e}",
            exc_info=True,
        )
        return
    if not progress:
        return
    embedded = int(progress.get("embedded_chunks") or 0)
    total = int(progress.get("total_chunks") or 0)
    if embedded < total:
        raise EmbeddingPipelineError(
            f"partial index for source {source_id}: "
            f"{embedded}/{total} chunks embedded"
        )


def embed_and_store_documents(
    docs: List[Any],
    folder_name: str,
    source_id: str,
    task_status: Any,
    *,
    attempt_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Embeds documents and stores them in a vector store.

    Resumable across Celery autoretries of the *same* task: when
    ``attempt_id`` matches the stored checkpoint's ``attempt_id``,
    the loop resumes from ``last_index + 1``. A different
    ``attempt_id`` (a fresh sync / reingest invocation) resets the
    checkpoint so the index is rebuilt from chunk 0 — this is what
    keeps a completed checkpoint from poisoning the next sync.

    Args:
        docs: List of documents to be embedded and stored.
        folder_name: Directory to save the vector store.
        source_id: Unique identifier for the source.
        task_status: Task state manager for progress updates.
        attempt_id: Stable id of the current task invocation,
            typically ``self.request.id`` from the Celery task body.
            ``None`` is treated as a fresh attempt every time.
        user_id: When provided, per-percent SSE progress events are
            published to ``user:{user_id}`` for the in-app upload toast.
            ``None`` is the safe default — workers without a user
            context (e.g. background syncs) skip the publish.

    Returns:
        None

    Raises:
        OSError: If unable to create folder or save vector store.
        EmbeddingPipelineError: If a chunk fails after retries.
    """
    # Ensure the folder exists
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    # Validate docs is not empty
    if not docs:
        raise ValueError("No documents to embed - check file format and extension")

    total_docs = len(docs)
    # Atomic upsert that preserves checkpoint state on attempt-id match
    # (autoretry of same task) and resets it on mismatch (fresh sync /
    # reingest). Returns the new resume index — 0 means "start fresh".
    resume_index = _init_progress_and_resume_index(
        source_id, total_docs, attempt_id,
    )
    is_resume = resume_index > 0

    # Initialize vector store
    if settings.VECTOR_STORE == "faiss":
        if is_resume:
            # Load the existing FAISS index from storage so chunks
            # already embedded by the prior attempt survive the
            # save_local rewrite at the end of this run.
            store = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE,
                source_id=source_id,
                embeddings_key=os.getenv("EMBEDDINGS_KEY"),
            )
            loop_start = resume_index
        else:
            # FAISS requires at least one doc to construct the store;
            # seed with ``docs[0]`` and let the loop pick up at index 1.
            store = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE,
                docs_init=[docs[0]],
                source_id=source_id,
                embeddings_key=os.getenv("EMBEDDINGS_KEY"),
            )
            # Record the seeded chunk so single-doc ingests don't fail
            # ``assert_index_complete`` — the loop never runs for
            # ``total_docs == 1`` and would otherwise leave
            # ``embedded_chunks`` at 0 / ``last_index`` at -1. The loop
            # body's per-iteration ``_record_progress`` overshoots
            # correctly for multi-chunk runs (counts seed + iterations),
            # so writing this checkpoint up-front is a no-op for those.
            _record_progress(source_id, last_index=0, embedded_chunks=1)
            loop_start = 1
    else:
        store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE,
            source_id=source_id,
            embeddings_key=os.getenv("EMBEDDINGS_KEY"),
        )
        # Only wipe the index on a fresh run — a resume must keep the
        # chunks that earlier attempts already embedded.
        if not is_resume:
            store.delete_index()
        loop_start = resume_index

    if is_resume and loop_start >= total_docs:
        # Nothing left to do; the loop runs zero iterations and
        # downstream finalize logic still executes. This is only
        # reachable on a same-attempt retry of a task whose previous
        # attempt finished — typically a Celery acks_late redelivery
        # after the task already returned. The ``assert_index_complete``
        # tripwire still validates ``embedded == total`` afterwards.
        loop_start = total_docs

    # Process and embed documents
    chunk_error: Exception | None = None
    failed_idx: int | None = None
    last_published_pct = -1
    source_id_str = str(source_id)
    for idx in tqdm(
        range(loop_start, total_docs),
        desc="Embedding 🦖",
        unit="docs",
        total=total_docs - loop_start,
        bar_format="{l_bar}{bar}| Time Left: {remaining}",
    ):
        doc = docs[idx]
        try:
            # Update task status for progress tracking
            progress = int(((idx + 1) / total_docs) * 100)
            task_status.update_state(state="PROGRESS", meta={"current": progress})

            # SSE push for sub-second upload-toast updates. Throttled to one
            # event per percent so a 10k-chunk ingest emits ~100 events,
            # not 10k. The Celery update_state above stays the source of
            # truth for the polling-fallback path.
            if user_id and progress > last_published_pct:
                publish_user_event(
                    user_id,
                    "source.ingest.progress",
                    {
                        "current": progress,
                        "total": total_docs,
                        "embedded_chunks": idx + 1,
                        "stage": "embedding",
                    },
                    scope={"kind": "source", "id": source_id_str},
                )
                last_published_pct = progress

            # Add document to vector store
            add_text_to_store_with_retry(store, doc, source_id)
            _record_progress(source_id, last_index=idx, embedded_chunks=idx + 1)
        except Exception as e:
            chunk_error = e
            failed_idx = idx
            logging.error(f"Error embedding document {idx}: {e}", exc_info=True)
            logging.info(f"Saving progress at document {idx} out of {total_docs}")
            try:
                store.save_local(folder_name)
                logging.info("Progress saved successfully")
            except Exception as save_error:
                logging.error(f"CRITICAL: Failed to save progress: {save_error}", exc_info=True)
                # Continue without breaking to attempt final save
            break

    # Save the vector store
    if settings.VECTOR_STORE == "faiss":
        try:
            store.save_local(folder_name)
            logging.info("Vector store saved successfully.")
        except Exception as e:
            logging.error(f"CRITICAL: Failed to save final vector store: {e}", exc_info=True)
            raise OSError(f"Unable to save vector store to {folder_name}: {e}") from e
    else:
        logging.info("Vector store saved successfully.")

    # Re-raise after the partial save: the chunks that *did* embed are
    # flushed to disk and recorded in ``ingest_chunk_progress``, so a
    # Celery autoretry resumes via ``_read_resume_index`` and only
    # re-runs the failed-and-after chunks. Without the raise, the
    # task body returns success and ``with_idempotency`` finalises
    # ``task_dedup`` as ``completed`` for a partial index — poisoning
    # the cache for 24h.
    if chunk_error is not None:
        raise EmbeddingPipelineError(
            f"embed failure at chunk {failed_idx}/{total_docs} "
            f"for source {source_id}"
        ) from chunk_error
