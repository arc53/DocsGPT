"""Conversation analytics: the tuning knobs of the background sweep that labels stored conversations.

Whether the decision model may label conversations at all is ``DECISION_ANALYTICS_ENABLED`` (decision model
settings); which agents are labelled, and with which topics, is each agent's own setting in the UI.
"""

from __future__ import annotations

import logging

from pydantic import Field, model_validator

from docsgpt.core.settings._shared import SettingsGroup

logger = logging.getLogger(__name__)

# (backfill, retention) pairs already warned about: a process builds Settings more than once (``docsgpt doctor``
# three times), and the same mismatch is one warning.
_WARNED_BACKFILL_CUTS: set[tuple[int, int]] = set()


class AnalyticsSettings(SettingsGroup):
    """How the analytics sweep runs; none of these are shown in the UI."""

    ANALYTICS_QUEUE: str = Field(
        default="analytics",
        description=(
            "Celery queue of the analytics sweep and the docs-gap digest. A sweep waits on decision-model calls for "
            "minutes: a bare prefork worker still consumes the queue and gives up one process to it during a "
            "backlog, `docsgpt worker` on the solo pool (macOS, Windows) leaves it to `docsgpt worker --analytics`, "
            "and a dedicated `-Q analytics -c 1` worker isolates it."
        ),
    )
    ANALYTICS_SWEEP_SECONDS: int = Field(
        default=300,
        ge=60,
        description="Seconds between two analytics sweeps; new labels appear within about two intervals.",
    )
    ANALYTICS_SWEEP_BUDGET_SECONDS: int = Field(
        default=240,
        ge=10,
        description=(
            "Seconds one sweep may spend starting decision-model calls; shorter than the interval, so sweeps do not "
            "queue up. A call started near the end may still run to its background deadline."
        ),
    )
    ANALYTICS_BATCH_STATES: int = Field(
        default=16,
        ge=1,
        le=64,
        description=(
            "States per decision-model call, about four turns: around 25 s of compute on 4 vCPU, within the "
            "background deadline at the default share. Never more than DECISION_MAX_BATCH_STATES; below a message's "
            "states (up to four), a message is split across calls."
        ),
    )
    ANALYTICS_TURN_SETTLE_SECONDS: int = Field(
        default=60,
        ge=0,
        description="Seconds a message must be unchanged before it is labelled, so a retry or edit finishes first.",
    )
    ANALYTICS_CONVERSATION_IDLE_MINUTES: int = Field(
        default=30,
        ge=1,
        description="Minutes after its last message before a conversation's own labels (goal met, tags) are asked.",
    )
    ANALYTICS_RESOLUTION_WINDOW_HOURS: int = Field(
        default=24,
        ge=1,
        description="Hours of silence after which a conversation's resolution is no longer pending.",
    )
    ANALYTICS_BACKFILL_DAYS: int = Field(
        default=7,
        ge=1,
        description=(
            "Days back the sweep labels, newest first; also how far rows from an older model are relabelled. A value "
            "past ANALYTICS_RETENTION_DAYS is cut to it, with a warning."
        ),
    )
    ANALYTICS_RETENTION_DAYS: int = Field(
        default=90,
        ge=1,
        description=(
            "Days conversation labels are kept, by message time, before the cleanup task removes them; labels are "
            "also deleted with their conversation."
        ),
    )
    ANALYTICS_MAX_TOPICS: int = Field(
        default=15,
        ge=2,
        le=15,
        description=(
            "Most topics that don't overlap an agent's topic question offers: the decision model's 16 options less "
            "'none of these'. The owner's own topics come first; the agent's source folders fill what is left, "
            "largest first."
        ),
    )
    ANALYTICS_MAX_OVERLAPPING_TOPICS: int = Field(
        default=20,
        ge=0,
        le=50,
        description=(
            "Most topics that can overlap per agent; each is one more question per conversation. 0 turns them off."
        ),
    )
    ANALYTICS_FILTER_MIN_PROBABILITY: float = Field(
        default=0.5,
        gt=0.0,
        lt=1.0,
        description=(
            "Probability a label needs for the Logs label filter, its chips and the docs-gap examples. Rates never "
            "use it: they are sums of probabilities."
        ),
    )

    @model_validator(mode="after")
    def _backfill_within_retention(self) -> "AnalyticsSettings":
        """Cut ANALYTICS_BACKFILL_DAYS to ANALYTICS_RETENTION_DAYS, with a warning, rather than refuse to start.

        Rows past retention are purged, so a longer backfill would label them again on every sweep. The
        mismatch must not stop the API, the worker or the CLI, which load these settings whether analytics is on
        or not. Each mismatch is logged once per process, however often the settings are built.

        Returns:
            These settings, with the backfill no longer than retention.
        """
        if self.ANALYTICS_BACKFILL_DAYS > self.ANALYTICS_RETENTION_DAYS:
            cut = (self.ANALYTICS_BACKFILL_DAYS, self.ANALYTICS_RETENTION_DAYS)
            if cut not in _WARNED_BACKFILL_CUTS:
                _WARNED_BACKFILL_CUTS.add(cut)
                logger.warning(
                    "ANALYTICS_BACKFILL_DAYS (%d) exceeds ANALYTICS_RETENTION_DAYS (%d); labelling %d days back",
                    *cut, self.ANALYTICS_RETENTION_DAYS,
                )
            self.ANALYTICS_BACKFILL_DAYS = self.ANALYTICS_RETENTION_DAYS
        return self
