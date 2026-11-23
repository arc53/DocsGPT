"""The one access check for team-shared resources: roles, actions and switches.

Every shareable resource (``agent``, ``source``, ``tool``, ``prompt``) has an
owner and may be shared to teams as ``viewer`` or ``editor``. What each role
may do is a fixed table of *actions* per resource type (``ACTIONS``). The
owner can adjust a few of those rows on one resource with *switches*
(``SWITCHES``), stored in ``resource_share_settings``. A switch only ever moves
one action between two roles; it never touches owner-only actions such as
``manage_settings``.

Routes ask one question, ``require(conn, type, id, user, action)``, and get
back a :class:`ResourceAccess` (whose ``owner_id`` is the id to write as) or
an :class:`AccessDenied` carrying 404 (not visible) or 403 (visible, but the
role may not do this). List and get responses embed ``ResourceAccess.payload()``
(``access`` + ``allowed_actions``) so the frontend never re-derives the rules.

Access is resolved live on every call (grants JOIN ``team_members``), so a
revoked grant or membership denies on the next request.

An item a team workspace owns (its ``user_id`` is the team's principal,
``docsgpt/workspaces/principal.py``) follows a different table: the caller's
role in that team decides (``WORKSPACE_ACTIONS``), switches don't apply, and
grants are never consulted, so a non-member gets nothing whatever grant rows
exist. Its ``access`` is ``viewer``, ``editor`` or ``admin`` (the team Owner
included), never ``owner``, so every ``access == "owner"`` check keeps
meaning "the person who owns the row". The team's outside policy
(``docsgpt/workspaces/outside.py``) moves the actions that take items outside
the team between Admin and Editor, or takes them from everyone.

A team may share an item with a whole other team (``team_item_shares``). A
person in the receiving team who has no role in the owning team, or the
receiving team's principal, then gets the receiver's fixed actions
(``outside.RECEIVER_ACTIONS``: use it, nothing more) while the share is live:
the owning team isn't locked and still owns the item.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Iterator, Optional

from sqlalchemy import Connection, text

from docsgpt import tracing
from docsgpt.connectors.permissions import holds_owner_credentials, owner_credential_writes
from docsgpt.storage.db.base_repository import canonical_uuid, looks_like_uuid
from docsgpt.storage.db.repositories.agents import STORED_PROMPT_PRESETS, AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.workspaces.outside import (
    POLICY_LOCKED,
    RECEIVER_ACTIONS,
    cached_policies,
    outside_minimum,
    team_policy,
)
from docsgpt.workspaces.principal import is_principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least, team_role_for

logger = logging.getLogger(__name__)

RESOURCE_TYPES = ("agent", "source", "tool", "prompt")

# Weakest role that may perform each action by default. ``owner`` rows are
# owner-only unless a switch below moves them.
ACTIONS: dict[str, dict[str, str]] = {
    "agent": {
        "use": "viewer",  # chat with it
        "pin": "viewer",
        "view": "editor",  # open the edit page and read its full config
        "edit": "editor",
        "publish": "editor",
        "edit_policy": "editor",  # guardrails and quotas
        "view_logs": "editor",
        "manage_schedules": "editor",
        "export": "editor",
        "manage_access_details": "editor",  # API key, webhook, public link
        "move_folder": "viewer",  # file it in my own folders (personal filing, folder_items)
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
        "move_to_team": "owner",  # the team side also needs Editor there (the move service checks)
    },
    "source": {
        "use": "viewer",  # browse files, chunks, graph, wiki; test retrieval; attach to agents
        "move_folder": "viewer",  # file it in my own folders (personal filing, folder_items)
        "view_config": "editor",
        "edit": "editor",  # chunks, files, wiki, config, sync, reingest, GraphRAG, convert
        "reconnect": "owner",  # change the connector account
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
        "move_to_team": "owner",
    },
    "tool": {
        "use": "viewer",  # see it and run it inside the owner's shared agents
        "use_in_own": "viewer",  # add it to my own agents and chats
        "move_folder": "viewer",  # file it in my own folders (personal filing, folder_items)
        "edit": "editor",  # name, action descriptions, parameters, approval
        "edit_credentials": "editor",  # secrets, URL, auth (write-only); OAuth servers stay owner-only
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
        "move_to_team": "owner",
    },
    "prompt": {
        "use": "viewer",  # read it and use it in my own agents
        "move_folder": "viewer",  # file it in my own folders (personal filing, folder_items)
        "duplicate": "editor",
        "edit": "editor",
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
        "move_to_team": "owner",
    },
}

# Weakest *team* role per action on an item a team workspace owns, under the default outside
# policy (``admins``); ``workspace_role_table`` applies the team's actual policy.
# The Owner ranks above Admin and so has every row. There are no switches here, and no ``share``
# or ``manage_settings``: a team item has no per-item people, only whole-team shares with another
# team (``share_outside``). ``folder`` is the team's one folder tree (``docsgpt/api/user/folders``);
# ``resolve`` doesn't serve it.
WORKSPACE_ACTIONS: dict[str, dict[str, str]] = {
    "agent": {
        "use": "viewer",
        "pin": "viewer",
        "view": "editor",  # Viewers don't read an agent's config
        "edit": "editor",
        "edit_policy": "editor",
        "view_logs": "editor",
        "manage_schedules": "editor",
        "export": "editor",
        "move_folder": "editor",  # file it in the team's tree
        "publish": "admin",  # outward exposure: follows the outside policy
        "manage_access_details": "admin",  # key, widget, public link, webhook: follows the outside policy
        "share_outside": "admin",  # share with another team: follows the outside policy
        "delete": "admin",
        "move_out": "admin",  # to the acting Admin's Personal
    },
    "source": {
        "use": "viewer",
        "view_config": "viewer",
        "edit": "editor",
        "move_folder": "editor",
        "reconnect": "admin",
        "share_outside": "admin",
        "delete": "admin",
        "move_out": "admin",
    },
    "tool": {
        "use": "viewer",
        "use_in_own": "viewer",
        "edit": "editor",
        "edit_credentials": "editor",
        "move_folder": "editor",
        "share_outside": "admin",
        "delete": "admin",
        "move_out": "admin",
    },
    "prompt": {
        "use": "viewer",
        "duplicate": "viewer",
        "edit": "editor",
        "move_folder": "editor",
        "share_outside": "admin",
        "delete": "admin",
        "move_out": "admin",
    },
    "folder": {
        "list": "viewer",
        "create": "editor",
        "rename": "editor",
        "move": "editor",
        "file": "editor",
        "delete": "editor",  # items survive, moved to its parent
        "move_out": "admin",
    },
}

# Actions whose weakest role is the outside policy's (``outside.outside_minimum``).
_POLICY_ACTIONS = ("publish", "manage_access_details", "share_outside")

# What a locked team takes from everyone, its Owner included. ``publish`` stays with Admins: a
# draft can still go live for the team's members, it just never gets a key.
_LOCKED_REMOVES = ("manage_access_details", "share_outside", "move_out", "export")

# The ``access`` a team role gives on a team item: never ``owner`` (that stays the row's person-owner).
_TEAM_ACCESS = {"owner": "admin", "admin": "admin", "editor": "editor", "viewer": "viewer"}

# The ``access`` of a team that receives a share: view-level, whatever role its members hold.
_RECEIVER_ACCESS = "viewer"


@dataclass(frozen=True)
class Switch:
    """One owner switch: moves ``action`` to ``role_on`` or ``role_off``."""

    key: str
    default: bool
    action: str
    role_on: str
    role_off: str


# Order is the order the share dialog lists them in.
SWITCHES: dict[str, tuple[Switch, ...]] = {
    "agent": (
        Switch("editors_can_share", False, "share", "editor", "owner"),
        Switch("editors_can_delete", False, "delete", "editor", "owner"),
        # Off by default: a key, link or webhook reaches people the owner never shared with.
        Switch("editors_can_manage_access_details", False, "manage_access_details", "editor", "owner"),
        Switch("viewers_can_see_logs", False, "view_logs", "viewer", "editor"),
    ),
    "source": (
        Switch("editors_can_share", False, "share", "editor", "owner"),
        Switch("editors_can_delete", False, "delete", "editor", "owner"),
        Switch("viewers_can_see_config", True, "view_config", "viewer", "editor"),
    ),
    "tool": (
        Switch("editors_can_change_credentials", True, "edit_credentials", "editor", "owner"),
        Switch("editors_can_share", False, "share", "editor", "owner"),
        Switch("viewers_can_use_in_agents", True, "use_in_own", "viewer", "editor"),
    ),
    "prompt": (
        Switch("editors_can_share", False, "share", "editor", "owner"),
        Switch("viewers_can_duplicate", True, "duplicate", "viewer", "editor"),
    ),
}

_RANK = {"viewer": 1, "editor": 2, "owner": 3}

_REPO_FOR_TYPE = {
    "agent": AgentsRepository,
    "source": SourcesRepository,
    "prompt": PromptsRepository,
    "tool": UserToolsRepository,
}


class AccessDenied(Exception):
    """Raised by :func:`require`; ``status`` is 404 (not visible) or 403."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def default_settings(resource_type: str) -> dict[str, bool]:
    """Every switch of ``resource_type`` at its default."""
    return {s.key: s.default for s in SWITCHES.get(resource_type, ())}


def _merge(resource_type: str, stored: Optional[dict]) -> dict[str, bool]:
    merged = default_settings(resource_type)
    for key, value in (stored or {}).items():
        if key in merged and isinstance(value, bool):
            merged[key] = value
    return merged


def role_table(resource_type: str, settings: Optional[dict]) -> dict[str, str]:
    """``action -> weakest role`` for one resource, switches applied."""
    table = dict(ACTIONS[resource_type])
    merged = _merge(resource_type, settings)
    for switch in SWITCHES.get(resource_type, ()):
        table[switch.action] = switch.role_on if merged[switch.key] else switch.role_off
    return table


def allowed_actions(
    resource_type: str, access: Optional[str], settings: Optional[dict]
) -> set[str]:
    """The actions ``access`` may perform on a resource with these switches."""
    if access not in _RANK or resource_type not in ACTIONS:
        return set()
    rank = _RANK[access]
    return {action for action, role in role_table(resource_type, settings).items() if rank >= _RANK[role]}


def team_access_level(team_role: Optional[str]) -> Optional[str]:
    """The ``access`` a team role gives on a team item: ``admin`` for the Owner and Admins, else the role.

    Args:
        team_role: ``owner``, ``admin``, ``editor``, ``viewer`` or None.

    Returns:
        Optional[str]: ``admin``, ``editor`` or ``viewer``; None for no role (or an unknown one).
    """
    return _TEAM_ACCESS.get(team_role or "")


def _require_policy(policy: Optional[str]) -> str:
    """``policy``, or a ValueError: a team's actions are never read without the team's outside policy."""
    if not policy:
        raise ValueError("a team item's actions need the team's outside policy (policy=...)")
    return policy


def workspace_role_table(resource_type: str, *, policy: Optional[str]) -> dict[str, str]:
    """``action -> weakest team role`` on a team item (or folder) under the team's outside policy.

    Args:
        resource_type: ``agent``, ``source``, ``tool``, ``prompt`` or ``folder``.
        policy: The owning team's outside policy (``Workspace.outside_policy``, ``outside.team_policy``).
            An unknown value reads as ``locked``.

    Returns:
        dict[str, str]: Empty for an unknown type. An action nobody may do under the policy is absent.

    Raises:
        ValueError: No policy given.
    """
    policy = _require_policy(policy)
    table = dict(WORKSPACE_ACTIONS.get(resource_type) or {})
    minimum = outside_minimum(policy)
    if minimum is None:
        for action in _LOCKED_REMOVES:
            table.pop(action, None)
    else:
        for action in _POLICY_ACTIONS:
            if action in table:
                table[action] = minimum
    return table


def workspace_minimum(resource_type: str, action: str, *, policy: Optional[str]) -> Optional[str]:
    """The weakest team role that may do ``action`` on a team item under the policy.

    Args:
        resource_type: ``agent``, ``source``, ``tool``, ``prompt`` or ``folder``.
        action: The action.
        policy: The owning team's outside policy.

    Returns:
        Optional[str]: The role, or None when nobody may (locked, or no such action).

    Raises:
        ValueError: No policy given.
    """
    return workspace_role_table(resource_type, policy=policy).get(action)


def workspace_allowed_actions(
    resource_type: str, team_role: Optional[str], *, policy: Optional[str] = None
) -> set[str]:
    """The actions a team role may perform on an item (or folder) a team workspace owns.

    Args:
        resource_type: ``agent``, ``source``, ``tool``, ``prompt`` or ``folder``.
        team_role: The caller's role in the owning team, or None.
        policy: The owning team's outside policy; required.

    Returns:
        set[str]: Empty for no role, an unknown role or an unknown type.

    Raises:
        ValueError: No policy given, so a call that forgets it fails instead of allowing.
    """
    table = workspace_role_table(resource_type, policy=policy)
    if not table or team_access_level(team_role) is None:
        return set()
    return {action for action, minimum in table.items() if role_at_least(team_role, minimum)}


