"""Repository for ``decision_usage``: per-day counts of calls to the decision model, never text."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Connection, text

_COUNTERS = ("calls", "states", "answered", "ms_total", "queue_ms_total")


class DecisionUsageRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, rows: List[Dict[str, Any]]) -> int:
        """Add counts to their day's rows, creating the rows that do not exist yet.

        Args:
            rows: ``day``, ``feature``, ``mode``, ``model_version`` and ``status``, with the increments of
                ``calls``, ``states``, ``answered``, ``ms_total`` and ``queue_ms_total``.

        Returns:
            The number of rows written.
        """
        if not rows:
            return 0
        statement = text(
            """
            INSERT INTO decision_usage
                (day, feature, mode, model_version, status, calls, states, answered, ms_total, queue_ms_total)
            VALUES
                (:day, :feature, :mode, :model_version, :status, :calls, :states, :answered, :ms_total,
                 :queue_ms_total)
            ON CONFLICT (day, feature, mode, model_version, status) DO UPDATE SET
                calls = decision_usage.calls + EXCLUDED.calls,
                states = decision_usage.states + EXCLUDED.states,
                answered = decision_usage.answered + EXCLUDED.answered,
                ms_total = decision_usage.ms_total + EXCLUDED.ms_total,
                queue_ms_total = decision_usage.queue_ms_total + EXCLUDED.queue_ms_total,
                updated_at = now()
            """
        )
        result = self._conn.execute(statement, [{**row, "model_version": row.get("model_version") or ""}
                                                for row in rows])
        return result.rowcount or 0

    def totals(
        self,
        since: datetime.date,
        until: datetime.date,
        feature: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Counts summed over a day range, per feature, mode, model version and status.

        Args:
            since: First day, inclusive.
            until: Last day, inclusive.
            feature: Only this feature's rows; every feature when ``None``.

        Returns:
            One dict per (feature, mode, model_version, status) with the summed counters, ordered by feature.
        """
        sums = ", ".join(f"SUM({c}) AS {c}" for c in _COUNTERS)
        rows = self._conn.execute(
            text(
                f"""
                SELECT feature, mode, model_version, status, {sums}
                FROM decision_usage
                WHERE day BETWEEN :since AND :until
                  AND (CAST(:feature AS text) IS NULL OR feature = :feature)
                GROUP BY feature, mode, model_version, status
                ORDER BY feature, mode, model_version, status
                """
            ),
            {"since": since, "until": until, "feature": feature},
        ).mappings()
        return [
            {
                **{k: row[k] for k in ("feature", "mode", "model_version", "status")},
                **{c: int(row[c]) if c in ("calls", "states", "answered") else float(row[c]) for c in _COUNTERS},
            }
            for row in rows
        ]

    def purge_older_than(self, days: int) -> int:
        """Delete the days before the last ``days`` (the retention window)."""
        result = self._conn.execute(
            text("DELETE FROM decision_usage WHERE day < CURRENT_DATE - CAST(:days AS integer)"),
            {"days": max(1, days)},
        )
        return result.rowcount or 0
