"""An agent's gap summary: what kinds of gaps its answers had, by topic, over the last 30 days.

One shape serves the agent drawer's first screen (``GET /api/drafter/agent_gaps``), the agent recipe's improve
mode and its read tools. It is Insights data only, read under the agent's scope (all its traffic, as its owner's
Insights page reads it): expected counts summed from the decision model's ``gap_type`` probabilities, weighted
by the turn's topic share when the agent asks a topic question. No model call.

:class:`InsightsReader` serves the recipe's live read tools (``get_gap_examples``, ``get_conversations``) and
:func:`conversation_excerpt` the one conversation a Logs row starts from: both read only the labels and
conversations of one agent the caller may edit, a few capped rows at a time. What they return is end users' text,
for the model fenced as data.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import Connection

from docsgpt.analytics import schema as analytics_schema
from docsgpt.analytics.insights import MIN_SAMPLE
from docsgpt.drafter import topics_recipe
from docsgpt.drafter.fencing import clean_text
from docsgpt.storage.db.repositories.conversation_labels import (
    ConversationLabelsRepository,
    LOG_LABELS,
    log_label_keys,
    MIN_GROUP_GAPS,
    Scope,
    SUMMARY_GAP_TYPES,
    TAG_PREFIX,
)

logger = logging.getLogger(__name__)

#: The window the summary reads, as Insights' "last 30 days".
DAYS = 30
#: Analysed conversations in the window before the summary is offered: Insights holds a figure until it has this many.
NEEDED = MIN_SAMPLE
#: Most rows of the summary.
MAX_ROWS = 10
#: Most questions or conversations one read tool call returns, and the characters of each text.
MAX_EXAMPLES = 5
EXAMPLE_CHARS = 200
EXCERPT_CHARS = 300
#: Characters of the question and of the answer of the conversation a Logs row starts from, and the turns read.
CONVERSATION_CHARS = 600
CONVERSATION_TURNS = 20
#: ``topics_recipe.insights_off`` reasons, as the summary names them.
_REASONS = {"off_on_this_instance": "off_on_this_instance", "turned_off_for_this_agent": "agent_off"}


def window(days: int = DAYS, now: Optional[datetime.datetime] = None) -> tuple[datetime.datetime, datetime.datetime]:
    """``(start, end)`` of the last ``days`` days as the Insights filters cut them: from the start of the first day
    to the end of today, in UTC."""
    end = now or datetime.datetime.now(datetime.timezone.utc)
    start = (end - datetime.timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, end.replace(hour=23, minute=59, second=59, microsecond=999999)


def shown_count(value: Any) -> int:
    """An expected count rounded the way the Insights page shows it (``Math.round``: halves up)."""
    return int(math.floor(float(value or 0) + 0.5))


def agent_scope(agent: dict) -> Scope:
    """The agent's labels, all its traffic (the Docs gaps panel's scope for an agent)."""
    return Scope(agent_id=str(agent["id"]), api_key=agent.get("key") or None)


def asks_topics(conn: Connection, agent: dict) -> bool:
    """Whether the agent asks a one-pick topic question, so its gaps are summed per topic.

    A broken source structure (the options read every source) counts as no question.
    """
    from docsgpt.analytics import topics as analytics_topics
    from docsgpt.analytics.config import AnalyticsConfig

    config = AnalyticsConfig.parse((agent.get("config") or {}).get("analytics"))
    try:
        return bool(analytics_topics.options(conn, agent, config))
    except Exception:
        logger.warning("drafter: no topic list for agent %s", agent.get("id"), exc_info=True)
        return False


def unavailable(reason: str, conversations: int = 0) -> dict:
    """The summary when there is none to show, ``reason`` saying why."""
    return {"available": False, "reason": reason, "conversations": conversations, "needed": NEEDED, "days": DAYS,
            "rows": []}


def agent_gaps(conn: Connection, user_id: str, agent: dict) -> dict:
    """The agent's gap summary, read through ``conn``.

    Args:
        conn: A read-only connection.
        user_id: The caller; the agent row must be one they may edit (``topics_recipe.editable_agent``). The
            summary is the agent's whole traffic, as its owner's Insights page shows it.
        agent: The agent row.

    Returns:
        ``{"available", "reason", "conversations", "needed", "days", "rows"}``. ``reason`` is
        ``off_on_this_instance``, ``agent_off`` or ``not_enough`` (fewer than ``needed`` analysed conversations
        in ``days``) when unavailable, else None; ``conversations`` counts the analysed conversations (0 while
        Insights is off). ``rows`` holds at most :data:`MAX_ROWS` ``{topic, gap_type, expected, turns,
        previous}``, the most expected gaps first: ``topic`` is None for an agent without a topic question, and
        ``previous`` is None until the period before has labelled answers.
    """
    off = topics_recipe.insights_off(agent)
    if off:
        return unavailable(_REASONS.get(off, off))
    repo = ConversationLabelsRepository(conn)
    scope = agent_scope(agent)
    schema_hash = analytics_schema.SCHEMA_HASH
    start, end = window()
    conversations = repo.gap_conversations(scope, schema_hash, start, end)
    if conversations < NEEDED:
        return unavailable("not_enough", conversations)
    by_topic = asks_topics(conn, agent)
    previous_start = start - (end - start)
    groups = repo.gap_type_groups(scope, schema_hash, start, end, previous_start, MAX_ROWS, MIN_GROUP_GAPS,
                                  by_topic=by_topic)
    compared = bool(groups) and repo.gap_labelled(scope, schema_hash, previous_start, start) > 0
    rows = [{
        "topic": group["topic"] if by_topic else None,
        "gap_type": group["gap_type"],
        "expected": shown_count(group["expected"]),
        "turns": shown_count(group["turns"]),
        "previous": shown_count(group["previous"]) if compared else None,
    } for group in groups]
    return {"available": True, "reason": None, "conversations": conversations, "needed": NEEDED, "days": DAYS,
            "rows": rows}


def agent_gaps_for(user_id: str, agent_id: str) -> dict:
    """``GET /api/drafter/agent_gaps``: :func:`agent_gaps` for an agent the caller may edit.

    Raises:
        AccessDenied: The caller can't edit the agent.
    """
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        return agent_gaps(conn, user_id, topics_recipe.editable_agent(conn, user_id, agent_id))


def _question(value: Any, limit: int) -> str:
    """One end user's text on one line, cleaned and cut."""
    return clean_text(" ".join(str(value or "").split()), limit)


