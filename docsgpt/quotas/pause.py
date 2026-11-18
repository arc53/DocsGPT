"""Why a schedule, an agent's outside access or a team's connection is paused for its payer.

A pause is derived from the accounts, team roles and allowance it depends on
each time someone asks, at run time (the scheduler, the outside-access gates)
and when a payload is built, by the same functions. Nothing is written when a
pause starts or ends: a reactivated account, a member re-added with the role,
someone taking over, or a new allowance window resumes it by itself.

The reasons, strongest first (:data:`PAUSE_REASONS`):

* ``owner_inactive``: an account it runs on is deactivated (the agent's
  person owner, the schedule's setter, the outside access's payer).
* ``team_locked``: outside access only: the agent's team is locked (its
  outside policy, ``docsgpt/workspaces/outside.py``), which pauses every way
  in from outside for everyone, signed-in link visitors included, until it
  unlocks.
* ``payer_left``: on a team agent, the payer no longer holds the role that
  pays for it: the setter of a schedule ``manage_schedules`` (Editor and up),
  the payer of outside access ``manage_access_details`` (the role the team's
  outside policy gives it: Admin and up, or Editor and up). A personal agent
  never has this reason.
* ``no_payer``: nobody can be billed: a schedule stored under a team's
  principal, or a team agent with outside access on and no payer.
* ``payer_out_of_allowance``: the payer's allowance is used up, until the
  window resets (``until``).

The agent's own limit is not a payer pause and is not reported here.

A team's connection (:func:`connection_pause`) is paid for by the person who
connected it (``connected_by``), who must stay an Admin of the team. The first
three reasons apply to it (:data:`ACCOUNT_PAUSES`): while one holds, the
account is not used at all. Out of allowance only holds back its scheduled
syncs; anything a person starts is paid by that person.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from docsgpt.quotas.payer import published_access_payer
from docsgpt.quotas.service import QuotaExceeded, QuotaService
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.outside import POLICY_LOCKED
from docsgpt.workspaces.outside import team_policy as _team_policy
from docsgpt.workspaces.principal import is_principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least, team_role_for

OWNER_INACTIVE = "owner_inactive"
TEAM_LOCKED = "team_locked"
PAYER_LEFT = "payer_left"
NO_PAYER = "no_payer"
PAYER_OUT_OF_ALLOWANCE = "payer_out_of_allowance"

#: Every pause reason, strongest first: when several hold, the first is reported.
PAUSE_REASONS = (OWNER_INACTIVE, TEAM_LOCKED, PAYER_LEFT, NO_PAYER, PAYER_OUT_OF_ALLOWANCE)

#: The reasons a team's connection is not used at all (no sync, no picker, no tool call), strongest first.
ACCOUNT_PAUSES = (OWNER_INACTIVE, PAYER_LEFT, NO_PAYER)

#: The team role the person who connected a team's account must keep (the role that manages connections).
_CONNECTOR_ROLE = "admin"

#: Agent columns that say whether outside access is on (``has_outside_access``).
_ACCESS_COLUMNS = ("key", "shared_token", "incoming_webhook_token")


@dataclass(frozen=True)
class Pause:
    """Why something is paused.

    Attributes:
        reason: One of :data:`PAUSE_REASONS`.
        payer: The person it is paused for, or None when nobody pays (``no_payer``).
        until: When it resumes by itself (the allowance window's reset), else None.
        left_team: For ``payer_left``: True when the payer is no longer in the
            team, False when they are still in it with a role too low to pay;
            None for the other reasons.
    """

    reason: str
    payer: Optional[str]
    until: Optional[datetime] = None
    left_team: Optional[bool] = None

    def payload(self) -> dict:
        """The ``paused_for`` shape payloads carry.

        Returns:
            ``{reason, until}``, ``until`` an ISO string or None, plus
            ``left_team`` for ``payer_left``.
        """
        body = {"reason": self.reason, "until": self.until.isoformat() if self.until else None}
        if self.reason == PAYER_LEFT:
            body["left_team"] = self.left_team
        return body


class PayerChecks:
    """What one request has already learned about payers, so a list checks each distinct payer once.

    Caches each payer's allowance check, each person's team role, each team's
    outside policy, each account's deactivation and each person's email. Make
    one per request (or per list) and pass it to every :func:`schedule_pause`
    and :func:`outside_access_pause` call; never keep it across requests,
    since roles and allowances change.
    """

    def __init__(self) -> None:
        self._quota: dict[tuple, Optional[QuotaExceeded]] = {}
        self._roles: dict[tuple, Optional[str]] = {}
        self._policies: dict[str, str] = {}
        self._inactive: dict[str, bool] = {}
        self._emails: dict[str, Optional[str]] = {}

    def quota(self, user_id: str, bucket: str, now: Optional[datetime] = None) -> Optional[QuotaExceeded]:
        """``QuotaService.check(user_id, bucket)``, once per payer, bucket and instant.

        Args:
            user_id: A person.
            bucket: ``agent`` or ``direct``.
            now: Reference instant, for tests.

        Returns:
            Why the payer may not start a run, or None.
        """
        key = (user_id, bucket, now)
        if key not in self._quota:
            self._quota[key] = QuotaService.check(user_id, bucket, now)
        return self._quota[key]

    def team_role(self, conn: Any, user_id: str, team_id: str) -> Optional[str]:
        """A person's role in a team (``team_role_for``), once per person and team.

        Args:
            conn: Open connection.
            user_id: The person.
            team_id: The team.

        Returns:
            ``owner``, ``admin``, ``editor``, ``viewer`` or None when not in the team.
        """
        key = (user_id, team_id)
        if key not in self._roles:
            self._roles[key] = team_role_for(conn, user_id, team_id)
        return self._roles[key]

    def policy(self, conn: Any, team_id: str) -> str:
        """A team's outside policy (``outside.team_policy``), once per team.

        Args:
            conn: Open connection.
            team_id: The team.

        Returns:
            ``admins``, ``editors`` or ``locked`` (``locked`` for a team that can't be read).
        """
        if team_id not in self._policies:
            self._policies[team_id] = _team_policy(conn, team_id)
        return self._policies[team_id]

    def deactivated(self, conn: Any, *user_ids: Optional[str]) -> bool:
        """Whether any of ``user_ids`` is a deactivated account; each id is looked up once.

        Args:
            conn: Open connection.
            *user_ids: User ids; empty ones are ignored.

        Returns:
            True when at least one of them is deactivated.
        """
        ids = [str(user_id) for user_id in user_ids if user_id]
        unknown = [user_id for user_id in ids if user_id not in self._inactive]
        if unknown:
            inactive = UsersRepository(conn).deactivated_among(unknown)
            for user_id in unknown:
                self._inactive[user_id] = user_id in inactive
        return any(self._inactive[user_id] for user_id in ids)

    def emails(self, conn: Any, user_ids: Iterable[Optional[str]]) -> dict[str, str]:
        """The stored email of each of ``user_ids``, looking up in one query only the ids not yet seen.

        A list passes every row's person first, so each row's own lookup is then answered from the cache.

        Args:
            conn: Open connection.
            user_ids: User ids; empty ones are ignored.

        Returns:
            ``{user_id: email}`` for the ids with an email on file; the rest are absent.
        """
        ids = [str(user_id) for user_id in user_ids if user_id]
        unknown = list(dict.fromkeys(user_id for user_id in ids if user_id not in self._emails))
        if unknown:
            found = UsersRepository(conn).emails_for(unknown)
            for user_id in unknown:
                self._emails[user_id] = found.get(user_id)
        return {user_id: self._emails[user_id] for user_id in ids if self._emails[user_id]}


def _holds(checks: PayerChecks, conn: Any, user_id: str, team_id: str, action: str) -> bool:
    """Whether a person's team role still allows ``action`` on the team's agents under the team's outside policy."""
    # Imported here: the access module pulls in the whole API layer.
    from docsgpt.api.user.resource_access import workspace_minimum

    minimum = workspace_minimum("agent", action, policy=checks.policy(conn, team_id))
    return minimum is not None and role_at_least(checks.team_role(conn, user_id, team_id), minimum)


def _person(user_id: Any) -> Optional[str]:
    """``user_id`` when it names a person, else None (empty, or a team's principal)."""
    if not user_id or is_principal_id(user_id):
        return None
    return str(user_id)


def _owner(agent: Mapping[str, Any]) -> Optional[str]:
    return agent.get("user_id") or agent.get("user") or None


def _outside_access_off(agent: Mapping[str, Any]) -> bool:
    """Whether the row shows every way in from outside switched off.

    A row without any of those columns can't say so and counts as on, so a
    gate handed a partial row never lets traffic through for that reason.
    """
    if not any(column in agent for column in _ACCESS_COLUMNS):
        return False
    return not (
        agent.get("key")
        or (agent.get("shared") and agent.get("shared_token"))
        or agent.get("incoming_webhook_token")
    )


def schedule_pause(
    conn: Any,
    schedule: Mapping[str, Any],
    agent: Optional[Mapping[str, Any]],
    *,
    checks: Optional[PayerChecks] = None,
    now: Optional[datetime] = None,
) -> Optional[Pause]:
    """Why a schedule's runs are paused for its payer (the person who set it), or None when they may run.

    Args:
        conn: Open connection.
        schedule: The schedule row (``user_id``, its setter and payer).
        agent: The agent it runs (``user_id``, ``id``, ``key``), or the agentless config.
        checks: The request's :class:`PayerChecks`; a fresh one when None.
        now: Reference instant for the allowance window, for tests.

    Returns:
        The strongest :class:`Pause` that holds, or None. A schedule a person
        paused, or auto-pause stopped (``schedules.status``), is not reported here.
    """
    checks = checks or PayerChecks()
    agent = agent or {}
    owner = _owner(agent)
    setter = _person(schedule.get("user_id"))
    if checks.deactivated(conn, _person(owner), setter):
        return Pause(OWNER_INACTIVE, setter)
    team_id = team_of_principal(owner)
    if team_id and setter and not _holds(checks, conn, setter, team_id, "manage_schedules"):
        return Pause(PAYER_LEFT, setter, left_team=checks.team_role(conn, setter, team_id) is None)
    if setter is None:
        return Pause(NO_PAYER, None)
    # As the run's own pre-check: traffic through an agent, keyed or not, is the agent bucket.
    bucket = "agent" if (agent.get("key") or agent.get("id") or agent.get("_id")) else "direct"
    exceeded = checks.quota(setter, bucket, now)
    if exceeded is not None:
        return Pause(PAYER_OUT_OF_ALLOWANCE, setter, exceeded.resets_at)
    return None


def outside_access_pause(
    conn: Any,
    agent: Optional[Mapping[str, Any]],
    *,
    checks: Optional[PayerChecks] = None,
    now: Optional[datetime] = None,
) -> Optional[Pause]:
    """Why an agent's outside access (key, widget, link, webhook, ``/v1``, MCP) is paused, or None.

    Its payer is :func:`~docsgpt.quotas.payer.published_access_payer`: the
    team agent's ``access_payer_id``, or a personal agent's owner.

    Args:
        conn: Open connection.
        agent: The agent row (``user_id``, ``access_payer_id`` and the access
            columns ``key``, ``shared``, ``shared_token``, ``incoming_webhook_token``), or None.
        checks: The request's :class:`PayerChecks`; a fresh one when None.
        now: Reference instant for the allowance window, for tests.

    Returns:
        The strongest :class:`Pause` that holds, or None (also when nothing is
        switched on, so nothing is paused).
    """
    if not agent or _outside_access_off(agent):
        return None
    checks = checks or PayerChecks()
    owner = _owner(agent)
    payer = _person(published_access_payer(agent))
    if checks.deactivated(conn, _person(owner), payer):
        return Pause(OWNER_INACTIVE, payer)
    team_id = team_of_principal(owner)
    if team_id and checks.policy(conn, team_id) == POLICY_LOCKED:
        return Pause(TEAM_LOCKED, payer)
    if team_id and payer and not _holds(checks, conn, payer, team_id, "manage_access_details"):
        return Pause(PAYER_LEFT, payer, left_team=checks.team_role(conn, payer, team_id) is None)
    if payer is None:
        # A personal agent always has its owner to pay; only a broken row has neither.
        return Pause(NO_PAYER, None) if owner else None
    exceeded = checks.quota(payer, "agent", now)
    if exceeded is not None:
        return Pause(PAYER_OUT_OF_ALLOWANCE, payer, exceeded.resets_at)
    return None


def connection_pause(
    conn: Any,
    row: Mapping[str, Any],
    *,
    checks: Optional[PayerChecks] = None,
    allowance: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Pause]:
    """Why a team's connection is paused for the person who connected it, or None when it may be used.

    Args:
        conn: Open connection.
        row: The ``connector_sessions`` row (``user_id``, ``connected_by``).
        checks: The request's :class:`PayerChecks`; a fresh one when None.
        allowance: Also check that person's allowance (the ``direct`` bucket
            graph extraction bills), for a scheduled sync; other uses are paid
            by whoever starts them.
        now: Reference instant for the allowance window, for tests.

    Returns:
        The strongest :class:`Pause` that holds, or None. Always None for a
        personal connection: its owner uses it and pays as they always have.
    """
    owner = row.get("user_id")
    if not is_principal_id(owner):
        return None
    checks = checks or PayerChecks()
    payer = _person(row.get("connected_by"))
    team_id = team_of_principal(owner)
    if payer and checks.deactivated(conn, payer):
        return Pause(OWNER_INACTIVE, payer)
    if payer and team_id:
        role = checks.team_role(conn, payer, team_id)
        if not role_at_least(role, _CONNECTOR_ROLE):
            return Pause(PAYER_LEFT, payer, left_team=role is None)
    if payer is None or team_id is None:
        return Pause(NO_PAYER, None)
    if allowance:
        exceeded = checks.quota(payer, "direct", now)
        if exceeded is not None:
            return Pause(PAYER_OUT_OF_ALLOWANCE, payer, exceeded.resets_at)
    return None