def _access_payload(
    access: Optional[str], actions: Iterable[str], team_id: Optional[str], team_role: Optional[str]
) -> dict:
    """The access fields of an item payload."""
    if team_id:
        origin = "team"
    elif access == "owner":
        origin = "own"
    else:
        origin = "shared" if access else None
    return {
        "access": access,
        "allowed_actions": sorted(actions),
        "workspace": {"kind": "team" if team_id else "personal", "team_id": team_id},
        "team_role": team_role,
        "origin": origin,
    }


def receiver_payload(
    resource_type: str, via_team_id: str, owner_team_id: Optional[str], owner_team_name: Optional[str]
) -> dict:
    """The access fields of a team item as a team it was shared with sees it.

    It lives in the receiving team's workspace (``workspace``), comes from the owning team
    (``shared_from``) and carries the receiver's fixed actions; no team role.

    Args:
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        via_team_id: The receiving team.
        owner_team_id: The team that owns and shared it.
        owner_team_name: That team's name.

    Returns:
        dict: ``access``, ``allowed_actions``, ``workspace``, ``team_role`` (None), ``origin``
        (``team_shared``) and ``shared_from`` (``{team_id, name}``).
    """
    payload = _access_payload(
        _RECEIVER_ACCESS, RECEIVER_ACTIONS.get(resource_type, ()), str(via_team_id), None
    )
    payload["origin"] = "team_shared"
    payload["shared_from"] = {"team_id": owner_team_id, "name": owner_team_name}
    return payload


def public_settings(resource_type: str, settings: Optional[dict]) -> list[dict]:
    """The switches as ``[{key, value, default}]`` in display order."""
    merged = _merge(resource_type, settings)
    return [
        {"key": s.key, "value": merged[s.key], "default": s.default}
        for s in SWITCHES.get(resource_type, ())
    ]


def settings_for(conn: Connection, resource_type: str, resource_id: str) -> dict[str, bool]:
    """The resource's switches, defaults filled in."""
    rid = canonical_uuid(str(resource_id))
    return settings_many(conn, resource_type, [rid])[rid]


def settings_many(
    conn: Connection, resource_type: str, resource_ids: Iterable[str]
) -> dict[str, dict[str, bool]]:
    """``resource_id -> switches`` for many resources in one query.

    Keys are canonical (lowercase) UUIDs, the form Postgres returns.
    """
    ids = [canonical_uuid(str(r)) for r in resource_ids]
    out = {rid: default_settings(resource_type) for rid in ids}
    uuids = [rid for rid in ids if looks_like_uuid(rid)]
    if not uuids:
        return out
    rows = conn.execute(
        text(
            """
            SELECT resource_id, settings FROM resource_share_settings
            WHERE resource_type = :t AND resource_id = ANY(CAST(:ids AS uuid[]))
            """
        ),
        {"t": resource_type, "ids": uuids},
    ).fetchall()
    for rid, stored in rows:
        out[str(rid)] = _merge(resource_type, stored)
    return out


def set_settings(
    conn: Connection, resource_type: str, resource_id: str, changes: dict, updated_by: str
) -> dict[str, bool]:
    """Merge ``changes`` into the resource's switches and return the result.

    Only switches someone set are stored; the rest follow their default, so
    a later change of a default reaches every resource nobody set it on.

    Raises:
        ValueError: an unknown key or a non-boolean value.
    """
    known = default_settings(resource_type)
    for key, value in changes.items():
        if key not in known:
            raise ValueError(f"Unknown setting: {key}")
        if not isinstance(value, bool):
            raise ValueError(f"Setting {key} must be true or false")
    row = conn.execute(
        text(
            "SELECT settings FROM resource_share_settings "
            "WHERE resource_type = :t AND resource_id = CAST(:id AS uuid)"
        ),
        {"t": resource_type, "id": resource_id},
    ).first()
    stored = {k: v for k, v in ((row[0] if row else None) or {}).items() if k in known and isinstance(v, bool)}
    explicit = {**stored, **changes}
    conn.execute(
        text(
            """
            INSERT INTO resource_share_settings (resource_type, resource_id, settings, updated_by)
            VALUES (:t, CAST(:id AS uuid), CAST(:s AS jsonb), :by)
            ON CONFLICT (resource_type, resource_id)
            DO UPDATE SET settings = EXCLUDED.settings, updated_by = EXCLUDED.updated_by,
                          updated_at = now()
            """
        ),
        {"t": resource_type, "id": resource_id, "s": json.dumps(explicit), "by": updated_by},
    )
    return _merge(resource_type, explicit)


def delete_settings(conn: Connection, resource_type: str, resource_id: str) -> None:
    """Drop a deleted resource's switches (the table has no FK to cascade)."""
    if looks_like_uuid(resource_id):
        conn.execute(
            text("DELETE FROM resource_share_settings WHERE resource_type = :t AND resource_id = CAST(:id AS uuid)"),
            {"t": resource_type, "id": resource_id},
        )


@dataclass(frozen=True)
class ResourceAccess:
    """What one user may do on one resource.

    Attributes:
        access: ``owner``, ``editor`` or ``viewer`` on a personal item; ``admin``, ``editor`` or
            ``viewer`` on a team item (never ``owner``: that is the row's person-owner only).
        owner_id: The id to read and write the resource as (the team's principal for a team item).
        team_id: The owning team, for a team item; None for a personal one.
        team_role: The caller's role in that team (``owner``, ``admin``, ``editor``, ``viewer``), for
            a team item reached through membership; None otherwise.
        via_team_id: For a team item reached through a share with another team, that receiving
            team; None otherwise. ``team_id`` stays the owning team.
        owner_team_name: The owning team's name, for such a share (``shared_from``).
    """

    resource_type: str
    resource_id: str
    access: str
    owner_id: str
    settings: dict = field(default_factory=dict)
    actions: frozenset = frozenset()
    team_id: Optional[str] = None
    team_role: Optional[str] = None
    via_team_id: Optional[str] = None
    owner_team_name: Optional[str] = None

    def can(self, action: str) -> bool:
        return action in self.actions

    @property
    def is_team_item(self) -> bool:
        """Whether a team workspace owns the item."""
        return self.team_id is not None

    def payload(self) -> dict:
        """The access fields every API response embeds for this resource.

        Returns:
            dict: ``access``, ``allowed_actions``, ``workspace`` (``{kind, team_id}``), ``team_role``
            and ``origin`` (``own``, ``team`` or ``shared``). An item reached through a share with
            another team lives in that receiving team's workspace, with ``origin`` ``team_shared``
            and ``shared_from`` (:func:`receiver_payload`).
        """
        if self.via_team_id:
            return receiver_payload(self.resource_type, self.via_team_id, self.team_id, self.owner_team_name)
        return _access_payload(self.access, self.actions, self.team_id, self.team_role)


def build(resource_type: str, resource_id: str, access: str, owner_id: str, settings: dict) -> ResourceAccess:
    """A :class:`ResourceAccess` from already-known parts (list endpoints)."""
    merged = _merge(resource_type, settings)
    return ResourceAccess(
        resource_type=resource_type,
        resource_id=str(resource_id),
        access=access,
        owner_id=owner_id,
        settings=merged,
        actions=frozenset(allowed_actions(resource_type, access, merged)),
    )


def build_team(
    resource_type: str, resource_id: str, owner_id: str, team_role: Optional[str], *, policy: Optional[str] = None
) -> Optional[ResourceAccess]:
    """A :class:`ResourceAccess` for a team item from the caller's role (team list endpoints).

    Args:
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        resource_id: The item's id.
        owner_id: The item's ``user_id``: the team's principal.
        team_role: The caller's role in the team (``Workspace.role``).
        policy: The team's outside policy (``Workspace.outside_policy``); required.

    Returns:
        Optional[ResourceAccess]: None when ``owner_id`` is not a principal or the role gives nothing.

    Raises:
        ValueError: No policy given.
    """
    _require_policy(policy)
    team_id = team_of_principal(owner_id)
    access = team_access_level(team_role)
    if team_id is None or access is None:
        return None
    return ResourceAccess(
        resource_type=resource_type,
        resource_id=str(resource_id),
        access=access,
        owner_id=owner_id,
        settings={},
        actions=frozenset(workspace_allowed_actions(resource_type, team_role, policy=policy)),
        team_id=team_id,
        team_role=team_role,
    )


def payload_for(
    resource_type: str,
    access: Optional[str],
    settings: Optional[dict],
    *,
    team_id: Optional[str] = None,
    team_role: Optional[str] = None,
    policy: Optional[str] = None,
) -> dict:
    """The access fields of an item payload without a lookup (list endpoints).

    For a personal item pass the caller's ``access`` and the item's switches.
    For a team item pass ``team_id``, the caller's ``team_role``
    (``Workspace.role``) and the team's ``policy`` (``Workspace.outside_policy``);
    ``access`` and ``settings`` are then ignored, since the role decides and
    switches don't apply.

    Args:
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        access: ``owner``, ``editor``, ``viewer`` or None (personal items).
        settings: The item's stored switches (personal items).
        team_id: The owning team, for a team item.
        team_role: The caller's role in that team.
        policy: That team's outside policy; required with ``team_id``.

    Returns:
        dict: See :meth:`ResourceAccess.payload`.

    Raises:
        ValueError: ``team_id`` without ``policy``.
    """
    if team_id:
        level = team_access_level(team_role)
        actions = workspace_allowed_actions(resource_type, team_role, policy=policy)
        return _access_payload(level, actions, str(team_id), team_role)
    return _access_payload(access, allowed_actions(resource_type, access, settings), None, None)


# Per-read memo of :func:`resolve`, on only inside :func:`cached_resolves`.
_RESOLVE_CACHE: ContextVar[Optional[dict]] = ContextVar("resource_access_resolve_cache", default=None)


@contextmanager
def cached_resolves():
    """Remember :func:`resolve` answers for the rest of one read.

    A page read asks about the same resources several times (sponsor details,
    run state, names); inside this block each ``(type, id, user)`` is looked
    up once. Only for reads: a write must see a grant change at once.
    """
    token = _RESOLVE_CACHE.set({})
    try:
        with cached_policies():
            yield
    finally:
        _RESOLVE_CACHE.reset(token)


def resolve(
    conn: Connection, resource_type: str, resource_id: str, user_id: str
) -> Optional[ResourceAccess]:
    """The caller's access to a resource, or None when they can't see it."""
    cache = _RESOLVE_CACHE.get()
    if cache is None:
        return _resolve_uncached(conn, resource_type, resource_id, user_id)
    key = (resource_type, str(resource_id or "").lower(), user_id)
    if key not in cache:
        cache[key] = _resolve_uncached(conn, resource_type, resource_id, user_id)
    return cache[key]


# The table of each item kind, for owner-agnostic lookups by id.
_ITEM_TABLES = {"agent": "agents", "source": "sources", "prompt": "prompts", "tool": "user_tools", "folder": "folders"}


def resource_owner(conn: Connection, resource_type: str, resource_id: Optional[str]) -> Optional[str]:
    """The ``user_id`` that owns an item, whoever asks (a person, or a team's principal).

    Args:
        conn: Open database connection.
        resource_type: ``agent``, ``source``, ``prompt``, ``tool`` or ``folder``.
        resource_id: The item's id.

    Returns:
        Optional[str]: The owner, or None for an unknown kind, a non-UUID id or a missing row.
    """
    table = _ITEM_TABLES.get(resource_type)
    if table is None or not resource_id or not looks_like_uuid(str(resource_id)):
        return None
    return conn.execute(
        text(f"SELECT user_id FROM {table} WHERE id = CAST(:id AS uuid)"), {"id": str(resource_id)}
    ).scalar()


def _live_shares(
    conn: Connection, user_id: str, resource_type: str, resource_id: str, owner_team_id: str
) -> list[dict]:
    """The live shares of a team's item that reach ``user_id``, oldest first.

    Live: the row names the item's current owning team, and that team isn't locked (a lock
    pauses its shares; unlocking brings them back with nothing written). A person is reached
    through any team they are in; a team's principal only through its own team. Who shared it,
    and whether they are still in either team, doesn't matter.
    """
    rows = _share_rows(conn, user_id, resource_type, resource_id, owner_team_id)
    if not rows or team_policy(conn, owner_team_id) == POLICY_LOCKED:
        return []
    return rows


