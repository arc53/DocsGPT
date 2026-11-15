"""Helpers the Activity modules share: running a query, reading its timestamps, scoping it to a workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.storage.db.base_repository import row_to_dict
from docsgpt.workspaces.principal import PRINCIPAL_PREFIX

#: The bound parameter holding the workspace's team id as text (NULL for Personal).
WS_PARAM = "ws_team"


def owner_team_sql(column: str) -> str:
    """SQL for the team (as text) whose principal ``column`` names; NULL for a person or NULL.

    Args:
        column: An owner column, e.g. ``a.user_id``.

    Returns:
        str: A parenthesized SQL text expression.
    """
    return (
        f"(CASE WHEN left({column}, {len(PRINCIPAL_PREFIX)}) = '{PRINCIPAL_PREFIX}' "
        f"THEN substr({column}, {len(PRINCIPAL_PREFIX) + 1}) END)"
    )


def schedule_team_sql(schedule: str = "s", agent: str = "a") -> str:
    """SQL for a schedule's workspace team (as text): its agent's team, else its origin chat's.

    Args:
        schedule: The ``schedules`` alias.
        agent: The alias of ``agents`` joined on the schedule's agent.

    Returns:
        str: A parenthesized SQL text expression; NULL for Personal.
    """
    return (
        f"(CASE WHEN {schedule}.agent_id IS NOT NULL THEN {owner_team_sql(agent + '.user_id')} "
        f"ELSE (SELECT ws_oc.team_id::text FROM conversations ws_oc WHERE ws_oc.id = {schedule}.origin_conversation_id)"
        " END)"
    )


def in_workspace_sql(team_expr: str) -> str:
    """SQL that holds when ``team_expr`` (a team id as text, NULL for Personal) is the request's workspace.

    The workspace comes in as the :data:`WS_PARAM` bound parameter
    (:func:`workspace_params`).

    Args:
        team_expr: A SQL text expression.

    Returns:
        str: A parenthesized boolean SQL expression.
    """
    return f"(({team_expr}) IS NOT DISTINCT FROM CAST(:{WS_PARAM} AS text))"


def workspace_params(team_id: Optional[str]) -> Dict[str, Any]:
    """The bound parameter :func:`in_workspace_sql` reads.

    Args:
        team_id: The workspace's team id, or None for Personal.

    Returns:
        dict: ``{WS_PARAM: team id or None}``.
    """
    return {WS_PARAM: str(team_id) if team_id else None}


def query_rows(conn: Connection, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run ``sql`` and return its rows as dicts.

    Args:
        conn: A connection.
        sql: The query.
        params: Its bound parameters.

    Returns:
        The rows, through ``row_to_dict`` (timestamps come back as ISO text).
    """
    return [row_to_dict(r) for r in conn.execute(text(sql), params).fetchall()]


def parse_time(value: Any) -> datetime:
    """``value`` (a datetime or ISO text) as an aware datetime; naive means UTC.

    Args:
        value: The timestamp.

    Returns:
        The aware datetime.

    Raises:
        ValueError: When the text is not ISO 8601.
        TypeError: When ``value`` can't be read as one.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def as_datetime(value: Any) -> Optional[datetime]:
    """Like ``parse_time``, but ``None`` for an empty or unreadable value.

    Args:
        value: The timestamp (a row value from ``query_rows``, say).

    Returns:
        The aware datetime, or ``None``.
    """
    if value in (None, ""):
        return None
    try:
        return parse_time(value)
    except (TypeError, ValueError):
        return None
