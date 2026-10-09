"""Monitors (polled checks that wake the agent), webhook trigger links and human approval links."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class MonitorSettings(SettingsGroup):
    """What the ``monitor`` tool may watch, how often, for how long, and how trigger and approval links behave."""

    MONITORS_ENABLED: bool = Field(
        default=True,
        description=(
            "Offer the monitor tool: polled checks of a webpage or any tool, ingest events, webhook trigger links "
            "and human approval links that resume the conversation when something happens. Needs "
            "AUTO_RESUME_ENABLED, since a monitor reports back by resuming the conversation."
        ),
    )
    MONITOR_JUDGE_MODEL: Optional[str] = Field(
        default=None,
        description=(
            "Model that judges a monitor's natural-language condition, only after its deterministic check passed "
            "(or on a change when it has none). Unset uses the deployment's default model."
        ),
    )
    MONITOR_DEFAULT_INTERVAL_SECONDS: int = Field(
        default=900, ge=60, description="Seconds between checks of a polled monitor that names no interval."
    )
    MONITOR_MIN_INTERVAL_SECONDS: int = Field(
        default=300,
        ge=60,
        description="Shortest interval a polled monitor may use, in seconds; a shorter request is raised to it.",
    )
    MONITOR_DEFAULT_TTL_DAYS: int = Field(
        default=7, ge=1, description="Days a monitor (and its trigger or approval link) lives when none is named."
    )
    MONITOR_MAX_TTL_DAYS: int = Field(default=30, ge=1, description="Longest lifetime a monitor may ask for, in days.")
    MONITOR_DEFAULT_MAX_WAKES: int = Field(
        default=1, ge=1, description="Times a monitor may wake the agent when none is named; at 0 left it finishes."
    )
    MONITOR_MAX_WAKES: int = Field(default=20, ge=1, description="Most wakes one monitor may ask for.")
    MONITOR_MAX_ACTIVE_PER_USER: int = Field(
        default=5, ge=0, description="Active or paused monitors one user may have; 0 turns creating them off."
    )
    MONITOR_MAX_WAKES_PER_HOUR: int = Field(
        default=5,
        ge=1,
        description=(
            "Circuit breaker: a monitor that would wake the agent more often than this in an hour is paused, "
            "and the conversation is told why."
        ),
    )
    MONITOR_UNREACHABLE_GRACE_SECONDS: int = Field(
        default=3600,
        ge=60,
        description=(
            "How long a monitor's source may stay unreachable (device offline, server down, timeout, 5xx) before "
            "the agent is told once and the monitor pauses. Unreachable checks are skipped, never a change."
        ),
    )
    MONITOR_JUDGE_TOKEN_BUDGET: int = Field(
        default=100_000,
        ge=0,
        description=(
            "Tokens one monitor's condition judge may use over its lifetime; past it the monitor pauses and says "
            "so. 0 means no limit."
        ),
    )
    PUBLIC_APP_URL: Optional[str] = Field(
        default=None,
        description=(
            "Public address of the web UI, used for human approval links (/approve/<token>). Unset uses "
            "PUBLIC_API_BASE_URL, then API_URL: the API serves the UI itself when SERVE_UI is on. Set it when the "
            "UI runs elsewhere, e.g. http://localhost:5173 for the Vite dev server."
        ),
    )
    TRIGGER_RATE_PER_MINUTE: int = Field(
        default=30, ge=1, description="Requests one trigger link accepts per minute; more get 429."
    )
    TRIGGER_MAX_PAYLOAD_BYTES: int = Field(
        default=65536, ge=1024, description="Largest request body a trigger link accepts, in bytes; larger gets 413."
    )
    TRIGGER_GET_MAX_HITS: int = Field(
        default=100,
        ge=1,
        description=(
            "Calls a webhook link that also accepts GET takes over its lifetime (a POST-only link takes 1000). "
            "Lower, since a GET link can be fired by anything that opens it."
        ),
    )
    TRIGGER_GET_DEFAULT_TTL_HOURS: int = Field(
        default=24,
        ge=1,
        description=(
            "Default lifetime, in hours, of a webhook link that also accepts GET, when monitor_create asks for "
            "none (a POST-only link defaults to MONITOR_DEFAULT_TTL_DAYS). An explicit expires_in still applies, up "
            "to MONITOR_MAX_TTL_DAYS."
        ),
    )
    TRIGGER_DEDUPE_WINDOW_SECONDS: int = Field(
        default=600,
        ge=1,
        description=(
            "Seconds in which a trigger link delivery with the same body as an earlier one (and no "
            "Idempotency-Key, webhook-id or X-GitHub-Delivery) counts as a repeat. The same body sent later, such "
            "as a nightly job's, is a new event."
        ),
    )
