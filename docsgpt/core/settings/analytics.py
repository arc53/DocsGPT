"""Conversation analytics: the tuning knobs of the background sweep that labels stored conversations.

Whether the decision model may label conversations at all is ``DECISION_ANALYTICS_ENABLED`` (decision model
settings); which agents are labelled, and with which topics and tags, is each agent's own setting in the UI.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from docsgpt.core.settings._shared import SettingsGroup


class AnalyticsSettings(SettingsGroup):
    """How the analytics sweep runs; none of these are shown in the UI."""

    ANALYTICS_QUEUE: str = Field(
        default="analytics",
        description=(
            "Celery queue of the analytics sweep. A sweep waits on decision-model calls for minutes, so its own "
            "queue keeps it from holding a `docsgpt` or `parsing` slot; a bare worker still consumes it, and "
            "operators can isolate it with `-Q analytics -c 1`."
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
            "background deadline at the default share."
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
            "Days back the sweep labels, newest first; also how far rows from an older model are relabelled. Must "
            "not exceed ANALYTICS_RETENTION_DAYS."
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
            "Most topics an agent's topic question offers; the decision model's 16 options less 'none of these'. "
            "Automatic topic lists keep the largest sections."
        ),
    )
    ANALYTICS_MAX_TAGS: int = Field(
        default=20,
        ge=0,
        le=50,
        description="Most custom tags per agent; every tag is one more question per conversation.",
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
    def _backfill_within_retention(self):
        # Rows past retention are purged; a longer backfill would label them again on every sweep.
        if self.ANALYTICS_BACKFILL_DAYS > self.ANALYTICS_RETENTION_DAYS:
            raise ValueError("ANALYTICS_BACKFILL_DAYS must not exceed ANALYTICS_RETENTION_DAYS")
        return self
