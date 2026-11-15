"""The workspace a request works in: Personal, or a team the caller belongs to.

The client names it in the ``X-DocsGPT-Workspace`` header (``personal`` or a
team id), or in the ``workspace`` query parameter where it can't set headers
(``EventSource``, download links). No header means Personal, so old clients,
personal access tokens and scripts keep working.

The header is a request, not a credential: :func:`current_workspace` checks
membership and answers 404 ``workspace_not_found`` to a non-member, the same
as for a team that doesn't exist. Only lists, creates and new conversations
read it; a route about one item goes by the item's own workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from flask import Response, g, has_request_context, jsonify, make_response, request
from sqlalchemy import Connection

from docsgpt.storage.db.session import db_readonly
from docsgpt.workspaces.principal import canonical_team_id, is_principal_id, principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least, team_role_for

#: The request header naming the workspace.
WORKSPACE_HEADER = "X-DocsGPT-Workspace"

#: The query parameter fallback for requests that can't set headers.
WORKSPACE_PARAM = "workspace"

#: The value naming the caller's own workspace.
PERSONAL = "personal"

_G_KEY = "_docsgpt_workspaces"


class WorkspaceError(Exception):
    """A refused workspace: an HTTP status, a stable error code and a message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def response(self) -> Response:
        """The JSON error response, ``{"success": false, "error": code, "message"}``."""
        return make_response(jsonify({"success": False, "error": self.code, "message": self.message}), self.status)


@dataclass(frozen=True)
class Workspace:
    """Where a request's lists and creates live.

    Attributes:
        kind: ``personal`` or ``team``.
        team_id: The team's id (canonical), or None for Personal.
        owner_id: Who owns items created here: the caller in Personal, the team's principal in a team.
        role: The caller's role: ``owner`` in Personal; ``owner``, ``admin``, ``editor`` or ``viewer`` in a
            team; None for a team principal acting as itself.
    """

    kind: str
    team_id: Optional[str]
    owner_id: str
    role: Optional[str]

    @property
    def is_personal(self) -> bool:
        """Whether this is the caller's own workspace."""
        return self.kind == PERSONAL

    @property
    def is_team(self) -> bool:
        """Whether this is a team workspace."""
        return self.kind == "team"

    def owner_for_create(self, caller: str) -> tuple[str, str]:
        """``(owner_id, created_by)`` for an item the caller creates here.

        Args:
            caller: The person creating it.

        Returns:
            tuple[str, str]: The owner to write as, and the caller as creator.
        """
        return self.owner_id, caller


def parse_workspace_ref(req: Any = None) -> Optional[str]:
    """The team a request names, or None for Personal.

    The header wins over the query parameter; blank and ``personal`` mean Personal.

    Args:
        req: The Flask request (the current one by default).

    Returns:
        Optional[str]: The raw team reference (not yet checked), or None.
    """
    req = req if req is not None else request
    raw = req.headers.get(WORKSPACE_HEADER)
    if raw is None or not raw.strip():
        raw = req.args.get(WORKSPACE_PARAM)
    value = (raw or "").strip()
    if not value or value.lower() == PERSONAL:
        return None
    return value


def _caller() -> Optional[str]:
    token = getattr(request, "decoded_token", None)
    return token.get("sub") if isinstance(token, dict) else None


def _resolve(conn: Connection, caller: str, ref: Optional[str]) -> Workspace:
    if is_principal_id(caller):
        # A run acting as a team (an agent key) works in that team only, whatever it sends.
        return Workspace(kind="team", team_id=team_of_principal(caller), owner_id=caller, role=None)
    if ref is None:
        return Workspace(kind=PERSONAL, team_id=None, owner_id=caller, role="owner")
    team_id = canonical_team_id(ref)
    role = team_role_for(conn, caller, team_id) if team_id else None
    if role is None:
        raise WorkspaceError(404, "workspace_not_found", "Workspace not found")
    return Workspace(kind="team", team_id=team_id, owner_id=principal_id(team_id), role=role)


def current_workspace(conn: Optional[Connection] = None) -> Workspace:
    """The current request's workspace, checked against the caller's membership.

    Memoised on ``flask.g`` per caller and reference, so a request reads membership once.

    Args:
        conn: Open connection; a read-only one is opened when None.

    Returns:
        Workspace: Personal when the request names none.

    Raises:
        WorkspaceError: 401 ``authentication_required`` with no caller; 404 ``workspace_not_found`` when the
            caller is not in the named team (a malformed or unknown id included).
    """
    caller = _caller()
    if not caller:
        raise WorkspaceError(401, "authentication_required", "Authentication required")
    ref = parse_workspace_ref(request)
    cache = g.setdefault(_G_KEY, {}) if has_request_context() else {}
    key = (caller, ref)
    if key in cache:
        return cache[key]
    if conn is not None:
        workspace = _resolve(conn, caller, ref)
    else:
        with db_readonly() as own:
            workspace = _resolve(own, caller, ref)
    cache[key] = workspace
    return workspace


def require_workspace_role(workspace: Workspace, minimum: str) -> None:
    """Refuse unless the caller holds ``minimum`` or stronger in the workspace (Personal always passes).

    Args:
        workspace: From :func:`current_workspace`.
        minimum: ``viewer``, ``editor``, ``admin`` or ``owner``.

    Raises:
        WorkspaceError: 403 ``workspace_role_required``.
    """
    if workspace.is_personal:
        return
    if not role_at_least(workspace.role, minimum):
        raise WorkspaceError(403, "workspace_role_required", f"This needs the {minimum} role in the team")
