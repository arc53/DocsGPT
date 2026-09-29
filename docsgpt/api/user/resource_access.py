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
    if not holder:
        return None
    owner = holder.get("user_id")
    if can_use_ref(conn, resource_type, str(resource_id), owner):
        return owner
    return active_sponsor(conn, holder_type, holder, resource_type, resource_id)


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
      access: it stays stopped until someone confirms taking it over.

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
        live = active_sponsor(conn, holder_type, holder, resource_type, resource_id)
        if live:
            plan.sponsors[key] = live
        elif caller_may and key in confirmed:
            plan.sponsors[key] = caller
        elif is_new and caller != owner_id:
            (plan.needs_confirmation if caller_may else plan.not_allowed).append((resource_type, resource_id))
        elif previous.get(key):
            plan.sponsors[key] = previous[key]
    plan.unexpected = sorted(confirmed - eligible)
    return plan


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
