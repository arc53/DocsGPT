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
``no_payer`` instead: nobody can be billed for it. It also pauses while that
payer no longer holds the Admin role in the agent's team (demoted, or left it),
and works again once they have the role back or someone else takes it over.

An outside caller is told only that the agent is paused, never whose account it
is or why.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from docsgpt.quotas.pause import NO_PAYER, PAYER_LEFT, PayerChecks, outside_access_pause
from docsgpt.quotas.payer import NO_PAYER_CODE, NO_PAYER_MESSAGE
from docsgpt.storage.db.repositories.users import UsersRepository

# The code and message every refused outside request carries.
PAUSED_CODE = "agent_paused"
PAUSED_MESSAGE = "This agent is paused, so it can't answer right now."

# The reason a skipped schedule run and the agent and schedule payloads carry.
OWNER_INACTIVE = "owner_inactive"

# Agent columns that switch a way in from outside on (a key, a public link, a webhook).
_ACCESS_COLUMNS = ("key", "shared", "shared_token", "incoming_webhook_token")


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


class AgentPayerLeftError(AgentPausedError):
    """An outside run of a team agent whose published-access payer no longer holds the Admin role there.

    Outside callers get the plain ``agent_paused`` code and message; ``reason``
    is for logs only.
    """

    reason = PAYER_LEFT


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


class _GateChecks(PayerChecks):
    """:class:`PayerChecks` that leaves the payer's allowance out.

    The gate refuses for the accounts and roles alone. Running out of
    allowance is enforced by the usage check before a run starts, which words
    it for outside callers, so each outside request costs no usage sum here.
    """

    def quota(self, user_id: str, bucket: str, now: Optional[datetime] = None) -> None:
        return None

    def deactivated(self, conn: Any, *user_ids: Optional[str]) -> bool:
        return any_deactivated(conn, *user_ids)


def outside_access_refusal(conn: Any, agent: Optional[dict]) -> Optional[AgentPausedError]:
    """Why outside access to ``agent`` (key, widget, webhook, public link, ``/v1``, MCP, search) is refused, or None.

    Args:
        conn: Open database connection.
        agent: The agent row (``user_id``, ``access_payer_id``), or None.

    Returns:
        :class:`AgentNoPayerError` when nobody pays for the agent's outside
        traffic (a team agent with no published-access payer),
        :class:`AgentPausedError` when its owner or that payer is deactivated,
        :class:`AgentPayerLeftError` when the payer of a team agent's outside
        access is no longer an Admin there (demoted or left), else None. The
        payer's allowance is not checked here.
    """
    if not agent:
        return None
    # The caller already came in through one of the agent's ways in, maybe
    # one turned off since (a queued webhook, a resumed turn): ask as if
    # access were on, so a closed door never reads as "nothing to pause".
    row = {key: value for key, value in agent.items() if key not in _ACCESS_COLUMNS}
    pause = outside_access_pause(conn, row, checks=_GateChecks())
    if pause is None:
        return None
    if pause.reason == NO_PAYER:
        return AgentNoPayerError()
    if pause.reason == PAYER_LEFT:
        return AgentPayerLeftError()
    return AgentPausedError()


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
