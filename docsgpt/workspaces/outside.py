"""Who may take a team's items outside the team: the team's outside policy.

Outside means another team (a whole-team share of an agent, source, tool or
prompt) and every way in that reaches people who aren't members: an agent's
API key, widget, public link and webhook. A team picks one policy
(``teams.outside_policy``):

* ``admins`` (the default): its Admins and Owner;
* ``editors``: Editors too;
* ``locked``: nobody, the Owner included. Outside access on the team's agents
  and its shares with other teams pause (nothing is rewritten, so unlocking
  brings them back), and moving items out and exporting stop as well.

Viewers never take anything outside. Only Admins and the Owner change the
policy, and once it is locked only the Owner unlocks it.

A team that receives a share uses the item with fixed, view-level actions
(:data:`RECEIVER_ACTIONS`): it can't change it, publish it or pass it on.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from sqlalchemy import Connection, text

from docsgpt.workspaces.principal import canonical_team_id
from docsgpt.workspaces.roles import role_at_least

POLICY_ADMINS = "admins"
POLICY_EDITORS = "editors"
POLICY_LOCKED = "locked"

#: Every outside policy, in the order the team page offers them.
POLICIES = (POLICY_ADMINS, POLICY_EDITORS, POLICY_LOCKED)

#: The policy of a new team, and of every team that existed before the setting.
DEFAULT_POLICY = POLICY_ADMINS

#: Error code of something refused because the team is locked.
CODE_TEAM_LOCKED = "team_locked"

#: Error code of an Admin trying to change a locked team's policy.
CODE_POLICY_OWNER_ONLY = "policy_owner_only"

#: The weakest team role that may take items outside, per policy (None: nobody).
_MINIMUM = {POLICY_ADMINS: "admin", POLICY_EDITORS: "editor", POLICY_LOCKED: None}

#: What a team that receives a share may do with the item: use it, nothing more.
RECEIVER_ACTIONS: dict[str, frozenset] = {
    "agent": frozenset({"use", "pin"}),
    "source": frozenset({"use"}),  # browse files and chunks, test retrieval, attach to agents
    "tool": frozenset({"use", "use_in_own"}),
    "prompt": frozenset({"use"}),
}


def outside_minimum(policy: Optional[str]) -> Optional[str]:
    """The weakest team role that may take the team's items outside under ``policy``.

    Args:
        policy: One of :data:`POLICIES`.

    Returns:
        Optional[str]: ``admin`` or ``editor``; None when nobody may (``locked``, or an unknown value,
        which is read as locked so a bad value never opens anything).
    """
    return _MINIMUM.get(policy or "")


def may_take_outside(role: Optional[str], policy: Optional[str]) -> bool:
    """Whether a team role may share the team's items with another team, or switch outside access on.

    Args:
        role: The person's role in the team (``owner``, ``admin``, ``editor``, ``viewer``) or None.
        policy: The team's policy.

    Returns:
        bool: True when the policy lets that role do it.
    """
    minimum = outside_minimum(policy)
    return minimum is not None and role_at_least(role, minimum)


def may_set_policy(role: Optional[str], current: Optional[str], new: Optional[str]) -> bool:
    """Whether a team role may change the team's policy from ``current`` to ``new``.

    Admins and the Owner change it while it isn't locked; once locked, only the Owner may.
    An instance admin has no team role and so no way in here: ownership is transferred instead.

    Args:
        role: The caller's role in the team.
        current: The policy now.
        new: The policy asked for.

    Returns:
        bool: True when the change is allowed (also for a no-op change).
    """
    if new not in POLICIES or not role_at_least(role, "admin"):
        return False
    if current == POLICY_LOCKED or current not in POLICIES:
        return role == "owner"
    return True


# Per-read memo of :func:`team_policy`, on only inside :func:`cached_policies`.
_POLICY_CACHE: ContextVar[Optional[dict]] = ContextVar("outside_policy_cache", default=None)


@contextmanager
def cached_policies() -> Iterator[None]:
    """Remember each team's policy for the rest of one read (``resource_access.cached_resolves`` enters it).

    Only for reads: a write must see a policy change at once.
    """
    token = _POLICY_CACHE.set({})
    try:
        yield
    finally:
        _POLICY_CACHE.reset(token)


def _read_policy(conn: Connection, team_id: Optional[str], lock: Optional[str] = None) -> str:
    if team_id is None:
        return POLICY_LOCKED
    suffix = {"share": " FOR SHARE", "update": " FOR UPDATE"}.get(lock or "", "")
    value = conn.execute(
        text(f"SELECT outside_policy FROM teams WHERE id = CAST(:id AS uuid){suffix}"), {"id": team_id}
    ).scalar()
    return value if value in POLICIES else POLICY_LOCKED


def team_policy(conn: Connection, team_id: Optional[str], *, lock: Optional[str] = None) -> str:
    """A team's outside policy.

    Args:
        conn: Open connection.
        team_id: The team's id.
        lock: ``share`` or ``update`` to lock the team row for the rest of the transaction (a write that
            must not race a policy change); a locked read is never memoised.

    Returns:
        str: One of :data:`POLICIES`; ``locked`` for a missing team or a malformed id, so a team that
        can't be read never lets anything out.
    """
    canonical = canonical_team_id(team_id)
    cache = _POLICY_CACHE.get()
    if lock or cache is None or canonical is None:
        return _read_policy(conn, canonical, lock)
    if canonical not in cache:
        cache[canonical] = _read_policy(conn, canonical)
    return cache[canonical]
