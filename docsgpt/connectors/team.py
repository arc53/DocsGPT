"""Who may do what with a connection, and who owns a new one.

A personal connection is its owner's alone. A team's connection is owned by
the team's principal and records the person who connected it
(``connected_by``). Every member may see it, Editors may sync its sources,
Admins manage it, and only the person who connected it, while still an Admin,
browses the account (the picker, file and repository lists, choosing what a
source syncs): the account is theirs, so nobody else looks inside it, other
Admins included. Anyone outside the team, and anyone asking about someone
else's personal connection, is told it doesn't exist. Instance admins get no
override, and a team principal never acts on a connection itself.

A connection is a team's only when the request says so (``owner=team``) and
the caller is an Admin of the team the workspace header names; without it a
new connection is the caller's own, whatever the header. Routes about one
connection go by the row's owner and ignore the header.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from flask import Response, jsonify, make_response

from docsgpt.quotas.pause import PayerChecks, connection_pause
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.workspaces.principal import is_principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least

#: The ``owner`` value that asks for a team connection on a create route.
OWNER_TEAM = "team"
#: The ``owner`` value (and the payload's) of a person's own connection.
OWNER_PERSONAL = "personal"

#: The least team role each action on a team connection needs. ``pick`` (browse the account) also needs the
#: caller to be the person who connected it.
CONNECTION_ACTIONS = {"view": "viewer", "sync": "editor", "manage": "admin", "pick": "admin"}

#: Error codes a refused or unusable connection answers with (mapped to copy by the frontend).
CONNECTION_NOT_FOUND = "connection_not_found"
CONNECTION_ADMIN_REQUIRED = "connection_admin_required"
CONNECTION_PICKER_OWNER_ONLY = "connection_picker_owner_only"
CONNECTION_PAUSED = "connection_paused"
ACCOUNT_ALREADY_CONNECTED = "account_already_connected"
TEAM_CONNECTION_OUTSIDE = "team_connection_outside"
#: The existing workspace code an Editor-level action answers below Editor.
_ROLE_REQUIRED = "workspace_role_required"


class ConnectionDenied(Exception):
    """A refused connection action: an HTTP status, a stable error code and a message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def response(self) -> Response:
        """The JSON error response, ``{"success": false, "error": code, "message"}``."""
        return make_response(jsonify({"success": False, "error": self.code, "message": self.message}), self.status)


def _not_found() -> ConnectionDenied:
    return ConnectionDenied(404, CONNECTION_NOT_FOUND, "Connection not found")


@dataclass(frozen=True)
class ConnectionAccess:
    """What one person may do with one connection.

    Attributes:
        row: The ``connector_sessions`` row.
        owner_id: Its owner: a person, or a team's principal.
        team_id: The owning team, or None for a personal connection.
        role: The person's team role (``viewer`` … ``owner``), or ``owner`` on their own personal connection.
        connected_by: The person who connected a team's account (the row's ``connected_by``); None on a
            personal connection.
        user: The person this access is for.
    """

    row: Mapping[str, Any] = field(repr=False)
    owner_id: str
    team_id: Optional[str]
    role: Optional[str]
    connected_by: Optional[str]
    user: Optional[str] = None

    @property
    def is_team(self) -> bool:
        """Whether the connection is a team's."""
        return self.team_id is not None

    def can(self, action: str) -> bool:
        """Whether the person may do ``action`` (see :data:`CONNECTION_ACTIONS`).

        Args:
            action: ``view``, ``sync``, ``manage`` or ``pick``.

        Returns:
            True when allowed.

        Raises:
            ValueError: An unknown action.
        """
        minimum = _minimum(action)
        if not self.is_team:
            return self.role == "owner"
        if not role_at_least(self.role, minimum):
            return False
        if action == "pick":
            return bool(self.user) and self.user == self.connected_by
        return True

    def allowed_actions(self) -> list[str]:
        """Every action the person may do, in :data:`CONNECTION_ACTIONS` order."""
        return [action for action in CONNECTION_ACTIONS if self.can(action)]


def _minimum(action: str) -> str:
    try:
        return CONNECTION_ACTIONS[action]
    except KeyError:
        raise ValueError(f"unknown connection action: {action!r}") from None


def is_team_connection(row: Optional[Mapping[str, Any]]) -> bool:
    """Whether ``row`` is a team's connection (owned by a team's principal).

    Args:
        row: A ``connector_sessions`` row, or None.

    Returns:
        True for a team's connection.
    """
    return bool(row) and is_principal_id(row.get("user_id"))


def connection_access(
    conn: Any, row: Mapping[str, Any], user: Optional[str], *, checks: Optional[PayerChecks] = None
) -> Optional[ConnectionAccess]:
    """What ``user`` may do with a connection row, or None when it is none of theirs.

    Args:
        conn: Open connection.
        row: The ``connector_sessions`` row.
        user: The person asking.
        checks: The request's :class:`PayerChecks`, to look up each team role once across a list.

    Returns:
        Their :class:`ConnectionAccess`, or None: someone else's personal connection, a team they are not
        in, or a principal asking.
    """
    if not user or is_principal_id(user) or not row:
        return None
    owner = row.get("user_id")
    if not is_principal_id(owner):
        if owner != user:
            return None
        return ConnectionAccess(row, owner, None, "owner", None, user)
    team_id = team_of_principal(owner)
    if team_id is None:
        return None
    role = (checks or PayerChecks()).team_role(conn, user, team_id)
    if role is None:
        return None
    return ConnectionAccess(row, owner, team_id, role, row.get("connected_by"), user)