def _share_rows(
    conn: Connection, user_id: str, resource_type: str, resource_id: str, owner_team_id: str
) -> list[dict]:
    """The share rows of a team's item that name ``user_id``'s side, live or paused by a lock.

    A person is named through any team they are in; a team's principal only through its own team. Only rows
    naming the item's current owning team count.

    Args:
        conn: Open database connection.
        user_id: A person, or a team's principal.
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        resource_id: The item's canonical id.
        owner_team_id: The team that owns the item now.

    Returns:
        list[dict]: The rows, oldest first.
    """
    if resource_type not in RECEIVER_ACTIONS:
        return []
    repo = TeamItemSharesRepository(conn)
    if is_principal_id(user_id):
        own_team = team_of_principal(user_id)
        rows = [r for r in repo.teams_for(resource_type, resource_id) if str(r.get("team_id")) == own_team]
    else:
        rows = repo.reaching(user_id, resource_type, resource_id)
    return [r for r in rows if str(r.get("owner_team_id")) == owner_team_id]


def shared_in(conn: Connection, resource_type: str, resource_id: Optional[str], user_id: Optional[str]) -> bool:
    """Whether a share of another team's item names ``user_id``'s side, even while its owning team is locked.

    A lock only pauses a share: unlocking brings it back with nothing written. So whatever must hold for an
    item used through a share (it is borrowed, so a key, public link or webhook can't reach it) holds while
    the share is paused too.

    Args:
        conn: Open database connection.
        resource_type: ``source``, ``tool`` or ``prompt``.
        resource_id: The item's id.
        user_id: A person, or a team's principal (whom a holder runs as).

    Returns:
        bool: True when such a row exists.
    """
    if not user_id or not resource_id or not looks_like_uuid(str(resource_id)):
        return False
    owner_team_id = team_of_principal(resource_owner(conn, resource_type, str(resource_id)))
    if owner_team_id is None or owner_team_id == team_of_principal(user_id):
        return False
    return bool(_share_rows(conn, user_id, resource_type, canonical_uuid(str(resource_id)), owner_team_id))


def team_item_reach(
    conn: Connection, user_id: Optional[str], resource_type: str, resource_id: Optional[str],
    prefer_team: Optional[str] = None,
) -> Optional[str]:
    """The team through which a share of a team's item reaches ``user_id``, or None.

    Args:
        conn: Open database connection.
        user_id: A person, or a team's principal.
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        resource_id: The item's id.
        prefer_team: The team to answer when the item reaches the person through it (the request's
            workspace, or an existing chat's team); otherwise the oldest share decides.

    Returns:
        Optional[str]: The receiving team's id; None when no live share reaches them (no row, the
        owning team locked, the item no longer that team's, or they aren't in the receiving team).
    """
    if not user_id or not resource_id or not looks_like_uuid(str(resource_id)):
        return None
    owner_team_id = team_of_principal(resource_owner(conn, resource_type, str(resource_id)))
    if owner_team_id is None:
        return None
    rows = _live_shares(conn, user_id, resource_type, canonical_uuid(str(resource_id)), owner_team_id)
    teams = [str(r["team_id"]) for r in rows]
    if not teams:
        return None
    preferred = str(prefer_team).lower() if prefer_team else None
    return preferred if preferred in teams else teams[0]


def _resolve_team_item(
    conn: Connection, resource_type: str, resource_id: str, owner_id: str, user_id: str
) -> Optional[ResourceAccess]:
    """The caller's access to an item a team owns: their role in that team, a share into their team, or None.

    Never falls back to grants: a team item has none that count. A member of the owning team
    gets their role there, under the team's outside policy. Anyone else, another team's
    principal included, gets the receiver's fixed actions while a live share reaches them.
    """
    team_id = team_of_principal(owner_id)
    if team_id is None:
        return None
    if not is_principal_id(user_id):
        role = team_role_for(conn, user_id, team_id)
        if role is not None:
            return build_team(resource_type, resource_id, owner_id, role, policy=team_policy(conn, team_id))
    rows = _live_shares(conn, user_id, resource_type, resource_id, team_id)
    if not rows:
        return None
    return ResourceAccess(
        resource_type=resource_type,
        resource_id=str(resource_id),
        access=_RECEIVER_ACCESS,
        owner_id=owner_id,
        settings={},
        actions=frozenset(RECEIVER_ACTIONS[resource_type]),
        team_id=team_id,
        team_role=None,
        via_team_id=str(rows[0]["team_id"]),
        owner_team_name=rows[0].get("owner_team_name"),
    )


def _resolve_uncached(
    conn: Connection, resource_type: str, resource_id: str, user_id: str
) -> Optional[ResourceAccess]:
    repo_cls = _REPO_FOR_TYPE.get(resource_type)
    if repo_cls is None or not resource_id or not user_id:
        return None
    # Postgres matches any casing but returns lowercase; canonicalise so the
    # switch lookup (keyed by the returned id) can't miss.
    resource_id = canonical_uuid(str(resource_id))
    owned = repo_cls(conn).get_any(resource_id, user_id)
    if owned is not None:
        rid = str(owned.get("id") or resource_id)
        ra = build(resource_type, rid, "owner", user_id, settings_for(conn, resource_type, rid))
        # A team's principal reads its own items as their owner (runs as the team).
        return replace(ra, team_id=team_of_principal(user_id)) if is_principal_id(user_id) else ra
    # Only canonical UUIDs can carry a grant or a team owner; casting anything
    # else would poison the transaction.
    if not looks_like_uuid(str(resource_id)):
        return None
    # The workspace step: a team's item answers from the caller's team role
    # alone, so no grant row (stale, or forced in) can open it to anyone else.
    owner = resource_owner(conn, resource_type, str(resource_id))
    if is_principal_id(owner):
        return _resolve_team_item(conn, resource_type, str(resource_id), owner, user_id)
    level = TeamScopeRepository(conn).effective_access(user_id, resource_type, str(resource_id))
    if level is None:
        return None
    grants = TeamResourceGrantsRepository(conn).list_for_resource(resource_type, str(resource_id))
    if not grants:
        return None
    # Every grant row carries the same denormalised owner id.
    owner_id = grants[0].get("owner_id")
    return build(resource_type, str(resource_id), level, owner_id, settings_for(conn, resource_type, str(resource_id)))


def require(
    conn: Connection, resource_type: str, resource_id: str, user_id: str, action: str
) -> ResourceAccess:
    """Resolve and check one action.

    Raises:
        KeyError: ``action`` is not an action of ``resource_type`` (a bug).
        AccessDenied: 404 when the resource isn't visible, 403 when the
            caller's role may not perform ``action``.
    """
    if action not in ACTIONS.get(resource_type, {}) and action not in WORKSPACE_ACTIONS.get(resource_type, {}):
        raise KeyError(f"{resource_type} has no action {action!r}")
    ra = resolve(conn, resource_type, resource_id, user_id)
    if ra is None:
        raise AccessDenied(404, f"{resource_type.capitalize()} not found")
    if not ra.can(action):
        raise AccessDenied(403, "Your access to this item doesn't allow that")
    return ra


# --- Resource sponsors ------------------------------------------------------
#
# An agent (or workflow) runs as its owner, so a source, prompt or tool it
# references is authorized against the owner. When a team editor attaches one
# the owner can't use, the editor may become its *sponsor*: the holder row's
# ``resource_sponsors`` maps ``"<type>:<id>"`` to the editor's id, and at run
# time the resource is authorized as the sponsor while they can still edit the
# holder and still may sponsor the resource. A tool still runs with its own
# row's credentials (the tool owner's), whoever the principal is.
#
# Sponsoring extends a resource to everyone who uses the holder, so it takes
# more than being able to use it: the sponsor must own the resource or have
# ``edit`` on it (``can_sponsor_ref``). It is never implied: a save that would
# make the caller a new sponsor needs their explicit confirmation
# (``plan_sponsors``), and when a sponsor loses access the resource stops
# rather than passing to whoever saves next.

# Action a principal needs on a referenced resource for a holder to run it.
REF_USE_ACTION = {"source": "use", "prompt": "use", "tool": "use_in_own"}

# Action a user needs on a resource to sponsor it (owners have every action).
SPONSOR_ACTION = "edit"

# Why a recorded sponsorship doesn't run (``sponsor_details`` ``reason``).
REASON_CANNOT_EDIT_HOLDER = "sponsor_cannot_edit_agent"
REASON_CANNOT_EDIT_RESOURCE = "sponsor_cannot_edit_resource"

# Error codes of a save the sponsor rules refuse.
CODE_CONFIRMATION_REQUIRED = "sponsor_confirmation_required"
CODE_NOT_ALLOWED = "sponsor_not_allowed"
CODE_UNEXPECTED_CONFIRMATION = "sponsor_confirmation_unexpected"


def sponsor_key(resource_type: str, resource_id: str) -> str:
    """The ``resource_sponsors`` key for one referenced resource."""
    return f"{resource_type}:{resource_id}"


def can_use_ref(conn: Connection, resource_type: str, resource_id: str, user_id: Optional[str]) -> bool:
    """Whether ``user_id`` may have ``resource_id`` run inside something they hold.

    Args:
        conn: Open database connection.
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.
        user_id: The would-be principal.

    Returns:
        True when the user owns the resource or a team grant gives them
        ``use`` (``use_in_own`` for a tool).
    """
    if not user_id or not resource_id:
        return False
    ra = resolve(conn, resource_type, str(resource_id), user_id)
    return ra is not None and ra.can(REF_USE_ACTION[resource_type])


def ref_attachable(conn: Connection, resource_type: str, resource_id: Optional[str], caller: Optional[str]) -> bool:
    """Whether ``caller`` may newly reference a resource from an agent or a workflow node.

    The one gate for a save that adds a source, prompt or tool: agent create
    and update and workflow node saves all ask it. The caller's own access
    counts, not the holder owner's: an editor of a shared agent must not wire
    in the owner's private tool (run with the owner's credentials), source or
    prompt. Refs that belong to no one always pass: an empty source or prompt
    (no reference), the ``default`` source and prompt presets, and the
    synthetic ids of default and builtin tools. A tool id must be a non-empty
    string: an empty one names no tool and is refused. A ref already on the
    holder is the caller's business to skip; this only judges new ones.

    Args:
        conn: Open database connection.
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.
        caller: The user saving, owner or editor.

    Returns:
        True when the caller may attach it (see :func:`can_use_ref`).
    """
    if resource_type == "tool" and (not isinstance(resource_id, str) or not resource_id.strip()):
        return False
    if not resource_id:
        return True
    rid = str(resource_id)
    if resource_type == "source" and rid == "default":
        return True
    if resource_type == "prompt" and rid in ("default", *STORED_PROMPT_PRESETS):
        return True
    if resource_type == "tool":
        # Lazy: default_tools imports this module lazily too.
        from docsgpt.agents.default_tools import is_synthesized_tool_id

        if is_synthesized_tool_id(rid):
            return True
    return can_use_ref(conn, resource_type, rid, caller)


def can_sponsor_ref(conn: Connection, resource_type: str, resource_id: str, user_id: Optional[str]) -> bool:
    """Whether ``user_id`` may extend ``resource_id`` to someone else's agent.

    Using a resource is not enough to hand it to another agent's audience:
    the sponsor must own it or reach it with ``edit`` through a team grant
    (any team). A team's own item is never sponsored: it reaches people by
    their team role only, so an Editor can't extend it to someone else's
    agent and its audience.

    Args:
        conn: Open database connection.
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.
        user_id: The would-be sponsor.

    Returns:
        True when the user owns the resource or may edit it.
    """
    if not user_id or not resource_id or is_principal_id(user_id):
        return False
    ra = resolve(conn, resource_type, str(resource_id), user_id)
    return (
        ra is not None
        and not ra.is_team_item
        and ra.can(SPONSOR_ACTION)
        and ra.can(REF_USE_ACTION[resource_type])
    )


def _holder_editable_by(conn: Connection, holder_type: str, holder: dict, user_id: str) -> bool:
    """Whether ``user_id`` may still edit the agent or workflow ``holder``.

    A workflow is edited through an agent of its owner that uses it, so the
    check is ``edit`` on any such agent (mirrors the workflow routes).
    """
    if holder_type == "agent":
        ra = resolve(conn, "agent", str(holder["id"]), user_id)
        return ra is not None and ra.can("edit")
    if holder_type == "workflow":
        for agent_id in _workflow_agent_ids(conn, holder):
            ra = resolve(conn, "agent", str(agent_id), user_id)
            if ra is not None and ra.can("edit"):
                return True
        return False
    raise ValueError(f"Unknown sponsor holder type: {holder_type}")


