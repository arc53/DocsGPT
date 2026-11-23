"""Who may do what with a custom model, and who owns a new one.

A person's custom model is theirs alone. A team's custom model is owned by the
team's principal, which seals its key, and records the Admin who added it
(``created_by``). Every member sees it and may use it (Editors set it on the
team's agents and workflows, as their role already allows), and Admins and
the Owner add, edit, test and delete it. Only they see its base URL. Anyone
outside the team, and anyone asking about someone else's personal model, is
told it doesn't exist. Instance admins get no override, and a team principal
never acts on a model itself.

A model is a team's only when the request says so (``owner=team``) and the
caller is an Admin of the team the workspace header names; without it a new
model is the caller's own, whatever the header. Routes about one model go by
the row's owner and ignore the header. An item may only name custom models its
own owner owns, so a person's model never runs in a team and a team's model
never runs outside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from flask import Response, jsonify, make_response

from docsgpt.quotas.pause import PayerChecks
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.workspaces.principal import is_principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least

#: The ``owner`` value that asks for a team's model on a create or list route.
OWNER_TEAM = "team"
#: The ``owner`` value (and the payload's) of a person's own model.
OWNER_PERSONAL = "personal"

#: The least team role each action on a team's model needs. Setting a model on a team item is ``use``
#: plus the item's own edit role, which the item's routes check.
MODEL_ACTIONS = {"view": "viewer", "use": "viewer", "manage": "admin"}

#: Error codes a refused model action answers with (mapped to copy by the frontend).
CODE_MODEL_NOT_FOUND = "model_not_found"
CODE_MODEL_ADMIN_REQUIRED = "model_admin_required"
#: A team's model named on a personal item, or on another team's item.
CODE_CUSTOM_MODEL_TEAM_ONLY = "custom_model_team_only"
#: An import into a team needs a new team model, which only an Admin may add.
CODE_CUSTOM_MODEL_ADMIN_REQUIRED = "custom_model_admin_required"
#: The PAT rule table's code, reused for a team model's writes, which tokens may not make.
CODE_NOT_AVAILABLE_TO_TOKENS = "not_available_to_tokens"
_ROLE_REQUIRED = "workspace_role_required"


class ModelDenied(Exception):
    """A refused model action: an HTTP status, a stable error code and a message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def response(self) -> Response:
        """The JSON error response, ``{"success": false, "error": code, "message"}``."""
        return make_response(jsonify({"success": False, "error": self.code, "message": self.message}), self.status)


def _not_found() -> ModelDenied:
    return ModelDenied(404, CODE_MODEL_NOT_FOUND, "Model not found")


def _minimum(action: str) -> str:
    try:
        return MODEL_ACTIONS[action]
    except KeyError:
        raise ValueError(f"unknown model action: {action!r}") from None


@dataclass(frozen=True)
class ModelAccess:
    """What one person may do with one custom model.

    Attributes:
        row: The ``user_custom_models`` row.
        owner_id: Its owner: a person, or a team's principal. The key is sealed with it.
        team_id: The owning team, or None for a person's own model.
        role: The person's team role (``viewer`` … ``owner``), or ``owner`` on their own model.
        user: The person this access is for.
    """

    row: Mapping[str, Any] = field(repr=False)
    owner_id: str
    team_id: Optional[str]
    role: Optional[str]
    user: Optional[str] = None

    @property
    def is_team(self) -> bool:
        """Whether the model is a team's."""
        return self.team_id is not None

    def can(self, action: str) -> bool:
        """Whether the person may do ``action`` (see :data:`MODEL_ACTIONS`).

        Args:
            action: ``view``, ``use`` or ``manage``.

        Returns:
            True when allowed.

        Raises:
            ValueError: An unknown action.
        """
        minimum = _minimum(action)
        if not self.is_team:
            return self.role == "owner"
        return role_at_least(self.role, minimum)

    def allowed_actions(self) -> list[str]:
        """Every action the person may do, in :data:`MODEL_ACTIONS` order."""
        return [action for action in MODEL_ACTIONS if self.can(action)]


def is_team_model(row: Optional[Mapping[str, Any]]) -> bool:
    """Whether ``row`` is a team's custom model (owned by a team's principal).

    Args:
        row: A ``user_custom_models`` row, or None.

    Returns:
        True for a team's model.
    """
    return bool(row) and is_principal_id(row.get("user_id"))


