"""Team principals: the ``users`` row that owns a team workspace's items.

A team's principal id is ``'__team__' || teams.id`` (migration 0065). It is a
``users`` row of kind ``team``, created with the team, and it is never a login,
a member, a grant owner or a payer. The id is derivable from the team id and
recognisable by its prefix alone, so the auth boundary can refuse it without
a database read. It has no ``:``, so it is safe in storage paths on Windows.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Connection

#: The reserved prefix of every principal id; no person's id may start with it.
PRINCIPAL_PREFIX = "__team__"

#: Notices that still reach someone when a principal owns the item and no person started the work:
#: the team's admins (and owner) hear about failures; anything else with no actor is dropped.
ADMIN_NOTICE_KINDS = frozenset(
    {"schedule_failed", "schedule_paused", "docs_gaps", "sync_failed", "source.ingest.failed", "payer_left"}
)


def canonical_team_id(team_id: Any) -> Optional[str]:
    """The canonical (lower-case) UUID string of ``team_id``, or None when it isn't one."""
    if team_id is None or team_id == "":
        return None
    try:
        return str(UUID(str(team_id)))
    except (TypeError, ValueError, AttributeError):
        return None


def principal_id(team_id: Any) -> str:
    """The principal id of a team.

    Args:
        team_id: The team's UUID (a ``UUID`` or its string, any case).

    Returns:
        str: ``'__team__' + <canonical team id>``.

    Raises:
        ValueError: ``team_id`` is not a UUID.
    """
    canonical = canonical_team_id(team_id)
    if canonical is None:
        raise ValueError(f"not a team id: {team_id!r}")
    return f"{PRINCIPAL_PREFIX}{canonical}"


def is_principal_id(user_id: Any) -> bool:
    """Whether ``user_id`` has the principal prefix (syntax only, no database read).

    Args:
        user_id: Any value; only a string can be a principal id.

    Returns:
        bool: True for a string starting with :data:`PRINCIPAL_PREFIX`.
    """
    return isinstance(user_id, str) and user_id.startswith(PRINCIPAL_PREFIX)


def team_of_principal(user_id: Any) -> Optional[str]:
    """The team id a principal id names.

    Args:
        user_id: A user id.

    Returns:
        Optional[str]: The canonical team id, or None when ``user_id`` is not a well-formed principal id.
    """
    if not is_principal_id(user_id):
        return None
    return canonical_team_id(user_id[len(PRINCIPAL_PREFIX):])


def create_principal(conn: Connection, team_id: Any) -> dict:
    """Create the team's principal row if it is missing, and return it.

    ``TeamsRepository.create`` calls this in the same transaction as the team insert.

    Args:
        conn: Open connection (the caller's transaction).
        team_id: The team's id.

    Returns:
        dict: The principal ``users`` row.
    """
    from docsgpt.storage.db.repositories.users import UsersRepository

    return UsersRepository(conn).create_team_principal(team_id)


def route_owner_notice(
    conn: Connection, owner_id: Optional[str], actor_id: Optional[str], kind: str
) -> list[str]:
    """Who gets a notice addressed to an item's owner.

    A person owner gets it as before. When the owner is a team principal (whose
    stream nobody reads), the person who started the work gets it; with no
    such person, a failure kind (:data:`ADMIN_NOTICE_KINDS`) goes to the team's
    admins and owner, and anything else is dropped.

    Args:
        conn: Open connection.
        owner_id: The item's owner (``users.user_id``).
        actor_id: The person who started the work, if any.
        kind: The notice or event kind.

    Returns:
        list[str]: Person ids to notify, sorted; empty to drop the notice.
    """
    if not owner_id:
        return []
    if not is_principal_id(owner_id):
        return [owner_id]
    if actor_id and not is_principal_id(actor_id):
        return [actor_id]
    if kind not in ADMIN_NOTICE_KINDS:
        return []
    team_id = team_of_principal(owner_id)
    if team_id is None:
        return []
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    return TeamsRepository(conn).admin_ids(team_id)
