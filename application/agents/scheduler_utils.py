"""Cron/tz computations for the scheduler (shared by dispatcher, routes, and tool)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


_DELAY_RE = re.compile(r"^\s*(\d+)\s*(s|m|h|d)\s*$", re.IGNORECASE)
_DELAY_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86_400}


class ScheduleValidationError(ValueError):
    """Raised when a schedule's cron, run_at, or delay is invalid."""


def resolve_timezone(tz_name: Optional[str]) -> ZoneInfo:
    """Return a ``ZoneInfo`` for ``tz_name`` (default UTC)."""
    name = (tz_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleValidationError(f"Unknown timezone: {name}") from exc


def parse_cron(expression: str) -> None:
    """Validate a 5-field cron expression; raise on bad input."""
    # croniter defers some malformed inputs until get_next, so force one here.
    if not expression or not isinstance(expression, str):
        raise ScheduleValidationError("Cron expression is required.")
    fields = expression.strip().split()
    if len(fields) != 5:
        raise ScheduleValidationError("Cron expression must have 5 fields.")
    try:
        itr = croniter(expression, datetime.now(timezone.utc))
        itr.get_next(datetime)
    except (ValueError, KeyError) as exc:
        raise ScheduleValidationError(f"Invalid cron expression: {exc}") from exc


_CRON_INTERVAL_WINDOW = 64


def cron_interval_seconds(expression: str, tz_name: Optional[str]) -> int:
    """Return the smallest gap between ticks in a rolling window (enforces SCHEDULE_MIN_INTERVAL).

    Walks _CRON_INTERVAL_WINDOW ticks because bursty expressions like
    ``* 9 * * *`` have tiny within-burst gaps and huge between-burst gaps;
    sampling only two adjacent ticks would miss the small gap.
    """
    parse_cron(expression)
    tz = resolve_timezone(tz_name)
    anchor_local = datetime.now(timezone.utc).astimezone(tz)
    itr = croniter(expression, anchor_local)
    prev = itr.get_next(datetime)
    smallest: Optional[int] = None
    for _ in range(_CRON_INTERVAL_WINDOW - 1):
        nxt = itr.get_next(datetime)
        gap = int((nxt - prev).total_seconds())
        if gap > 0 and (smallest is None or gap < smallest):
            smallest = gap
        prev = nxt
    return smallest if smallest is not None else 0


def next_cron_run(
    expression: str,
    tz_name: Optional[str],
    after: Optional[datetime] = None,
) -> datetime:
    """Return the next fire time strictly after ``after`` (UTC, tz-aware).

    Evaluates the cadence in the schedule's IANA tz so DST boundaries land on
    the intended local clock-time (e.g. 9 AM Warsaw stays 9 AM across the jump).
    """
    parse_cron(expression)
    tz = resolve_timezone(tz_name)
    anchor_utc = after if after is not None else datetime.now(timezone.utc)
    if anchor_utc.tzinfo is None:
        anchor_utc = anchor_utc.replace(tzinfo=timezone.utc)
    anchor_local = anchor_utc.astimezone(tz)
    itr = croniter(expression, anchor_local)
    nxt_local = itr.get_next(datetime)
    return nxt_local.astimezone(timezone.utc)


def parse_delay(delay: str) -> timedelta:
    """Parse a duration like ``30m`` / ``2h`` / ``1d`` into a timedelta."""
    if not isinstance(delay, str):
        raise ScheduleValidationError("delay must be a string like '30m' or '2h'.")
    match = _DELAY_RE.match(delay)
    if not match:
        raise ScheduleValidationError(
            "delay must look like '30s', '15m', '2h', or '1d'."
        )
    amount, unit = int(match.group(1)), match.group(2).lower()
    if amount <= 0:
        raise ScheduleValidationError("delay must be positive.")
    return timedelta(seconds=amount * _DELAY_MULTIPLIERS[unit])


def parse_run_at(run_at: str, tz_name: Optional[str] = None) -> datetime:
    """Parse an ISO 8601 timestamp; naive values resolve in ``tz_name``.

    Naive values inside the DST "fall back" hour resolve to the earlier instance
    (zoneinfo default fold=0); pass an explicit offset to select the later one.
    """
    if not isinstance(run_at, str) or not run_at.strip():
        raise ScheduleValidationError("run_at must be an ISO 8601 string.")
    try:
        parsed = datetime.fromisoformat(run_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleValidationError(f"Invalid run_at: {exc}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=resolve_timezone(tz_name))
    return parsed.astimezone(timezone.utc)


def clamp_once_horizon(run_at: datetime, max_horizon_seconds: int) -> None:
    """Raise when ``run_at`` is in the past or beyond the once-task horizon."""
    now = datetime.now(timezone.utc)
    if run_at <= now:
        raise ScheduleValidationError("run_at is in the past.")
    if max_horizon_seconds > 0 and run_at - now > timedelta(seconds=max_horizon_seconds):
        raise ScheduleValidationError(
            "run_at is beyond the maximum allowed scheduling horizon."
        )
