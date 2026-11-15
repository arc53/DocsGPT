"""Outside access to a deactivated owner's agents pauses.

While the account that owns an agent is deactivated (``users.active = false``,
set by an admin or by SCIM), the ways in that run on that person's credentials
without a signed-in teammate are refused at run time: the agent's API key (and
the widget that uses it), its public share link, its incoming webhook, and its
schedules, as well as schedules a deactivated person set on someone else's
agent. Nothing is deleted or rewritten, so reactivating the account brings them
all back. A teammate with a team grant keeps chatting with the agent in the
app, as grants did before.

An outside caller is told only that the agent is paused, never whose account it
is or why.
"""

from __future__ import annotations

from typing import Any, Optional

from docsgpt.storage.db.repositories.users import UsersRepository

# The code and message every refused outside request carries.
PAUSED_CODE = "agent_paused"
PAUSED_MESSAGE = "This agent is paused, so it can't answer right now."

# The reason a skipped schedule run and the agent and schedule payloads carry.
OWNER_INACTIVE = "owner_inactive"


class AgentPausedError(Exception):
    """An outside run of an agent whose owner's account is deactivated."""

    code = PAUSED_CODE
    message = PAUSED_MESSAGE

    def __init__(self) -> None:
        super().__init__(self.message)


def any_deactivated(conn: Any, *user_ids: Optional[str]) -> bool:
    """Whether any of ``user_ids`` belongs to a deactivated account.

    An id with no ``users`` row is active, as for personal access tokens.

    Args:
        conn: Open database connection.
        *user_ids: User ids; empty ones are ignored.

    Returns:
        True when at least one of them is deactivated.
    """
    ids = [str(user_id) for user_id in user_ids if user_id]
    return bool(ids) and bool(UsersRepository(conn).deactivated_among(ids))


def refuse_if_owner_deactivated(conn: Any, agent: Optional[dict]) -> None:
    """Raise :class:`AgentPausedError` when ``agent``'s owner is deactivated.

    Args:
        conn: Open database connection.
        agent: The agent row (needs ``user_id``), or None.

    Raises:
        AgentPausedError: The owner's account is deactivated.
    """
    if agent and any_deactivated(conn, agent.get("user_id") or agent.get("user")):
        raise AgentPausedError()
