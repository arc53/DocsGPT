"""Team roles: Viewer < Editor < Admin < Owner.

The owner is ``teams.owner_id``; the other three are stored in
``team_members.role`` as ``team_viewer``, ``team_editor`` and ``team_admin``
(migration 0065). The API speaks the short names. ``team_member`` is the old
stored name of a non-admin member and is read as a viewer.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid

#: Team roles, weakest first.
TEAM_ROLES = ("viewer", "editor", "admin", "owner")

_RANK = {role: rank for rank, role in enumerate(TEAM_ROLES, start=1)}

#: The stored ``team_members.role`` of each assignable role (the owner is ``teams.owner_id``).
_STORED = {"admin": "team_admin", "editor": "team_editor", "viewer": "team_viewer"}

#: Stored or legacy names read back as API roles.
_FROM_STORED = {"team_admin": "admin", "team_editor": "editor", "team_viewer": "viewer", "team_member": "viewer"}


def role_rank(role: Optional[str]) -> int:
    """The rank of a team role (``viewer`` 1 ... ``owner`` 4); 0 for None or anything else."""
    return _RANK.get(role or "", 0)


def role_at_least(role: Optional[str], minimum: str) -> bool:
    """Whether ``role`` is ``minimum`` or stronger. None (not a member) never is."""
    return role_rank(role) > 0 and role_rank(role) >= role_rank(minimum)


def to_stored_role(role: Any) -> str:
    """The ``team_members.role`` value for an assignable role.

    Accepts the API names (``admin``, ``editor``, ``viewer``), the stored names,
    and the legacy ``team_member`` (a viewer), ignoring case and spaces.

    Args:
        role: The requested role.

    Returns:
        str: ``team_admin``, ``team_editor`` or ``team_viewer``.

    Raises:
        ValueError: Anything else, ``owner`` included (ownership is transferred, not assigned).
    """
    value = str(role or "").strip().lower()
    if value in _STORED:
        return _STORED[value]
    if value in _FROM_STORED:
        return _STORED[_FROM_STORED[value]]
    raise ValueError(f"not a team role: {role!r}")


def from_stored_role(stored: Optional[str]) -> Optional[str]:
    """The API role of a stored ``team_members.role`` (None for an unknown value)."""
    return _FROM_STORED.get(stored or "")


def legacy_member_role(role: Optional[str]) -> Optional[str]:
    """The pre-workspace ``member_role`` value kept on team payloads for today's UI.

    Args:
        role: An API role, or None.

    Returns:
        Optional[str]: ``team_admin`` for admins and the owner, ``team_member`` for the rest, None for None.
    """
    if role is None:
        return None
    return "team_admin" if role_at_least(role, "admin") else "team_member"


def team_role_for(conn: Connection, user_id: Optional[str], team_id: Any) -> Optional[str]:
    """A person's role in a team: ``owner`` for ``teams.owner_id``, else their strongest stored role.

    Instance admins get nothing implicit here: no row, no role.

    Args:
        conn: Open connection.
        user_id: The person's id.
        team_id: The team's id.

    Returns:
        Optional[str]: ``owner``, ``admin``, ``editor`` or ``viewer``; None when they are not in the team
        (or the team doesn't exist).
    """
    if not user_id or not team_id or not looks_like_uuid(str(team_id)):
        return None
    row = conn.execute(
        text(
            """
            SELECT t.owner_id = :user_id AS is_owner,
                   (SELECT array_agg(DISTINCT m.role) FROM team_members m
                    WHERE m.team_id = t.id AND m.user_id = :user_id) AS roles
            FROM teams t WHERE t.id = CAST(:team_id AS uuid)
            """
        ),
        {"user_id": user_id, "team_id": str(team_id)},
    ).fetchone()
    if row is None:
        return None
    if row[0]:
        return "owner"
    roles = [from_stored_role(r) for r in (row[1] or [])]
    roles = [r for r in roles if r]
    return max(roles, key=role_rank) if roles else None
