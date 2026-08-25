import os
import logging
from typing import Any, List, Optional
from retry import retry
from tqdm import tqdm
from application.core.settings import settings
from application.events.publisher import publish_user_event
from application.parser.file.base_parser import DocumentParseError
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


# Fallback when ``settings.EMBEDDINGS_BATCH_SIZE`` is unset or unusable.
DEFAULT_EMBEDDINGS_BATCH_SIZE = 32


def _resolve_batch_size() -> int:
    """Read ``EMBEDDINGS_BATCH_SIZE``, falling back to the default.

    Tolerates a missing, ``None`` or non-numeric setting (tests patch
    ``settings`` with a ``MagicMock``) so a misconfiguration degrades to
    the default batch rather than breaking ingest.

    Returns:
        Chunks per embed request, always >= 1.
    """
    raw = getattr(settings, "EMBEDDINGS_BATCH_SIZE", None)
    # Explicit type check rather than a bare ``int(raw)``: ``int(MagicMock())``
    # succeeds and yields 1, which would silently drop ingest back to the
    # per-chunk behaviour this batching replaces.
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return DEFAULT_EMBEDDINGS_BATCH_SIZE
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_EMBEDDINGS_BATCH_SIZE
    return max(1, size)


# Per-batch inline retry. Aggressive defaults (tries=10, delay=60) blocked
# the loop for up to 9 min per chunk and wedged the heartbeat: lower the
# tail so a transient failure fails-fast and the chunk-progress checkpoint
# resumes cleanly on next dispatch.
@retry(tries=3, delay=5, backoff=2)
def add_texts_to_store_with_retry(
    store: Any, docs: List[Any], source_id: str
) -> None:
    """Add a batch of documents to the vector store with retry logic.

    One call per batch replaces one call per chunk: the remote embeddings
    API accepts a list, and the store writes the whole batch in a single
    transaction, so this collapses N HTTP round-trips and N INSERTs into
    one of each. Safe to retry — ``add_texts`` embeds before it inserts
    and rolls back on failure, so a failed batch writes nothing.

    Args:
        store: The vector store object.
        docs: The documents to be added.
        source_id: Unique identifier for the source.

    Raises:
        Exception: If the batch fails after all retry attempts.
    """
    if not docs:
        return
    try:
        texts: List[str] = []
        metadatas: List[Any] = []
        for doc in docs:
            # Sanitize content to remove NUL characters that cause ingestion failures
            doc.page_content = sanitize_content(doc.page_content)
            doc.metadata["source_id"] = str(source_id)
            texts.append(doc.page_content)
            metadatas.append(doc.metadata)
        store.add_texts(texts, metadatas=metadatas)
    except Exception as e:
        logging.error(
            f"Failed to add {len(docs)} document(s) with retry: {e}", exc_info=True
        )
        raise


def add_text_to_store_with_retry(store: Any, doc: Any, source_id: str) -> None:
    """Add a single document to the vector store with retry logic.

    Thin wrapper over :func:`add_texts_to_store_with_retry`, kept for the
    per-chunk fallback in the embed loop and for callers outside it.

    Args:
        store: The vector store object.
        doc: The document to be added.
        source_id: Unique identifier for the source.

    Raises:
        Exception: If document addition fails after all retry attempts.
    """
    add_texts_to_store_with_retry(store, [doc], source_id)


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


