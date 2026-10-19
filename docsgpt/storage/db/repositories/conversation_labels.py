"""Repository for ``conversation_labels``: the decision model's labels on stored conversations.

The analytics sweep (``docsgpt.analytics.tasks``) writes and reads rows here; every candidate query takes the
running ``schema_hash`` and ``model_version``, so a message labelled under other wording or by another model is a
candidate again. The dashboard reads (insights, docs gaps, Logs labels) take only the ``schema_hash``: rows of every
model under the running wording count, and the interval takes the widest model's calibration error. They scope on
the row's own ``agent_id`` or ``user_id``, so each runs on ``agent_time_idx`` or ``user_time_idx``. Projections are
explicit, never ``SELECT *``.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Connection, text

from docsgpt.analytics.derive import NEGATIVE_REACTIONS
from docsgpt.analytics.states import (
    COMPRESSION_SUMMARY_MARKER,
    COMPRESSION_SUMMARY_PROMPT,
    TERMINATED_RESPONSE_PLACEHOLDER,
)
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


# A conversation-level row (no message), written so the unique target index serves the lookup.
_NO_MESSAGE = "00000000-0000-0000-0000-000000000000"


def _conversation_level(alias: str) -> str:
    return f"COALESCE({alias}.message_id, '{_NO_MESSAGE}'::uuid) = '{_NO_MESSAGE}'::uuid"


def _is_turn(m: str) -> str:
    """SQL: message ``m`` holds a finished answer (``states.Message.is_turn``)."""
    return (f"({m}.status = 'complete' AND btrim(COALESCE({m}.response, '')) <> ''"
            f" AND btrim({m}.response) <> :placeholder)")


#: The Logs ``label`` filter and row chips: per key, which row the label sits on (``message``: the turn's own row;
#: ``reply``: a reaction row, matched on the reply it read), the stored label and the options whose probabilities
#: sum to the chip's. In the order chips are listed; ``tag:<id>`` rows (conversation level) follow.
LOG_LABELS: Dict[str, tuple[str, str, tuple[str, ...]]] = {
    "docs_gap": ("message", "gap_type", ("docs missing",)),
    "not_answered": ("message", "answer_status",
                     ("partially answered", "declined, no information", "asked a clarifying question")),
    "negative_reaction": ("reply", "reaction", NEGATIVE_REACTIONS),
    "frustrated": ("reply", "frustrated", ("yes",)),
    "asks_human": ("reply", "asks_human", ("yes",)),
}
TAG_PREFIX = "tag:"


def _mass(alias: str, options: Iterable[str]) -> str:
    """SQL: the summed probability of ``options`` in row ``alias`` (code constants, quoted as literals)."""
    parts = [f"COALESCE(({alias}.probabilities->>'{o.replace(chr(39), chr(39) * 2)}')::float8, 0)" for o in options]
    return "(" + " + ".join(parts) + ")"


def log_label_exists(key: str, message_expr: str) -> str:
    """SQL: the Logs row whose message id is ``message_expr`` carries ``key`` at even odds or better.

    Binds ``:schema_hash`` and ``:label_min``, and ``:label_name`` for a tag. ``key`` must be a ``LOG_LABELS`` key
    or ``tag:<id>``.
    """
    if key.startswith(TAG_PREFIX):
        return f"""EXISTS (
            SELECT 1 FROM conversation_messages lm
            JOIN conversation_labels cl
              ON cl.conversation_id = lm.conversation_id AND {_conversation_level("cl")} AND cl.label = :label_name
            WHERE lm.id = {message_expr} AND cl.schema_hash = :schema_hash
              AND {_mass("cl", ("yes",))} >= :label_min)"""
    side, label, options = LOG_LABELS[key]
    column = "message_id" if side == "message" else "reply_message_id"
    return f"""EXISTS (
        SELECT 1 FROM conversation_labels cl
        WHERE cl.{column} = {message_expr} AND cl.label = '{label}' AND cl.schema_hash = :schema_hash
          AND {_mass("cl", options)} >= :label_min)"""


def log_label_keys(rows: Iterable[dict], min_probability: float) -> List[str]:
    """The chip keys of one Logs row from its label rows (``label`` + ``probabilities``), in ``LOG_LABELS`` order."""
    by_label: Dict[str, dict] = {}
    for row in rows:
        by_label[row["label"]] = row["probabilities"] or {}
    keys = []
    for key, (_side, label, options) in LOG_LABELS.items():
        probabilities = by_label.get(label)
        if probabilities is not None and sum(float(probabilities.get(o) or 0) for o in options) >= min_probability:
            keys.append(key)
    tags = sorted(label for label, p in by_label.items()
                  if label.startswith(TAG_PREFIX) and float(p.get("yes") or 0) >= min_probability)
    return keys + tags


@dataclass(frozen=True)
class Scope:
    """Whose labels a dashboard reads: an agent's, all its traffic (its owner's view), or else one user's.

    Attributes:
        agent_id: The agent's id; labels match on their own ``agent_id``, resolved when they were written (also
            for conversations asked with the agent's key only).
        api_key: The agent's key (``None`` for key-less agents), for the message counts, which match
            conversations the way the other analytics routes do.
        user_id: The user whose own traffic is read when there is no agent.
    """

    agent_id: Optional[str] = None
    api_key: Optional[str] = None
    user_id: Optional[str] = None

    def labels(self, alias: str, params: Dict[str, Any]) -> str:
        if self.agent_id:
            params["scope_agent"] = self.agent_id
            return f"{alias}.agent_id = CAST(:scope_agent AS uuid)"
        params["scope_user"] = self.user_id
        return f"{alias}.user_id = :scope_user"

    def conversations(self, alias: str, params: Dict[str, Any]) -> str:
        if self.agent_id:
            params["scope_agent"] = self.agent_id
            params["scope_key"] = self.api_key
            return f"({alias}.api_key = :scope_key OR {alias}.agent_id = CAST(:scope_agent AS uuid))"
        params["scope_user"] = self.user_id
        return f"{alias}.user_id = :scope_user"


#: What a docs-gap group is keyed and named by: the effective topic, or the turn's first stored source (its
#: ``source_id``, or its page: the stored ``source`` path or URL, else its title).
_GAP_KEYS = {
    "source": ("NULLIF(m.sources->0->>'source_id', '')", "NULL"),
    "page": ("COALESCE(NULLIF(m.sources->0->>'source', ''), NULLIF(m.sources->0->>'title', ''))",
             "COALESCE(NULLIF(m.sources->0->>'title', ''), NULLIF(m.sources->0->>'source', ''))"),
}
GAP_GROUPS = ("topic", "source", "page")


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

    # ---- dashboard reads ----------------------------------------------------------------------------------------

    def coverage(
        self, scope: Scope, schema_hash: str, start: datetime.datetime, end: datetime.datetime
    ) -> Dict[str, int]:
        """Turns, replies and conversations in ``[start, end]``, against how many carry labels.

        A turn is a user message with a finished answer, a reply a user message after one, both counted at their
        own time; a conversation counts at its last message, as its ``goal_met`` row does. Messages of an agent
        with analytics off count only where they carry labels from before, so coverage never stays short of
        what the sweep would label.

        Returns:
            ``turns``, ``labelled_turns`` (with ``answer_status``), ``replies``, ``labelled_replies`` (with
            ``reaction``), ``conversations`` and ``labelled_conversations`` (with ``goal_met``).
        """
        params: Dict[str, Any] = {"schema_hash": schema_hash, "start": start, "end": end,
                                  "placeholder": TERMINATED_RESPONSE_PLACEHOLDER}
        where = scope.conversations("c", params)
        row = self._conn.execute(
            text(
                f"""
                WITH conv AS (
                    SELECT DISTINCT m.conversation_id FROM conversation_messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.timestamp >= :start AND m.timestamp <= :end AND {where}
                ),
                seq AS (
                    SELECT m.id, m.conversation_id, m.timestamp >= :start AND m.timestamp <= :end AS in_window,
                           {_is_turn("m")} AS is_turn,
                           LAG({_is_turn("m")}) OVER (PARTITION BY m.conversation_id ORDER BY m.position) AS after_turn,
                           ROW_NUMBER() OVER (PARTITION BY m.conversation_id ORDER BY m.position DESC) = 1 AS is_last,
                           {_ENABLED} AS enabled
                    FROM conv
                    JOIN conversations c ON c.id = conv.conversation_id
                    {_AGENT}
                    JOIN conversation_messages m ON m.conversation_id = conv.conversation_id
                    WHERE {_usable("m")}
                )
                SELECT
                    COUNT(*) FILTER (WHERE s.in_window AND s.is_turn AND (s.enabled OR a.id IS NOT NULL)) AS turns,
                    COUNT(a.id) FILTER (WHERE s.in_window AND s.is_turn) AS labelled_turns,
                    COUNT(*) FILTER (WHERE s.in_window AND s.after_turn AND (s.enabled OR r.id IS NOT NULL))
                        AS replies,
                    COUNT(r.id) FILTER (WHERE s.in_window AND s.after_turn) AS labelled_replies,
                    COUNT(*) FILTER (WHERE s.in_window AND s.is_last AND (s.enabled OR g.id IS NOT NULL))
                        AS conversations,
                    COUNT(g.id) FILTER (WHERE s.in_window AND s.is_last) AS labelled_conversations
                FROM seq s
                LEFT JOIN conversation_labels a
                    ON a.message_id = s.id AND a.label = 'answer_status' AND a.schema_hash = :schema_hash
                LEFT JOIN conversation_labels r
                    ON r.reply_message_id = s.id AND r.label = 'reaction' AND r.schema_hash = :schema_hash
                LEFT JOIN conversation_labels g
                    ON s.is_last AND g.conversation_id = s.conversation_id AND {_conversation_level("g")}
                   AND g.label = 'goal_met' AND g.schema_hash = :schema_hash
                """
            ),
            params,
        ).one()
        return {key: int(value or 0) for key, value in row._mapping.items()}

    def _window(self, scope: Scope, schema_hash: str, start, end, labels: Iterable[str],
                params: Dict[str, Any]) -> str:
        params.update({"schema_hash": schema_hash, "start": start, "end": end, "labels": list(labels)})
        return (f"{scope.labels('l', params)} AND l.occurred_at >= :start AND l.occurred_at <= :end"
                " AND l.label = ANY(CAST(:labels AS text[])) AND l.schema_hash = :schema_hash")

    def label_counts(self, scope: Scope, schema_hash: str, start, end, labels: Iterable[str]) -> Dict[str, dict]:
        """Per label in ``[start, end]``: its rows, their languages and models, and answer status's greetings.

        Returns:
            ``{label: {"n", "en", "es", "zh", "ru", "other", "versions", "not_request"}}``; ``other`` is every
            language outside en/es/zh/ru, ``not_request`` the summed ``not a request`` probability.
        """
        params: Dict[str, Any] = {}
        where = self._window(scope, schema_hash, start, end, labels, params)
        result = self._conn.execute(
            text(
                f"""
                SELECT l.label, COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE COALESCE(l.lang, 'en') = 'en') AS en,
                       COUNT(*) FILTER (WHERE l.lang = 'es') AS es,
                       COUNT(*) FILTER (WHERE l.lang = 'zh') AS zh,
                       COUNT(*) FILTER (WHERE l.lang = 'ru') AS ru,
                       COUNT(*) FILTER (WHERE COALESCE(l.lang, 'en') NOT IN ('en', 'es', 'zh', 'ru')) AS other,
                       array_agg(DISTINCT l.model_version) AS versions,
                       COALESCE(SUM((l.probabilities->>'not a request')::float8), 0) AS not_request
                FROM conversation_labels l
                WHERE {where}
                GROUP BY l.label
                """
            ),
            params,
        )
        out = {}
        for row in result.fetchall():
            values = dict(row._mapping)
            label = values.pop("label")
            out[label] = {**{k: int(values[k]) for k in ("n", "en", "es", "zh", "ru", "other")},
                          "versions": list(values["versions"] or []), "not_request": float(values["not_request"])}
        return out

    def label_sums(self, scope: Scope, schema_hash: str, start, end, labels: Iterable[str],
                   bucket_format: Optional[str] = None) -> List[dict]:
        """Expected counts: the summed probability of every option of every label in ``[start, end]``.

        Args:
            bucket_format: A ``to_char`` format; when given, per UTC bucket too.

        Returns:
            Rows of ``label``, ``option`` and ``expected``, and ``bucket`` (``None`` without a format).
        """
        params: Dict[str, Any] = {}
        where = self._window(scope, schema_hash, start, end, labels, params)
        bucket = "NULL"
        if bucket_format:
            params["fmt"] = bucket_format
            bucket = "to_char(l.occurred_at AT TIME ZONE 'UTC', :fmt)"
        result = self._conn.execute(
            text(
                f"""
                SELECT {bucket} AS bucket, l.label, p.key AS option, SUM(p.value::float8) AS expected
                FROM conversation_labels l
                CROSS JOIN LATERAL jsonb_each_text(l.probabilities) AS p(key, value)
                WHERE {where}
                GROUP BY 1, l.label, p.key
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def bucket_counts(self, scope: Scope, schema_hash: str, start, end, labels: Iterable[str],
                      bucket_format: str) -> List[dict]:
        """Rows per UTC bucket and label in ``[start, end]``: ``bucket``, ``label``, ``n``."""
        params: Dict[str, Any] = {"fmt": bucket_format}
        where = self._window(scope, schema_hash, start, end, labels, params)
        result = self._conn.execute(
            text(
                f"""
                SELECT to_char(l.occurred_at AT TIME ZONE 'UTC', :fmt) AS bucket, l.label, COUNT(*) AS n
                FROM conversation_labels l
                WHERE {where}
                GROUP BY 1, l.label
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def _gaps_cte(self, group_by: str, scope: Scope, schema_hash: str, params: Dict[str, Any]) -> str:
        """SQL: one row per gap turn and group in ``[:prev_start, :end]``, with its share of the group.

        Columns: ``key``, ``name``, ``message_id``, ``conversation_id``, ``occurred_at``, ``model_version``,
        ``current`` (in ``[:start, :end]``), ``gap`` (the turn's ``docs missing`` probability), ``weight`` (its
        share of the group: its effective-topic probability, else 1), ``p`` (``gap * weight``) and ``usual``
        (the group is the turn's most likely one).
        """
        params["schema_hash"] = schema_hash
        where = (f"{scope.labels('g', params)} AND g.label = 'gap_type' AND g.schema_hash = :schema_hash"
                 " AND g.occurred_at >= :prev_start AND g.occurred_at <= :end")
        common = ("g.message_id, g.conversation_id, g.occurred_at, g.model_version, g.occurred_at >= :start AS current,"
                  " (g.probabilities->>'docs missing')::float8 AS gap")
        if group_by == "topic":
            return f"""
                SELECT t.key, t.key AS name, {common}, t.value::float8 AS weight,
                       (g.probabilities->>'docs missing')::float8 * t.value::float8 AS p, te.top = t.key AS usual
                FROM conversation_labels g
                JOIN conversation_labels te
                    ON te.message_id = g.message_id AND te.label = 'topic_effective'
                   AND te.schema_hash = :schema_hash
                CROSS JOIN LATERAL jsonb_each_text(te.probabilities) AS t(key, value)
                WHERE {where}
            """
        key, name = _GAP_KEYS[group_by]
        return f"""
            SELECT {key} AS key, {name} AS name, {common}, 1.0::float8 AS weight,
                   (g.probabilities->>'docs missing')::float8 AS p, true AS usual
            FROM conversation_labels g
            LEFT JOIN conversation_messages m ON m.id = g.message_id
            WHERE {where}
        """

    def gap_groups(
        self, group_by: str, scope: Scope, schema_hash: str, start, end, previous_start, limit: int,
        min_expected: float,
    ) -> List[dict]:
        """Docs-gap groups in ``[start, end]``, the most expected gaps first, with the window before.

        Args:
            group_by: ``topic``, ``source`` or ``page`` (``GAP_GROUPS``).
            previous_start: Start of the window of equal length just before ``start``.
            limit: Most groups returned.
            min_expected: Groups with fewer expected gaps are left out.

        Returns:
            ``key`` (``None``: no source retrieved), ``name``, ``expected``, ``turns`` (the group's summed
            weights), ``previous`` and ``versions`` (the models of its rows).
        """
        params: Dict[str, Any] = {"start": start, "end": end, "prev_start": previous_start, "limit": int(limit),
                                  "min_expected": float(min_expected)}
        cte = self._gaps_cte(group_by, scope, schema_hash, params)
        result = self._conn.execute(
            text(
                f"""
                WITH g AS ({cte})
                SELECT key, MAX(name) AS name,
                       COALESCE(SUM(p) FILTER (WHERE current), 0) AS expected,
                       COALESCE(SUM(weight) FILTER (WHERE current), 0) AS turns,
                       COALESCE(SUM(p) FILTER (WHERE NOT current), 0) AS previous,
                       array_agg(DISTINCT model_version) FILTER (WHERE current) AS versions
                FROM g
                GROUP BY key
                HAVING COALESCE(SUM(p) FILTER (WHERE current), 0) >= :min_expected
                ORDER BY expected DESC, key NULLS LAST
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def gap_examples(
        self, group_by: str, scope: Scope, schema_hash: str, start, end, keys: Iterable[Optional[str]],
        min_probability: float, per_group: int,
    ) -> List[dict]:
        """Example questions of docs-gap groups: turns in ``[start, end]`` that are a gap at ``min_probability``
        or better, under the group they most likely belong to, the likeliest first.

        Returns:
            ``key``, ``message_id``, ``conversation_id``, ``prompt`` (its first 200 characters), ``p`` (the
            turn's share of the group's gaps) and ``timestamp``.
        """
        keys = list(keys)
        named = [k for k in keys if k is not None]
        params: Dict[str, Any] = {"start": start, "end": end, "prev_start": start, "keys": named,
                                  "with_null": None in keys, "min_p": float(min_probability),
                                  "per_group": int(per_group)}
        cte = self._gaps_cte(group_by, scope, schema_hash, params)
        result = self._conn.execute(
            text(
                f"""
                WITH g AS ({cte}),
                ranked AS (
                    SELECT g.*, ROW_NUMBER() OVER (PARTITION BY g.key ORDER BY g.p DESC, g.occurred_at DESC) AS rank
                    FROM g
                    WHERE g.current AND g.usual AND g.gap >= :min_p
                      AND (g.key = ANY(CAST(:keys AS text[])) OR (g.key IS NULL AND :with_null))
                )
                SELECT r.key, CAST(r.message_id AS text) AS message_id,
                       CAST(r.conversation_id AS text) AS conversation_id, LEFT(m.prompt, 200) AS prompt,
                       r.p, m.timestamp
                FROM ranked r
                JOIN conversation_messages m ON m.id = r.message_id
                WHERE r.rank <= :per_group
                ORDER BY r.key, r.rank
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def source_names(self, source_ids: Iterable[str]) -> Dict[str, str]:
        """``{id: name}`` of the given sources (UUIDs only), for the docs-gap source groups."""
        from docsgpt.storage.db.base_repository import looks_like_uuid

        ids = sorted({str(i) for i in source_ids if i and looks_like_uuid(str(i))})
        if not ids:
            return {}
        result = self._conn.execute(
            text("SELECT CAST(id AS text) AS id, name FROM sources WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": ids},
        )
        return {row.id: row.name for row in result.fetchall() if row.name}

    def log_rows(self, message_ids: Iterable[str], schema_hash: str) -> List[dict]:
        """The label rows behind Logs chips for the given messages: their own turn labels, the reactions they
        made, and their conversation's tags.

        Returns:
            ``target`` (the message the row describes), ``agent_id``, ``label`` and ``probabilities``.
        """
        ids = sorted({str(i) for i in message_ids})
        if not ids:
            return []
        own = sorted({label for side, label, _ in LOG_LABELS.values() if side == "message"})
        replies = sorted({label for side, label, _ in LOG_LABELS.values() if side == "reply"})
        result = self._conn.execute(
            text(
                f"""
                SELECT CAST(l.message_id AS text) AS target, CAST(l.agent_id AS text) AS agent_id, l.label,
                       l.probabilities
                FROM conversation_labels l
                WHERE l.message_id = ANY(CAST(:ids AS uuid[])) AND l.label = ANY(CAST(:own AS text[]))
                  AND l.schema_hash = :schema_hash
                UNION ALL
                SELECT CAST(l.reply_message_id AS text), CAST(l.agent_id AS text), l.label, l.probabilities
                FROM conversation_labels l
                WHERE l.reply_message_id = ANY(CAST(:ids AS uuid[])) AND l.label = ANY(CAST(:replies AS text[]))
                  AND l.schema_hash = :schema_hash
                UNION ALL
                SELECT CAST(m.id AS text), CAST(l.agent_id AS text), l.label, l.probabilities
                FROM conversation_messages m
                JOIN conversation_labels l
                    ON l.conversation_id = m.conversation_id AND {_conversation_level("l")}
                   AND l.label LIKE 'tag:%' AND l.schema_hash = :schema_hash
                WHERE m.id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"ids": ids, "own": own, "replies": replies, "schema_hash": schema_hash},
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def tag_names(self, agent_ids: Iterable[str]) -> Dict[str, str]:
        """``{tag id: name}`` over the given agents' current analytics tags."""
        ids = sorted({str(i) for i in agent_ids if i})
        if not ids:
            return {}
        result = self._conn.execute(
            text(
                "SELECT a.config->'analytics'->'tags' AS tags FROM agents a WHERE a.id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": ids},
        )
        names: Dict[str, str] = {}
        for row in result.fetchall():
            for tag in row.tags if isinstance(row.tags, list) else []:
                if isinstance(tag, dict) and tag.get("id") and tag.get("name"):
                    names[str(tag["id"])] = str(tag["name"])
        return names