def model_access(
    conn: Any, row: Optional[Mapping[str, Any]], user: Optional[str], *, checks: Optional[PayerChecks] = None
) -> Optional[ModelAccess]:
    """What ``user`` may do with a model row, or None when it is none of theirs.

    Args:
        conn: Open connection.
        row: The ``user_custom_models`` row.
        user: The person asking.
        checks: The request's :class:`PayerChecks`, to look up each team role once across a list.

    Returns:
        Their :class:`ModelAccess`, or None: someone else's personal model, a team they are not in, or a
        principal asking.
    """
    if not user or is_principal_id(user) or not row:
        return None
    owner = row.get("user_id")
    if not is_principal_id(owner):
        if owner != user:
            return None
        return ModelAccess(row, owner, None, "owner", user)
    team_id = team_of_principal(owner)
    if team_id is None:
        return None
    role = (checks or PayerChecks()).team_role(conn, user, team_id)
    if role is None:
        return None
    return ModelAccess(row, owner, team_id, role, user)


def authorize_model(conn: Any, model_id: Any, user: Optional[str], action: str) -> ModelAccess:
    """Load a custom model by id and check ``user`` may do ``action`` with it.

    The row's owner decides, never the request's workspace.

    Args:
        conn: Open connection.
        model_id: The model's id.
        user: The person asking (the request's ``sub``).
        action: ``view``, ``use`` or ``manage``.

    Returns:
        The person's :class:`ModelAccess`.

    Raises:
        ModelDenied: 404 ``model_not_found`` when it doesn't exist or is none of theirs; 403
            ``model_admin_required`` for ``manage`` below Admin.
        ValueError: An unknown action.
    """
    minimum = _minimum(action)
    row = UserCustomModelsRepository(conn).get_by_id(str(model_id)) if model_id else None
    access = model_access(conn, row, user) if row else None
    if access is None:
        raise _not_found()
    if access.can(action):
        return access
    if minimum == "admin":
        raise ModelDenied(403, CODE_MODEL_ADMIN_REQUIRED, "This needs the admin role in the team")
    raise ModelDenied(403, _ROLE_REQUIRED, f"This needs the {minimum} role in the team")


def _owner_value(owner_param: Any) -> str:
    from docsgpt.workspaces.context import WorkspaceError

    value = str(owner_param or "").strip().lower()
    if value in ("", OWNER_PERSONAL, OWNER_TEAM):
        return value or OWNER_PERSONAL
    raise WorkspaceError(400, "invalid_owner", "owner must be personal or team")


def wants_team(owner_param: Any) -> bool:
    """Whether a request's ``owner`` value asks for the team.

    Args:
        owner_param: The request's ``owner`` value.

    Returns:
        True for ``team``.

    Raises:
        WorkspaceError: 400 ``invalid_owner`` for anything but empty, ``personal`` or ``team``.
    """
    return _owner_value(owner_param) == OWNER_TEAM


def creation_owner(conn: Any, user: str, owner_param: Any) -> tuple[str, Optional[str]]:
    """Who owns a model ``user`` is adding (or testing before adding), and who is recorded as adding it.

    Personal unless the request asks for the team (``owner=team``); the header's team is never inferred.

    Args:
        conn: Open connection.
        user: The person adding it.
        owner_param: The request's ``owner`` value: None, empty or ``personal``, or ``team``.

    Returns:
        ``(user, None)`` for a person's own model; ``(the team's principal, user)`` for the team the
        workspace header names.

    Raises:
        WorkspaceError: 400 ``invalid_owner`` for any other value; 400 ``team_workspace_required`` when no
            team is named; 404 ``workspace_not_found`` outside that team; 403 ``workspace_role_required``
            below Admin.
    """
    from docsgpt.workspaces.context import WorkspaceError, current_workspace, require_workspace_role

    if not wants_team(owner_param):
        return user, None
    workspace = current_workspace(conn)
    if not workspace.is_team:
        raise WorkspaceError(400, "team_workspace_required", "Switch to the team to add a model for it")
    require_workspace_role(workspace, MODEL_ACTIONS["manage"])
    if is_principal_id(user):
        raise WorkspaceError(403, _ROLE_REQUIRED, "A team can't add a model by itself")
    return workspace.owner_id, user


def listed_owner(conn: Any, user: str, owner_param: Any) -> str:
    """Whose models a list shows: the caller's, or with ``owner=team`` the header team's.

    Args:
        conn: Open connection.
        user: The caller.
        owner_param: The request's ``owner`` value.

    Returns:
        The caller, or the team's principal (any member may list them).

    Raises:
        WorkspaceError: 400 ``invalid_owner`` or ``team_workspace_required``, 404 outside the team.
    """
    from docsgpt.workspaces.context import WorkspaceError, current_workspace, require_workspace_role

    if not wants_team(owner_param):
        return user
    workspace = current_workspace(conn)
    if not workspace.is_team:
        raise WorkspaceError(400, "team_workspace_required", "Switch to the team to see its models")
    require_workspace_role(workspace, MODEL_ACTIONS["view"])
    return workspace.owner_id


