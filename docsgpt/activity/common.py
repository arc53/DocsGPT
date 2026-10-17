"""Helpers the Activity modules share: running a query, reading its timestamps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.storage.db.base_repository import row_to_dict


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