def authorize_connection(
    conn: Any, connection_id: Any, user: Optional[str], action: str, *, for_update: bool = False
) -> ConnectionAccess:
    """Load a connection and check ``user`` may do ``action`` with it.

    Args:
        conn: Open connection.
        connection_id: The connection's id.
        user: The person asking (the request's ``sub``).
        action: ``view``, ``sync``, ``manage`` or ``pick``.
        for_update: Lock the row until the transaction ends, so what is decided from it still holds when
            it is written.

    Returns:
        The person's :class:`ConnectionAccess`.

    Raises:
        ConnectionDenied: 404 ``connection_not_found`` when it doesn't exist or is none of theirs; 403
            ``connection_picker_owner_only`` for ``pick`` by anyone but the Admin who connected it;
            403 ``connection_admin_required`` for ``manage`` (or ``pick``) below Admin; 403
            ``workspace_role_required`` for ``sync`` below Editor.
        ValueError: An unknown action.
    """
    minimum = _minimum(action)
    repo = ConnectorSessionsRepository(conn)
    row = None
    if connection_id:
        row = repo.get_for_update(str(connection_id)) if for_update else repo.get(str(connection_id))
    access = connection_access(conn, row, user) if row else None
    if access is None:
        raise _not_found()
    if access.can(action):
        return access
    if action == "pick" and user != access.connected_by:
        raise ConnectionDenied(
            403, CONNECTION_PICKER_OWNER_ONLY, "Only the person who connected this account can browse it"
        )
    if minimum == "admin":
        raise ConnectionDenied(403, CONNECTION_ADMIN_REQUIRED, "This needs the admin role in the team")
    raise ConnectionDenied(403, _ROLE_REQUIRED, f"This needs the {minimum} role in the team")


def creation_owner(conn: Any, user: str, owner_param: Optional[str]) -> tuple[str, Optional[str]]:
    """Who owns a connection ``user`` is creating, and who is recorded as connecting it.

    Personal unless the request asks for the team (``owner=team``); the header's team is never inferred, so a
    chat's "Connect" card sent from a team still makes a personal connection.

    Args:
        conn: Open connection.
        user: The person creating it.
        owner_param: The request's ``owner`` value: None, empty or ``personal``, or ``team``.

    Returns:
        ``(user, None)`` for a personal connection; ``(the team's principal, user)`` for the team the
        workspace header names.

    Raises:
        WorkspaceError: 400 ``invalid_owner`` for any other value; 400 ``team_workspace_required`` when no
            team is named; 404 ``workspace_not_found`` outside that team; 403 ``workspace_role_required``
            below Admin.
    """
    from docsgpt.workspaces.context import WorkspaceError, current_workspace, require_workspace_role

    value = (owner_param or "").strip().lower()
    if value in ("", OWNER_PERSONAL):
        return user, None
    if value != OWNER_TEAM:
        raise WorkspaceError(400, "invalid_owner", "owner must be personal or team")
    workspace = current_workspace(conn)
    if not workspace.is_team:
        raise WorkspaceError(400, "team_workspace_required", "Switch to the team to connect an account for it")
    require_workspace_role(workspace, CONNECTION_ACTIONS["manage"])
    if is_principal_id(user):
        raise WorkspaceError(403, _ROLE_REQUIRED, "A team can't connect an account by itself")
    return workspace.owner_id, user


def connection_fields(
    conn: Any, row: Mapping[str, Any], viewer: Optional[str], *, checks: Optional[PayerChecks] = None
) -> dict:
    """The owner, pause and permission fields a connection payload carries for ``viewer``.

    Args:
        conn: Open connection.
        row: The ``connector_sessions`` row.
        viewer: The person reading it.
        checks: The request's :class:`PayerChecks`, shared across a list.

    Returns:
        ``{owner, team_id, connected_by, paused_for, allowed_actions, can_pick}``: ``owner`` is ``personal``
        or ``team``; ``connected_by`` is ``{user_id, label}`` (their email when on file, else their id;
        named to every member, also after they left) or None; ``paused_for`` is why the account can't be
        used (``Pause.payload()``, account pauses only) or None; ``can_pick`` is False while it is paused.
    """
    checks = checks or PayerChecks()
    access = connection_access(conn, row, viewer, checks=checks)
    allowed = access.allowed_actions() if access else []
    if not is_team_connection(row):
        return {
            "owner": OWNER_PERSONAL, "team_id": None, "connected_by": None, "paused_for": None,
            "allowed_actions": allowed, "can_pick": "pick" in allowed,
        }
    pause = connection_pause(conn, row, checks=checks)
    person = row.get("connected_by")
    connected_by = None
    if person:
        label = checks.emails(conn, [person]).get(person)
        connected_by = {"user_id": person, "label": label or person}
    return {
        "owner": OWNER_TEAM,
        "team_id": team_of_principal(row.get("user_id")),
        "connected_by": connected_by,
        "paused_for": pause.payload() if pause else None,
        "allowed_actions": allowed,
        "can_pick": "pick" in allowed and pause is None,
    }
