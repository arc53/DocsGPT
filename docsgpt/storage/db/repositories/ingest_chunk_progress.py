"""Repository for ``ingest_chunk_progress``; per-source resume + heartbeat."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder


# An ingest whose vectors no source will ever own: no ``sources`` row, over
# (stalled for good, or embedded but the source never saved), and quiet for
# ``:ttl`` hours. An unfinished ``active`` row is the reconciler's to resume
# or stall first; a row with a source is never matched, so a source's own
# vectors (a sync or reingest reuses the source id) are never touched.
_ORPHAN = """(
    NOT EXISTS (SELECT 1 FROM sources s WHERE s.id = icp.source_id)
    AND (icp.status = 'stalled' OR icp.embedded_chunks >= icp.total_chunks)
    AND icp.last_updated < now() - make_interval(hours => :ttl)
)"""


class IngestChunkProgressRepository:
    """Read/write helpers for ``ingest_chunk_progress``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def init_progress(
        self,
        source_id: str,
        total_chunks: int,
        attempt_id: Optional[str] = None,
        *,
        fingerprint: Optional[str] = None,
        dispatch: Optional[dict] = None,
    ) -> dict:
        """Upsert the progress row; keep the checkpoint only for the same work.

        With a ``fingerprint`` on both sides, the checkpoint is kept when the
        chunk set is the same and either this is the same attempt (a Celery
        autoretry or redelivery) or the stored run did not finish (a new task
        resuming a killed ingest). A changed chunk set, or a finished run seen
        by a new attempt, resets ``last_index`` to ``-1`` so the loop starts
        from chunk 0 and a completed checkpoint never no-ops the next sync.

        Without a fingerprint on either side (FAISS, or rows written before
        fingerprints) the old rule holds: keep it on the same ``attempt_id``,
        where ``IS NOT DISTINCT FROM`` treats two NULLs as equal.

        ``resume_attempts`` survives only the same ``attempt_id``: the
        reconciler queues a resume under the original task id, so any other
        id is a new ingest and starts the count again. Every branch sets
        ``status`` back to ``'active'`` and stores this run's ``dispatch``.
        """
        same_attempt = "ingest_chunk_progress.attempt_id IS NOT DISTINCT FROM EXCLUDED.attempt_id"
        keep = f"""(CASE
            WHEN ingest_chunk_progress.chunk_fingerprint IS NULL
                 OR EXCLUDED.chunk_fingerprint IS NULL
            THEN {same_attempt}
            ELSE ingest_chunk_progress.chunk_fingerprint = EXCLUDED.chunk_fingerprint
                 AND ({same_attempt}
                      OR ingest_chunk_progress.embedded_chunks < ingest_chunk_progress.total_chunks)
        END)"""
        result = self._conn.execute(
            text(
                f"""
                INSERT INTO ingest_chunk_progress (
                    source_id, total_chunks, embedded_chunks, last_index,
                    attempt_id, chunk_fingerprint, dispatch, last_updated
                )
                VALUES (
                    CAST(:source_id AS uuid), :total_chunks, 0, -1,
                    :attempt_id, :fingerprint, CAST(:dispatch AS jsonb), now()
                )
                ON CONFLICT (source_id) DO UPDATE SET
                    total_chunks = EXCLUDED.total_chunks,
                    last_updated = now(),
                    last_index = CASE WHEN {keep}
                        THEN ingest_chunk_progress.last_index ELSE -1 END,
                    embedded_chunks = CASE WHEN {keep}
                        THEN ingest_chunk_progress.embedded_chunks ELSE 0 END,
                    resume_attempts = CASE WHEN {same_attempt}
                        THEN ingest_chunk_progress.resume_attempts ELSE 0 END,
                    attempt_id = EXCLUDED.attempt_id,
                    chunk_fingerprint = EXCLUDED.chunk_fingerprint,
                    dispatch = EXCLUDED.dispatch,
                    status = 'active'
                RETURNING *
                """
            ),
            {
                "source_id": str(source_id),
                "total_chunks": int(total_chunks),
                "attempt_id": attempt_id,
                "fingerprint": fingerprint,
                "dispatch": json.dumps(dispatch, cls=PGNativeJSONEncoder) if dispatch is not None else None,
            },
        )
        return row_to_dict(result.fetchone())

    def record_chunk(
        self, source_id: str, last_index: int, embedded_chunks: int
    ) -> None:
        """Persist progress after a chunk is embedded.

        Also sets ``status`` back to ``'active'``: an ingest that is still
        embedding is not stalled, though another ingest of the same source
        may have failed and closed the row (``mark_failed``) meanwhile. The
        last chunk drops ``dispatch``: a finished embed is never queued again.
        """
        self._conn.execute(
            text(
                """
                UPDATE ingest_chunk_progress
                SET last_index = :last_index,
                    embedded_chunks = :embedded_chunks,
                    status = 'active',
                    dispatch = CASE WHEN :embedded_chunks >= total_chunks
                        THEN NULL ELSE dispatch END,
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

    def delete(self, source_id: str) -> bool:
        """Delete the progress row for ``source_id``.

        A manual reingest supersedes any prior ingest state — including a
        reconciler ``'stalled'`` escalation — so dropping the row clears
        the derived ``failed`` ingest status the sources list shows.
        Returns ``True`` when a row was removed.
        """
        result = self._conn.execute(
            text(
                "DELETE FROM ingest_chunk_progress "
                "WHERE source_id = CAST(:source_id AS uuid)"
            ),
            {"source_id": str(source_id)},
        )
        return result.rowcount > 0

    def reopen(self, source_id: str) -> bool:
        """Reopen an unfinished checkpoint for a manual retry of its source.

        The row goes back to ``'active'`` with its checkpoint, so the retry
        resumes when it brings the same chunk set (see :meth:`init_progress`)
        and the sources list shows it in progress meanwhile. ``dispatch`` is
        dropped: the retry is a task of its own, not the one stored here.

        Args:
            source_id: The source being retried.

        Returns:
            ``True`` when an unfinished row was reopened; ``False`` when there
            is none, or it finished.
        """
        result = self._conn.execute(
            text(
                """
                UPDATE ingest_chunk_progress
                SET status = 'active', dispatch = NULL, last_updated = now()
                WHERE source_id = CAST(:source_id AS uuid)
                  AND embedded_chunks < total_chunks
                """
            ),
            {"source_id": str(source_id)},
        )
        return result.rowcount > 0

    def mark_failed(self, source_id: str) -> bool:
        """Close an unfinished checkpoint whose ingest just failed.

        Sets ``status`` to ``'stalled'``, the one terminal value the column
        allows, which every reader already takes as "ended without
        finishing": the sources list shows it as failed and Activity › Now
        drops it. Without this the row looks in flight until the
        reconciler's stalled sweep. A finished row is left alone (the
        failure came after embedding), and ``init_progress`` reopens the
        row when a retry starts embedding again. ``dispatch`` is dropped: the
        reconciler never queues a failed ingest again.

        Args:
            source_id: The source whose ingest failed.

        Returns:
            ``True`` when a row was closed.
        """
        result = self._conn.execute(
            text(
                """
                UPDATE ingest_chunk_progress
                SET status = 'stalled', dispatch = NULL
                WHERE source_id = CAST(:source_id AS uuid)
                  AND status = 'active'
                  AND embedded_chunks < total_chunks
                """
            ),
            {"source_id": str(source_id)},
        )
        return result.rowcount > 0

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

    def list_orphans(self, ttl_hours: int, limit: int = 100) -> list[dict]:
        """Ingests whose vectors no source owns, quiet for ``ttl_hours``, oldest first.

        Args:
            ttl_hours: Hours since the last progress.
            limit: Most rows to return.

        Returns:
            Their progress rows.
        """
        result = self._conn.execute(
            text(
                f"""
                SELECT icp.* FROM ingest_chunk_progress icp
                WHERE {_ORPHAN}
                ORDER BY icp.last_updated ASC
                LIMIT :limit
                """
            ),
            {"ttl": int(ttl_hours), "limit": int(limit)},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def lock_orphan(self, source_id: str, ttl_hours: int) -> Optional[dict]:
        """Lock ``source_id``'s row if it is still an orphan; ``None`` if not, or held.

        Held until the caller's transaction ends, so a new ingest of the same
        source waits in ``init_progress`` until its old vectors are gone.

        Args:
            source_id: The source.
            ttl_hours: Hours since the last progress.

        Returns:
            The locked row, or ``None``.
        """
        result = self._conn.execute(
            text(
                f"""
                SELECT icp.* FROM ingest_chunk_progress icp
                WHERE icp.source_id = CAST(:sid AS uuid) AND {_ORPHAN}
                FOR UPDATE OF icp SKIP LOCKED
                """
            ),
            {"sid": str(source_id), "ttl": int(ttl_hours)},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def without_source(self, ttl_hours: int, source_ids: Optional[list[str]] = None) -> list[dict]:
        """Every row with no ``sources`` row, with ``swept`` saying whether it is an orphan yet.

        Args:
            ttl_hours: Hours since the last progress; ``0`` means nothing is swept.
            source_ids: Only these sources (UUID strings), when given.

        Returns:
            Progress rows, each with a boolean ``swept``.
        """
        only = "AND icp.source_id = ANY(CAST(:ids AS uuid[]))" if source_ids is not None else ""
        swept = f"(:ttl > 0 AND {_ORPHAN})"
        result = self._conn.execute(
            text(
                f"""
                SELECT icp.*, {swept} AS swept FROM ingest_chunk_progress icp
                WHERE NOT EXISTS (SELECT 1 FROM sources s WHERE s.id = icp.source_id)
                {only}
                ORDER BY icp.last_updated ASC
                """
            ),
            {"ttl": int(ttl_hours), "ids": list(source_ids or [])},
        )
        return [row_to_dict(r) for r in result.fetchall()]

