"""Repository for ``conversation_labels``: the decision model's labels on stored conversations.

The analytics sweep (``docsgpt.analytics.tasks``) writes and reads rows here; every candidate query takes the
running ``schema_hash`` and ``model_version``, so a message labelled under other wording or by another model is a
candidate again. Projections are explicit, never ``SELECT *``.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Connection, text

from docsgpt.analytics.states import COMPRESSION_SUMMARY_MARKER, COMPRESSION_SUMMARY_PROMPT
from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes

#: The label every labelled user message carries (its request type) or, when one of its states could not be
#: built or was refused as a bad item, ``_error``. A message with neither, or with one older than its last edit,
#: is labelled again.
MARKERS = ("request_type", "_error")
ERROR = "_error"

_UPSERT_COLUMNS = (
    "conversation_id", "message_id", "reply_message_id", "user_id", "agent_id", "level", "label", "top", "p_top",
    "probabilities", "derived", "lang", "options_hash", "schema_hash", "model_version", "occurred_at",
)

_PROJECTION = (
    "CAST(l.message_id AS text) AS message_id, CAST(l.reply_message_id AS text) AS reply_message_id, "
    "l.level, l.label, l.top, l.p_top, l.probabilities, l.derived, l.lang, l.options_hash, l.occurred_at, "
    "l.created_at"
)

# The agent a conversation belongs to: its own ``agent_id``, else the agent whose key it was asked with.
_AGENT = """
    LEFT JOIN LATERAL (
        SELECT a.id, a.config FROM agents a
        WHERE a.id = c.agent_id
           OR (c.agent_id IS NULL AND COALESCE(c.api_key, '') <> '' AND a.key = c.api_key)
        LIMIT 1
    ) ag ON true
