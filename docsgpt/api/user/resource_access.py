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
import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy import Connection, text

from docsgpt.connectors.permissions import owner_credential_writes
from docsgpt.storage.db.base_repository import canonical_uuid, looks_like_uuid
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

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
        "edit_credentials": "editor",  # secrets, URL, auth (write-only); OAuth servers stay owner-only
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
    # Postgres matches any casing but returns lowercase; canonicalise so the
    # switch lookup (keyed by the returned id) can't miss.
    resource_id = canonical_uuid(str(resource_id))
    owned = repo_cls(conn).get_any(resource_id, user_id)
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


def can_sponsor_ref(conn: Connection, resource_type: str, resource_id: str, user_id: Optional[str]) -> bool:
    """Whether ``user_id`` may extend ``resource_id`` to someone else's agent.

    Using a resource is not enough to hand it to another agent's audience:
    the sponsor must own it or reach it with ``edit`` through a team grant
    (any team).

    Args:
        conn: Open database connection.
        resource_type: ``source``, ``prompt`` or ``tool``.
        resource_id: The referenced id.
        user_id: The would-be sponsor.

    Returns:
        True when the user owns the resource or may edit it.
    """
    if not user_id or not resource_id:
        return False
    ra = resolve(conn, resource_type, str(resource_id), user_id)
    return ra is not None and ra.can(SPONSOR_ACTION) and ra.can(REF_USE_ACTION[resource_type])


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
    if not holder or not resource_id:
        return None, None
    recorded = holder.get("resource_sponsors") or {}
    sponsor = recorded.get(sponsor_key(resource_type, str(resource_id))) or recorded.get(
        sponsor_key(resource_type, str(resource_id).lower())
    )
    if not sponsor or sponsor == holder.get("user_id"):
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

_REF_TABLES = {"source": "sources", "prompt": "prompts", "tool": "user_tools"}


@dataclass(frozen=True)
class RefAccess:
    """Who a holder runs one referenced resource as, or why it doesn't run.

    Attributes:
        principal: The user it is authorized as (the holder's owner or a live
            sponsor); None when it doesn't run.
        reason: None while it runs; else :data:`REASON_DELETED`,
            :data:`REASON_OWNER_LOST_ACCESS` or a sponsor reason.
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


def ref_access(
    conn: Connection, holder_type: str, holder: Optional[dict], resource_type: str, resource_id: str
) -> RefAccess:
    """Whether and as whom a holder runs one referenced resource.

    The run and the edit page both ask this. The owner runs it when they may
    use it, else a live sponsor does; otherwise it is stopped, because the row
    is gone, a recorded sponsor no longer qualifies, or the owner lost access.

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
        return RefAccess(owner)
    sponsor, sponsor_reason = sponsor_state(conn, holder_type, holder, resource_type, rid)
    if sponsor and sponsor_reason is None:
        return RefAccess(sponsor, None, sponsor)
    if not _ref_exists(conn, resource_type, rid):
        return RefAccess(None, REASON_DELETED, sponsor)
    return RefAccess(None, sponsor_reason or REASON_OWNER_LOST_ACCESS, sponsor)


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
        refs: ``(type, id)`` pairs.

    Returns:
        dict: ``"<type>:<id>" -> name`` for the ones found.
    """
    queries = {
        "source": "SELECT id, name FROM sources WHERE id = ANY(CAST(:ids AS uuid[]))",
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
        state, reason, active, can_confirm}``. ``label`` is the sponsor's
        email when on file; ``state`` is ``active`` or ``inactive``, and
        ``reason`` (None while active) is :data:`REASON_CANNOT_EDIT_HOLDER`
        or :data:`REASON_CANNOT_EDIT_RESOURCE`; ``active`` mirrors ``state``.
        ``can_confirm`` says whether ``viewer`` may take an inactive one
        over by confirming it on their next save.
    """
    sponsors = holder.get("resource_sponsors") or {}
    if not sponsors:
        return []
    user_ids = sorted({u for u in sponsors.values() if u})
    labels = dict(
        conn.execute(
            text(
                "SELECT user_id, email FROM users WHERE user_id = ANY(:ids) "
                "AND email IS NOT NULL AND email <> ''"
            ),
            {"ids": user_ids},
        ).fetchall()
    ) if user_ids else {}
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
                "user_id": user_id,
                "label": labels.get(user_id) or user_id,
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
    """``user_id -> email`` for the ones with an email on file."""
    ids = sorted({u for u in user_ids if u})
    if not ids:
        return {}
    return dict(
        conn.execute(
            text(
                "SELECT user_id, email FROM users WHERE user_id = ANY(:ids) "
                "AND email IS NOT NULL AND email <> ''"
            ),
            {"ids": ids},
        ).fetchall()
    )


def _connection_state(conn: Connection, tool: dict, owner: Optional[str], policies_box: list) -> tuple:
    """``(reason, connection, mode)`` for a tool the holder runs as ``owner``.

    ``connection`` (``{id, connector_key, name}``) and ``mode`` (``owner`` or
    ``member``, after any mode an admin forces) are set for a tool that has a
    connection, and ``connection`` also for one that lost it. ``reason`` is
    why the connection keeps the tool from running, else None.
    """
    from docsgpt.connectors import catalog, service
    from docsgpt.connectors.resolve import connection_stop_reason, effective_credential_mode, resolve_connection

    if not tool.get("connection_id") and not catalog.definition_for_tool(tool.get("name") or ""):
        return None, None, None
    if not policies_box:
        policies_box.append(service.load_policies(conn))
    resolved = resolve_connection(tool, owner, conn=conn, policies=policies_box[0])
    reason = connection_stop_reason(tool, resolved)
    if resolved is not None:
        connection = {
            "id": resolved.connection_id,
            "connector_key": resolved.connector_key,
            "name": resolved.connector_name,
        }
        mode = effective_credential_mode(tool, policies_box[0], resolved.connector_key)
        return reason, connection, mode
    if reason is None:
        return None, None, None
    definition = catalog.definition_for_tool(tool.get("name") or "")
    return reason, {"id": None, "connector_key": definition.key, "name": definition.name}, None