@dataclass(frozen=True)
class InsightsReader:
    """Live, capped reads of one agent's labelled conversations, for the agent recipe's read tools.

    Built only for an agent the caller may edit, while its summary is available. Each call opens its own
    read-only transaction (the stream runs after the request's has closed) and reads only this agent's labels.

    Attributes:
        agent_id: The agent.
        api_key: Its key (``None`` when it has none).
        by_topic: Whether it asks a topic question, so a topic narrows the reads.
        start: The window's start.
        end: The window's end.
    """

    agent_id: str
    api_key: Optional[str]
    by_topic: bool
    start: datetime.datetime
    end: datetime.datetime

    @classmethod
    def for_summary(cls, agent: dict, summary: dict) -> "InsightsReader":
        """A reader for ``agent`` over the window of its :func:`agent_gaps` ``summary``, narrowing by topic when
        the summary is by topic."""
        start, end = window()
        by_topic = any(row["topic"] is not None for row in summary.get("rows") or [])
        return cls(str(agent["id"]), agent.get("key") or None, by_topic, start, end)

    def _scope(self) -> Scope:
        return Scope(agent_id=self.agent_id, api_key=self.api_key)

    def gap_examples(self, gap_type: str, topic: Optional[str] = None) -> list[str]:
        """Up to :data:`MAX_EXAMPLES` distinct questions that were this gap type (in ``topic``), likeliest first.

        Raises:
            ValueError: ``gap_type`` is not one of ``SUMMARY_GAP_TYPES``.
        """
        from docsgpt.core.settings import settings
        from docsgpt.storage.db.session import db_readonly

        if gap_type not in SUMMARY_GAP_TYPES:
            raise ValueError(gap_type)
        topic = topic if self.by_topic and topic else None
        with db_readonly() as conn:
            rows = ConversationLabelsRepository(conn).gap_examples(
                "topic" if topic else "all", self._scope(), analytics_schema.SCHEMA_HASH, self.start, self.end,
                [topic], settings.ANALYTICS_FILTER_MIN_PROBABILITY, MAX_EXAMPLES * 3, gap_type=gap_type,
            )
        out: list[str] = []
        for row in rows:
            text = _question(row.get("prompt"), EXAMPLE_CHARS)
            if text and text.casefold() not in {q.casefold() for q in out}:
                out.append(text)
        return out[:MAX_EXAMPLES]

    def conversations(self, label: str, topic: Optional[str] = None) -> list[dict]:
        """Up to :data:`MAX_EXAMPLES` ``{question, answer}`` excerpts the Logs filter ``label`` selects.

        Raises:
            ValueError: ``label`` is not a ``LOG_LABELS`` key.
        """
        from docsgpt.core.settings import settings
        from docsgpt.storage.db.session import db_readonly

        if label not in LOG_LABELS:
            raise ValueError(label)
        topic = topic if self.by_topic and topic else None
        with db_readonly() as conn:
            rows = ConversationLabelsRepository(conn).labelled_turns(
                self._scope(), analytics_schema.SCHEMA_HASH, self.start, self.end, label,
                settings.ANALYTICS_FILTER_MIN_PROBABILITY, MAX_EXAMPLES, topic=topic,
            )
        return [{"question": _question(row.get("prompt"), EXCERPT_CHARS),
                 "answer": clean_text(row.get("response"), EXCERPT_CHARS)} for row in rows]


