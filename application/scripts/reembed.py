"""Re-embed an existing index with the currently configured embedding model.

Changing ``EMBEDDINGS_NAME`` does not change vectors already stored. Because
several models share a width -- granite-311m and all-mpnet-base-v2 are both
768-dimensional -- a swapped model does not fail any dimension check. It simply
retrieves against vectors that mean something else, which shows up as bad
answers rather than as an error.

This script rebuilds the vectors from the chunk text already held in the store,
so it never re-downloads, re-parses or re-chunks anything: no source files, no
crawl, no docling. It works against pgvector and FAISS.

Usage::

    python -m application.scripts.reembed --dry-run     # report, change nothing
    python -m application.scripts.reembed               # re-embed everything
    python -m application.scripts.reembed --sources a,b # only these sources
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import sql

from application.core.settings import settings
from application.vectorstore.model_registry import resolve
from application.vectorstore.vector_creator import VectorCreator

logger = logging.getLogger("reembed")

#: Stores this script knows how to rewrite in place.
SUPPORTED_STORES = ("pgvector", "faiss")

#: Chunks embedded (and, for pgvector, written) per transaction.
DEFAULT_BATCH_SIZE = 64


@dataclass
class _RebuildDoc:
    """Minimal document shape ``FaissStore(docs_init=...)`` accepts."""

    page_content: str
    metadata: Dict[str, Any]


class ReembedError(RuntimeError):
    """Raised for a misconfiguration the user needs to fix before running."""


def _log_setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def list_source_ids(store_type: str) -> List[str]:
    """Every source id that has vectors in the configured store.

    Args:
        store_type: ``"pgvector"`` or ``"faiss"``.

    Returns:
        Source ids, sorted for a stable and resumable ordering.
    """
    if store_type == "pgvector":
        return _pgvector_source_ids()
    return _faiss_source_ids()


def _pgvector_source_ids() -> List[str]:
    store = VectorCreator.create_vectorstore("pgvector", source_id="")
    # ``_get_connection`` hands back a pooled connection, not a context
    # manager: closing it via ``with`` would cost the pool a slot.
    conn = store._get_connection()
    cursor = conn.cursor()
    try:
        # Table and column names cannot be bound as parameters, so they go
        # through ``sql.Identifier``, which quotes them. They are internal
        # constants rather than user input, but composing SQL by f-string is
        # the habit worth not having.
        cursor.execute(
            sql.SQL(
                "SELECT DISTINCT source_id FROM {table} "
                "WHERE source_id IS NOT NULL ORDER BY source_id"
            ).format(table=sql.Identifier(store._table_name))
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        store.close()


def _faiss_source_ids() -> List[str]:
    """Directories under the FAISS root that hold an index."""
    from application.storage.storage_creator import StorageCreator

    storage = StorageCreator.get_storage()
    root = "indexes"
    ids: List[str] = []
    try:
        for path in storage.list_files(root):
            # ``indexes/<source_id>/index.faiss``
            parts = str(path).split("/")
            if parts and parts[-1].endswith(".faiss") and len(parts) >= 2:
                ids.append(parts[-2])
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user below
        raise ReembedError(
            f"Could not list FAISS indexes under {root!r}: {exc}"
        ) from exc
    return sorted(set(ids))


def reembed_pgvector(source_id: str, batch_size: int, dry_run: bool) -> Tuple[int, int]:
    """Rewrite one source's vectors in place.

    Rows are updated, never deleted and re-inserted, so an interrupted run
    leaves every chunk present and simply re-does its batch next time.

    Args:
        source_id: Source whose chunks to re-embed.
        batch_size: Chunks per embed call and per transaction.
        dry_run: When true, count the work and change nothing.

    Returns:
        ``(chunks_seen, chunks_written)``.
    """
    store = VectorCreator.create_vectorstore("pgvector", source_id=source_id)
    table, vector_column = store._table_name, store._vector_column
    conn = store._get_connection()

    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL("SELECT id, text FROM {table} WHERE source_id = %s ORDER BY id").format(
                table=sql.Identifier(table)
            ),
            (source_id,),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()

    if dry_run or not rows:
        store.close()
        return len(rows), 0

    written = 0
    try:
        for batch in _batched(rows, batch_size):
            vectors = store._embedding.embed_documents([row[1] or "" for row in batch])
            cursor = conn.cursor()
            try:
                cursor.executemany(
                    sql.SQL(
                        "UPDATE {table} SET {column} = %s::vector WHERE id = %s"
                    ).format(
                        table=sql.Identifier(table),
                        column=sql.Identifier(vector_column),
                    ),
                    [
                        (str(list(vector)), row[0])
                        for vector, row in zip(vectors, batch)
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
            written += len(batch)
    finally:
        store.close()
    return len(rows), written


def reembed_faiss(source_id: str, batch_size: int, dry_run: bool) -> Tuple[int, int]:
    """Rebuild one FAISS index from the chunk text in its sidecar.

    A FAISS index is a flat array, so this rebuilds rather than updates. Every
    new vector is computed *before* the old index is touched, so an interrupt
    during embedding leaves the existing index intact.

    Args:
        source_id: Source whose index to rebuild.
        batch_size: Chunks per embed call.
        dry_run: When true, count the work and change nothing.

    Returns:
        ``(chunks_seen, chunks_written)``.
    """
    store = VectorCreator.create_vectorstore(
        "faiss", source_id=source_id, embeddings_key="embeddings"
    )
    chunks: List[Dict[str, Any]] = store.get_chunks() or []
    if dry_run or not chunks:
        return len(chunks), 0

    docs = [
        _RebuildDoc(chunk.get("text") or "", chunk.get("metadata") or {})
        for chunk in chunks
    ]

    # Constructing with ``docs_init`` embeds everything into a fresh in-memory
    # index and touches nothing on disk. The existing index is only replaced by
    # ``save_local`` below, so a failure while embedding leaves it intact.
    rebuilt = VectorCreator.create_vectorstore(
        "faiss", source_id=source_id, embeddings_key="embeddings", docs_init=docs
    )
    rebuilt.save_local()
    return len(chunks), len(docs)


def run(
    store_type: str,
    source_ids: Optional[Sequence[str]],
    batch_size: int,
    dry_run: bool,
) -> int:
    """Re-embed the requested sources. Returns a process exit code."""
    model = settings.EMBEDDINGS_NAME
    spec = resolve(model)
    logger.info(
        "Re-embedding %s with %s (%s)",
        store_type,
        model,
        f"{spec.dimension} dims" if spec else "width determined at runtime",
    )
    if dry_run:
        logger.info("Dry run: nothing will be written.")

    ids = list(source_ids) if source_ids else list_source_ids(store_type)
    if not ids:
        logger.warning("No sources found; nothing to do.")
        return 0
    logger.info("%d source(s) to process", len(ids))

    handler = reembed_pgvector if store_type == "pgvector" else reembed_faiss
    total_seen = total_written = 0
    failures: List[str] = []
    started = time.monotonic()

    for position, source_id in enumerate(ids, start=1):
        try:
            seen, written = handler(source_id, batch_size, dry_run)
            total_seen += seen
            total_written += written
            logger.info(
                "[%d/%d] %s: %d chunk(s)%s",
                position,
                len(ids),
                source_id,
                seen,
                "" if dry_run else f", {written} re-embedded",
            )
        except Exception as exc:  # noqa: BLE001 -- one bad source must not stop the run
            failures.append(source_id)
            logger.error("[%d/%d] %s FAILED: %s", position, len(ids), source_id, exc)

    elapsed = time.monotonic() - started
    logger.info(
        "Done in %.1fs: %d chunk(s) seen, %d re-embedded, %d source(s) failed",
        elapsed,
        total_seen,
        total_written,
        len(failures),
    )
    if failures:
        logger.error("Failed sources: %s", ", ".join(failures))
        logger.error("Re-run with --sources %s to retry just those.", ",".join(failures))
        return 1
    if dry_run:
        logger.info("Re-run without --dry-run to apply.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m application.scripts.reembed",
        description=__doc__.split("\n\n")[0],
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change, write nothing"
    )
    parser.add_argument(
        "--sources", help="comma-separated source ids; default is every source"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"chunks per embed call (default {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _log_setup(args.verbose)

    store_type = (settings.VECTOR_STORE or "").lower()
    if store_type not in SUPPORTED_STORES:
        logger.error(
            "VECTOR_STORE is %r; this script supports %s. For other stores, "
            "delete and re-ingest the affected sources.",
            settings.VECTOR_STORE,
            " and ".join(SUPPORTED_STORES),
        )
        return 2

    sources = (
        [s.strip() for s in args.sources.split(",") if s.strip()]
        if args.sources
        else None
    )
    try:
        return run(store_type, sources, max(1, args.batch_size), args.dry_run)
    except ReembedError as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
