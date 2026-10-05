"""Calendar-aligned UTC quota windows, computed at read time (no reset job)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

PERIODS = ("day", "week", "month")


def window_bounds(period: str, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """Return ``(start, resets_at)`` of the window containing ``now``.

    Args:
        period: ``day`` (from 00:00), ``week`` (from Monday) or ``month`` (from the 1st).
        now: Reference instant; defaults to the current time. Naive values are read as UTC.

    Raises:
        ValueError: If ``period`` is not one of ``PERIODS``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return midnight, midnight + timedelta(days=1)
    if period == "week":
        start = midnight - timedelta(days=midnight.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = midnight.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        return start, next_month
    raise ValueError(f"unknown quota period: {period!r}")
