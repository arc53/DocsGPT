"""Which turns may hand a tool call off, and which conversations a finished job may resume.

``bind_turn`` is the one hook a chat turn calls: it puts a
:class:`BackgroundContext` on the turn's ``ToolExecutor``. A continuation
turn builds its own (``continuation=True``), so a woken turn can hand calls
off and check on jobs like a chat turn while staying headless (approval-gated
tools denied). An executor without one (scheduled and webhook runs, workflow
nodes, research steps built elsewhere) runs every call in the foreground as
before.
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
        continuation: A woken (headless) turn: it may hand calls off though
            nobody is in it to approve anything.
    """

    user_id: str
    conversation_id: str
    origin_message_id: Optional[str] = None
    agent_id: Optional[str] = None
    api_route: bool = False
    continuation: bool = False
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
    workflow node's. A poll-only turn (``api_route``) needs no message: its
    jobs never resume the conversation, so a ``/v1`` round resumed from a
    pause that has no row of its own still hands calls off, and offers the
    same tools as the round that paused.

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
    if not conversation_id or not user_id or not (message_id or api_route):
        return None
    if getattr(executor, "headless", False) or getattr(executor, "workflow_run_id", None):
        return None
    context = BackgroundContext(
        user_id=str(user_id),
        conversation_id=str(conversation_id),
        origin_message_id=str(message_id) if message_id else None,
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

    Continuation turns are billed to the conversation's owner, the person
    chatting, so they are limited to that person's own chats: not API-key or
    widget traffic (``api_key``), not a shared agent's public link
    (``is_shared_usage``, which its publisher pays for), and not ``/v1``.
    Those get poll-only jobs. A chat on an agent somebody else owns resumes
    while the chatter can still use that agent (a grant that still holds);
    it runs as the agent's owner, as the chat does. In a team workspace, a
    member's own chat on that team's agent resumes while they are still in the
    team (the member pays, the agent runs as the team); other team chats are
    poll-only.

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
            "SELECT c.user_id, c.api_key, c.is_shared_usage, c.agent_id, c.team_id, a.user_id AS agent_owner "
            "FROM conversations c LEFT JOIN agents a ON a.id = c.agent_id "
            "WHERE c.id = CAST(:id AS uuid)"
        ),
        {"id": str(conversation_id)},
    ).fetchone()
    if row is None:
        return False
    mapping = row._mapping
    if mapping["user_id"] != user_id or mapping["api_key"]:
        return False
    team_id = mapping.get("team_id")
    if team_id is not None:
        from docsgpt.workspaces.principal import principal_id
        from docsgpt.workspaces.roles import team_role_for

        # A team chat on the team's own agent, for someone still in the team. An
        # agentless team chat stays poll-only: a continuation would run it with
        # the member's personal tools, not the team's.
        team_agent = mapping["agent_id"] is not None and mapping["agent_owner"] == principal_id(team_id)
        return team_agent and team_role_for(conn, user_id, team_id) is not None
    if mapping["is_shared_usage"]:
        return False
    if mapping["agent_id"] is not None and mapping["agent_owner"] != user_id:
        from docsgpt.api.user.resource_access import resolve

        # Resolved live, so a revoked grant or a left team stops it on the next wake.
        access = resolve(conn, "agent", str(mapping["agent_id"]), user_id)
        return access is not None and access.can("use")
    return True