def _embed_batch_individually(
    store: Any,
    docs: List[Any],
    batch_start: int,
    batch_end: int,
    source_id: str,
) -> tuple[Exception | None, int | None]:
    """Re-run one failed batch a chunk at a time, checkpointing as it goes.

    Called only after a batch raised. Preserves the pre-batching failure
    contract: chunks before the offender are embedded and recorded, and the
    returned index is the exact chunk that failed rather than the batch head.

    Args:
        store: The vector store object.
        docs: The full chunk list.
        batch_start: Index of the first chunk in the failed batch.
        batch_end: Index one past the last chunk in the failed batch.
        source_id: Unique identifier for the source.

    Returns:
        ``(None, None)`` when every chunk succeeded on its own, else the
        exception and the index of the chunk that failed.
    """
    for idx in range(batch_start, batch_end):
        try:
            add_text_to_store_with_retry(store, docs[idx], source_id)
            _record_progress(source_id, last_index=idx, embedded_chunks=idx + 1)
        except Exception as e:
            return e, idx
    return None, None


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
    progress_start: int = 0,
    progress_end: int = 100,
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
        progress_start: Percent the reported progress maps to at chunk 0.
            Lets a caller reserve the lower band for an earlier stage
            (e.g. parsing). Defaults to ``0`` (embed owns the whole bar).
        progress_end: Percent the reported progress maps to at the final
            chunk. Defaults to ``100``.

    Returns:
        None

    Raises:
        OSError: If unable to create folder or save vector store.
        EmbeddingPipelineError: If a chunk fails after retries.
    """
    # Ensure the folder exists
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    # Drop blank documents before validating. A file that parses to nothing
    # (empty upload, whitespace-only, an image-only PDF with no OCR) used to
    # reach here as a one-element list of "" and ingest as a healthy source,
    # putting an embedding of the empty string into the index.
    docs = [
        d for d in docs
        if str(getattr(d, "text", getattr(d, "page_content", d)) or "").strip()
    ]
    if not docs:
        # ``DocumentParseError``, not ``ValueError``: an empty or image-only
        # file yields nothing on every attempt, so this must reach the Celery
        # tasks' ``dont_autoretry_for`` and fail once. As a bare ``ValueError``
        # it was swept up by ``autoretry_for=(Exception,)`` and re-failed
        # identically across the whole backoff envelope.
        raise DocumentParseError(
            "No text could be extracted from this file. It may be empty, "
            "image-only, or in an unsupported format."
        )

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

    # Process and embed documents, one batch per embed request. Progress is
    # checkpointed per batch rather than per chunk, so a 3k-chunk ingest
    # writes ~90 progress rows instead of 3k — the per-chunk bookkeeping
    # (Neon UPDATE + Celery update_state + SSE) dominated wall-clock more
    # than the embedding itself.
    chunk_error: Exception | None = None
    failed_idx: int | None = None
    last_published_pct = -1
    source_id_str = str(source_id)
    progress_span = progress_end - progress_start
    batch_size = _resolve_batch_size()
    batch_starts = list(range(loop_start, total_docs, batch_size))
    for batch_start in tqdm(
        batch_starts,
        desc="Embedding 🦖",
        unit="batch",
        total=len(batch_starts),
        bar_format="{l_bar}{bar}| Time Left: {remaining}",
    ):
        batch_end = min(batch_start + batch_size, total_docs)
        last_idx = batch_end - 1
        try:
            # Map the embed loop into [progress_start, progress_end].
            progress = progress_start + int(
                (batch_end / total_docs) * progress_span
            )
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
                        "embedded_chunks": batch_end,
                        "stage": "embedding",
                    },
                    scope={"kind": "source", "id": source_id_str},
                )
                last_published_pct = progress

            # Add the batch to the vector store
            add_texts_to_store_with_retry(
                store, docs[batch_start:batch_end], source_id
            )
            _record_progress(
                source_id, last_index=last_idx, embedded_chunks=batch_end
            )
        except Exception as batch_exc:
            # The batch failed as a unit and wrote nothing (``add_texts``
            # embeds before it inserts and rolls back). Re-run it one chunk
            # at a time so a single poison chunk — an oversized input the
            # embeddings server rejects — costs only itself: the chunks
            # before it still land and are checkpointed, and ``failed_idx``
            # names the real offender instead of the batch head.
            logging.warning(
                f"Batch embed failed for chunks {batch_start}-{last_idx} "
                f"({batch_exc}); retrying individually to isolate the failure"
            )
            chunk_error, failed_idx = _embed_batch_individually(
                store, docs, batch_start, batch_end, source_id
            )
            if chunk_error is None:
                # Every chunk passed on its own — the batch-level failure was
                # transient (or a payload-size limit). Progress is recorded.
                continue
            logging.error(
                f"Error embedding document {failed_idx}: {chunk_error}",
                exc_info=True,
            )
            logging.info(
                f"Saving progress at document {failed_idx} out of {total_docs}"
            )
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