def conversation_excerpt(conn: Connection, agent: dict, conversation_id: str) -> Optional[dict]:
    """One of the agent's conversations as the model reads it: a question, its answer, and their Logs labels.

    The turn is the first one that fell short by Insights' labels (a Logs label, or a likely gap type), else the
    conversation's first question.

    Args:
        conn: A read-only connection.
        agent: The agent row, one the caller may edit.
        conversation_id: The conversation the user started from.

    Returns:
        ``{"question", "answer", "labels", "gap_type"}`` (each text at most :data:`CONVERSATION_CHARS`; ``labels``
        the ``LOG_LABELS`` keys the turn carries, ``gap_type`` its likeliest gap type at the Logs filter's
        odds or None), or None when it is not the agent's conversation.
    """
    from docsgpt.core.settings import settings
    from docsgpt.storage.db.base_repository import looks_like_uuid

    if not isinstance(conversation_id, str) or not looks_like_uuid(conversation_id):
        return None
    repo = ConversationLabelsRepository(conn)
    turns = repo.agent_conversation_turns(conversation_id, str(agent["id"]), agent.get("key"), CONVERSATION_TURNS)
    if not turns:
        return None
    rows: dict[str, list[dict]] = {}
    for row in repo.log_rows([t["id"] for t in turns], analytics_schema.SCHEMA_HASH, agent_id=str(agent["id"])):
        rows.setdefault(row["target"], []).append(row)
    floor = settings.ANALYTICS_FILTER_MIN_PROBABILITY

    def keys(turn: dict) -> list[str]:
        return [k for k in log_label_keys(rows.get(turn["id"], []), floor) if not k.startswith(TAG_PREFIX)]

    def gap_type(turn: dict) -> Optional[str]:
        gap = next((r["probabilities"] or {} for r in rows.get(turn["id"], []) if r["label"] == "gap_type"), {})
        likeliest = max(SUMMARY_GAP_TYPES, key=lambda g: float(gap.get(g) or 0))
        return likeliest if float(gap.get(likeliest) or 0) >= floor else None

    turn = next((t for t in turns if keys(t) or gap_type(t)), turns[0])
    return {
        "question": clean_text(turn.get("prompt"), CONVERSATION_CHARS),
        "answer": clean_text(turn.get("response"), CONVERSATION_CHARS),
        "labels": keys(turn),
        "gap_type": gap_type(turn),
    }