"""
_ENABLED = "COALESCE(ag.config->'analytics'->>'enabled', 'true') <> 'false'"
_TAGS_HASH = "md5(COALESCE(ag.config->'analytics'->'tags', '[]'::jsonb)::text)"


def _usable(m: str) -> str:
    """SQL: message ``m`` is a finished user message (complete or failed, with a prompt), not a compression summary
    row (marked, or, written before the marker, its label with nothing else on the row): ``states.messages``."""
    return f"""
        {m}.status IN ('complete', 'failed')
        AND COALESCE({m}.prompt, '') <> ''
        AND COALESCE({m}.message_metadata->>'{COMPRESSION_SUMMARY_MARKER}', '') <> 'true'
        AND NOT ({m}.prompt = '{COMPRESSION_SUMMARY_PROMPT}' AND {m}.tool_calls = '[]'::jsonb
                 AND {m}.message_metadata = '{{}}'::jsonb)
    """


def _unlabelled(m: str) -> str:
    """SQL: message ``m`` has no marker under the running schema and model, or only one older than its last edit."""
    return f"""
        NOT EXISTS (
            SELECT 1 FROM conversation_labels lm
            WHERE lm.message_id = {m}.id AND lm.label IN ('request_type', '_error')
              AND lm.schema_hash = :schema_hash AND lm.model_version = :model_version
              AND lm.created_at >= {m}.updated_at
        )
    """


def _scope(params: Dict[str, Any], agent_id: Optional[str], exclude: Iterable[str], column: str) -> str:
    """The optional agent and already-seen-conversation clauses, binding their parameters."""
    clauses = ""
    if agent_id:
        clauses += " AND ag.id = CAST(:agent_id AS uuid)"
        params["agent_id"] = agent_id
    exclude = list(exclude)
    if exclude:
        clauses += f" AND {column} <> ALL(CAST(:exclude AS uuid[]))"
        params["exclude"] = exclude
    return clauses


def _dump(value: Any) -> str:
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


class ConversationLabelsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert_many(self, rows: List[Dict[str, Any]]) -> int:
        """Write label rows, replacing the row of the same conversation, message and label.

        Args:
            rows: Dicts with the table's columns; ``message_id``, ``reply_message_id``, ``agent_id``, ``top``,
                ``p_top``, ``lang`` and ``options_hash`` may be missing.

        Returns:
            The number of rows written.
        """
        if not rows:
            return 0
        statement = text(
            """
            INSERT INTO conversation_labels
                (conversation_id, message_id, reply_message_id, user_id, agent_id, level, label, top, p_top,
                 probabilities, derived, lang, options_hash, schema_hash, model_version, occurred_at)
            VALUES
                (CAST(:conversation_id AS uuid), CAST(:message_id AS uuid), CAST(:reply_message_id AS uuid),
                 :user_id, CAST(:agent_id AS uuid), :level, :label, :top, :p_top, CAST(:probabilities AS jsonb),
                 :derived, :lang, :options_hash, :schema_hash, :model_version, :occurred_at)
            ON CONFLICT (conversation_id, COALESCE(message_id, '00000000-0000-0000-0000-000000000000'::uuid), label)
            DO UPDATE SET
                reply_message_id = EXCLUDED.reply_message_id, user_id = EXCLUDED.user_id,
                agent_id = EXCLUDED.agent_id, level = EXCLUDED.level, top = EXCLUDED.top,
                p_top = EXCLUDED.p_top, probabilities = EXCLUDED.probabilities, derived = EXCLUDED.derived,
                lang = EXCLUDED.lang, options_hash = EXCLUDED.options_hash, schema_hash = EXCLUDED.schema_hash,
                model_version = EXCLUDED.model_version, occurred_at = EXCLUDED.occurred_at, created_at = now()
            """
        )
        payload = []
        for row in rows:
            values = {column: row.get(column) for column in _UPSERT_COLUMNS}
            values["probabilities"] = _dump(row["probabilities"])
            values["derived"] = bool(row.get("derived"))
            # Topic and tag names are the owner's text; a NUL would make the INSERT raise and take the batch.
            for column in ("label", "top", "options_hash", "lang"):
                values[column] = strip_null_bytes(values[column])
            payload.append(values)
        result = self._conn.execute(statement, payload)
        return result.rowcount or 0

    def purge_older_than(self, days: int) -> int:
        """Delete rows whose message (or conversation) is older than ``days``; returns how many."""
        result = self._conn.execute(
            text("DELETE FROM conversation_labels WHERE occurred_at < NOW() - make_interval(days => :days)"),
            {"days": max(1, int(days))},
        )
        return result.rowcount or 0

    def delete_conversation_tags(self, conversation_id: str, keep: Iterable[str]) -> int:
        """Delete a conversation's ``tag:<id>`` rows whose tag is not in ``keep`` (the agent removed it)."""
        result = self._conn.execute(
            text(
                """
                DELETE FROM conversation_labels
                WHERE conversation_id = CAST(:conversation_id AS uuid) AND message_id IS NULL
                  AND label LIKE 'tag:%' AND label <> ALL(CAST(:keep AS text[]))
                """
            ),
            {"conversation_id": conversation_id, "keep": list(keep)},
        )
        return result.rowcount or 0

    def for_conversation(self, conversation_id: str, schema_hash: str, model_version: str) -> List[dict]:
        """Every row of one conversation under the running schema and model, oldest message first."""
        result = self._conn.execute(
            text(
                f"""
                SELECT {_PROJECTION} FROM conversation_labels l
                WHERE l.conversation_id = CAST(:conversation_id AS uuid)
                  AND l.schema_hash = :schema_hash AND l.model_version = :model_version
                ORDER BY l.occurred_at, l.label
                """
            ),
            {"conversation_id": conversation_id, "schema_hash": schema_hash, "model_version": model_version},
        )
        return [dict(row._mapping) for row in result.fetchall()]

    # ---- the sweep's candidates ---------------------------------------------------------------------------------

    def message_candidates(
        self,
        schema_hash: str,
        model_version: str,
        days: int,
        settle_seconds: int,
        limit: int,
        agent_id: Optional[str] = None,
        exclude: Iterable[str] = (),
    ) -> List[dict]:
        """Conversations with unlabelled messages, the newest such message first.

        A message is a candidate when it is a finished user message from the last ``days``, unchanged for
        ``settle_seconds``, in a conversation with no agent or whose agent has analytics on, and it has no marker
        (``MARKERS``) under the running schema and model newer than its last edit.

        Args:
            schema_hash: The running ``schema.SCHEMA_HASH``.
            model_version: The running ``decisions.model_version()``.
            days: The backfill window.
            settle_seconds: How long a message must be unchanged.
            limit: Most conversations returned.
            agent_id: Only this agent's conversations.
            exclude: Conversation ids already handled in this sweep.

        Returns:
            ``conversation_id``, ``user_id``, ``agent_id`` (resolved through the API key when the conversation
            has none) and ``newest``.
        """
        params: Dict[str, Any] = {"schema_hash": schema_hash, "model_version": model_version, "days": int(days),
                                  "settle": float(settle_seconds), "limit": int(limit)}
        scope = _scope(params, agent_id, exclude, "m.conversation_id")
        result = self._conn.execute(
            text(
                f"""
                SELECT CAST(m.conversation_id AS text) AS conversation_id, c.user_id,
                       CAST(ag.id AS text) AS agent_id, MAX(m.timestamp) AS newest
                FROM conversation_messages m
                JOIN conversations c ON c.id = m.conversation_id
                {_AGENT}
                WHERE m.timestamp >= NOW() - make_interval(days => :days)
                  AND m.updated_at <= NOW() - make_interval(secs => :settle)
                  AND {_usable("m")} AND {_ENABLED} AND {_unlabelled("m")} {scope}
                GROUP BY m.conversation_id, c.user_id, ag.id
                ORDER BY newest DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def count_message_candidates(
        self, schema_hash: str, model_version: str, days: int, agent_id: Optional[str] = None
    ) -> Dict[str, int]:
        """How many messages and conversations ``message_candidates`` would find, settled or not (``--dry-run``)."""
        params: Dict[str, Any] = {"schema_hash": schema_hash, "model_version": model_version, "days": int(days)}
        scope = _scope(params, agent_id, (), "m.conversation_id")
        row = self._conn.execute(
            text(
                f"""
                SELECT COUNT(*) AS messages, COUNT(DISTINCT m.conversation_id) AS conversations,
                       COUNT(*) FILTER (WHERE m.status = 'complete' AND COALESCE(m.response, '') <> '') AS turns
                FROM conversation_messages m
                JOIN conversations c ON c.id = m.conversation_id
                {_AGENT}
                WHERE m.timestamp >= NOW() - make_interval(days => :days)
                  AND {_usable("m")} AND {_ENABLED} AND {_unlabelled("m")} {scope}
                """
            ),
            params,
        ).one()
        return dict(row._mapping)

    def unlabelled_message_ids(
        self, conversation_id: str, schema_hash: str, model_version: str, days: int, settle_seconds: int
    ) -> set[str]:
        """The ids of one conversation's messages that ``message_candidates`` counts as unlabelled."""
        result = self._conn.execute(
            text(
                f"""
                SELECT CAST(m.id AS text) FROM conversation_messages m
                WHERE m.conversation_id = CAST(:conversation_id AS uuid)
                  AND m.timestamp >= NOW() - make_interval(days => :days)
                  AND m.updated_at <= NOW() - make_interval(secs => :settle)
                  AND {_usable("m")} AND {_unlabelled("m")}
                """
            ),
            {"conversation_id": conversation_id, "schema_hash": schema_hash, "model_version": model_version,
             "days": int(days), "settle": float(settle_seconds)},
        )
        return {row[0] for row in result.fetchall()}

    def conversation_candidates(
        self,
        schema_hash: str,
        model_version: str,
        days: int,
        idle_minutes: int,
        limit: int,
        agent_id: Optional[str] = None,
        exclude: Iterable[str] = (),
    ) -> List[dict]:
        """Idle conversations whose own labels (goal met, tags) are missing or stale, the most recent first.

        A conversation is a candidate when its last user message is within the last ``days`` and older than
        ``idle_minutes``, every one of its messages in the window is labelled, and it has no ``goal_met`` row
        under the running schema and model, the row is older than its last message, or the agent's tags changed
        since (``tags_hash``). A conversation whose state could not be built (an ``_error`` row newer than its
        last message) is not asked again.

        Returns:
            ``conversation_id``, ``user_id``, ``agent_id``, ``last_at`` and ``tags_hash``, the value to store
            as the ``goal_met`` row's ``options_hash``.
        """
        params: Dict[str, Any] = {"schema_hash": schema_hash, "model_version": model_version, "days": int(days),
                                  "idle": int(idle_minutes), "limit": int(limit)}
        scope = _scope(params, agent_id, exclude, "conv.conversation_id")
        result = self._conn.execute(
            text(
                f"""
                WITH conv AS (
                    SELECT m.conversation_id, MAX(m.timestamp) AS last_at, MAX(m.updated_at) AS last_updated
                    FROM conversation_messages m
                    WHERE m.timestamp >= NOW() - make_interval(days => :days) AND {_usable("m")}
                    GROUP BY m.conversation_id
                    HAVING MAX(m.timestamp) < NOW() - make_interval(mins => :idle)
                )
                SELECT CAST(conv.conversation_id AS text) AS conversation_id, c.user_id,
                       CAST(ag.id AS text) AS agent_id, conv.last_at, {_TAGS_HASH} AS tags_hash
                FROM conv
                JOIN conversations c ON c.id = conv.conversation_id
                {_AGENT}
                LEFT JOIN conversation_labels g
                    ON g.conversation_id = conv.conversation_id AND g.message_id IS NULL AND g.label = 'goal_met'
                WHERE {_ENABLED}
                  AND (g.id IS NULL OR g.schema_hash <> :schema_hash OR g.model_version <> :model_version
                       OR g.created_at < conv.last_updated OR g.options_hash IS DISTINCT FROM {_TAGS_HASH})
                  AND NOT EXISTS (
                      SELECT 1 FROM conversation_labels e
                      WHERE e.conversation_id = conv.conversation_id AND e.message_id IS NULL
                        AND e.label = '_error' AND e.schema_hash = :schema_hash
                        AND e.model_version = :model_version AND e.created_at >= conv.last_updated
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM conversation_messages m
                      WHERE m.conversation_id = conv.conversation_id
                        AND m.timestamp >= NOW() - make_interval(days => :days)
                        AND {_usable("m")} AND {_unlabelled("m")}
                  ) {scope}
                ORDER BY conv.last_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def pending_resolutions(
        self, schema_hash: str, model_version: str, window_hours: int, limit: int, exclude: Iterable[str] = ()
    ) -> List[dict]:
        """Conversations whose ``resolution`` still has pending mass though their last message is past the window.

        Returns:
            ``conversation_id``, ``user_id``, ``agent_id`` and ``last_at``.
        """
        params: Dict[str, Any] = {"schema_hash": schema_hash, "model_version": model_version,
                                  "window": int(window_hours), "limit": int(limit)}
        clause = ""
        exclude = list(exclude)
        if exclude:
            clause = " AND l.conversation_id <> ALL(CAST(:exclude AS uuid[]))"
            params["exclude"] = exclude
        result = self._conn.execute(
            text(
                f"""
                SELECT CAST(l.conversation_id AS text) AS conversation_id, l.user_id,
                       CAST(l.agent_id AS text) AS agent_id, l.occurred_at AS last_at
                FROM conversation_labels l
                WHERE l.label = 'resolution' AND l.message_id IS NULL
                  AND l.schema_hash = :schema_hash AND l.model_version = :model_version
                  AND l.occurred_at < NOW() - make_interval(hours => :window)
                  AND COALESCE((l.probabilities->>'pending')::float8, 0) > 0 {clause}
                ORDER BY l.occurred_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    # ---- the weekly digest --------------------------------------------------------------------------------------

    def digest_agents(self) -> List[dict]:
        """Agents whose owner asked for the weekly docs-gap digest and whose analytics is on.

        Returns:
            ``id``, ``user_id`` (the owner) and ``name``.
        """
        result = self._conn.execute(
            text(
                """
                SELECT CAST(a.id AS text) AS id, a.user_id, a.name FROM agents a
                WHERE a.config->'analytics'->>'digest' = 'true'
                  AND COALESCE(a.config->'analytics'->>'enabled', 'true') <> 'false'
                ORDER BY a.created_at
                """
            )
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def docs_gaps(
        self, agent_id: str, schema_hash: str, since: datetime.datetime, until: datetime.datetime
    ) -> Dict[str, Any]:
        """One agent's expected docs gaps in ``[since, until)``: in all, and per effective topic.

        A turn's gap is its ``gap_type`` row's ``docs missing`` probability; a topic's share of it is the turn's
        ``topic_effective`` probability of that topic, so the per-topic values sum to the total over turns that
        have a topic.

        Returns:
            ``{"expected", "turns", "topics": {name: expected}}``.
        """
        params = {"agent_id": agent_id, "schema_hash": schema_hash, "since": since, "until": until}
        window = """
            g.agent_id = CAST(:agent_id AS uuid) AND g.label = 'gap_type' AND g.schema_hash = :schema_hash
            AND g.occurred_at >= :since AND g.occurred_at < :until
        """
        total = self._conn.execute(
            text(
                f"""
                SELECT COALESCE(SUM((g.probabilities->>'docs missing')::float8), 0) AS expected, COUNT(*) AS turns
                FROM conversation_labels g WHERE {window}
                """
            ),
            params,
        ).one()
        topics = self._conn.execute(
            text(
                f"""
                SELECT t.key AS topic, SUM((g.probabilities->>'docs missing')::float8 * t.value::float8) AS expected
                FROM conversation_labels g
                JOIN conversation_labels te
                    ON te.message_id = g.message_id AND te.label = 'topic_effective'
                   AND te.schema_hash = :schema_hash
                CROSS JOIN LATERAL jsonb_each_text(te.probabilities) AS t(key, value)
                WHERE {window}
                GROUP BY t.key
                """
            ),
            params,
        ).fetchall()
        return {"expected": float(total.expected), "turns": int(total.turns),
                "topics": {row.topic: float(row.expected) for row in topics}}
