"""An agent's own limit: tokens and requests over a rolling 24 hours.

The limit caps one agent however it is reached: chats, API key, widget and
public-link traffic, schedules, webhooks, background continuations and
workflow steps. Usage rows reach the agent through its key (``api_key``) or
its id (``agent_id``, which keyless agents and workflow steps carry), so both
count. A run is one request: its calls share a request id.

The agent limit is checked before the payer's allowance; the first one used
up is the one named.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from docsgpt.core.settings import settings
from docsgpt.quotas.service import QuotaExceededError
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository

#: The rolling window the agent limit counts over.
WINDOW_HOURS = 24


@dataclass(frozen=True)
class AgentLimitExceeded:
    """The agent limit that blocks a run.

    Attributes:
        agent_id: The agent.
        dimension: ``tokens`` or ``requests``.
        usage: What the agent used in the window.
        limit: Its limit.
    """

    agent_id: Optional[str]
    dimension: str
    usage: int
    limit: int

    @property
    def message(self) -> str:
        """The refusal, naming the agent's limit."""
        noun = "token" if self.dimension == "tokens" else "request"
        return (
            f"This agent's {noun} limit is reached ({self.usage:,} of {self.limit:,} {self.dimension} "
            f"in the last {WINDOW_HOURS} hours). Please try again later."
        )

    def to_payload(self) -> dict:
        """Return the client-facing error body."""
        return {
            "success": False,
            "error_code": "agent-limit-exceeded",
            "message": self.message,
            "limit_scope": "agent_limit",
            "dimension": self.dimension,
            "usage": self.usage,
            "limit": self.limit,
            "window_hours": WINDOW_HOURS,
        }


class AgentLimitExceededError(QuotaExceededError):
    """Raised where a run refused by its agent's limit has no HTTP response to carry the refusal.

    A :class:`QuotaExceededError`, so every headless caller stops the run the
    way it stops one over the payer's allowance, with this message as the
    reason. ``exceeded`` is the :class:`AgentLimitExceeded`.
    """

    def __init__(self, exceeded: AgentLimitExceeded) -> None:
        self.exceeded = exceeded
        Exception.__init__(self, exceeded.message)


def _flag(value: Any) -> bool:
    """A limit switch; legacy rows stored it as the string ``"True"``."""
    return value if isinstance(value, bool) else value == "True"


def has_agent_limit(agent: Mapping[str, Any]) -> bool:
    """Whether the agent has a token or request limit switched on."""
    return _flag(agent.get("limited_token_mode", False)) or _flag(agent.get("limited_request_mode", False))


def agent_limit_exceeded(
    conn: Any, agent: Mapping[str, Any], now: Optional[datetime.datetime] = None
) -> Optional[AgentLimitExceeded]:
    """Return the agent's used-up limit, or None when it may take another run.

    The check runs before a run, so the run that crosses the limit completes
    and the next one is refused.

    Args:
        conn: An open database connection.
        agent: The agent row: its limit switches and limits, ``key`` and ``id``.
        now: Reference instant, for tests.

    Returns:
        The token limit when both are used up, else the request limit, else None.
    """
    token_mode = _flag(agent.get("limited_token_mode", False))
    request_mode = _flag(agent.get("limited_request_mode", False))
    if not (token_mode or request_mode):
        return None
    raw_id = agent.get("id") or agent.get("_id")
    agent_id = str(raw_id) if raw_id and looks_like_uuid(str(raw_id)) else None
    api_key = agent.get("key") or None
    if agent_id is None and api_key is None:
        return None
    end = now or datetime.datetime.now(datetime.timezone.utc)
    window = {"start": end - datetime.timedelta(hours=WINDOW_HOURS), "end": end, "api_key": api_key,
              "agent_id": agent_id}
    repo = TokenUsageRepository(conn)
    if token_mode:
        limit = int(agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"])
        used = int(repo.sum_tokens_in_range(**window) or 0)
        if limit > 0 and used >= limit:
            return AgentLimitExceeded(agent_id=agent_id, dimension="tokens", usage=used, limit=limit)
    if request_mode:
        limit = int(agent.get("request_limit") or settings.DEFAULT_AGENT_LIMITS["request_limit"])
        used = int(repo.count_in_range(**window) or 0)
        if limit > 0 and used >= limit:
            return AgentLimitExceeded(agent_id=agent_id, dimension="requests", usage=used, limit=limit)
    return None
