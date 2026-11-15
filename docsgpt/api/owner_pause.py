"""Outside access to a deactivated owner's agents pauses.

While the account that owns an agent is deactivated (``users.active = false``,
set by an admin or by SCIM), the ways in that run on that person's credentials
without a signed-in teammate are refused at run time: the agent's API key (and
the widget that uses it), its public share link, its incoming webhook, and its
schedules, as well as schedules a deactivated person set on someone else's
agent. Nothing is deleted or rewritten, so reactivating the account brings them
all back. A teammate with a team grant keeps chatting with the agent in the
app, as grants did before.

The same pause applies while the agent's published-access payer
(``agents.access_payer_id``, the person billed for that outside traffic) is
deactivated. A team agent (owned by its team's principal, which is never
"deactivated") whose published access names no payer is refused with
``no_payer`` instead: nobody can be billed for it.

An outside caller is told only that the agent is paused, never whose account it
is or why.
"""

from __future__ import annotations

from typing import Any, Optional

from docsgpt.quotas.payer import NO_PAYER_CODE, NO_PAYER_MESSAGE, published_access_payer
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import is_principal_id

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


class AgentNoPayerError(AgentPausedError):
    """An outside run of a team agent whose published access names nobody to bill."""

    code = NO_PAYER_CODE
    message = NO_PAYER_MESSAGE


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


def outside_access_refusal(conn: Any, agent: Optional[dict]) -> Optional[AgentPausedError]:
    """Why outside access to ``agent`` (key, widget, webhook, public link, ``/v1``) is refused, or None.

    Args:
        conn: Open database connection.
        agent: The agent row (``user_id``, ``access_payer_id``), or None.

    Returns:
        :class:`AgentNoPayerError` when nobody pays for the agent's outside
        traffic (a team agent with no published-access payer),
        :class:`AgentPausedError` when its owner or that payer is deactivated,
        else None.
    """
    if not agent:
        return None
    owner = agent.get("user_id") or agent.get("user")
    payer = published_access_payer(agent)
    if payer is None:
        return AgentNoPayerError() if owner else None
    # A principal owner is never "deactivated"; the person billed for the traffic can be.
    person_owner = None if is_principal_id(owner) else owner
    if any_deactivated(conn, person_owner, payer):
        return AgentPausedError()
    return None


def refuse_if_owner_deactivated(conn: Any, agent: Optional[dict]) -> None:
    """Raise when outside access to ``agent`` is refused (see :func:`outside_access_refusal`).

    Args:
        conn: Open database connection.
        agent: The agent row (needs ``user_id``), or None.

    Raises:
        AgentPausedError: The owner or the published-access payer is
            deactivated; :class:`AgentNoPayerError` (a subclass, code
            ``no_payer``) when nobody pays for the agent's outside traffic.
    """
    refusal = outside_access_refusal(conn, agent)
    if refusal is not None:
        raise refusal
