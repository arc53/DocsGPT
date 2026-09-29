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
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

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
        "move_folder": "owner",
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
    },
    "source": {
        "use": "viewer",  # browse files, chunks, graph, wiki; test retrieval; attach to agents
        "view_config": "editor",
        "edit": "editor",  # chunks, files, wiki, config, sync, reingest, GraphRAG, convert
        "reconnect": "owner",  # change the connector account
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
    },
    "tool": {
        "use": "viewer",  # see it and run it inside the owner's shared agents
        "use_in_own": "viewer",  # add it to my own agents and chats
        "edit": "editor",  # name, action descriptions, parameters, approval
        "edit_credentials": "editor",  # secrets, URL, auth, reconnect OAuth (write-only)
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
    },
    "prompt": {
        "use": "viewer",  # read it and use it in my own agents
        "duplicate": "editor",
        "edit": "editor",
        "share": "owner",
        "delete": "owner",
        "manage_settings": "owner",
    },
}


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
        Switch("editors_can_manage_access_details", True, "manage_access_details", "editor", "owner"),
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


def public_settings(resource_type: str, settings: Optional[dict]) -> list[dict]:
    """The switches as ``[{key, value, default}]`` in display order."""
    merged = _merge(resource_type, settings)
    return [
        {"key": s.key, "value": merged[s.key], "default": s.default}
        for s in SWITCHES.get(resource_type, ())
    ]


def settings_for(conn: Connection, resource_type: str, resource_id: str) -> dict[str, bool]:
    """The resource's switches, defaults filled in."""
    return settings_many(conn, resource_type, [resource_id])[resource_id]


def settings_many(
    conn: Connection, resource_type: str, resource_ids: Iterable[str]
) -> dict[str, dict[str, bool]]:
    """``resource_id -> switches`` for many resources in one query."""
    ids = [str(r) for r in resource_ids]
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

    Raises:
        ValueError: an unknown key or a non-boolean value.
    """
    known = default_settings(resource_type)
    for key, value in changes.items():
        if key not in known:
            raise ValueError(f"Unknown setting: {key}")
        if not isinstance(value, bool):
            raise ValueError(f"Setting {key} must be true or false")
    merged = {**settings_for(conn, resource_type, resource_id), **changes}
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
        {"t": resource_type, "id": resource_id, "s": json.dumps(merged), "by": updated_by},
    )
    return merged


def delete_settings(conn: Connection, resource_type: str, resource_id: str) -> None:
    """Drop a deleted resource's switches (the table has no FK to cascade)."""
    if looks_like_uuid(resource_id):
        conn.execute(
            text("DELETE FROM resource_share_settings WHERE resource_type = :t AND resource_id = CAST(:id AS uuid)"),
            {"t": resource_type, "id": resource_id},
        )


@dataclass(frozen=True)
class ResourceAccess:
    """What one user may do on one resource."""

    resource_type: str
    resource_id: str
    access: str  # owner | editor | viewer
    owner_id: str  # the id to read and write the resource as
    settings: dict = field(default_factory=dict)
    actions: frozenset = frozenset()

    def can(self, action: str) -> bool:
        return action in self.actions

    def payload(self) -> dict:
        """The fields every API response embeds for this resource."""
        return {"access": self.access, "allowed_actions": sorted(self.actions)}


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


def payload_for(resource_type: str, access: Optional[str], settings: Optional[dict]) -> dict:
    """``access`` + ``allowed_actions`` without an owner lookup (list endpoints)."""
    return {
        "access": access,
        "allowed_actions": sorted(allowed_actions(resource_type, access, settings)),
    }


def resolve(
    conn: Connection, resource_type: str, resource_id: str, user_id: str
) -> Optional[ResourceAccess]:
    """The caller's access to a resource, or None when they can't see it."""
    repo_cls = _REPO_FOR_TYPE.get(resource_type)
    if repo_cls is None or not resource_id or not user_id:
        return None
    owned = repo_cls(conn).get_any(str(resource_id), user_id)
    if owned is not None:
        rid = str(owned.get("id") or resource_id)
        return build(resource_type, rid, "owner", user_id, settings_for(conn, resource_type, rid))
    # Only canonical UUIDs can carry a grant; casting anything else would
    # poison the transaction.
    if not looks_like_uuid(str(resource_id)):
        return None
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
    if action not in ACTIONS.get(resource_type, {}):
        raise KeyError(f"{resource_type} has no action {action!r}")
    ra = resolve(conn, resource_type, resource_id, user_id)
    if ra is None:
        raise AccessDenied(404, f"{resource_type.capitalize()} not found")
    if not ra.can(action):
        raise AccessDenied(403, "Your access to this item doesn't allow that")
    return ra
