"""Background jobs (slow tool calls handed off from a turn) and auto-resume (continuation turns)."""

from __future__ import annotations

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class BackgroundSettings(SettingsGroup):
    """How long a turn waits on a tool call, what a handed-off job may use, and when the agent is resumed."""

    BACKGROUND_JOBS_ENABLED: bool = Field(
        default=True,
        description=(
            "Hand a slow tool call off to a background job instead of keeping the turn waiting on it. Off, every "
            "call runs in the foreground until its own timeout, as before."
        ),
    )
    BACKGROUND_YIELD_SECONDS: int = Field(
        default=30,
        ge=1,
        description=(
            "Seconds a chat turn waits on a server-side tool call before handing it off to a background job. A "
            "call that finishes sooner behaves exactly as before."
        ),
    )
    BACKGROUND_JOB_MAX_SECONDS: int = Field(
        default=1000,
        ge=1,
        description=(
            "Hard lifetime of one background job in seconds; past it the job is failed. Matches "
            "SANDBOX_EXEC_MAX_TIMEOUT by default."
        ),
    )
    BACKGROUND_MAX_JOBS_PER_CONVERSATION: int = Field(
        default=2,
        ge=0,
        description=(
            "Running background jobs one conversation may have. Over the cap a slow call keeps running in the "
            "foreground; it never fails because of the cap."
        ),
    )
    BACKGROUND_MAX_JOBS_PER_USER: int = Field(
        default=5,
        ge=0,
        description="Running background jobs one user may have, across conversations; same over-cap rule.",
    )
    BACKGROUND_RESULT_RETENTION_DAYS: int = Field(
        default=7,
        gt=0,
        description="Days a finished background job and its result are kept.",
    )
    BACKGROUND_POOL_SIZE: int = Field(
        default=16,
        ge=1,
        description=(
            "Threads per API or worker process that run tool calls a turn may hand off. A call that finds the "
            "pool full runs inline, as before."
        ),
    )
    AUTO_RESUME_ENABLED: bool = Field(
        default=True,
        description=(
            "Resume the agent in the same conversation when a background job finishes, so the result reaches "
            "the user without them asking. Off, results wait for check_job or the user's next message."
        ),
    )
    AUTO_RESUME_MAX_RESULT_CHARS: int = Field(
        default=16000,
        ge=500,
        description="Characters of one job result a continuation turn sees; longer results keep their head and tail.",
    )
    AUTO_RESUME_MAX_CONSECUTIVE: int = Field(
        default=5,
        ge=1,
        description=(
            "Continuation turns a conversation may get in a row without a user message in between. Past it, "
            "results wait for check_job or the user's next message, so a job that starts a job cannot loop."
        ),
    )
