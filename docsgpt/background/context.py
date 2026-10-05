"""Which turns may hand a tool call off, and which conversations a finished job may resume.

``bind_turn`` is the one hook a chat turn calls: it puts a
:class:`BackgroundContext` on the turn's ``ToolExecutor``. An executor
without one (scheduled and webhook runs, workflow nodes, continuation turns,
research steps built elsewhere) runs every call in the foreground as before.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy import Connection, text

from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class BackgroundContext:
    """What a hand-off needs to know about the turn it happens in.

    Attributes:
        user_id: The conversation's owner (the turn's caller).
        conversation_id: The conversation the job reports back to.
        origin_message_id: The turn's reserved message.
        agent_id: The agent the turn runs.
        api_route: The OpenAI-compatible ``/v1`` route, whose clients can't be
            resumed: jobs there are poll-only.
    """

    user_id: str
    conversation_id: str
    origin_message_id: Optional[str] = None
    agent_id: Optional[str] = None
    api_route: bool = False
    _auto_resume: Optional[bool] = field(default=None, repr=False)

    @property
    def yield_seconds(self) -> float:
        """How long a call runs in the foreground before it is handed off."""
        return float(max(1, int(settings.BACKGROUND_YIELD_SECONDS)))

    def auto_resume(self) -> bool:
        """Whether a finished job resumes this conversation (looked up once, on the first hand-off)."""
        if self._auto_resume is None:
            try:
                from docsgpt.storage.db.session import db_readonly

                with db_readonly() as conn:
                    self._auto_resume = auto_resume_allowed(
                        conn, self.conversation_id, self.user_id, api_route=self.api_route
                    )
            except Exception:
                logger.exception("auto-resume policy lookup failed; the job is poll-only")
                self._auto_resume = False
        return bool(self._auto_resume)


def bind_turn(
    executor: Any,
    *,
    conversation_id: Optional[str],
    message_id: Optional[str],
    decoded_token: Optional[Dict[str, Any]],
    agent_id: Optional[str] = None,
    api_route: bool = False,
) -> Optional[BackgroundContext]:
    """Let this chat turn hand slow tool calls off to background jobs.

    Only a persisted, interactive turn qualifies: it has a conversation and a
    reserved message to report back to, and its executor is not headless or a
    workflow node's.

    Args:
        executor: The turn's ``ToolExecutor``.
        conversation_id: The turn's conversation.
        message_id: The turn's reserved message.
        decoded_token: The caller's token; its ``sub`` owns the jobs.
        agent_id: The agent the turn runs.
        api_route: True on ``/v1``: jobs are handed off but never auto-resumed.

    Returns:
        The context set on the executor, or None when the turn does not qualify.
    """
    if executor is None or not settings.BACKGROUND_JOBS_ENABLED:
        return None
    user_id = (decoded_token or {}).get("sub")
    if not conversation_id or not message_id or not user_id:
        return None
    if getattr(executor, "headless", False) or getattr(executor, "workflow_run_id", None):
        return None
    context = BackgroundContext(
        user_id=str(user_id),
        conversation_id=str(conversation_id),
        origin_message_id=str(message_id),
        agent_id=str(agent_id) if agent_id else None,
        api_route=bool(api_route),
    )
    try:
        executor.background = context
    except Exception:
        logger.debug("executor does not take a background context")
        return None
    return context


def auto_resume_allowed(
    conn: Connection, conversation_id: str, user_id: str, *, api_route: bool = False
) -> bool:
    """Whether a finished job may start a continuation turn in this conversation.

    Continuation turns are billed to the conversation's owner and run with the
    owner's tools, so they are limited to conversations the owner holds
    outright: not API-key or widget traffic (``api_key``), not a shared
    agent's public link (``is_shared_usage``), not ``/v1``, and not an agent
    somebody else owns. Those get poll-only jobs.

    Args:
        conn: A database connection.
        conversation_id: The conversation.
        user_id: Who the job belongs to.
        api_route: The turn came through ``/v1``.

    Returns:
        True when the conversation may be resumed.
    """
    if not settings.AUTO_RESUME_ENABLED or api_route:
        return False
    row = conn.execute(
        text(
            "SELECT c.user_id, c.api_key, c.is_shared_usage, c.agent_id, a.user_id AS agent_owner "
            "FROM conversations c LEFT JOIN agents a ON a.id = c.agent_id "
            "WHERE c.id = CAST(:id AS uuid)"
        ),
        {"id": str(conversation_id)},
    ).fetchone()
    if row is None:
        return False
    mapping = row._mapping
    if mapping["user_id"] != user_id or mapping["api_key"] or mapping["is_shared_usage"]:
        return False
    if mapping["agent_id"] is not None and mapping["agent_owner"] != user_id:
        return False
    return True
