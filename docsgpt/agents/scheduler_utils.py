"""Cron/tz computations for the scheduler (shared by dispatcher, routes, and tool)."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


# One or more ``<amount><unit>`` parts, largest unit first by convention but
# not enforced: ``30m``, ``1h20m``, ``2d 4h``.
_DELAY_RE = re.compile(r"^\s*(?:\d+\s*[smhd]\s*)+$", re.IGNORECASE)
_DELAY_PART_RE = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
_DELAY_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86_400}


class ScheduleValidationError(ValueError):
    """Raised when a schedule's cron, run_at, or delay is invalid."""


def resolve_timezone(tz_name: Optional[str]) -> ZoneInfo:
    """Return a ``ZoneInfo`` for ``tz_name`` (default UTC)."""
    name = (tz_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    # A directory ("America"), a path or an over-long name raises OSError or
    # ValueError rather than ZoneInfoNotFoundError.
    except (ZoneInfoNotFoundError, OSError, ValueError) as exc:
        raise ScheduleValidationError(f"Unknown timezone: {name[:64]}") from exc


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


def cron_runs(
    expression: str,
    tz_name: Optional[str],
    *,
    after: datetime,
    until: datetime,
    limit: int,
) -> List[datetime]:
    """Return the fire times strictly after ``after`` and before ``until`` (UTC, tz-aware).

    The same times as calling ``next_cron_run`` from each fire time in turn,
    for expanding a schedule over a window: the expression is validated and
    the zone resolved once, and one iterator walks the local clock, so DST
    lands as it does there.

    A cron's times of day are the same on every day it fires (the minute and
    hour fields don't depend on the date), so the walk goes one step at a
    time only through the first whole day and days whose clock changes. On
    any other day it steps once, to find the day, and repeats the times. A
    croniter step costs about 17µs, and a 15-minute cron has 4,032 of them
    in six weeks.

    Args:
        expression: A 5-field cron expression.
        tz_name: The schedule's IANA zone (default UTC).
        after: Exclusive lower bound.
        until: Exclusive upper bound.
        limit: The most times returned.

    Returns:
        Up to ``limit`` fire times, oldest first.

    Raises:
        ScheduleValidationError: The expression or the zone is invalid.
    """
    parse_cron(expression)
    tz = resolve_timezone(tz_name)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    seen = after.astimezone(tz)
    itr = croniter(expression, seen)
    # Offsets from local midnight of one whole day without a clock change.
    times: Optional[List[timedelta]] = None
    out: List[datetime] = []
    fire = itr.get_next(datetime)
    while len(out) < limit:
        day = fire.date()
        start = _local_midnight(day, tz)
        plain = _local_midnight(day + timedelta(days=1), tz) - start == timedelta(days=1)
        if plain and times is not None:
            since = fire.astimezone(timezone.utc) - start
            for offset in times:
                if offset < since:
                    continue
                at = start + offset
                if at >= until or len(out) >= limit:
                    return out
                out.append(at)
            # On to the next day the cron fires.
            seen = (start + times[-1]).astimezone(tz)
            itr = croniter(expression, seen)
            fire = itr.get_next(datetime)
            continue
        whole = seen.date() < day
        offsets: List[timedelta] = []
        while fire.date() == day:
            at = fire.astimezone(timezone.utc)
            if at >= until or len(out) >= limit:
                return out
            out.append(at)
            offsets.append(at - start)
            seen = fire
            fire = itr.get_next(datetime)
        if plain and whole and times is None:
            times = offsets
    return out


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    """The start of ``day`` on the ``tz`` clock, in UTC."""
    return datetime.combine(day, time(), tzinfo=tz).astimezone(timezone.utc)


def parse_delay(delay: str) -> timedelta:
    """Parse a duration like ``30m`` / ``2h`` / ``1h20m`` into a timedelta."""
    if not isinstance(delay, str):
        raise ScheduleValidationError("delay must be a string like '30m' or '2h'.")
    if not _DELAY_RE.match(delay):
        raise ScheduleValidationError(
            "delay must look like '30s', '15m', '2h', '1d', or a combination such as '1h30m'."
        )
    seconds = sum(
        int(amount) * _DELAY_MULTIPLIERS[unit.lower()]
        for amount, unit in _DELAY_PART_RE.findall(delay)
    )
    if seconds <= 0:
        raise ScheduleValidationError("delay must be positive.")
    return timedelta(seconds=seconds)


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