def model_fields(
    conn: Any, row: Mapping[str, Any], viewer: Optional[str], *, checks: Optional[PayerChecks] = None
) -> dict:
    """The owner and permission fields a custom model payload carries for ``viewer``.

    Args:
        conn: Open connection.
        row: The ``user_custom_models`` row.
        viewer: The person reading it.
        checks: The request's :class:`PayerChecks`, shared across a list.

    Returns:
        ``{owner, team_id, created_by, allowed_actions}``: ``owner`` is ``personal`` or ``team``;
        ``created_by`` is ``{user_id, label}`` on a team's model (their email when on file, else their id;
        named also after they left) and None on a person's own.
    """
    checks = checks or PayerChecks()
    access = model_access(conn, row, viewer, checks=checks)
    allowed = access.allowed_actions() if access else []
    if not is_team_model(row):
        return {"owner": OWNER_PERSONAL, "team_id": None, "created_by": None, "allowed_actions": allowed}
    person = row.get("created_by")
    created_by = None
    if person:
        label = checks.emails(conn, [person]).get(person)
        created_by = {"user_id": person, "label": label or person}
    return {
        "owner": OWNER_TEAM,
        "team_id": team_of_principal(row.get("user_id")),
        "created_by": created_by,
        "allowed_actions": allowed,
    }


def unowned_custom_models(conn: Any, owner_id: Optional[str], ids: Iterable[Any]) -> list[str]:
    """The custom models among ``ids`` that an item owned by ``owner_id`` can't run with.

    A custom model resolves in its owner's account, so an item may only name its own owner's: a person's
    on their own items, a team's on the team's items.

    Args:
        conn: Open connection.
        owner_id: The item's owner: a person or a team's principal.
        ids: Model ids the item names; blanks, non-strings and catalog ids are ignored.

    Returns:
        The offending ids, as given.
    """
    candidates = [m for m in ids if isinstance(m, str) and m.strip()]
    if not candidates:
        return []
    repo = UserCustomModelsRepository(conn)
    existing = repo.existing_ids(candidates)
    if not existing:
        return []
    owned = {m.lower() for m in repo.owned_ids(owner_id, existing)} if owner_id else set()
    return [m for m in existing if m.lower() not in owned]


def endpoint_key(base_url: Any, upstream_model_id: Any) -> tuple[str, str]:
    """What makes two custom models the same model: where they point and which model they ask for.

    The base URL ignores the case of its scheme and host and trailing slashes, but not the case of its
    path, which may name a tenant or deployment; the name never counts, so a team's copy named
    differently still matches.

    Args:
        base_url: The OpenAI-compatible endpoint.
        upstream_model_id: The id sent to the provider.

    Returns:
        ``(base_url, upstream_model_id)``, normalized.
    """
    return _normalized_url(base_url), str(upstream_model_id or "").strip()


def _normalized_url(base_url: Any) -> str:
    """``base_url`` without trailing slashes, its scheme and host lowercased and the rest kept as typed.

    Args:
        base_url: A URL, or anything (an unparsable value is only stripped).

    Returns:
        The normalized URL.
    """
    url = str(base_url or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    userinfo, at, host = parts.netloc.rpartition("@")
    return urlunsplit((parts.scheme.lower(), f"{userinfo}{at}{host.lower()}", parts.path, parts.query, parts.fragment))


def matching_model(rows: Iterable[Mapping[str, Any]], base_url: Any, upstream_model_id: Any) -> Optional[dict]:
    """The row among ``rows`` that is the same model as the given endpoint, or None.

    Enabled rows come first, then the oldest, so the pick is stable.

    Args:
        rows: ``user_custom_models`` rows of one owner.
        base_url: The endpoint to match.
        upstream_model_id: The upstream id to match.

    Returns:
        The matching row, or None.
    """
    key = endpoint_key(base_url, upstream_model_id)
    if not key[0] or not key[1]:
        return None
    found = [dict(r) for r in rows if endpoint_key(r.get("base_url"), r.get("upstream_model_id")) == key]
    found.sort(key=_match_order)
    return found[0] if found else None


def _match_order(row: Mapping[str, Any]) -> tuple[bool, str, str]:
    """The order :func:`matching_model` picks in: enabled rows first, then the oldest, then by id."""
    return not row.get("enabled", True), str(row.get("created_at") or ""), str(row.get("id"))


def index_models(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict]:
    """Each endpoint's match among ``rows``, for looking up many models against one owner's.

    Looking a model's :func:`endpoint_key` up here gives what :func:`matching_model` would pick from the
    same rows.

    Args:
        rows: ``user_custom_models`` rows of one owner.

    Returns:
        ``{endpoint_key: row}``; rows without a base URL or upstream id never match and are left out.
    """
    index: dict[tuple[str, str], dict] = {}
    for row in sorted((dict(r) for r in rows), key=_match_order):
        key = endpoint_key(row.get("base_url"), row.get("upstream_model_id"))
        if key[0] and key[1]:
            index.setdefault(key, row)
    return index