def resource_states(
    conn: Connection,
    holder_type: str,
    holder: dict,
    refs: Iterable[tuple[str, str]],
    viewer: Optional[str],
) -> list[dict]:
    """Whether each resource a holder references runs, for its edit page.

    Uses the run's own checks (:func:`ref_access`, :func:`resolve_holder_tool`
    and the tool's connection as the run resolves it for the owner), so a
    resource shown as stopped is one the run leaves out. Presets and builtin
    tools always run and are not listed. Only for readers who may edit the
    holder: the caller checks that.

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
        list: Per resource ``{key, type, id, name, state, reason, sponsor,
        contact, connection, can_confirm, can_reconnect}``. ``state`` is
        ``active`` or ``stopped``; ``reason`` (None while active) is one of
        ``deleted``, ``owner_lost_access``, the sponsor reasons,
        ``connection_needs_reconnect``, ``connection_removed`` or
        ``connector_disabled``. ``sponsor`` and ``contact`` are
        ``{user_id, label}`` or None: the recorded sponsor, and someone other
        than the reader who can fix it. ``connection`` (``{id,
        connector_key, name}``) names the service of a tool with a
        connection, and of one whose connection reason stopped it.
        For a running tool, ``credential_mode`` is ``owner`` or ``member``
        when it has a connection (else None), ``account`` (``{user_id,
        label}``) is whose account an ``owner``-mode connection acts as, and
        ``owner_credential_writes`` names its write actions on credentials
        its owner stored (what the API write allowlist covers); empty for
        everything else.
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
    entries = []
    for resource_type, rid in pairs:
        key = sponsor_key(resource_type, rid)
        info = rows.get(key) or {}
        connection = mode = account = None
        writes: list[str] = []
        if resource_type == "tool":
            tool_row, access = resolve_holder_tool(conn, holder_type, holder, rid, tools_repo=tools_repo)
            reason = access.reason
            if tool_row is not None and reason is None:
                reason, connection, mode = _connection_state(conn, tool_row, owner, policies_box)
                # Whose account an owner-mode connection acts as: the tool's owner.
                account = tool_row.get("user_id") if mode == "owner" else None
                writes = owner_credential_writes(tool_row)
        else:
            access = ref_access(conn, holder_type, holder, resource_type, rid)
            reason = access.reason
        sponsor = recorded.get(key)
        sponsor = sponsor if sponsor and sponsor != owner else None
        resource_owner = info.get("user_id")
        can_confirm = bool(
            reason in (REASON_OWNER_LOST_ACCESS, REASON_CANNOT_EDIT_HOLDER, REASON_CANNOT_EDIT_RESOURCE)
            and viewer_edits
            and can_sponsor_ref(conn, resource_type, rid, viewer)
        )
        contact = None
        if reason == REASON_OWNER_LOST_ACCESS:
            # The owner asks whoever shared it; an editor asks the owner.
            contact = resource_owner if viewer == owner else owner
        elif reason in (REASON_CONNECTION_NEEDS_RECONNECT, REASON_CONNECTION_REMOVED):
            contact = resource_owner
        if contact == viewer:
            contact = None
        name_visible = bool(
            reason is None
            or sponsor
            or holder_type == "agent"
            or (viewer and resolve(conn, resource_type, rid, viewer) is not None)
        )
        entries.append({
            "key": key,
            "type": resource_type,
            "id": rid,
            "name": info.get("name") if name_visible else None,
            "state": "active" if reason is None else "stopped",
            "reason": reason,
            "sponsor": sponsor,
            "contact": contact,
            "connection": connection,
            "credential_mode": mode,
            "account": account,
            "owner_credential_writes": writes,
            "can_confirm": can_confirm,
            "can_reconnect": bool(
                reason == REASON_CONNECTION_NEEDS_RECONNECT
                and connection
                and connection.get("id")
                and viewer
                and viewer == resource_owner
            ),
        })
    labels = _user_labels(conn, [u for e in entries for u in (e["sponsor"], e["contact"], e["account"])])
    for entry in entries:
        for field_name in ("sponsor", "contact", "account"):
            user_id = entry[field_name]
            entry[field_name] = {"user_id": user_id, "label": labels.get(user_id) or user_id} if user_id else None
    return entries


def visible_ref_ids(
    conn: Connection, holder_type: str, holder: dict, refs: Iterable[tuple[str, str]], viewer: Optional[str]
) -> set[str]:
    """Keys of references whose names ``viewer`` may read on the holder's edit page.

    Those the holder runs (its owner or a live sponsor may use them), those
    someone sponsored on it, and those the reader can see themselves.

    Args:
        conn: Open database connection.
        holder_type: ``agent`` or ``workflow``.
        holder: The holder row.
        refs: ``(type, id)`` pairs.
        viewer: The reader.

    Returns:
        set: ``"<type>:<id>"`` keys, ids lowercased.
    """
    recorded = {k.lower() for k in (holder.get("resource_sponsors") or {})}
    out: set[str] = set()
    for resource_type, resource_id in refs:
        rid = str(resource_id).lower()
        key = sponsor_key(resource_type, rid)
        if key in out or resource_type not in REF_USE_ACTION:
            continue
        if (
            key in recorded
            or ref_access(conn, holder_type, holder, resource_type, rid).principal
            or (viewer and resolve(conn, resource_type, rid, viewer) is not None)
        ):
            out.add(key)
    return out


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