def _workflow_agent_ids(conn: Connection, workflow: dict) -> list:
    """The ids of the workflow owner's agents that run ``workflow``."""
    return conn.execute(
        text("SELECT id FROM agents WHERE workflow_id = CAST(:wid AS uuid) AND user_id = :owner"),
        {"wid": str(workflow["id"]), "owner": workflow.get("user_id")},
    ).scalars().all()


def sponsor_state(
    conn: Connection, holder_type: str, holder: Optional[dict], resource_type: str, resource_id: str
) -> tuple[Optional[str], Optional[str]]:
    """The recorded sponsor of one reference and why it doesn't run, if it doesn't.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row (needs ``id``, ``user_id``, ``resource_sponsors``).
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.

    Returns:
        ``(sponsor, reason)``: ``sponsor`` is the recorded user or None;
        ``reason`` is None while the sponsorship runs, else
        :data:`REASON_CANNOT_EDIT_HOLDER` or :data:`REASON_CANNOT_EDIT_RESOURCE`.
        With no usable record both are None.
    """
    if not holder or not resource_id or is_principal_id(holder.get("user_id")):
        # A team holder never runs anything as a sponsor, whatever is recorded.
        return None, None
    recorded = holder.get("resource_sponsors") or {}
    sponsor = recorded.get(sponsor_key(resource_type, str(resource_id))) or recorded.get(
        sponsor_key(resource_type, str(resource_id).lower())
    )
    if not sponsor or sponsor == holder.get("user_id") or is_principal_id(sponsor):
        # A principal is never a sponsor: it would hand a team's item to a personal agent.
        return None, None
    try:
        if not _holder_editable_by(conn, holder_type, holder, sponsor):
            return sponsor, REASON_CANNOT_EDIT_HOLDER
        if not can_sponsor_ref(conn, resource_type, str(resource_id), sponsor):
            return sponsor, REASON_CANNOT_EDIT_RESOURCE
    except Exception:
        logger.exception("Sponsor check failed for %s %s", resource_type, resource_id)
        return sponsor, REASON_CANNOT_EDIT_RESOURCE
    return sponsor, None


def active_sponsor(
    conn: Connection, holder_type: str, holder: Optional[dict], resource_type: str, resource_id: str
) -> Optional[str]:
    """The sponsor a holder may run ``resource_id`` as, checked live.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row (needs ``id``, ``user_id``, ``resource_sponsors``).
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.

    Returns:
        The sponsor's id when one is recorded, still edits the holder and
        still may sponsor the resource (owns or edits it); else None.
    """
    sponsor, reason = sponsor_state(conn, holder_type, holder, resource_type, resource_id)
    return sponsor if sponsor and reason is None else None


def ref_principal(
    conn: Connection, holder_type: str, holder: Optional[dict], resource_type: str, resource_id: str
) -> Optional[str]:
    """The user a holder's referenced resource is authorized as, or None.

    The owner when they may use it (the default), else a live sponsor.
    """
    return ref_access(conn, holder_type, holder, resource_type, resource_id).principal


# --- Run state of attached resources ----------------------------------------
#
# One check decides whether an attached resource runs, for the run and for the
# edit page alike (``ref_access``, ``resolve_holder_tool``), so the page never
# says a resource runs when the run drops it, or the other way round.

# Why an attached resource doesn't run (``resource_states`` ``reason``), next
# to the sponsor reasons above.
REASON_DELETED = "deleted"
REASON_OWNER_LOST_ACCESS = "owner_lost_access"
REASON_CONNECTION_NEEDS_RECONNECT = "connection_needs_reconnect"
REASON_CONNECTION_REMOVED = "connection_removed"
REASON_CONNECTOR_DISABLED = "connector_disabled"
# A team's item used through its share with the holder's team: the share was removed, or the
# reader left the receiving team (``team_share_ended``), or the owning team is locked, which
# pauses its shares until it unlocks (``team_locked``).
REASON_TEAM_SHARE_ENDED = "team_share_ended"
REASON_TEAM_LOCKED = "team_locked"

_REF_TABLES = {"source": "sources", "prompt": "prompts", "tool": "user_tools"}


@dataclass(frozen=True)
class RefAccess:
    """Who a holder runs one referenced resource as, or why it doesn't run.

    Attributes:
        principal: The user it is authorized as (the holder's owner or a live
            sponsor); None when it doesn't run.
        reason: None while it runs; else :data:`REASON_DELETED`,
            :data:`REASON_OWNER_LOST_ACCESS`, :data:`REASON_TEAM_SHARE_ENDED`,
            :data:`REASON_TEAM_LOCKED` or a sponsor reason.
        sponsor: The recorded sponsor, running or not.
    """

    principal: Optional[str]
    reason: Optional[str] = None
    sponsor: Optional[str] = None


def _ref_exists(conn: Connection, resource_type: str, resource_id: str) -> bool:
    """Whether a row with this id exists, whoever owns it."""
    table = _REF_TABLES.get(resource_type)
    if table is None or not looks_like_uuid(str(resource_id)):
        return False
    return conn.execute(
        text(f"SELECT 1 FROM {table} WHERE id = CAST(:id AS uuid)"), {"id": str(resource_id)}
    ).first() is not None


# --- Who a run answers ------------------------------------------------------
#
# A holder runs as its owner, but someone else may be the one reading its
# answers: a person chatting with a shared agent, whoever set a schedule on it,
# or an outside caller. A team's item reaches only the people its team chose
# (members, and teams it is shared with), so a run leaves out a team item its
# reader can't use themselves. That also covers an agent shared before team
# items were confined to the people who reach them, and a reader who left.
# The value is the reader's id, ``""`` for an outside caller nobody signed in
# as, and None outside a run (the edit page), where nothing is left out.

_RUN_READER: ContextVar[Optional[str]] = tracing.carry(ContextVar("resource_access_run_reader", default=None))


@contextmanager
def run_reader(reader: Optional[str]) -> Iterator[None]:
    """Resolve the holder refs inside the block for ``reader`` (None: an outside caller nobody signed in as).

    Args:
        reader: Who reads the run's answers.
    """
    token = _RUN_READER.set(reader or "")
    try:
        yield
    finally:
        _RUN_READER.reset(token)


def current_run_reader() -> Optional[str]:
    """The reader of the run in progress, ``""`` for an anonymous outside caller, None outside a run."""
    return _RUN_READER.get()


def read_by(reader: Optional[str], events: Iterable[Any]) -> Iterator[Any]:
    """Iterate ``events`` with ``reader`` as the run's reader around each step, never across a yield.

    A run resolves its tools (and a workflow its nodes' refs) while it streams,
    after the request that set it up has returned, so the reader is bound to
    each step of the stream instead of to a block.

    Args:
        reader: Who reads the run's answers (None: an anonymous outside caller).
        events: The run's event stream.
    """
    iterator = iter(events)
    try:
        while True:
            with run_reader(reader):
                try:
                    event = next(iterator)
                except StopIteration:
                    return
            yield event
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()


def _team_reach_reason(conn: Connection, resource_type: str, resource_id: str, reader: Optional[str]) -> str:
    """Why a team's item doesn't reach ``reader``: its team is locked with a share that would, or none does.

    Args:
        conn: Open database connection.
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The item's id (owned by a team's principal).
        reader: A person, a team's principal, or empty for nobody.

    Returns:
        :data:`REASON_TEAM_LOCKED` or :data:`REASON_TEAM_SHARE_ENDED`.
    """
    owner_team = team_of_principal(resource_owner(conn, resource_type, resource_id))
    if reader and owner_team and resource_type in RECEIVER_ACTIONS:
        repo = TeamItemSharesRepository(conn)
        if is_principal_id(reader):
            own_team = team_of_principal(reader)
            rows = [r for r in repo.teams_for(resource_type, resource_id) if str(r.get("team_id")) == own_team]
        else:
            rows = repo.reaching(reader, resource_type, resource_id)
        if any(str(r.get("owner_team_id")) == owner_team for r in rows) and (
            team_policy(conn, owner_team) == POLICY_LOCKED
        ):
            return REASON_TEAM_LOCKED
    return REASON_TEAM_SHARE_ENDED


def _lost_reason(conn: Connection, resource_type: str, resource_id: str, user_id: Optional[str]) -> str:
    """Why ``user_id`` can no longer use an item that exists: a team's reach ended, or they lost access."""
    if is_principal_id(resource_owner(conn, resource_type, resource_id)):
        return _team_reach_reason(conn, resource_type, resource_id, user_id)
    return REASON_OWNER_LOST_ACCESS


def reader_refusal(
    conn: Connection, holder: Optional[dict], resource_type: str, resource_id: str
) -> Optional[str]:
    """Why the run's reader may not have ``resource_id`` in their run of ``holder``, or None when they may.

    Only inside a run (:func:`run_reader`) and only for a reader other than the
    holder's owner. Only a team's item is judged, and never one of the holder's
    own team: that team chose who its agents reach. Any other team's item runs
    only for a reader who can use it themselves (a member of its team, or of a
    team it is shared with while that share is live).

    Args:
        conn: Open database connection.
        holder: The holder row (needs ``user_id``).
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.

    Returns:
        Optional[str]: None, :data:`REASON_TEAM_SHARE_ENDED` or :data:`REASON_TEAM_LOCKED`.
    """
    reader = _RUN_READER.get()
    if reader is None or not holder:
        return None
    owner = holder.get("user_id")
    if reader and reader == owner:
        return None
    item_team = team_of_principal(resource_owner(conn, resource_type, str(resource_id)))
    if item_team is None or item_team == team_of_principal(owner):
        return None
    if reader and can_use_ref(conn, resource_type, str(resource_id), reader):
        return None
    return _team_reach_reason(conn, resource_type, str(resource_id), reader)


def reader_sources(conn: Connection, holder_type: str, holder: Optional[dict], source_ids: Iterable) -> list:
    """``source_ids`` without the team sources the run's reader may not have, each one left out logged.

    For sources that reach a holder another way than its refs (its knowledge
    folders), so they are judged as a direct ref would be (:func:`reader_refusal`).

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        source_ids: The ids, in run order.

    Returns:
        list: The ids kept, in order.
    """
    kept: list = []
    for sid in source_ids or []:
        refused = reader_refusal(conn, holder, "source", str(sid))
        if refused:
            log_stopped(holder_type, holder, "source", sid, refused)
            continue
        kept.append(sid)
    return kept


def ref_access(
    conn: Connection, holder_type: str, holder: Optional[dict], resource_type: str, resource_id: str
) -> RefAccess:
    """Whether and as whom a holder runs one referenced resource.

    The run and the edit page both ask this. The owner runs it when they may
    use it, else a live sponsor does; otherwise it is stopped, because the row
    is gone, a recorded sponsor no longer qualifies, or the owner lost access.
    Another team's item used through a share stops as ``team_share_ended``
    (the share was removed, or the owner left the team it reached them
    through) or ``team_locked`` (its team is locked). Inside a run, a team's
    item its reader can't use is stopped too (:func:`reader_refusal`).

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row (needs ``user_id``; ``id`` and
            ``resource_sponsors`` for sponsors).
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.

    Returns:
        RefAccess: The principal, or the reason it doesn't run.
    """
    if not holder:
        return RefAccess(None, REASON_OWNER_LOST_ACCESS)
    rid = str(resource_id)
    owner = holder.get("user_id")
    if can_use_ref(conn, resource_type, rid, owner):
        refused = reader_refusal(conn, holder, resource_type, rid)
        return RefAccess(None, refused) if refused else RefAccess(owner)
    sponsor, sponsor_reason = sponsor_state(conn, holder_type, holder, resource_type, rid)
    if sponsor and sponsor_reason is None:
        refused = reader_refusal(conn, holder, resource_type, rid)
        return RefAccess(None, refused, sponsor) if refused else RefAccess(sponsor, None, sponsor)
    if not _ref_exists(conn, resource_type, rid):
        return RefAccess(None, REASON_DELETED, sponsor)
    return RefAccess(None, sponsor_reason or _lost_reason(conn, resource_type, rid, owner), sponsor)


def resolve_holder_tool(
    conn: Connection, holder_type: str, holder: Optional[dict], tool_id: str, *, tools_repo=None
) -> tuple[Optional[dict], RefAccess]:
    """The tool row a holder runs ``tool_id`` with, and its access.

    Builtin and default tool ids resolve to their synthesized rows. A
    ``user_tools`` row resolves as the holder's owner, else as its live
    sponsor (see :func:`ref_access`); the row is the tool owner's either way.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        tool_id: The referenced tool id.
        tools_repo: A ``UserToolsRepository`` on ``conn`` to reuse.

    Returns:
        ``(row, access)``: the row, None when it doesn't run, and why.
    """
    # Lazy: default_tools imports this module lazily too.
    from docsgpt.agents.default_tools import resolve_tool_by_id

    repo = tools_repo or UserToolsRepository(conn)
    owner = (holder or {}).get("user_id")
    row = resolve_tool_by_id(tool_id, owner, user_tools_repo=repo)
    if row is not None:
        return row, RefAccess(owner)
    access = ref_access(conn, holder_type, holder, "tool", str(tool_id))
    if access.principal:
        row = resolve_tool_by_id(tool_id, access.principal, user_tools_repo=repo)
    if row is None:
        reason = access.reason or REASON_DELETED
        return None, RefAccess(None, reason, access.sponsor)
    return row, access


