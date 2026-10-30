"""Repository for ``content_scores``: prompt-injection scores keyed by a text's sha256 and the scorer, never text."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from sqlalchemy import Connection, text

#: The largest window count a ``SMALLINT`` column holds.
_MAX_WINDOWS = 32767


class ContentScoresRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_many(self, hashes: Sequence[str], scorer: str) -> Dict[str, Dict[str, Any]]:
        """The stored scores of ``hashes`` under ``scorer``, in one indexed query.

        Args:
            hashes: sha256 hex digests.
            scorer: The scorer id the rows must carry.

        Returns:
            Hash to ``{p, windows_scored, windows_total, stale}``, ``stale`` when the row was not seen in the
            last day (``touch`` would bump it); hashes without a row are absent.
        """
        wanted = sorted(set(hashes))
        if not wanted:
            return {}
        result = self._conn.execute(
            text(
                "SELECT content_hash, p, windows_scored, windows_total, "
                "last_seen_at < now() - interval '1 day' AS stale FROM content_scores "
                "WHERE content_hash = ANY(:hashes) AND scorer = :scorer"
            ),
            {"hashes": wanted, "scorer": scorer},
        )
        return {
            row.content_hash: {"p": float(row.p), "windows_scored": row.windows_scored,
                               "windows_total": row.windows_total, "stale": bool(row.stale)}
            for row in result.fetchall()
        }

    def upsert_many(self, rows: List[Dict[str, Any]]) -> int:
        """Store scores; a row already holding at least as many scored windows keeps its score.

        Either way the row is marked seen now, so retention keeps a text scored again.

        Args:
            rows: ``content_hash``, ``scorer``, ``p``, ``windows_scored`` and ``windows_total``.

        Returns:
            The number of rows written.
        """
        if not rows:
            return 0
        statement = text(
            """
            INSERT INTO content_scores (content_hash, scorer, p, windows_scored, windows_total)
            VALUES (:content_hash, :scorer, :p, :windows_scored, :windows_total)
            ON CONFLICT (content_hash, scorer) DO UPDATE SET
                p = CASE WHEN EXCLUDED.windows_scored > content_scores.windows_scored
                    THEN EXCLUDED.p ELSE content_scores.p END,
                windows_total = CASE WHEN EXCLUDED.windows_scored > content_scores.windows_scored
                    THEN EXCLUDED.windows_total ELSE content_scores.windows_total END,
                windows_scored = GREATEST(EXCLUDED.windows_scored, content_scores.windows_scored),
                last_seen_at = now()
            """
        )
        payload = [
            {
                **row,
                "windows_scored": min(int(row["windows_scored"]), _MAX_WINDOWS),
                "windows_total": min(int(row["windows_total"]), _MAX_WINDOWS),
            }
            for row in rows
        ]
        result = self._conn.execute(statement, payload)
        return result.rowcount or 0

    def touch(self, hashes: Sequence[str], scorer: str) -> int:
        """Mark rows as seen today, at most one write per row and day, so retention keeps text still in use.

        Returns:
            The number of rows bumped.
        """
        wanted = sorted(set(hashes))
        if not wanted:
            return 0
        result = self._conn.execute(
            text(
                "UPDATE content_scores SET last_seen_at = now() "
                "WHERE content_hash = ANY(:hashes) AND scorer = :scorer "
                "AND last_seen_at < now() - interval '1 day'"
            ),
            {"hashes": wanted, "scorer": scorer},
        )
        return result.rowcount or 0

    def purge_unseen_for(self, days: int) -> int:
        """Delete rows not seen for ``days`` days; returns how many."""
        result = self._conn.execute(
            text("DELETE FROM content_scores WHERE last_seen_at < NOW() - CAST(:days || ' days' AS interval)"),
            {"days": str(max(1, days))},
        )
        return result.rowcount or 0
