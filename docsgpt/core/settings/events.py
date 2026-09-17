"""Server-sent events, replay journal and remote-device sessions."""

from __future__ import annotations

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class EventsSettings(SettingsGroup):
    """The internal push channel (notifications and durable replay) and the Redis pool behind it."""

    ENABLE_SSE_PUSH: bool = Field(
        default=True,
        description=(
            "Internal SSE push channel (notifications and durable replay journal). False makes /api/events emit "
            '"push_disabled" and return; clients fall back to polling.'
        ),
    )
    EVENTS_STREAM_MAXLEN: int = Field(
        default=1000, ge=1, description="Per-user durable backlog cap in entries; ~24h of replay at typical rates."
    )
    SSE_KEEPALIVE_SECONDS: int = Field(default=15, ge=1, description="Interval between SSE keepalive comments.")
    SSE_MAX_CONCURRENT_PER_USER: int = Field(
        default=8,
        ge=0,
        description=(
            "Simultaneous SSE connections per user; each holds a pooled async Redis connection for its lifetime. "
            "8 covers multi-tab use without one user starving the pool. 0 disables."
        ),
    )
    ASYNC_REDIS_MAX_CONNECTIONS: int = Field(
        default=2000,
        ge=1,
        description=(
            "Pool size of the async Redis client behind the event-loop routes, per process. Every open "
            "notification tab, chat reconnect and device session holds one connection, so this caps concurrent "
            "streams per worker (redis-py's own default is 100). Keep the total across workers below the Redis "
            "server's maxclients (10000 by default)."
        ),
    )
    EVENTS_REPLAY_MAX_PER_REQUEST: int = Field(
        default=200,
        ge=1,
        description=(
            "Backlog entries XRANGE returns per /api/events snapshot. Bounds what one replay moves from Redis to "
            "the wire: a client looping Last-Event-ID reconnects enumerates at most this many per round-trip."
        ),
    )
    EVENTS_REPLAY_MAX_AGE_HOURS: int = Field(default=48, description="Oldest backlog entry a replay will return.")
    EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW: int = Field(
        default=30,
        description=(
            "Sliding-window cap on snapshot replays per user; exhausting it returns 429 with the cursor pinned "
            "so the client backs off until the window rolls over."
        ),
    )
    EVENTS_REPLAY_BUDGET_WINDOW_SECONDS: int = Field(default=60, description="Length of the replay budget window.")
    MESSAGE_EVENTS_RETENTION_DAYS: int = Field(
        default=14,
        gt=0,
        description=(
            "Retention for the message_events journal, enforced by the cleanup_message_events beat task. Replay "
            "only needs streams a client could still be tailing."
        ),
    )

    # Remote Device feature.
    REMOTE_DEVICE_SESSION_IDLE_SECONDS: int = Field(
        default=60, gt=0, description="Seconds without a heartbeat before a remote-device session is considered idle."
    )
    REMOTE_DEVICE_REQUIRE_SIGNATURE: bool = Field(
        default=False, description="Require signed commands from remote devices."
    )
    REMOTE_DEVICE_PAIRING_TTL_SECONDS: int = Field(default=600, gt=0, description="Lifetime of a pairing code.")
    REMOTE_DEVICE_CMD_QUEUE_TTL_SECONDS: int = Field(
        default=900,
        gt=605,
        description=(
            "Redis TTL of the per-device command queue, routing invocations cross-process so a scheduled run "
            "reaches the web-held device session. Must exceed the max drain deadline (605s) so a command for a "
            "briefly-offline device isn't evicted before its own drain gives up."
        ),
    )
    REMOTE_DEVICE_INVOCATION_TTL_SECONDS: int = Field(
        default=900, gt=0, description="Redis TTL of a pending remote-device invocation."
    )
    REMOTE_DEVICE_OUTPUT_STREAM_MAXLEN: int = Field(
        default=10_000, description="Cap on buffered output entries per remote-device invocation stream."
    )