def resolve_holder_tools(
    conn: Connection,
    holder_type: str,
    holder: Optional[dict],
    tool_ids: Iterable,
    *,
    headless: bool = False,
    tools_repo=None,
) -> dict[str, dict]:
    """Exactly the tools a holder runs, keyed by id: the one runtime resolver for agents and workflow nodes.

    Each id resolves through :func:`resolve_holder_tool` (the holder's owner,
    else a live sponsor), and a tool that doesn't run is logged with why;
    inside a run, so is a team's tool the run's reader can't use
    (:func:`reader_refusal`).
    Left out as well: server-attached tools (``check_job``: the server adds
    it, a saved id is not a choice), workflow-only builtins outside a
    workflow (``read_document``), and chat-only tools on a headless run
    (``scheduler``).

    Args:
        conn: Open database connection.
        holder_type: ``agent`` (an agent's ``tools``) or ``workflow`` (one
            agent node's ``tools``).
        holder: The holder row; its ``user_id`` is who the tools run as.
        tool_ids: The configured tool ids.
        headless: True for a scheduled or webhook run.
        tools_repo: A ``UserToolsRepository`` on ``conn`` to reuse.

    Returns:
        dict: ``tool_id -> row``, in configured order.
    """
    # Lazy: default_tools imports this module lazily too.
    from docsgpt.agents.default_tools import (
        is_headless_excluded_tool,
        is_server_attached_tool,
        is_server_attached_tool_id,
    )

    repo = tools_repo or UserToolsRepository(conn)
    tools: dict[str, dict] = {}
    for tid in tool_ids or []:
        if not tid or is_server_attached_tool_id(tid):
            continue
        row, access = resolve_holder_tool(conn, holder_type, holder, str(tid), tools_repo=repo)
        if row is None:
            log_stopped(holder_type, holder, "tool", tid, access.reason)
            continue
        # A stored tool the owner reaches directly skips ``ref_access``: the run's reader is checked here.
        refused = reader_refusal(conn, holder, "tool", str(tid)) if _sponsorable("tool", str(tid)) else None
        if refused:
            log_stopped(holder_type, holder, "tool", tid, refused)
            continue
        name = row.get("name")
        if is_server_attached_tool(name):
            continue
        if row.get("workflow_only") and holder_type != "workflow":
            continue
        if headless and is_headless_excluded_tool(name):
            continue
        tools[str(row["id"])] = row
    return tools


def authorized_holder_sources(
    conn: Connection, holder_type: str, holder: Optional[dict], source_ids: Iterable
) -> list:
    """The source ids a holder may retrieve from: the one runtime check for agents and workflow nodes.

    Each is authorized by :func:`ref_access` (the holder's owner, else a live
    sponsor, and inside a run only a team's source its reader may use); one
    that doesn't run is logged with why. Empty refs are
    skipped and an id listed twice (any casing) is kept once.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row; its ``user_id`` is who the sources run as.
        source_ids: The configured ids, in run order.

    Returns:
        list: The usable ids as given, in order.
    """
    allowed: list = []
    seen: set[str] = set()
    for sid in source_ids or []:
        if not sid:
            continue
        key = str(sid).lower()
        if key in seen:
            continue
        seen.add(key)
        access = ref_access(conn, holder_type, holder, "source", str(sid))
        if access.principal:
            allowed.append(sid)
        else:
            log_stopped(holder_type, holder, "source", sid, access.reason)
    return allowed


def log_stopped(
    holder_type: str, holder: Optional[dict], resource_type: str, resource_id, reason: Optional[str]
) -> None:
    """Log one attached resource a run leaves out, greppable by ``resource_stopped``.

    Args:
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.
        reason: Why it doesn't run.
    """
    holder_id = str((holder or {}).get("id") or "")
    logger.info(
        "resource_stopped holder=%s:%s type=%s id=%s reason=%s",
        holder_type, holder_id, resource_type, resource_id, reason,
        extra={
            "event": "resource_stopped",
            "holder_type": holder_type,
            "holder_id": holder_id,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "reason": reason,
        },
    )


def _sponsorable(resource_type: str, resource_id: str) -> bool:
    """Only real rows need a principal: skip presets and builtin tool ids."""
    rid = str(resource_id or "")
    if not looks_like_uuid(rid):
        return False
    if resource_type == "tool":
        # Lazy: default_tools imports this module lazily too.
        from docsgpt.agents.default_tools import is_synthesized_tool_id

        return not is_synthesized_tool_id(rid)
    return True


def agent_refs(agent: dict) -> list[tuple[str, str]]:
    """The ``(type, id)`` resources an agent row references."""
    refs = [("source", str(s)) for s in [agent.get("source_id"), *(agent.get("extra_source_ids") or [])] if s]
    if agent.get("prompt_id"):
        refs.append(("prompt", str(agent["prompt_id"])))
    refs.extend(("tool", str(t)) for t in agent.get("tools") or [] if t)
    return refs


def parse_confirmations(raw) -> set[str]:
    """``confirm_sponsor`` from a request as canonical ``"<type>:<id>"`` keys.

    Accepts a list, a JSON-encoded list (form posts) or a comma-separated
    string. Unknown shapes and malformed entries are dropped, so they can
    never confirm anything.

    Args:
        raw: The request value, or None.

    Returns:
        set: The confirmed keys, ids lowercased like stored refs.
    """
    if raw is None or raw == "":
        return set()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = raw.split(",")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return set()
    out: set[str] = set()
    for item in raw:
        resource_type, _, resource_id = str(item).strip().partition(":")
        if resource_type in REF_USE_ACTION and resource_id:
            out.add(sponsor_key(resource_type, canonical_uuid(resource_id.strip())))
    return out


@dataclass
class SponsorPlan:
    """What a save does to a holder's sponsors, and what stops it.

    Attributes:
        sponsors: The ``resource_sponsors`` map to store.
        needs_confirmation: ``(type, id)`` refs the save would newly have the
            caller sponsor without their confirmation; the save must be
            refused with :data:`CODE_CONFIRMATION_REQUIRED`.
        not_allowed: Newly attached ``(type, id)`` refs the owner can't use
            and the caller may not sponsor; the save must be refused.
        unexpected: Confirmed keys this save has no sponsorship for.
    """

    sponsors: dict = field(default_factory=dict)
    needs_confirmation: list = field(default_factory=list)
    not_allowed: list = field(default_factory=list)
    unexpected: list = field(default_factory=list)


def plan_sponsors(
    conn: Connection,
    holder_type: str,
    holder: Optional[dict],
    owner_id: str,
    caller: str,
    refs: Iterable[tuple[str, str]],
    previous_refs: Iterable[tuple[str, str]] = (),
    confirmed: Iterable[str] = (),
) -> SponsorPlan:
    """Work out the sponsors after ``caller`` saves ``refs``.

    Per referenced resource the owner can't use:

    * a recorded sponsor who still qualifies is kept;
    * the caller becomes the sponsor only when they may sponsor it
      (:func:`can_sponsor_ref`) and listed its key in ``confirmed``;
    * a newly attached one the caller may sponsor but didn't confirm goes to
      ``needs_confirmation``; one they may not sponsor goes to ``not_allowed``;
    * one already attached keeps its old record even when that sponsor lost
      access: it stays stopped until someone confirms taking it over;
    * a newly attached one ignores any record left from before it was
      removed, so a stale sponsor never vouches for it again.

    Resources the owner can use, presets and builtin tools need no sponsor.
    Removed refs drop out. A confirmed key that names none of the refs the
    caller could sponsor lands in ``unexpected``.

    A team holder (``owner_id`` a principal) takes no sponsors: a newly
    attached resource the team can't use goes to ``not_allowed``, one already
    attached stays stopped, and every confirmed key is ``unexpected``. The
    routes refuse such refs first with :func:`workspace_mismatch_refusal`.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row before the save (None when creating it).
        owner_id: The holder's owner.
        caller: The user saving.
        refs: Every ``(type, id)`` the holder references after the save.
        previous_refs: Every ``(type, id)`` it referenced before the save.
        confirmed: ``"<type>:<id>"`` keys the caller agreed to sponsor.

    Returns:
        SponsorPlan: The map to store and anything that refuses the save.
    """
    previous = (holder or {}).get("resource_sponsors") or {}
    before = {sponsor_key(t, str(i).lower()) for t, i in previous_refs}
    confirmed = set(confirmed)
    plan = SponsorPlan()
    if is_principal_id(owner_id):
        return _plan_team_holder(conn, owner_id, refs, before, confirmed)
    eligible: set[str] = set()
    seen: set[str] = set()
    for resource_type, resource_id in refs:
        resource_id = str(resource_id).lower()
        key = sponsor_key(resource_type, resource_id)
        if key in seen or not _sponsorable(resource_type, resource_id):
            continue
        seen.add(key)
        if can_use_ref(conn, resource_type, resource_id, owner_id):
            continue
        is_new = key not in before
        caller_may = caller != owner_id and can_sponsor_ref(conn, resource_type, resource_id, caller)
        if caller_may:
            eligible.add(key)
        # A record only vouches for a resource that stayed attached: one left
        # behind by a path that dropped the resource never covers it again.
        live = None if is_new else active_sponsor(conn, holder_type, holder, resource_type, resource_id)
        if live:
            plan.sponsors[key] = live
        elif caller_may and key in confirmed:
            plan.sponsors[key] = caller
        elif is_new and caller != owner_id:
            (plan.needs_confirmation if caller_may else plan.not_allowed).append((resource_type, resource_id))
        elif not is_new and previous.get(key):
            plan.sponsors[key] = previous[key]
    plan.unexpected = sorted(confirmed - eligible)
    return plan


def _plan_team_holder(
    conn: Connection, owner_id: str, refs: Iterable[tuple[str, str]], before: set[str], confirmed: set[str]
) -> SponsorPlan:
    """:func:`plan_sponsors` for a team holder: no sponsors, ever."""
    plan = SponsorPlan(unexpected=sorted(confirmed))
    seen: set[str] = set()
    for resource_type, resource_id in refs:
        resource_id = str(resource_id).lower()
        key = sponsor_key(resource_type, resource_id)
        if key in seen or not _sponsorable(resource_type, resource_id):
            continue
        seen.add(key)
        if key not in before and not can_use_ref(conn, resource_type, resource_id, owner_id):
            plan.not_allowed.append((resource_type, resource_id))
    return plan


def refusal_plan(plans: Iterable[SponsorPlan]) -> SponsorPlan:
    """One plan for :func:`sponsor_refusal` from several holders saved together.

    An agent save that also writes its workflow graph plans both holders
    against the same ``confirm_sponsor`` list: what either refuses refuses
    the save, and a confirmed key is unexpected only when neither holder
    could use it. ``sponsors`` stays empty; store each plan's own map.

    Args:
        plans: The plans of every holder the save writes.

    Returns:
        SponsorPlan: Lists merged for the refusal check.
    """
    plans = list(plans)
    merged = SponsorPlan()
    for plan in plans:
        merged.not_allowed.extend(plan.not_allowed)
        merged.needs_confirmation.extend(plan.needs_confirmation)
    if plans:
        merged.unexpected = sorted(set.intersection(*(set(plan.unexpected) for plan in plans)))
    return merged


def prune_sponsors(sponsors: Optional[dict], refs: Iterable[tuple[str, str]]) -> dict:
    """``sponsors`` without the keys of resources no longer referenced.

    For paths that rewrite a holder's references without going through
    :func:`plan_sponsors` (YAML import, a workflow graph written by import).

    Args:
        sponsors: The stored ``resource_sponsors`` map.
        refs: Every ``(type, id)`` the holder references now.

    Returns:
        dict: The map to store.
    """
    keep = {sponsor_key(t, str(i).lower()) for t, i in refs}
    return {k: v for k, v in (sponsors or {}).items() if k.lower() in keep}


