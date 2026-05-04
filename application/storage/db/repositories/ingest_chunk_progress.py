"""Repository for ``ingest_chunk_progress``; per-source resume + heartbeat."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class IngestChunkProgressRepository:
    """Read/write helpers for ``ingest_chunk_progress``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def init_progress(
        self,
        source_id: str,
        total_chunks: int,
        attempt_id: Optional[str] = None,
    ) -> dict:
        """Upsert the progress row, scoped by ``attempt_id``.

        On conflict the upsert distinguishes two cases:

        - **Same attempt** (``attempt_id`` matches the stored value):
          this is a Celery autoretry of the same task — preserve
          ``last_index`` / ``embedded_chunks`` so the embed loop resumes
          from the checkpoint. Only ``total_chunks`` and
          ``last_updated`` get refreshed.
        - **Different attempt** (a fresh invocation: manual reingest,
          scheduled sync, or any caller that didn't pass an
          ``attempt_id``): reset ``last_index`` to ``-1`` and
          ``embedded_chunks`` to ``0`` so the loop starts from chunk 0.
          This prevents a completed checkpoint from any prior run
          poisoning the index.

        ``IS NOT DISTINCT FROM`` treats two NULLs as equal — so legacy
        rows with NULL ``attempt_id`` resume against another NULL
        caller (e.g. test fixtures), but get reset the moment a real
        ``attempt_id`` arrives.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO ingest_chunk_progress (
                    source_id, total_chunks, embedded_chunks, last_index,
                    attempt_id, last_updated
                )
                VALUES (
                    CAST(:source_id AS uuid), :total_chunks, 0, -1,
                    :attempt_id, now()
                )
                ON CONFLICT (source_id) DO UPDATE SET
                    total_chunks = EXCLUDED.total_chunks,
                    last_updated = now(),
                    last_index = CASE
                        WHEN ingest_chunk_progress.attempt_id
                             IS NOT DISTINCT FROM EXCLUDED.attempt_id
                        THEN ingest_chunk_progress.last_index
                        ELSE -1
                    END,
                    embedded_chunks = CASE
                        WHEN ingest_chunk_progress.attempt_id
                             IS NOT DISTINCT FROM EXCLUDED.attempt_id
                        THEN ingest_chunk_progress.embedded_chunks
                        ELSE 0
                    END,
                    attempt_id = EXCLUDED.attempt_id
                RETURNING *
                """
            ),
            {
                "source_id": str(source_id),
                "total_chunks": int(total_chunks),
                "attempt_id": attempt_id,
            },
        )
        return row_to_dict(result.fetchone())

    def record_chunk(
        self, source_id: str, last_index: int, embedded_chunks: int
    ) -> None:
        """Persist progress after a chunk is embedded."""
        self._conn.execute(
            text(
                """
                UPDATE ingest_chunk_progress
                SET last_index = :last_index,
                    embedded_chunks = :embedded_chunks,
                    last_updated = now()
                WHERE source_id = CAST(:source_id AS uuid)
                """
            ),
            {
                "source_id": str(source_id),
                "last_index": int(last_index),
                "embedded_chunks": int(embedded_chunks),
            },
        )

    def get_progress(self, source_id: str) -> Optional[dict]:
        """Return the progress row for ``source_id`` if it exists."""
        result = self._conn.execute(
            text(
                "SELECT * FROM ingest_chunk_progress "
                "WHERE source_id = CAST(:source_id AS uuid)"
            ),
            {"source_id": str(source_id)},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def bump_heartbeat(self, source_id: str) -> None:
        """Refresh ``last_updated`` so the row looks alive to the reconciler."""
        self._conn.execute(
            text(
                """
                UPDATE ingest_chunk_progress
                SET last_updated = now()
                WHERE source_id = CAST(:source_id AS uuid)
                """
            ),
            {"source_id": str(source_id)},
        )
