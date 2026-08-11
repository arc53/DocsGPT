"""Repository for ``guardrail_events``; the decision audit journal."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import Connection, text

from application.storage.db.serialization import PGNativeJSONEncoder
from application.utils import strip_null_bytes


def _dump_jsonb(value: Any) -> str:
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


class GuardrailEventsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record_many(self, rows: List[Dict[str, Any]]) -> int:
        """Insert a batch of decision rows. Returns the number written."""
        if not rows:
            return 0
        statement = text(
            """
            INSERT INTO guardrail_events
                (user_id, api_key, agent_id, message_id, request_id, stage,
                 check_name, detector_type, action, outcome, category, score,
                 match_count, matched_value, detail, policy_snapshot)
            VALUES
                (:user_id, :api_key, CAST(:agent_id AS uuid),
                 CAST(:message_id AS uuid), :request_id, :stage,
                 :check_name, :detector_type, :action, :outcome, :category,
                 :score, :match_count, :matched_value, :detail,
                 CAST(:policy_snapshot AS jsonb))
            """
        )
        payload = [
            {
                "user_id": row.get("user_id"),
                "api_key": row.get("api_key"),
                "agent_id": row.get("agent_id"),
                "message_id": row.get("message_id"),
                "request_id": row.get("request_id"),
                "stage": row["stage"],
                "check_name": row["check_name"],
                "detector_type": row["detector_type"],
                "action": row["action"],
                "outcome": row["outcome"],
                "category": row.get("category"),
                "score": row.get("score"),
                "match_count": int(row.get("match_count") or 0),
                # Both are slices of user text; a NUL would make the INSERT
                # raise and take every buffered row for the turn with it.
                "matched_value": strip_null_bytes(row.get("matched_value")),
                "detail": strip_null_bytes((row.get("detail") or "")[:2000]) or None,
                "policy_snapshot": _dump_jsonb(row.get("policy_snapshot"))
                if row.get("policy_snapshot") is not None
                else None,
            }
            for row in rows
        ]
        result = self._conn.execute(statement, payload)
        return result.rowcount or 0

    # Explicit projection, never SELECT *: ``api_key`` is the agent's raw key
    # (masked everywhere else in the API) and ``matched_value`` is unredacted
    # source text. Neither belongs in a list response.
    _PUBLIC_COLUMNS = (
        "id, agent_id, message_id, request_id, stage, check_name, "
        "detector_type, action, outcome, category, score, match_count, "
        "detail, created_at"
    )

    def list_for_agent(
        self, agent_id: str, user_id: str, limit: int = 100, offset: int = 0
    ) -> List[dict]:
        result = self._conn.execute(
            text(
                f"""
                SELECT {self._PUBLIC_COLUMNS} FROM guardrail_events
                WHERE agent_id = CAST(:agent_id AS uuid) AND user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {
                "agent_id": agent_id,
                "user_id": user_id,
                "limit": max(1, min(limit, 500)),
                "offset": max(0, offset),
            },
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def summary_for_user(
        self, user_id: str, days: int = 30, agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Counts by check, action and outcome over a trailing window.

        Splits ``blocked`` from ``flagged`` because "we refused to answer" and
        "we noticed something" are different product problems, and both are
        different from "the check could not run".
        """
        params: Dict[str, Any] = {
            "user_id": user_id,
            "days": str(max(1, min(days, 365))),
        }
        # Built conditionally rather than with an ``IS NULL`` guard on the bind:
        # Postgres cannot infer a type for a NULL parameter that is only ever
        # compared against a uuid.
        agent_clause = ""
        if agent_id:
            agent_clause = " AND agent_id = CAST(:agent_id AS uuid)"
            params["agent_id"] = agent_id
        result = self._conn.execute(
            text(
                f"""
                SELECT check_name, stage, action, outcome, category,
                       COUNT(*) AS total
                FROM guardrail_events
                WHERE user_id = :user_id
                  AND created_at >= NOW() - CAST(:days || ' days' AS interval)
                  {agent_clause}
                GROUP BY check_name, stage, action, outcome, category
                ORDER BY total DESC
                """
            ),
            params,
        )
        rows = [dict(row._mapping) for row in result.fetchall()]
        blocked = sum(r["total"] for r in rows if r["action"] == "block" and r["outcome"] == "triggered")
        flagged = sum(r["total"] for r in rows if r["action"] == "flag" and r["outcome"] == "triggered")
        redacted = sum(r["total"] for r in rows if r["action"] == "redact" and r["outcome"] == "triggered")
        not_evaluated = sum(r["total"] for r in rows if r["outcome"] == "not_evaluated")
        return {
            "breakdown": rows,
            "totals": {
                "blocked": blocked,
                "flagged": flagged,
                "redacted": redacted,
                "not_evaluated": not_evaluated,
            },
        }

    def purge_older_than(self, days: int) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM guardrail_events "
                "WHERE created_at < NOW() - CAST(:days || ' days' AS interval)"
            ),
            {"days": str(max(1, days))},
        )
        return result.rowcount or 0

    def list_for_message(self, message_id: str) -> List[dict]:
        """Decisions recorded against one message, for the conversation view."""
        result = self._conn.execute(
            text(
                f"""
                SELECT {self._PUBLIC_COLUMNS} FROM guardrail_events
                WHERE message_id = CAST(:message_id AS uuid)
                ORDER BY created_at
                """
            ),
            {"message_id": message_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]
