"""Scheduled agent runs (see scheduler.md)."""

from __future__ import annotations

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class SchedulerSettings(SettingsGroup):
    """Cadence, quotas and timeouts of scheduled runs."""

    SCHEDULE_DISPATCHER_INTERVAL: int = Field(
        default=30, description="Seconds between dispatcher passes that enqueue due schedules."
    )
    SCHEDULE_MIN_INTERVAL: int = Field(default=900, description="Smallest allowed recurrence interval in seconds.")
    SCHEDULE_MAX_PER_USER: int = Field(default=50, description="Cap on schedules a user may own.")
    SCHEDULE_RUN_TIMEOUT: int = Field(default=600, description="Wall-clock cap on one scheduled run, in seconds.")
    SCHEDULE_MISFIRE_GRACE: int = Field(
        default=60, description="Seconds past the due time within which a missed run still fires."
    )
    SCHEDULE_AUTOPAUSE_FAILURES: int = Field(
        default=3, description="Consecutive failures after which a schedule is paused automatically."
    )
    SCHEDULE_ONCE_MAX_HORIZON: int = Field(
        default=31_536_000, description="How far ahead a one-off run may be scheduled, in seconds (one year)."
    )
    SCHEDULE_RUN_OUTPUT_RETENTION_DAYS: int = Field(default=90, gt=0, description="Days scheduled-run output is kept.")