def ref_names(conn: Connection, refs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Display names of referenced resources, looked up by id (owner-agnostic).

    Args:
        conn: Open database connection.
        refs: ``(type, id)`` pairs; ``folder`` names a knowledge folder a save
            asks to confirm (``folder_knowledge.plan_folder_confirmations``).

    Returns:
        dict: ``"<type>:<id>" -> name`` for the ones found.
    """
    queries = {
        "source": "SELECT id, name FROM sources WHERE id = ANY(CAST(:ids AS uuid[]))",
        "folder": "SELECT id, name FROM folders WHERE id = ANY(CAST(:ids AS uuid[]))",
        "prompt": "SELECT id, name FROM prompts WHERE id = ANY(CAST(:ids AS uuid[]))",
        "tool": (
            "SELECT id, COALESCE(NULLIF(custom_name, ''), NULLIF(display_name, ''), name) "
            "FROM user_tools WHERE id = ANY(CAST(:ids AS uuid[]))"
        ),
    }
    by_type: dict[str, list[str]] = {}
    for resource_type, resource_id in refs:
        if resource_type in queries and looks_like_uuid(str(resource_id)):
            by_type.setdefault(resource_type, []).append(str(resource_id))
    out: dict[str, str] = {}
    for resource_type, ids in by_type.items():
        for rid, name in conn.execute(text(queries[resource_type]), {"ids": ids}).fetchall():
            if name:
                out[sponsor_key(resource_type, str(rid))] = name
    return out


def holder_audience(conn: Connection, holder_type: str, holder: dict, *, api_key: Optional[bool] = None) -> dict:
    """Who reaches a holder's resources: its teams and outside entry points.

    For a workflow, the union over the owner's agents that run it.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        api_key: Override for an agent whose key this save creates.

    Returns:
        dict: ``teams`` (names, sorted), and booleans ``api_key`` (API and
        widget), ``public_link`` and ``webhook``.
    """
    if holder_type == "agent":
        agents = [holder]
    else:
        ids = [str(a) for a in _workflow_agent_ids(conn, holder)]
        agents = [a for a in (AgentsRepository(conn).get_by_id(i) for i in ids) if a]
    grants_repo = TeamResourceGrantsRepository(conn)
    teams: set[str] = set()
    for agent in agents:
        teams.update(g.get("team_name") for g in grants_repo.list_for_resource("agent", str(agent["id"])))
    has_key = any(a.get("key") for a in agents)
    return {
        "teams": sorted(t for t in teams if t),
        "api_key": bool(has_key if api_key is None else api_key or has_key),
        "public_link": any(a.get("shared") and a.get("shared_token") for a in agents),
        "webhook": any(a.get("incoming_webhook_token") for a in agents),
    }


def sponsor_refusal(
    conn: Connection, holder_type: str, holder: dict, plan: SponsorPlan, *, api_key: Optional[bool] = None
) -> Optional[tuple[dict, int]]:
    """The error body and status for a save ``plan`` refuses, or None.

    In order: 403 :data:`CODE_NOT_ALLOWED` (a new resource the caller may not
    sponsor), 400 :data:`CODE_UNEXPECTED_CONFIRMATION`, then 409
    :data:`CODE_CONFIRMATION_REQUIRED` listing what the caller would sponsor
    and the holder's audience, so the client can ask and retry with
    ``confirm_sponsor``.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row before the save.
        plan: The result of :func:`plan_sponsors`.
        api_key: Passed to :func:`holder_audience`.

    Returns:
        ``(body, status)`` or None when the save may go ahead.
    """
    def _resources(pairs: list) -> list[dict]:
        names = ref_names(conn, pairs)
        return [
            {
                "key": sponsor_key(t, i),
                "type": t,
                "id": i,
                "name": names.get(sponsor_key(t, i)),
            }
            for t, i in pairs
        ]

    if plan.not_allowed:
        return {
            "success": False,
            "code": CODE_NOT_ALLOWED,
            "message": (
                "You can't add a resource the owner can't use unless you own it or can edit it."
            ),
            "resources": _resources(plan.not_allowed),
        }, 403
    if plan.unexpected:
        return {
            "success": False,
            "code": CODE_UNEXPECTED_CONFIRMATION,
            "message": "confirm_sponsor lists resources this save doesn't ask you to sponsor.",
            "unexpected": plan.unexpected,
        }, 400
    if plan.needs_confirmation:
        return {
            "success": False,
            "code": CODE_CONFIRMATION_REQUIRED,
            "message": (
                "These resources would run with your access for everyone who uses this agent. "
                "Confirm to add them."
            ),
            "resources": _resources(plan.needs_confirmation),
            "audience": holder_audience(conn, holder_type, holder, api_key=api_key),
        }, 409
    return None


def sponsor_details(
    conn: Connection, holder_type: str, holder: dict, viewer: Optional[str] = None
) -> list[dict]:
    """The holder's sponsored resources for its edit page.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        viewer: The user reading the page; sets ``can_confirm``.

    Returns:
        list: Per sponsored resource ``{key, type, id, name, user_id, label,
        state, reason, active, can_confirm}``. ``user_id`` and ``label`` (the
        sponsor's email when on file) are both None for a sponsor the reader
        doesn't know (see :func:`people_named_to`); ``state`` is ``active``
        or ``inactive``, and
        ``reason`` (None while active) is :data:`REASON_CANNOT_EDIT_HOLDER`
        or :data:`REASON_CANNOT_EDIT_RESOURCE`; ``active`` mirrors ``state``.
        ``can_confirm`` says whether ``viewer`` may take an inactive one
        over by confirming it on their next save.
    """
    sponsors = holder.get("resource_sponsors") or {}
    if not sponsors:
        return []
    labels = person_labels(conn, viewer, holder, sponsors.values())
    entries = []
    for key, user_id in sponsors.items():
        resource_type, _, resource_id = key.partition(":")
        if resource_type in REF_USE_ACTION and resource_id:
            entries.append((key, resource_type, resource_id, user_id))
    names = ref_names(conn, [(t, i) for _, t, i, _ in entries])
    viewer_edits = bool(
        viewer
        and viewer != holder.get("user_id")
        and _holder_editable_by(conn, holder_type, holder, viewer)
    )
    out = []
    for key, resource_type, resource_id, user_id in entries:
        _, reason = sponsor_state(conn, holder_type, holder, resource_type, resource_id)
        active = reason is None
        out.append(
            {
                "key": key,
                "type": resource_type,
                "id": resource_id,
                "name": names.get(key),
                **(_person(user_id, labels, user_id in labels) or {"user_id": None, "label": None}),
                "state": "active" if active else "inactive",
                "reason": reason,
                "active": active,
                "can_confirm": bool(
                    not active
                    and viewer_edits
                    and can_sponsor_ref(conn, resource_type, resource_id, viewer)
                ),
            }
        )
    return out


def holder_editable_by(conn: Connection, holder_type: str, holder: dict, user_id: Optional[str]) -> bool:
    """Whether ``user_id`` may edit the agent or workflow ``holder``.

    Its owner always may; anyone else needs ``edit`` on the agent (for a
    workflow, on one of its owner's agents that run it).

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        user_id: The reader.

    Returns:
        bool: Whether they may edit it.
    """
    if not user_id or not holder:
        return False
    if user_id == holder.get("user_id"):
        return True
    return _holder_editable_by(conn, holder_type, holder, user_id)


def _ref_rows(conn: Connection, refs: Iterable[tuple[str, str]]) -> dict[str, dict]:
    """``"<type>:<id>" -> {name, user_id}`` for referenced rows, owner-agnostic, per type in one query."""
    queries = {
        "source": "SELECT id, name, user_id FROM sources WHERE id = ANY(CAST(:ids AS uuid[]))",
        "prompt": "SELECT id, name, user_id FROM prompts WHERE id = ANY(CAST(:ids AS uuid[]))",
        "tool": (
            "SELECT id, COALESCE(NULLIF(custom_name, ''), NULLIF(display_name, ''), name), user_id "
            "FROM user_tools WHERE id = ANY(CAST(:ids AS uuid[]))"
        ),
    }
    by_type: dict[str, list[str]] = {}
    for resource_type, resource_id in refs:
        if resource_type in queries and looks_like_uuid(str(resource_id)):
            by_type.setdefault(resource_type, []).append(str(resource_id))
    out: dict[str, dict] = {}
    for resource_type, ids in by_type.items():
        for rid, name, owner in conn.execute(text(queries[resource_type]), {"ids": ids}).fetchall():
            out[sponsor_key(resource_type, str(rid))] = {"name": name, "user_id": owner}
    return out


def _user_labels(conn: Connection, user_ids: Iterable[Optional[str]]) -> dict[str, str]:
    """``user_id -> label``: a person's email when on file, a team principal's team name.

    Args:
        conn: Open database connection.
        user_ids: The ids to label.

    Returns:
        dict[str, str]: Only the ids that have a label.
    """
    ids = sorted({u for u in user_ids if u})
    if not ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT u.user_id, CASE WHEN u.kind = 'team' THEN t.name ELSE u.email END
            FROM users u LEFT JOIN teams t ON t.id = u.team_id
            WHERE u.user_id = ANY(:ids)
            """
        ),
        {"ids": ids},
    ).fetchall()
    return {user_id: label for user_id, label in rows if label}


# ``resource_states`` ``note`` for a running tool on each caller's own account.
NOTE_PER_USER_ACCOUNT = "per_user_account"

# ``resource_states`` ``contact_role``: whom to ask, when someone can fix it.
CONTACT_RESOURCE_OWNER = "resource_owner"


# What ``resource_states`` says about how a tool runs, for anything that
# isn't a running tool.
_NO_RUN_DETAILS = {
    "note": None,
    "credential_mode": None,
    "account": None,
    "owner_credential_writes": [],
    "writes_allowed": True,
}


def _tool_run_state(conn: Connection, tool: dict, owner: Optional[str], policies_box: list) -> tuple:
    """``(reason, connection, run)`` for a tool the holder runs as ``owner``.

    Resolved the way the run resolves it. Only an owner-mode tool's account
    is judged (see ``connection_stop_reason``); a member-mode one runs on
    each caller's own account.

    ``connection`` is ``(id, connector_key, name)`` for a tool with a
    connection or one that lost it, else None. ``run`` is what
    ``resource_states`` says about a tool that runs, :data:`_NO_RUN_DETAILS`
    for one that doesn't: ``note`` (:data:`NOTE_PER_USER_ACCOUNT` in member
    mode), ``credential_mode`` (``owner`` or ``member`` after any mode an
    admin forces, for a tool with a connection), ``account`` (the tool's
    owner, whose saved credentials or owner-mode connection it acts with),
    the ``owner_credential_writes`` outside callers need allowlisted, and
    ``writes_allowed`` (False when an admin turned off changes through its
    connector).
    """
    from docsgpt.connectors import catalog, service
    from docsgpt.connectors.resolve import (
        MODE_MEMBER,
        REMOVED_CONNECTION_KEY,
        connection_stop_reason,
        is_connectionless_member,
        resolve_connection,
    )

    # A member-mode tool without a connection (a team's) still resolves: by the service it names.
    if not tool.get("connection_id") and not is_connectionless_member(tool):
        reason = connection_stop_reason(tool, None)
        if reason is not None:
            marker = (tool.get("config") or {}).get(REMOVED_CONNECTION_KEY)
            key = marker if isinstance(marker, str) and marker else None
            definition = catalog.get_definition(key) if key else catalog.definition_for_tool(tool.get("name") or "")
            connection = (None, definition.key if definition else key, definition.name if definition else None)
            return reason, connection, dict(_NO_RUN_DETAILS)
        mode, writes_allowed, connection = None, True, None
    else:
        if not policies_box:
            policies_box.append(service.load_policies(conn))
        resolved = resolve_connection(tool, owner, conn=conn, policies=policies_box[0])
        connection = (resolved.connection_id, resolved.connector_key, resolved.connector_name)
        reason = connection_stop_reason(tool, resolved)
        if reason is not None:
            return reason, connection, dict(_NO_RUN_DETAILS)
        mode, writes_allowed = resolved.mode, resolved.writes_allowed
    member = mode == MODE_MEMBER
    return None, connection, {
        "note": NOTE_PER_USER_ACCOUNT if member else None,
        "credential_mode": mode,
        "account": tool.get("user_id") if not member and holds_owner_credentials(tool) else None,
        "owner_credential_writes": owner_credential_writes(tool) if writes_allowed else [],
        "writes_allowed": writes_allowed,
    }


def _connection_payload(connection: Optional[tuple], reader_owns: bool, can_reconnect: bool) -> Optional[dict]:
    """The ``connection`` a reader may see: the id only to reconnect it, its own name only to its owner."""
    if connection is None:
        return None
    from docsgpt.connectors import catalog

    connection_id, connector_key, name = connection
    if not reader_owns:
        # The owner's name for the account (a custom MCP server's label, say)
        # is theirs; others see the service's own name.
        definition = catalog.get_definition(connector_key) if connector_key else None
        name = definition.name if definition else None
    return {"id": connection_id if can_reconnect else None, "connector_key": connector_key, "name": name}


def people_named_to(
    conn: Connection,
    viewer: Optional[str],
    holder: dict,
    people: Iterable[tuple[Optional[str], Optional[tuple[str, str]]]],
) -> set:
    """Which people an agent or workflow page may name to its reader.

    The one rule for every person the page names (a sponsor, whom a
    resource runs as, whom to ask, whose credentials a tool uses): only
    someone the reader knows already. That is the reader, the holder's
    owner, anyone who sponsored something on the reader's own holder, and
    anyone who shares a team with the reader; a person named as the owner
    of one resource only when, besides sharing a team, the reader can see
    that resource too. Anyone else is left unnamed.

    Args:
        conn: Open database connection.
        viewer: The user reading the page.
        holder: The agent or workflow row (``user_id``, ``resource_sponsors``).
        people: ``(user_id, ref)`` pairs; ``ref`` is the ``(type, id)`` the
            person is named as the owner of, or None.

    Returns:
        set: The ``(user_id, ref)`` pairs that may be named.
    """
    pairs = {(user_id, ref) for user_id, ref in people if user_id}
    owner = holder.get("user_id")
    known = {u for u in (viewer, owner) if u}
    if viewer and viewer == owner:
        known.update(u for u in (holder.get("resource_sponsors") or {}).values() if u)
    rest = sorted({user_id for user_id, _ in pairs if user_id not in known})
    teammates: set = set()
    if viewer and rest:
        teammates = {row[0] for row in conn.execute(
            text(
                "SELECT DISTINCT theirs.user_id FROM team_members mine "
                "JOIN team_members theirs ON theirs.team_id = mine.team_id "
                "WHERE mine.user_id = :viewer AND theirs.user_id = ANY(:ids)"
            ),
            {"viewer": viewer, "ids": rest},
        ).fetchall()}
    named = set()
    for user_id, ref in pairs:
        if user_id in known or (
            user_id in teammates and (ref is None or resolve(conn, ref[0], ref[1], viewer) is not None)
        ):
            named.add((user_id, ref))
    return named


def person_labels(
    conn: Connection, viewer: Optional[str], holder: Optional[dict], user_ids: Iterable[Optional[str]]
) -> dict[str, str]:
    """How an agent or workflow page names each person to its reader.

    The names the sponsor list ("Added by …") uses: only people the reader
    knows (:func:`people_named_to`), each by their email when on file, else
    by their user id.

    Args:
        conn: Open database connection.
        viewer: The user reading the page.
        holder: The agent or workflow row, or None off a holder.
        user_ids: The people to name.

    Returns:
        dict: ``user_id -> label`` for the ones the reader may see named.
    """
    named = {user_id for user_id, _ in people_named_to(conn, viewer, holder or {}, [(u, None) for u in user_ids])}
    emails = _user_labels(conn, named)
    return {user_id: emails.get(user_id) or user_id for user_id in named}


def creator_payloads(conn: Connection, viewer: Optional[str], rows: Iterable[dict]) -> dict[str, dict]:
    """Who added each item of a list, as its reader may see them named.

    A team's item names who added it to every member, also after that person
    left the team: it is the team's own record. A personal item names its
    creator only to someone who knows them (:func:`people_named_to`).

    Args:
        conn: Open database connection.
        viewer: The user reading the list.
        rows: Item rows (``user_id``, ``created_by``); every row must be one the viewer can see.

    Returns:
        dict[str, dict]: ``created_by -> {user_id, label}``, both None for someone left unnamed.
        Feed it to :func:`created_by_payload` per row.
    """
    rows = [row for row in rows if row.get("created_by")]
    in_team = {row["created_by"] for row in rows if is_principal_id(row.get("user_id"))}
    others = {row["created_by"] for row in rows} - in_team
    labels = _user_labels(conn, in_team)
    out = {user_id: _person(user_id, labels, True) for user_id in in_team}
    if others:
        known = person_labels(conn, viewer, None, others)
        out.update({user_id: _person(user_id, known, user_id in known) for user_id in others})
    return out


def created_by_payload(row: dict, creators: dict[str, dict]) -> Optional[dict]:
    """One row's ``created_by`` field from :func:`creator_payloads`, or None when the row records nobody."""
    return creators.get(row.get("created_by")) if row.get("created_by") else None


def _person(user_id: Optional[str], labels: dict, named: bool) -> Optional[dict]:
    """``{user_id, label}`` for someone the reader may see named, both None otherwise."""
    if not user_id:
        return None
    if not named:
        return {"user_id": None, "label": None}
    return {"user_id": user_id, "label": labels.get(user_id) or user_id}


def resource_states(
    conn: Connection,
    holder_type: str,
    holder: dict,
    refs: Iterable[tuple[str, str]],
    viewer: Optional[str],
) -> list[dict]:
    """Whether each resource a holder references runs, for its edit page.

    Uses the run's own checks (:func:`ref_access`, :func:`resolve_holder_tool`
    and an owner-mode tool's connection as the run resolves it for the
    owner), so a source or prompt shown as stopped is one the run leaves out,
    and a tool shown as stopped is left out or can't run until someone acts:
    a tool whose owner-mode account needs attention is still offered to the
    model, and pauses (or, with nobody to ask, is refused) when called.
    Presets and builtin tools always run and are not listed. Only for readers
    who may edit the holder: the caller checks that.

    A name is given only for a resource that runs, that the reader can see
    themselves, that someone sponsored on the holder, or that is attached to
    an agent (agent saves check every reference), so a reference to someone
    else's resource never reveals its name.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        refs: The ``(type, id)`` resources it references.
        viewer: The user reading the page.

    Returns:
        list: Per resource ``{key, type, id, name, state, reason, note,
        sponsor, contact, contact_role, connection, runs_as, credential_mode,
        account, owner_credential_writes, writes_allowed, can_confirm,
        can_reconnect}``. ``state`` is
        ``active`` or ``stopped``; ``reason`` (None while active) is one of
        ``deleted``, ``owner_lost_access``, the sponsor reasons,
        ``connection_needs_reconnect``, ``connection_removed`` or
        ``connector_disabled``. ``sponsor`` (``{user_id, label}``) is the
        recorded sponsor. ``contact_role`` is ``resource_owner`` when the
        resource's owner (not the reader) can fix it, and ``contact`` names
        them, or is None. ``connection`` (``{id, connector_key, name}``)
        names the service of a connected tool, and of one whose connection
        reason stopped it; ``id`` only when the reader may reconnect it, and
        the account's own name only for its owner. ``runs_as`` (``{user_id,
        label}``) is the live sponsor a running item runs as, None when it
        runs as the owner or doesn't run.
        For a running tool, ``note`` is ``per_user_account`` when it runs on
        each caller's own account; ``credential_mode`` is ``owner`` or
        ``member`` when it has a connection (else None); ``account`` is whose
        saved credentials or ``owner``-mode connection it acts with (the
        tool's owner); ``owner_credential_writes`` names its write actions on
        those credentials (what the API write allowlist covers); and
        ``writes_allowed`` is False when an admin turned off changes through
        its connector. Other items get None, None, None, ``[]`` and True.
        Every person is named only to a reader who knows them
        (:func:`people_named_to`): ``sponsor``, ``runs_as`` and ``account``
        are then ``{user_id: None, label: None}``, and ``contact`` None.
        ``can_confirm``: the reader may take it over on their next save;
        ``can_reconnect``: the reader owns the connection that needs signing
        in again.
    """
    owner = holder.get("user_id")
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for resource_type, resource_id in refs:
        rid = str(resource_id).lower()
        key = sponsor_key(resource_type, rid)
        if key in seen or resource_type not in REF_USE_ACTION or not _sponsorable(resource_type, rid):
            continue
        seen.add(key)
        pairs.append((resource_type, rid))
    if not pairs:
        return []
    rows = _ref_rows(conn, pairs)
    recorded = {k.lower(): v for k, v in (holder.get("resource_sponsors") or {}).items()}
    viewer_edits = bool(viewer and viewer != owner and _holder_editable_by(conn, holder_type, holder, viewer))
    tools_repo = UserToolsRepository(conn)
    policies_box: list = []
    entries: list[dict] = []

    def reader_sees(resource_type: str, rid: str) -> bool:
        return bool(viewer) and resolve(conn, resource_type, rid, viewer) is not None

    for resource_type, rid in pairs:
        key = sponsor_key(resource_type, rid)
        info = rows.get(key) or {}
        connection = None
        run = dict(_NO_RUN_DETAILS)
        if resource_type == "tool":
            tool_row, access = resolve_holder_tool(conn, holder_type, holder, rid, tools_repo=tools_repo)
            reason = access.reason
            if tool_row is not None and reason is None:
                reason, connection, run = _tool_run_state(conn, tool_row, owner, policies_box)
        else:
            access = ref_access(conn, holder_type, holder, resource_type, rid)
            reason = access.reason
        sponsor = recorded.get(key)
        sponsor = sponsor if sponsor and sponsor != owner else None
        # Who it runs as now: a live sponsor, or None for the owner (a
        # recorded sponsor stops mattering once the owner can use it).
        runs_as = access.principal if reason is None and access.principal != owner else None
        resource_owner = info.get("user_id")
        can_confirm = bool(
            reason in (REASON_OWNER_LOST_ACCESS, REASON_CANNOT_EDIT_HOLDER, REASON_CANNOT_EDIT_RESOURCE)
            and viewer_edits
            and can_sponsor_ref(conn, resource_type, rid, viewer)
        )
        # Whoever owns the resource can share it again or fix its account.
        contact = (
            resource_owner
            if reason in (REASON_OWNER_LOST_ACCESS, REASON_CONNECTION_NEEDS_RECONNECT, REASON_CONNECTION_REMOVED)
            and resource_owner
            and resource_owner != viewer
            else None
        )
        name_visible = bool(reason is None or sponsor or holder_type == "agent" or reader_sees(resource_type, rid))
        can_reconnect = bool(
            reason == REASON_CONNECTION_NEEDS_RECONNECT
            and connection
            and connection[0]
            and viewer
            and viewer == resource_owner
        )
        entries.append({
            "key": key,
            "type": resource_type,
            "id": rid,
            "name": info.get("name") if name_visible else None,
            "state": "active" if reason is None else "stopped",
            "reason": reason,
            "note": run["note"],
            "sponsor": sponsor,
            "contact": contact,
            "contact_role": CONTACT_RESOURCE_OWNER if contact else None,
            "connection": _connection_payload(connection, bool(viewer) and viewer == resource_owner, can_reconnect),
            "runs_as": runs_as,
            "credential_mode": run["credential_mode"],
            "account": run["account"],
            "owner_credential_writes": run["owner_credential_writes"],
            "writes_allowed": run["writes_allowed"],
            "can_confirm": can_confirm,
            "can_reconnect": can_reconnect,
        })
    # Every person is named by the one rule (:func:`people_named_to`); whom
    # to ask and whose credentials a tool uses are named as the owner of
    # that resource.
    people = [
        (entry[field_name], (entry["type"], entry["id"]) if field_name in ("contact", "account") else None)
        for entry in entries
        for field_name in ("sponsor", "runs_as", "contact", "account")
    ]
    named = people_named_to(conn, viewer, holder, people)
    labels = _user_labels(conn, [user_id for user_id, ref in named])
    for entry in entries:
        ref = (entry["type"], entry["id"])
        entry["sponsor"] = _person(entry["sponsor"], labels, (entry["sponsor"], None) in named)
        entry["runs_as"] = _person(entry["runs_as"], labels, (entry["runs_as"], None) in named)
        entry["account"] = _person(entry["account"], labels, (entry["account"], ref) in named)
        # Whom to ask stays a role for someone the reader doesn't know.
        contact = _person(entry["contact"], labels, (entry["contact"], ref) in named)
        entry["contact"] = contact if contact and contact["user_id"] else None
    return entries


def best_effort(conn: Connection, label: str, compute, default):
    """``compute()``, or ``default`` when it fails, without failing the read.

    Runs inside a savepoint, so a failed query doesn't poison the rest of
    the read's transaction.

    Args:
        conn: Open database connection.
        label: What is computed, for the log line.
        compute: A no-argument callable.
        default: What to return when it raises.
    """
    try:
        with conn.begin_nested():
            return compute()
    except Exception:
        logger.exception("Could not work out %s; left out of the read", label)
        return default


def named_ref_keys(states: list[dict]) -> set[str]:
    """Keys of the references whose names :func:`resource_states` gave the reader.

    The same rule decides which node resources a workflow read names in its
    ``ref_details``, so the two never disagree.

    Args:
        states: :func:`resource_states` for the reader.

    Returns:
        set: ``"<type>:<id>"`` keys, ids lowercased.
    """
    return {state["key"] for state in states if state.get("name") is not None}


def sponsor_audience(
    conn: Connection, holder_type: str, holder: dict, states: list[dict], sponsors: list[dict]
) -> Optional[dict]:
    """The holder's audience when the reader may take something over, else None.

    A take-over runs the resource with the reader's access for everyone who
    uses the holder, so the page shows them who that is before they agree.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        states: :func:`resource_states` for the reader.
        sponsors: :func:`sponsor_details` for the reader.

    Returns:
        dict or None: :func:`holder_audience`, when any item has ``can_confirm``.
    """
    if not any(item.get("can_confirm") for item in [*states, *sponsors]):
        return None
    return holder_audience(conn, holder_type, holder)


# --- Outside access -----------------------------------------------------------
#
# An API key (and the widget that runs on it), a public link and an incoming
# webhook let people run an agent whom nobody shared it with. The agent runs
# its tools and sources as its owner, so a tool or source the owner reaches
# only through a team grant (a *borrowed* one) would reach them too, though
# its own owner shared it with the agent's owner alone. So an agent that uses
# a borrowed tool or source gets none of the three, and one can't be added to
# an agent that has one. A sponsored resource (an editor's own, confirmed for
# the agent's audience) runs as its sponsor, not the owner, and is left to the
# sponsor rules; prompts carry no credentials and don't count.

# Error code of a key, link, webhook or save refused for a borrowed resource.
CODE_BORROWED_RESOURCE = "borrowed_resource"

_BORROWED_TYPES = ("source", "tool")


def has_outside_access(agent: Optional[dict]) -> bool:
    """Whether people outside the agent's shares can run it: a key, a public link or a webhook.

    Args:
        agent: The agent row.

    Returns:
        bool: True when it has an API key, a live public link or an incoming
        webhook token.
    """
    return bool(
        agent
        and (
            agent.get("key")
            or (agent.get("shared") and agent.get("shared_token"))
            or agent.get("incoming_webhook_token")
        )
    )


def holder_has_outside_access(conn: Connection, holder_type: str, holder: Optional[dict]) -> bool:
    """:func:`has_outside_access` for an agent, or for any of its owner's agents that run a workflow.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row, or None (a workflow not saved yet).

    Returns:
        bool: Whether anyone outside the shares reaches the holder.
    """
    if not holder:
        return False
    if holder_type == "agent":
        return has_outside_access(holder)
    rows = conn.execute(
        text(
            "SELECT key, shared, shared_token, incoming_webhook_token FROM agents "
            "WHERE workflow_id = CAST(:wid AS uuid) AND user_id = :owner"
        ),
        {"wid": str(holder["id"]), "owner": holder.get("user_id")},
    ).mappings().all()
    return any(has_outside_access(dict(row)) for row in rows)


def borrowed_refs(
    conn: Connection,
    owner_id: Optional[str],
    refs: Iterable[tuple[str, str]],
    folder_ids: Iterable = (),
    *,
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
) -> list[tuple[str, str]]:
    """The tools and sources among ``refs`` and the folders' sources that ``owner_id`` reaches only through a grant.

    Borrowed means someone else owns it and the holder's owner may use it
    (:func:`can_use_ref`), so the holder runs it with the owner's grant, or
    another team shares it with the owner's side while that team is locked
    (:func:`shared_in`: unlocking brings the share back). One the owner can't
    use runs as a sponsor or not at all, and isn't borrowed.
    Prompts, presets and builtin tools never are.

    Args:
        conn: Open database connection.
        owner_id: The holder's owner, whom it runs as.
        refs: ``(type, id)`` pairs the holder references.
        folder_ids: Knowledge folders it reads; each source a folder feeds
            counts as referenced (``folder_knowledge.folder_source_ids``).
        holder_type: ``agent`` or ``workflow`` for a saved holder, so a
            teammate's folder feeds what it feeds on that holder.
        holder: The saved holder row.

    Returns:
        list: The borrowed ``(type, id)`` pairs, ids lowercased, each once.
    """
    candidates = [(t, str(i).lower()) for t, i in refs if t in _BORROWED_TYPES and i]
    folder_ids = [f for f in folder_ids or [] if f]
    if folder_ids:
        # Lazy: folder_knowledge imports this module.
        from docsgpt.api.user.folder_knowledge import folder_source_ids

        candidates.extend(
            ("source", sid)
            for sid in folder_source_ids(conn, folder_ids, holder_type, holder, keep_borrowed=True)
        )
    pairs: list[tuple[str, str]] = []
    for resource_type, rid in candidates:
        if (resource_type, rid) not in pairs and _sponsorable(resource_type, rid):
            pairs.append((resource_type, rid))
    if not pairs or not owner_id:
        return []
    rows = _ref_rows(conn, pairs)
    return [
        (resource_type, rid)
        for resource_type, rid in pairs
        if (row := rows.get(sponsor_key(resource_type, rid)))
        and row.get("user_id") != owner_id
        and (can_use_ref(conn, resource_type, rid, owner_id) or shared_in(conn, resource_type, rid, owner_id))
    ]


def _join_words(items: list[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def borrowed_refusal(
    conn: Connection,
    refs: list[tuple[str, str]],
    viewer: Optional[str],
    holder: Optional[dict] = None,
    *,
    attaching: bool = False,
) -> tuple[dict, int]:
    """The 403 body for a key, link, webhook or save that borrowed resources refuse.

    The message names each resource and whose it is (by the rule of
    :func:`people_named_to`; "someone else" otherwise) and what to do.

    Args:
        conn: Open database connection.
        refs: The borrowed ``(type, id)`` pairs (see :func:`borrowed_refs`).
        viewer: The user asking.
        holder: The agent or workflow row, for naming people.
        attaching: True when a save adds them to a holder that has outside
            access; False when outside access is asked for a holder that uses them.

    Returns:
        ``(body, 403)``: ``success``, ``code`` (:data:`CODE_BORROWED_RESOURCE`),
        ``message`` and ``resources`` (``{key, type, id, name, owner}``,
        ``owner`` being ``{user_id, label}``, both None for someone the
        viewer doesn't know).
    """
    rows = _ref_rows(conn, refs)
    owners = [(rows.get(sponsor_key(t, i)) or {}).get("user_id") for t, i in refs]
    labels = person_labels(conn, viewer, holder, owners)
    resources, phrases = [], []
    for (resource_type, rid), owner in zip(refs, owners):
        name = (rows.get(sponsor_key(resource_type, rid)) or {}).get("name")
        person = _person(owner, labels, owner in labels) or {"user_id": None, "label": None}
        resources.append(
            {"key": sponsor_key(resource_type, rid), "type": resource_type, "id": rid, "name": name, "owner": person}
        )
        what = f'the {resource_type} "{name}"' if name else f"a {resource_type}"
        phrases.append(f"{what} from {person['label'] or 'someone else'}")
    listed = _join_words(phrases)
    them = "it" if len(refs) == 1 else "them"
    rule = "an agent that uses another person's tools or sources can't have an API key, public link or webhook"
    if attaching:
        message = (
            f"{listed[0].upper()}{listed[1:]} can't be added: this agent has an API key, public link or webhook, "
            f"and {rule}. Use {them} in an agent without those."
        )
    else:
        message = f"This agent uses {listed}. An{rule[2:]}. Remove {them} from the agent first."
    return {
        "success": False,
        "code": CODE_BORROWED_RESOURCE,
        "message": message,
        "error": message,
        "resources": resources,
    }, 403


# --- Workspace references -------------------------------------------------------
#
# A team agent or workflow runs as the team's principal, so everything it
# references must be the team's own: a member's personal source or tool
# would otherwise run for the whole team (and for its outside traffic) with no
# sponsor to answer for it. The one exception is a source, tool or prompt
# another team shared with this team: the share answers for it, and
# ``borrowed_refs`` keeps a holder that uses one unpublished. Presets and
# builtin tools belong to no one and always pass. A personal holder may still
# reference a team item its owner can use; ``borrowed_refs`` keeps such an
# agent unpublished.

# Error code of a save that references items from another workspace.
CODE_WORKSPACE_MISMATCH = "workspace_mismatch"


def _ownerless_ref(resource_type: str, resource_id: str) -> bool:
    """Presets and builtin tools: references that belong to no workspace."""
    if resource_type == "source" and resource_id == "default":
        return True
    if resource_type == "prompt" and resource_id in ("default", *STORED_PROMPT_PRESETS):
        return True
    if resource_type == "tool":
        # Lazy: default_tools imports this module lazily too.
        from docsgpt.agents.default_tools import is_synthesized_tool_id

        return is_synthesized_tool_id(resource_id)
    return False


# Kinds a team holder may use from another team through a share with its own team.
_SHARED_IN_REF_TYPES = ("source", "tool", "prompt")


def _shared_into(conn: Connection, team_id: Optional[str], resource_type: str, resource_id: str, owner: str) -> bool:
    """Whether the item's owning team shares it with ``team_id`` (a row naming that owning team).

    A share paused by a lock still counts, so saving an agent while its source's team is locked
    doesn't fail: the item just doesn't run until the team unlocks. Adding one needs it live
    (:func:`ref_attachable` asks :func:`resolve`).
    """
    owner_team = team_of_principal(owner)
    if team_id is None or owner_team is None or resource_type not in _SHARED_IN_REF_TYPES:
        return False
    row = TeamItemSharesRepository(conn).get(team_id, resource_type, resource_id)
    return row is not None and str(row.get("owner_team_id")) == owner_team


def workspace_mismatches(
    conn: Connection, owner_id: Optional[str], refs: Iterable[tuple[str, Optional[str]]]
) -> list[tuple[str, str]]:
    """The refs a team holder may not use: anything not its own principal's or shared into its team.

    Call it on every save that writes a team agent's or workflow node's
    references (create, update, graph save, import), with every ``(type, id)``
    it will hold, knowledge folders included as ``("folder", id)``. A
    personal holder is not judged here and gets an empty list.

    A source, tool or prompt another team shares with the holder's team
    passes. Fails closed: an unknown kind or a non-UUID id that isn't a preset or a
    builtin tool is a mismatch. A UUID that names no row is not (it runs
    nowhere, and refusing it would block every save of an agent whose tool
    was deleted).

    Args:
        conn: Open database connection.
        owner_id: The holder's owner (``Workspace.owner_id`` on create).
        refs: ``(type, id)`` pairs: ``source``, ``prompt``, ``tool``, ``folder`` or ``agent``.

    Returns:
        list[tuple[str, str]]: The offending pairs, ids lowercased, each once, in the order given.
    """
    if not is_principal_id(owner_id):
        return []
    out: list[tuple[str, str]] = []
    for resource_type, resource_id in refs:
        if resource_id is None or not str(resource_id).strip():
            continue
        rid = str(resource_id).strip().lower()
        pair = (resource_type, rid)
        if pair in out or _ownerless_ref(resource_type, rid):
            continue
        if resource_type not in _ITEM_TABLES or not looks_like_uuid(rid):
            out.append(pair)
            continue
        owner = resource_owner(conn, resource_type, rid)
        if owner is not None and owner != owner_id:
            if _shared_into(conn, team_of_principal(owner_id), resource_type, rid, owner):
                continue
            out.append(pair)
    return out


def _reader_sees(conn: Connection, resource_type: str, resource_id: str, viewer: Optional[str]) -> bool:
    """Whether ``viewer`` may learn the name of an item (they can reach it, or own the folder)."""
    if not viewer or not looks_like_uuid(resource_id):
        return False
    if resource_type == "folder":
        return resource_owner(conn, "folder", resource_id) == viewer
    if resource_type not in _REPO_FOR_TYPE:
        return False
    return resolve(conn, resource_type, resource_id, viewer) is not None


def workspace_mismatch_refusal(
    conn: Connection, refs: list[tuple[str, str]], viewer: Optional[str]
) -> tuple[dict, int]:
    """The 400 body for a save :func:`workspace_mismatches` refuses.

    Args:
        conn: Open database connection.
        refs: The offending pairs.
        viewer: The user saving; an item is named only when they can reach it.

    Returns:
        ``(body, 400)``: ``success``, ``error`` and ``code`` (:data:`CODE_WORKSPACE_MISMATCH`),
        ``message`` and ``resources`` (``{key, type, id, name}``).
    """
    names = ref_names(conn, refs)
    resources = []
    for resource_type, rid in refs:
        key = sponsor_key(resource_type, rid)
        visible = _reader_sees(conn, resource_type, rid, viewer)
        resources.append({"key": key, "type": resource_type, "id": rid, "name": names.get(key) if visible else None})
    return {
        "success": False,
        "error": CODE_WORKSPACE_MISMATCH,
        "code": CODE_WORKSPACE_MISMATCH,
        "message": (
            "A team's agents can only use the team's own sources, tools, prompts and folders. "
            "Move these to the team first, or pick the team's own."
        ),
        "resources": resources,
    }, 400
