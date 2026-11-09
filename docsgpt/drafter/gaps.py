"""An agent's gap summary: what kinds of gaps its answers had, by topic, over the last 30 days.

One shape serves the agent drawer's first screen (``GET /api/drafter/agent_gaps``), the agent recipe's improve
mode and its read tools. It is Insights data only, read under the agent's scope (all its traffic, as its owner's
Insights page reads it): expected counts summed from the decision model's ``gap_type`` probabilities, weighted
by the turn's topic share when the agent asks a topic question. No model call.
"""

from __future__ import annotations

import datetime
import logging
import math
from typing import Any, Optional

from sqlalchemy import Connection

from docsgpt.analytics import schema as analytics_schema
from docsgpt.analytics.insights import MIN_SAMPLE
from docsgpt.drafter import topics_recipe
from docsgpt.storage.db.repositories.conversation_labels import (
    ConversationLabelsRepository,
    MIN_GROUP_GAPS,
    Scope,
)

logger = logging.getLogger(__name__)

#: The window the summary reads, as Insights' "last 30 days".
DAYS = 30
#: Analysed conversations in the window before the summary is offered: Insights holds a figure until it has this many.
NEEDED = MIN_SAMPLE
#: Most rows of the summary.
MAX_ROWS = 10
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
