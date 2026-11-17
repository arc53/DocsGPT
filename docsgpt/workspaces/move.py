"""Move: take personal items into a team workspace, or a team's items out to a person's Personal.

Moving is the one way existing work enters a team. The person who owns an
agent, source, tool, prompt or folder moves it into a team where they are an
Editor or above; a team Admin moves the team's items out to their own
Personal. Ownership changes in place: ids, keys, links and history stay.

A move is planned first (:func:`plan_move`, read-only) and then applied
(:func:`apply_move`) in one transaction, only while the plan is unchanged:
the client sends back the plan's fingerprint, and a different one answers 409
``move_plan_changed`` with the fresh plan.

What a move takes along, and what it can't:

- An agent takes what it uses that the same owner holds: its sources, tools
  and prompt, the folders it reads live, its workflow and every other agent of
  that owner on the same workflow. A folder the mover drags takes its
  sub-folders and the items its owner filed there; a folder that comes only as
  an agent's knowledge takes its sub-folders and sources, and the agents, tools
  and prompts filed in it stay where they are, unfiled.
- Anything the agent uses that the owner doesn't hold (a teammate's tool, a
  shared source), or that can't live in a team (a tool on someone's connected
  account or paired device, a connector-synced source, a personal custom
  model, a tool whose saved secret no longer opens), is removed from the agent
  and listed. A dragged item the mover doesn't own is listed and never re-owned.
- Grants and share switches on moved items are deleted, sponsors cleared, and
  stored secrets re-sealed for the new owner. Someone else's personal filing of
  a moved item is deleted; the mover's own filing goes to the chosen folder.
- The mover's own chats with a moved agent follow it. Other people's stay in
  the workspace they were started in: a move never puts someone's private
  chat where a team's admins could export it. Chats through the agent's key,
  widget or webhook, stored under its owner, go to the new owner so the key
  can continue them. Schedules keep the person who set them (they pay), and
  outside access (key, link, webhook) keeps running on the mover as its payer.
  ``created_by`` is kept.
- A move in that would leave any agent with outside access (whoever owns it)
  using a moved item is refused with 409 ``move_would_borrow``: its key, link
  or webhook would serve a team's item. The agents the mover can open are
  named, the rest only counted; the client may add the mover's own to the move.
  Moving out, a team agent left behind can't use a personal item at all, so
  any team agent that uses a moved item, or reads one through a folder it
  stays in, refuses the move.
- Publishing in a team is an Admin's call, so bringing in an agent with
  outside access takes a team Admin (403 ``move_needs_admin``); an Editor
  turns its outside access off first, or asks an Admin.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from flask import Response, jsonify, make_response
from sqlalchemy import Connection, text

from docsgpt.agents.tool_executor import API_TOOL_SECRETS_KEY
from docsgpt.api.audit import record_event
from docsgpt.api.user.agents.sharing import access_payer_fields
from docsgpt.api.user.base import copy_agent_image_for_user, storage
from docsgpt.api.user.folders.service import (
    MAX_FOLDER_DEPTH,
    FolderError,
    FolderTree,
    folder_by_id,
    folder_paths,
)
from docsgpt.api.user.resource_access import (
    agent_refs,
    build_team,
    delete_settings,
    has_outside_access,
    person_labels,
    resolve,
    resource_owner,
)
from docsgpt.connectors import service as connector_service
from docsgpt.connectors.permissions import holds_owner_credentials
from docsgpt.security import encryption
from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.workspaces.context import PERSONAL, Workspace, WorkspaceError, require_workspace_role
from docsgpt.workspaces.locks import lock_owner_items
from docsgpt.workspaces.outside import team_policy
from docsgpt.workspaces.principal import canonical_team_id, is_principal_id, principal_id, team_of_principal
from docsgpt.workspaces.roles import from_stored_role, role_at_least, role_rank, team_role_for

logger = logging.getLogger(__name__)

#: What a move request may name.
MOVE_KINDS = ("agent", "source", "tool", "prompt", "folder")

#: The most items one request may name.
MAX_MOVE_ITEMS = 500

#: Why an item comes along (``moves_with[].reason``).
REASON_USED_BY_AGENT = "used_by_agent"
REASON_IN_FOLDER = "in_folder"
REASON_SAME_WORKFLOW = "same_workflow"

#: Why an item can't come (``cannot_move[].reason``).
CANT_CONNECTION = "connection_account"
CANT_CONNECTOR = "connector_synced"
CANT_CUSTOM_MODEL = "custom_model"
CANT_DEVICE = "remote_device"
CANT_NOT_YOURS = "not_yours"
CANT_IN_KNOWLEDGE = "in_knowledge_folder"
CANT_UNREADABLE = "credentials_unreadable"

#: What happens to it (``cannot_move[].effect``): taken off the moved agents, or just left where it is.
EFFECT_REMOVED = "removed_from_holder"
EFFECT_STAYS = "stays"

#: Error codes.
CODE_PLAN_CHANGED = "move_plan_changed"
CODE_WOULD_BORROW = "move_would_borrow"
CODE_NOTHING_TO_MOVE = "nothing_to_move"
CODE_NEEDS_ADMIN = "move_needs_admin"
CODE_UNREADABLE = "credentials_unreadable"

#: Audit events, by direction.
ITEM_EVENTS = {"in": "team.item_moved_in", "out": "team.item_moved_out"}
FOLDER_EVENTS = {"in": "team.folder_moved_in", "out": "team.folder_moved_out"}

_ITEM_KINDS = ("agent", "source", "tool", "prompt")
_TABLES = {
    "agent": "agents", "source": "sources", "tool": "user_tools", "prompt": "prompts", "folder": "folders",
    "workflow": "workflows",
}
_NAME_SQL = {
    "agent": "name",
    "source": "name",
    "prompt": "name",
    "folder": "name",
    "tool": "COALESCE(NULLIF(custom_name, ''), NULLIF(display_name, ''), name)",
}
_LIVE_SCHEDULES = ("active", "paused")

#: Where a stored secret lives in a tool's config.
_SECRET_KEYS = ("encrypted_credentials", API_TOOL_SECRETS_KEY)

# An agent's own columns that name a resource, read for every agent whoever owns it.
_AGENT_USE_SQL = {
    "source": "a.source_id = ANY(CAST(:ids AS uuid[])) OR a.extra_source_ids && CAST(:ids AS uuid[])",
    "tool": "jsonb_typeof(a.tools) = 'array' AND a.tools ?| CAST(:ids AS text[])",
    "prompt": "a.prompt_id = ANY(CAST(:ids AS uuid[]))",
    "folder": "a.knowledge_folder_ids && CAST(:ids AS uuid[])",
}
# The agent-node key of each kind in a workflow's current graph; prompts have none.
_NODE_KEYS = {"source": "sources", "tool": "tools", "folder": "folders"}
_NODE_USE_SQL = """
    SELECT DISTINCT a.id::text FROM workflow_nodes n
    JOIN workflows w ON w.id = n.workflow_id AND n.graph_version = w.current_graph_version
    JOIN agents a ON a.workflow_id = w.id
    WHERE a.agent_type = 'workflow' AND n.node_type = 'agent'
      AND workflow_node_refs(n.config, '{key}') && CAST(:ids AS text[])
"""


class MoveError(Exception):
    """A refused move: an HTTP status, a stable error code, a message and extra body fields."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def response(self) -> Response:
        """``{"success": false, "error": code, "message", **extra}`` with the status."""
        return make_response(
            jsonify({"success": False, "error": self.code, "message": self.message, **self.extra}), self.status
        )


@dataclass(frozen=True)
class MoveRequest:
    """A parsed move request.

    Attributes:
        team_id: The target team, or None to move out to the caller's Personal.
        folder_id: A folder of the target tree to put the items in, or None for the top level.
        items: ``(type, id)`` pairs as dragged, in order, each once.
        fingerprint: The plan's fingerprint (apply only).
    """

    team_id: Optional[str]
    folder_id: Optional[str]
    items: tuple
    fingerprint: Optional[str] = None


def parse_move_request(raw: Any) -> MoveRequest:
    """Check a move request body.

    Args:
        raw: ``{to: {workspace: "personal" | team_id, folder_id?}, items: [{type, id}], fingerprint?}``.

    Returns:
        MoveRequest: The parsed request.

    Raises:
        MoveError: 400 ``invalid_request`` for a malformed body; 404 ``workspace_not_found`` for a
            target that isn't a team id.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("to"), dict):
        raise MoveError(400, "invalid_request", "Say where to move: to.workspace is required")
    target = raw["to"].get("workspace")
    if not isinstance(target, str) or not target.strip():
        raise MoveError(400, "invalid_request", "to.workspace is required")
    team_id = None
    if target.strip().lower() != PERSONAL:
        team_id = canonical_team_id(target.strip())
        if team_id is None:
            raise MoveError(404, "workspace_not_found", "Workspace not found")
    folder_id = raw["to"].get("folder_id")
    if folder_id in ("", None):
        folder_id = None
    elif not isinstance(folder_id, str):
        raise MoveError(400, "invalid_request", "to.folder_id must be a folder id")
    items = raw.get("items")
    if not isinstance(items, list) or not items:
        raise MoveError(400, "invalid_request", "Name at least one item to move")
    if len(items) > MAX_MOVE_ITEMS:
        raise MoveError(400, "invalid_request", f"A move takes at most {MAX_MOVE_ITEMS} items")
    seen: list[tuple[str, str]] = []
    for item in items:
        kind = item.get("type") if isinstance(item, dict) else None
        item_id = item.get("id") if isinstance(item, dict) else None
        if kind not in MOVE_KINDS or not isinstance(item_id, str) or not item_id.strip():
            raise MoveError(400, "invalid_request", "Each item needs a type (agent, source, tool, prompt or "
                                                    "folder) and an id")
        pair = (kind, item_id.strip().lower() if looks_like_uuid(item_id.strip()) else item_id.strip())
        if pair not in seen:
            seen.append(pair)
    fingerprint = raw.get("fingerprint")
    return MoveRequest(team_id, folder_id, tuple(seen), fingerprint if isinstance(fingerprint, str) else None)


@dataclass
class _Entry:
    """One item the move re-owns."""

    kind: str
    id: str
    row: dict
    via: Optional[tuple[str, str]] = None
    reason: Optional[str] = None

    @property
    def name(self) -> Optional[str]:
        if self.kind == "tool":
            return self.row.get("custom_name") or self.row.get("display_name") or self.row.get("name")
        return self.row.get("name")


@dataclass
class MovePlan:
    """A planned move: the client's ``body`` and what the apply step needs.

    Attributes:
        body: The plan as the API returns it, ``fingerprint`` included.
        direction: ``in`` (into a team) or ``out`` (to the mover's Personal).
        mover: The person moving.
        old_owner: Who owns the items now (the mover, or the team's principal).
        new_owner: Who will (the team's principal, or the mover).
        team_id: The team on the other side.
        role: The mover's role in that team.
        target_folder_id: The folder of the new owner's tree the items go in, or None.
        moving: Every item re-owned, dragged items first: ``(type, id) -> entry``.
        workflows: The workflows that move with their agents, by id.
        roots: Moved folders whose parent stays behind: ``id -> (new parent, new name)``.
        slugs: The slug each moved agent that had one takes: ``agent id -> slug``.
        copied_images: Avatar copies the apply step wrote, removed again when the move doesn't commit.
        stays: Items filed in a moved folder that stay behind (their filing there is deleted).
        members: Everyone in the team (the owner included).
        blocking: Agents left behind that refuse the move (``borrowing_agents`` entries the mover can open).
        blocking_hidden: How many more refuse it that the mover can't open.
        legacy_tools: An agent's or node's tool refs that still name a tool by its Mongo id: ``old id -> uuid``.
        legacy_sources: A node's source refs that still name a source by its Mongo id: ``old id -> uuid``.
    """

    body: dict
    direction: str
    mover: str
    old_owner: str
    new_owner: str
    team_id: str
    role: Optional[str]
    target_folder_id: Optional[str]
    moving: dict = field(default_factory=dict)
    workflows: dict = field(default_factory=dict)
    roots: dict = field(default_factory=dict)
    slugs: dict = field(default_factory=dict)
    copied_images: list = field(default_factory=list)
    stays: list = field(default_factory=list)
    members: list = field(default_factory=list)
    blocking: list = field(default_factory=list)
    blocking_hidden: int = 0
    legacy_tools: dict = field(default_factory=dict)
    legacy_sources: dict = field(default_factory=dict)

    def ids(self, kind: str) -> list[str]:
        """The ids of one kind that move, in plan order."""
        return [item_id for k, item_id in self.moving if k == kind]


def _row(conn: Connection, kind: str, item_id: str) -> Optional[dict]:
    row = conn.execute(
        text(f"SELECT * FROM {_TABLES[kind]} WHERE id = CAST(:id AS uuid)"), {"id": item_id}
    ).fetchone()
    return row_to_dict(row) if row is not None else None


def _names(conn: Connection, kind: str, ids: Iterable[str]) -> dict[str, str]:
    ids = sorted({i for i in ids if looks_like_uuid(i)})
    if not ids:
        return {}
    rows = conn.execute(
        text(f"SELECT id::text, {_NAME_SQL[kind]} FROM {_TABLES[kind]} WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": ids},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _team_members(conn: Connection, team_id: str) -> dict[str, str]:
    """``user_id -> role`` of everyone in a team (``owner``, ``admin``, ``editor``, ``viewer``)."""
    rows = conn.execute(
        text(
            """
            SELECT user_id, array_agg(DISTINCT role) FROM team_members
            WHERE team_id = CAST(:t AS uuid) GROUP BY user_id
            """
        ),
        {"t": team_id},
    ).fetchall()
    out: dict[str, str] = {}
    for user_id, stored in rows:
        roles = [r for r in (from_stored_role(s) for s in stored or []) if r]
        if roles:
            out[user_id] = max(roles, key=role_rank)
    owner = conn.execute(text("SELECT owner_id FROM teams WHERE id = CAST(:t AS uuid)"), {"t": team_id}).scalar()
    if owner:
        out[owner] = "owner"
    return out


def _node_refs(config: Any) -> tuple[list[tuple[str, str]], list[str]]:
    """The ``(type, id)`` refs and model ids of one agent node's config, read like the engine reads it."""
    cfg = config.get("config") if isinstance(config, dict) and isinstance(config.get("config"), dict) else config
    if not isinstance(cfg, dict):
        return [], []
    refs: list[tuple[str, str]] = []
    for key, kind in (("tools", "tool"), ("sources", "source"), ("folders", "folder")):
        values = cfg.get(key)
        values = values if isinstance(values, list) else [values] if values else []
        refs.extend((kind, str(v).lower()) for v in values if v)
    model = cfg.get("model_id")
    return refs, [model] if isinstance(model, str) and model.strip() else []


def _agents_using(conn: Connection, kind: str, ids: list[str]) -> set[str]:
    """Every agent, whoever owns it, that names one of ``ids`` itself or in a node of its workflow.

    Args:
        conn: Open connection.
        kind: ``source``, ``tool``, ``prompt`` or ``folder`` (a folder it reads live).
        ids: Lower-case resource ids.

    Returns:
        set[str]: Agent ids.
    """
    ids = sorted({i for i in ids if looks_like_uuid(i)})
    if not ids:
        return set()
    text_ids = list(ids)
    if kind in ("source", "tool"):
        # Installs migrated from Mongo may still name a tool or source by its old id.
        table = _TABLES[kind]
        for (legacy,) in conn.execute(
            text(f"SELECT legacy_mongo_id FROM {table} WHERE id = ANY(CAST(:ids AS uuid[])) "
                 "AND legacy_mongo_id IS NOT NULL"),
            {"ids": ids},
        ):
            value = str(legacy).strip()
            if value:
                text_ids.extend({value, value.lower()})
    params = {"ids": text_ids if kind == "tool" else ids}
    found = {r[0] for r in conn.execute(
        text(f"SELECT a.id::text FROM agents a WHERE {_AGENT_USE_SQL[kind]}"), params
    )}
    if kind in _NODE_KEYS:
        found.update(r[0] for r in conn.execute(
            text(_NODE_USE_SQL.format(key=_NODE_KEYS[kind])), {"ids": text_ids}
        ))
    return found


def _secret_readable(blob: Any, owner: str) -> bool:
    """Whether a stored secret opens for its owner (so a move can re-seal it)."""
    if not blob:
        return True
    if not isinstance(blob, str):
        return False
    if encryption.envelope_key_id(blob) is not None:
        try:
            encryption.decrypt_json(blob, owner)
        except encryption.CredentialDecryptionError:
            return False
        return True
    # A v1 blob is never written for empty credentials, so empty means it didn't open.
    return bool(encryption.decrypt_credentials(blob, owner))


class _Planner:
    """Works out one plan; see :func:`plan_move`."""

    def __init__(self, conn: Connection, mover: str, request: MoveRequest) -> None:
        self.conn = conn
        self.mover = mover
        self.request = request
        self.moving: dict[tuple[str, str], _Entry] = {}
        self.cannot: dict[tuple[str, str], dict] = {}
        self.referenced: set[tuple[str, str]] = set()
        self.workflows: dict[str, dict] = {}
        self.stays: list[tuple[str, str]] = []
        self.dragged: list[tuple[str, str]] = []
        self.legacy_tools: dict[str, str] = {}
        self.legacy_sources: dict[str, str] = {}
        # Folders that take every item filed in them: the dragged ones and their sub-folders.
        self.whole_folders: set[str] = set()
        self._queue: list[tuple[str, str]] = []

    # --- sides --------------------------------------------------------------

    def _sides(self) -> None:
        conn, mover = self.conn, self.mover
        if is_principal_id(mover):
            raise MoveError(403, "not_a_person", "Only a person can move items")
        if self.request.team_id is not None:
            team_id = self.request.team_id
            role = team_role_for(conn, mover, team_id)
            if role is None:
                raise MoveError(404, "workspace_not_found", "Workspace not found")
            try:
                require_workspace_role(Workspace("team", team_id, principal_id(team_id), role), "editor")
            except WorkspaceError as err:
                raise MoveError(err.status, err.code, err.message) from err
            self.direction, self.team_id, self.role = "in", team_id, role
            self.old_owner, self.new_owner = mover, principal_id(team_id)
            return
        principal = None
        for kind, item_id in self.request.items:
            owner = resource_owner(conn, kind, item_id)
            if is_principal_id(owner):
                principal = owner
                break
        if principal is None:
            for kind, item_id in self.request.items:
                self._visible_row(kind, item_id)
            raise MoveError(400, "already_in_workspace", "These items are already in your Personal workspace")
        team_id = team_of_principal(principal)
        role = team_role_for(conn, mover, team_id)
        if role is None:
            raise MoveError(404, "not_found", "Item not found")
        try:
            FolderTree(principal, team_id, role, team_policy(conn, team_id)).require("move_out")
        except FolderError as err:
            raise MoveError(err.status, err.code, err.message) from err
        self.direction, self.team_id, self.role = "out", team_id, role
        self.old_owner, self.new_owner = principal, mover

    def _target(self) -> Optional[dict]:
        if not self.request.folder_id:
            return None
        try:
            folder, tree = folder_by_id(self.conn, self.request.folder_id, self.mover)
        except FolderError as err:
            raise MoveError(404, "folder_not_found", "Folder not found") from err
        if tree.owner_id != self.new_owner:
            raise MoveError(404, "folder_not_found", "That folder isn't in the workspace the items move to")
        return folder

    # --- what moves ------------------------------------------------------------

    def _classify(self, kind: str, row: dict) -> Optional[str]:
        """Why an item its owner holds can't come along, or None when it can."""
        if kind == "tool":
            config = row.get("config") if isinstance(row.get("config"), dict) else {}
            if not all(_secret_readable(config.get(key), row.get("user_id")) for key in _SECRET_KEYS):
                # It couldn't be re-sealed for the new owner; apply must never meet it.
                return CANT_UNREADABLE
        if self.direction == "out":
            return None
        if kind == "source":
            if str(row.get("type") or "").startswith("connector"):
                return CANT_CONNECTOR
            return CANT_CONNECTION if row.get("connection_id") else None
        if kind != "tool":
            return None
        name = row.get("name")
        if name == "remote_device":
            return CANT_DEVICE
        if row.get("credential_mode") == "member":
            # Runs on each person's own account; the team holds no connection of its own.
            return None
        if not holds_owner_credentials(row):
            return None
        config = row.get("config") or {}
        if row.get("connection_id"):
            session = ConnectorSessionsRepository(self.conn).get(str(row["connection_id"]))
            usable = (
                name == "mcp_tool"
                and session is not None
                and session.get("user_id") == row.get("user_id")
                and (session.get("auth_kind") or "") in ("api_key", "none")
                and connector_service.normalize_status(session) not in (
                    connector_service.STATUS_DISCONNECTED, connector_service.STATUS_RECONNECT,
                )
            )
            return None if usable else CANT_CONNECTION
        if name == "mcp_tool" and (config.get("auth_type") or "none") == "oauth":
            return CANT_CONNECTION
        return None

    def _cannot(self, key: tuple[str, str], reason: str, name: Optional[str]) -> None:
        if key not in self.cannot:
            self.cannot[key] = {"type": key[0], "id": key[1], "name": name, "reason": reason}

    def _visible_name(self, kind: str, item_id: str) -> Optional[str]:
        """The name of an item the mover doesn't own, when they can reach it."""
        if kind == "folder":
            return None
        if kind not in _TABLES or resolve(self.conn, kind, item_id, self.mover) is None:
            return None
        return _names(self.conn, kind, [item_id]).get(item_id)

    def _add(self, kind: str, item_id: str, row: dict, via: Optional[tuple[str, str]], reason: Optional[str]) -> None:
        key = (kind, item_id)
        if key in self.moving:
            return
        self.moving[key] = _Entry(kind, item_id, row, via, reason)
        self._queue.append(key)

    def _owned_candidate(self, kind: str, item_id: str) -> tuple[Optional[dict], Optional[str]]:
        """``(row, reason)`` for an item the old owner holds; ``(None, None)`` for anything else."""
        row = _row(self.conn, kind, item_id)
        if row is None or row.get("user_id") != self.old_owner:
            return None, None
        return row, self._classify(kind, row)

    def _visible_row(self, kind: str, raw_id: str) -> dict:
        """A dragged item's row, when the mover can see it.

        Raises:
            MoveError: 404 ``not_found`` otherwise, the same for a missing item and someone else's.
        """
        if kind == "folder":
            try:
                return folder_by_id(self.conn, raw_id, self.mover)[0]
            except FolderError as err:
                raise MoveError(404, "not_found", "Folder not found") from err
        ra = resolve(self.conn, kind, raw_id, self.mover)
        row = _row(self.conn, kind, ra.resource_id) if ra is not None else None
        if row is None:
            raise MoveError(404, "not_found", f"{kind.capitalize()} not found")
        return row

    def _drag(self) -> None:
        for kind, raw_id in self.request.items:
            row = self._visible_row(kind, raw_id)
            key = (kind, str(row["id"]))
            if row.get("user_id") != self.old_owner:
                # Never re-owned: someone else holds it.
                self._cannot(key, CANT_NOT_YOURS, _Entry(kind, key[1], row).name)
                continue
            reason = self._classify(kind, row)
            if reason:
                self._cannot(key, reason, _Entry(kind, key[1], row).name)
                continue
            if key not in self.moving:
                self.dragged.append(key)
            self._add(kind, key[1], row, None, None)
            if kind == "folder":
                self.whole_folders.update(FoldersRepository(self.conn).subtree_levels(key[1], self.old_owner))

    def _dependency(self, kind: str, item_id: str, via: tuple[str, str]) -> None:
        if kind in ("tool", "source") and not looks_like_uuid(item_id):
            # Installs migrated from Mongo may still name a tool or source by its old id: it is planned (and the
            # agent's or node's ref rewritten) as the item it names, so it doesn't stay behind unresolvable.
            legacy = self.legacy_tools if kind == "tool" else self.legacy_sources
            uuid_id = self.conn.execute(
                text(f"SELECT id::text FROM {_TABLES[kind]} WHERE lower(legacy_mongo_id) = :legacy LIMIT 1"),
                {"legacy": item_id.lower()},
            ).scalar()
            if uuid_id:
                legacy[item_id] = uuid_id
                item_id = uuid_id
        key = (kind, item_id)
        self.referenced.add(key)
        if key in self.moving or not looks_like_uuid(item_id):
            return
        owner = resource_owner(self.conn, kind, item_id)
        if owner is None:
            # A preset, a builtin tool, or a reference to something deleted.
            return
        if owner != self.old_owner:
            self._cannot(key, CANT_NOT_YOURS, self._visible_name(kind, item_id))
            return
        row, reason = self._owned_candidate(kind, item_id)
        if row is None:
            return
        if reason:
            self._cannot(key, reason, _Entry(kind, item_id, row).name)
            return
        self._add(kind, item_id, row, via, REASON_USED_BY_AGENT)

    def _expand_agent(self, entry: _Entry) -> None:
        conn, row, via = self.conn, entry.row, ("agent", entry.id)
        refs = [(t, str(i).lower()) for t, i in agent_refs(row)]
        refs.extend(("folder", str(f).lower()) for f in row.get("knowledge_folder_ids") or [] if f)
        models = [m for m in [row.get("default_model_id"), *(row.get("models") or [])] if isinstance(m, str) and m]
        workflow_id = str(row["workflow_id"]) if row.get("workflow_id") else None
        workflow = _row(conn, "workflow", workflow_id) if workflow_id else None
        if workflow is not None and workflow.get("user_id") == self.old_owner:
            self.workflows[workflow_id] = workflow
            # The runtime loads a workflow as its owner: its agents move together.
            siblings = conn.execute(
                text(
                    "SELECT * FROM agents WHERE workflow_id = CAST(:w AS uuid) AND user_id = :owner "
                    "AND id <> CAST(:a AS uuid) ORDER BY created_at, id"
                ),
                {"w": workflow_id, "owner": self.old_owner, "a": entry.id},
            ).fetchall()
            for sibling in siblings:
                sibling = row_to_dict(sibling)
                self._add("agent", str(sibling["id"]), sibling, via, REASON_SAME_WORKFLOW)
            nodes = conn.execute(
                text(
                    "SELECT config FROM workflow_nodes WHERE workflow_id = CAST(:w AS uuid) "
                    "AND graph_version = :v AND node_type = 'agent' ORDER BY node_id"
                ),
                {"w": workflow_id, "v": workflow.get("current_graph_version") or 1},
            ).fetchall()
            for (config,) in nodes:
                node_refs, node_models = _node_refs(config)
                refs.extend(node_refs)
                models.extend(node_models)
        for kind, item_id in refs:
            self._dependency(kind, item_id, via)
        if self.direction == "in" and models:
            # Lazy: the workflow routes import much of the API.
            from docsgpt.api.user.workflows.routes import personal_custom_models

            for model_id in personal_custom_models(conn, self.new_owner, models):
                model = conn.execute(
                    text("SELECT user_id, display_name FROM user_custom_models WHERE id = CAST(:i AS uuid)"),
                    {"i": model_id},
                ).fetchone()
                key = ("model", str(model_id).lower())
                self.referenced.add(key)
                self._cannot(key, CANT_CUSTOM_MODEL, model[1] if model and model[0] == self.mover else None)

    def _expand_folder(self, entry: _Entry) -> None:
        conn, via = self.conn, ("folder", entry.id)
        for child in FoldersRepository(conn).list_children(entry.id, self.old_owner):
            self._add("folder", str(child["id"]), child, via, REASON_IN_FOLDER)
        filings = conn.execute(
            text(
                "SELECT resource_type, resource_id::text FROM folder_items "
                "WHERE user_id = :owner AND folder_id = CAST(:f AS uuid) ORDER BY resource_type, resource_id"
            ),
            {"owner": self.old_owner, "f": entry.id},
        ).fetchall()
        whole = entry.id in self.whole_folders
        for kind, item_id in filings:
            key = (kind, item_id)
            if key in self.moving:
                continue
            row, reason = self._owned_candidate(kind, item_id)
            if row is None:
                self._cannot(key, CANT_NOT_YOURS, self._visible_name(kind, item_id))
                self.stays.append(key)
            elif reason:
                self._cannot(key, reason, _Entry(kind, item_id, row).name)
                self.stays.append(key)
            elif kind != "source" and not whole:
                # Reached only as an agent's knowledge: the folder brings what it feeds (its
                # sources), not the agents, tools and prompts filed there. They stay, unfiled,
                # unless something else in the move takes them.
                self._cannot(key, CANT_IN_KNOWLEDGE, _Entry(kind, item_id, row).name)
                self.stays.append(key)
            else:
                self._add(kind, item_id, row, via, REASON_IN_FOLDER)

    def _close(self) -> None:
        while self._queue:
            entry = self.moving[self._queue.pop(0)]
            if entry.kind == "agent":
                self._expand_agent(entry)
            elif entry.kind == "folder":
                self._expand_folder(entry)
        # An item left behind by a knowledge folder may still come another way (an agent uses it).
        for key in [k for k in self.cannot if k in self.moving]:
            del self.cannot[key]
        self.stays = [k for k in self.stays if k not in self.moving]

    # --- folders -----------------------------------------------------------------

    def _roots(self, target: Optional[dict]) -> tuple[dict, list[dict]]:
        repo = FoldersRepository(self.conn)
        moving = {item_id for kind, item_id in self.moving if kind == "folder"}
        parent = str(target["id"]) if target else None
        depth = len(repo.ancestors(parent, self.new_owner)) if parent else 0
        roots: dict[str, tuple[Optional[str], str]] = {}
        renames: list[dict] = []
        taken: set[str] = set()
        for kind, item_id in self.moving:
            if kind != "folder":
                continue
            row = self.moving[(kind, item_id)].row
            if row.get("parent_id") and str(row["parent_id"]) in moving:
                continue
            levels = repo.subtree_levels(item_id, self.old_owner)
            if depth + max(levels.values(), default=1) > MAX_FOLDER_DEPTH:
                raise MoveError(400, "folder_too_deep", f"Folders nest at most {MAX_FOLDER_DEPTH} levels deep")
            name = row.get("name") or "Folder"
            candidate, n = name, 2
            while candidate.lower() in taken or repo.sibling_named(self.new_owner, None, parent, candidate):
                candidate = f"{name[:74]} ({n})"
                n += 1
            taken.add(candidate.lower())
            roots[item_id] = (parent, candidate)
            if candidate != name:
                renames.append({"type": "folder", "id": item_id, "from": name, "to": candidate})
        return roots, renames

    def _slugs(self) -> tuple[dict[str, str], list[dict]]:
        """The slug each moving agent takes in the new owner's agents, and the ones a clash changed.

        An agent keeps its slug when the new owner has no agent with it (case
        ignored), else takes the first free ``-n`` form; agents moving together
        never take the same one.
        """
        # Lazy: the import/export module imports much of the agents API.
        from docsgpt.api.user.agents.portability import slugify

        repo = AgentsRepository(self.conn)
        slugs: dict[str, str] = {}
        renames: list[dict] = []
        taken: set[str] = set()
        for agent_id in self.ids("agent"):
            old = self.moving[("agent", agent_id)].row.get("slug")
            if not old:
                continue
            base = slugify(str(old))
            candidate, n = base, 2
            while candidate.lower() in taken or repo.find_by_slug(self.new_owner, candidate) is not None:
                candidate = f"{base}-{n}"
                n += 1
            taken.add(candidate.lower())
            slugs[agent_id] = candidate
            if candidate != str(old):
                renames.append({"type": "agent", "id": agent_id, "field": "slug", "from": str(old), "to": candidate})
        return slugs, renames

    # --- who and what -------------------------------------------------------------

    def _access(self, members: dict[str, str], team_name: str) -> dict:
        conn = self.conn
        if self.direction == "out":
            losing = {u: team_name for u in members if u != self.mover}
            gains = {"total": 0, "viewers": 0, "editors": 0, "admins": 0}
        else:
            others = [role for user, role in members.items() if user != self.mover]
            gains = {
                "total": len(others),
                "viewers": others.count("viewer"),
                "editors": others.count("editor"),
                "admins": sum(1 for r in others if r in ("admin", "owner")),
            }
            losing: dict[str, str] = {}
            for kind in _ITEM_KINDS:
                ids = [i for k, i in self.moving if k == kind]
                if not ids:
                    continue
                grants = conn.execute(
                    text(
                        """
                        SELECT g.team_id::text, g.target_user_id, t.name FROM team_resource_grants g
                        JOIN teams t ON t.id = g.team_id
                        WHERE g.resource_type = :k AND g.resource_id = ANY(CAST(:ids AS uuid[]))
                        ORDER BY t.name, g.team_id
                        """
                    ),
                    {"k": kind, "ids": ids},
                ).fetchall()
                for grant_team, target_user, name in grants:
                    people = [target_user] if target_user else list(_team_members(conn, grant_team))
                    for person in people:
                        if person not in members and person != self.mover:
                            losing.setdefault(person, name)
        labels = person_labels(conn, self.mover, None, losing)
        loses = [{"user_id": u, "label": labels.get(u), "via": losing[u]} for u in sorted(losing)]
        return {"gains": gains, "loses": loses}

    def _kept(self) -> dict:
        agents = [self.moving[k].row for k in self.moving if k[0] == "agent"]
        ids = [str(a["id"]) for a in agents]
        schedules = self.conn.execute(
            text(
                "SELECT id::text, agent_id::text, user_id FROM schedules "
                "WHERE agent_id = ANY(CAST(:ids AS uuid[])) AND status = ANY(:live) ORDER BY created_at, id"
            ),
            {"ids": ids, "live": list(_LIVE_SCHEDULES)},
        ).fetchall() if ids else []
        outside = {
            "api_key": any(a.get("key") for a in agents),
            "public_link": any(a.get("shared") and a.get("shared_token") for a in agents),
            "webhook": any(a.get("incoming_webhook_token") for a in agents),
        }
        labels = person_labels(self.conn, self.mover, None, [s[2] for s in schedules] + [self.mover])

        def person(user_id: str) -> dict:
            return {"user_id": user_id, "label": labels.get(user_id)}

        return {
            "schedules": [{"id": s[0], "agent_id": s[1], "paid_by": person(s[2])} for s in schedules],
            "outside_access": {**outside, "paid_by": person(self.mover) if any(outside.values()) else None},
        }

    def _folder_fed(self) -> list[str]:
        """The folders staying behind that feed a moving source today: each one it is filed in, and those above."""
        sources = self.ids("source")
        if not sources:
            return []
        repo = FoldersRepository(self.conn)
        chain: set[str] = set()
        for (folder_id,) in self.conn.execute(
            text(
                "SELECT DISTINCT folder_id::text FROM folder_items WHERE user_id = :old AND resource_type = 'source' "
                "AND resource_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"old": self.old_owner, "ids": sources},
        ):
            chain.update(repo.ancestors(folder_id, self.old_owner))
        return sorted(chain - set(self.ids("folder")))

    def _borrowing(self) -> tuple[list[dict], list[dict], int]:
        """Agents left behind that use a moving item.

        Moving in, any agent with outside access refuses the move, whoever owns
        it: its key, link or webhook would serve a team's item. The old owner's
        other agents are listed too. Moving out, every team agent left behind
        refuses, including one that reads a moved source through a folder it is
        filed in.

        Returns:
            tuple: ``(listed, blocking, hidden)``: the ``borrowing_agents`` entries the mover can open,
            those of them that refuse the move, and how many refusing agents the mover can't open.
        """
        conn = self.conn
        users: set[str] = set()
        for kind in ("source", "tool", "prompt", "folder"):
            users |= _agents_using(conn, kind, self.ids(kind))
        if self.direction == "out":
            users |= _agents_using(conn, "folder", self._folder_fed())
        users -= set(self.ids("agent"))
        rows = [row_to_dict(r) for r in conn.execute(
            text("SELECT * FROM agents WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": sorted(users)}
        ).fetchall()] if users else []
        listed: list[dict] = []
        blocking: list[dict] = []
        hidden = 0
        for row in rows:
            agent_id, owner, published = str(row["id"]), row.get("user_id"), has_outside_access(row)
            if self.direction == "out":
                if owner != self.old_owner:
                    continue
                blocks = True
            else:
                blocks = published
                if owner != self.old_owner and not blocks:
                    continue
            if owner != self.mover and resolve(conn, "agent", agent_id, self.mover) is None:
                # Not the mover's to see: counted, never named.
                hidden += int(blocks)
                continue
            entry = {"id": agent_id, "name": row.get("name"), "published": published}
            listed.append(entry)
            if blocks:
                blocking.append(entry)
        listed.sort(key=lambda a: (a["name"] or "", a["id"]))
        blocking.sort(key=lambda a: (a["name"] or "", a["id"]))
        return listed, blocking, hidden

    def _needs_admin(self) -> list[dict]:
        """Moving agents with outside access, when the mover isn't an Admin of the target team."""
        if self.direction != "in" or role_at_least(self.role, "admin"):
            return []
        return [
            {"id": e.id, "name": e.name} for e in self.moving.values()
            if e.kind == "agent" and has_outside_access(e.row)
        ]

    def _chats(self) -> int:
        """How many of the mover's own chats with the moving agents switch workspace."""
        agents = self.ids("agent")
        if not agents:
            return 0
        if self.direction == "out":
            return ConversationsRepository(self.conn).count_agent_chats(
                agents, team_id=self.team_id, user_ids=[self.mover],
            )
        # Moving in, the mover's hidden chats with the agent came through its key, widget or webhook: they
        # become the team's (see the executor's key chats), not chats of the mover's that switch.
        return int(self.conn.execute(
            text(
                "SELECT count(*) FROM conversations WHERE agent_id = ANY(CAST(:agents AS uuid[])) "
                "AND team_id IS NULL AND user_id = :mover AND visibility = 'listed'"
            ),
            {"agents": agents, "mover": self.mover},
        ).scalar() or 0)

    def ids(self, kind: str) -> list[str]:
        return [i for k, i in self.moving if k == kind]

    # --- the plan ---------------------------------------------------------------

    def run(self) -> MovePlan:
        self._sides()
        target = self._target()
        self._drag()
        self._close()
        roots, renames = self._roots(target)
        slugs, slug_renames = self._slugs()
        renames += slug_renames
        team = TeamsRepository(self.conn).get(self.team_id) or {}
        team_name = team.get("name") or ""
        members = _team_members(self.conn, self.team_id)
        borrowing, blocking, hidden = self._borrowing()
        if self.direction == "in":
            workspace = {"kind": "team", "team_id": self.team_id, "name": team_name}
        else:
            workspace = {"kind": PERSONAL, "team_id": None, "name": "Personal"}
        folder = None
        if target is not None:
            paths = folder_paths(FoldersRepository(self.conn).list_for_user(self.new_owner))
            folder = {"id": str(target["id"]), "name": target.get("name"), "path": paths.get(str(target["id"]), [])}
        for key, entry in self.cannot.items():
            entry["effect"] = EFFECT_REMOVED if key in self.referenced else EFFECT_STAYS
        body = {
            "to": {"workspace": workspace, "folder": folder},
            "items": [{"type": k, "id": i, "name": self.moving[(k, i)].name} for k, i in self.dragged],
            "moves_with": [
                {"type": e.kind, "id": e.id, "name": e.name, "via": {"type": e.via[0], "id": e.via[1]},
                 "reason": e.reason}
                for e in self.moving.values() if e.via is not None
            ],
            "cannot_move": list(self.cannot.values()),
            "access": self._access(members, team_name),
            "kept": self._kept(),
            "borrowing_agents": borrowing,
            "borrowing_others": hidden,
            "needs_admin": self._needs_admin(),
            "conversations_switched": self._chats(),
            "renames": renames,
        }
        body["fingerprint"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()
        ).hexdigest()[:32]
        return MovePlan(
            body=body,
            direction=self.direction,
            mover=self.mover,
            old_owner=self.old_owner,
            new_owner=self.new_owner,
            team_id=self.team_id,
            role=self.role,
            target_folder_id=str(target["id"]) if target else None,
            moving=self.moving,
            workflows=self.workflows,
            roots=roots,
            slugs=slugs,
            stays=self.stays,
            members=sorted(members),
            blocking=blocking,
            blocking_hidden=hidden,
            legacy_tools=self.legacy_tools,
            legacy_sources=self.legacy_sources,
        )


def plan_move(conn: Connection, mover: str, request: MoveRequest) -> MovePlan:
    """Plan a move without changing anything.

    Args:
        conn: Open connection (a read-only one will do).
        mover: The person moving.
        request: From :func:`parse_move_request`.

    Returns:
        MovePlan: ``body`` is the API's plan, with its ``fingerprint``.

    Raises:
        MoveError: 404 ``workspace_not_found`` (a team the mover isn't in), ``not_found`` (an item or folder
            they can't see) or ``folder_not_found`` (a target folder outside the target tree); 403
            ``workspace_role_required`` (a Viewer moving in, a non-Admin moving out); 400
            ``already_in_workspace`` or ``folder_too_deep``.
    """
    return _Planner(conn, mover, request).run()


def _borrow_message(agents: list[dict], hidden: int, direction: str) -> str:
    names = ", ".join(f'"{a["name"]}"' for a in agents)
    if direction == "out":
        return (f"The team's agent {names} uses what this move takes out of the team. "
                "Move it too, or remove those items from it first.")
    parts = [f"The agent {names}"] if agents else []
    if hidden:
        parts.append(f"{hidden} agent{'s' if hidden != 1 else ''} you can't open")
    who = " and ".join(parts)
    return (f"{who} can be reached from outside (a key, public link or webhook) and use what this move puts in "
            "the team, which outside access must not serve. Move it too, turn its outside access off, or remove "
            "those items from it first.")


def _sides_to_lock(conn: Connection, mover: str, request: MoveRequest) -> list[str]:
    """Who owns the items now and who will, read as the planner reads them, in lock order.

    Moving out, every team principal that owns a named item is included; the
    planner picks one of them, and holding more is harmless.

    Args:
        conn: Open connection.
        mover: The person moving.
        request: From :func:`parse_move_request`.

    Returns:
        list[str]: Owner ids, sorted so two moves never wait on each other's locks in a cycle.
    """
    owners = {mover}
    if request.team_id is not None:
        owners.add(principal_id(request.team_id))
    else:
        for kind, item_id in request.items:
            owner = resource_owner(conn, kind, item_id)
            if is_principal_id(owner):
                owners.add(owner)
    return sorted(owners)


def apply_move(conn: Connection, mover: str, request: MoveRequest) -> MovePlan:
    """Apply a move in one transaction (a savepoint of the caller's), only while its plan is unchanged.

    Args:
        conn: Open connection inside a transaction.
        mover: The person moving.
        request: From :func:`parse_move_request`, with the plan's ``fingerprint``.

    Returns:
        MovePlan: The plan that was applied.

    Raises:
        MoveError: Everything :func:`plan_move` raises; 400 ``fingerprint_required`` or ``nothing_to_move``;
            403 ``move_needs_admin`` (with ``agents``: moving agents with outside access, the mover below
            Admin); 409 ``move_plan_changed`` (with ``plan``, the fresh one), ``move_would_borrow`` (with
            ``agents`` and ``others``, a count of those the mover can't open) or ``credentials_unreadable``
            (with ``tools``). Any other error rolls the whole move back and propagates.
    """
    if not request.fingerprint:
        raise MoveError(400, "fingerprint_required", "Send the fingerprint of the plan you agreed to")
    sides = _sides_to_lock(conn, mover, request)
    # Before planning: turning on a key, link or webhook meanwhile, or saving refs on an agent that has one,
    # either lands first (and the plan sees it) or waits and sees the items moved.
    lock_owner_items(conn, *sides)
    folders = FoldersRepository(conn)
    for owner in sides:
        # The folder service's lock on each tree, taken before planning: a folder created in a moving one
        # meanwhile is either planned along or finds its parent gone, never left behind under a team's.
        folders.lock_tree(owner)
    with conn.begin_nested():
        plan = plan_move(conn, mover, request)
        if plan.body["fingerprint"] != request.fingerprint:
            raise MoveError(409, CODE_PLAN_CHANGED, "Something changed since the plan was made. Check the new plan.",
                            plan=plan.body)
        needs_admin = plan.body.get("needs_admin") or []
        if needs_admin:
            names = ", ".join(f'"{a["name"]}"' for a in needs_admin)
            raise MoveError(403, CODE_NEEDS_ADMIN,
                            f"{names} can be reached from outside (a key, public link or webhook), and only a "
                            "team Admin brings outside access into a team. Turn it off first, or ask an Admin.",
                            agents=needs_admin)
        if plan.blocking or plan.blocking_hidden:
            raise MoveError(409, CODE_WOULD_BORROW,
                            _borrow_message(plan.blocking, plan.blocking_hidden, plan.direction),
                            agents=plan.blocking, others=plan.blocking_hidden)
        if not plan.moving:
            raise MoveError(400, CODE_NOTHING_TO_MOVE, "None of these items can move")
        try:
            _Executor(conn, plan).run()
        except BaseException:
            # The savepoint rolls back, so no row points at the avatar copies any more.
            discard_copied_images(plan)
            raise
    return plan


def discard_copied_images(plan: MovePlan) -> None:
    """Delete the avatar copies a move wrote, once the move is known not to commit.

    Best effort: a copy left behind is an orphan file, never a broken agent.

    Args:
        plan: The plan whose apply step copied them.
    """
    for path in plan.copied_images:
        try:
            storage.delete_file(path)
        except Exception:
            logger.warning("Could not remove avatar copy %s of a failed move", path, exc_info=True)
    plan.copied_images.clear()


class _Executor:
    """Writes one plan; every step runs in :func:`apply_move`'s savepoint."""

    def __init__(self, conn: Connection, plan: MovePlan) -> None:
        self.conn = conn
        self.plan = plan
        self.old = plan.old_owner
        self.new = plan.new_owner
        # Who ``created_by`` names when a row records nobody: always a person.
        self.creator = plan.old_owner if plan.direction == "in" else plan.mover

    def _reown(self, table: str, ids: list[str], extra_sql: str = "", params: Optional[dict] = None) -> None:
        if not ids:
            return
        result = self.conn.execute(
            text(
                f"UPDATE {table} SET user_id = :new, created_by = COALESCE(created_by, :creator){extra_sql} "
                "WHERE id = ANY(CAST(:ids AS uuid[])) AND user_id = :old"
            ),
            {"new": self.new, "old": self.old, "creator": self.creator, "ids": ids, **(params or {})},
        )
        if result.rowcount != len(ids):
            # Someone changed the items since the plan was made; nothing is kept.
            raise MoveError(409, CODE_PLAN_CHANGED, "Something changed while moving. Plan the move again.")

    def run(self) -> None:
        plan, conn = self.plan, self.conn
        folders = plan.ids("folder")
        in_moving_folder = {
            (r[0], r[1]) for r in conn.execute(
                text(
                    "SELECT resource_type, resource_id::text FROM folder_items "
                    "WHERE user_id = :old AND folder_id = ANY(CAST(:f AS uuid[]))"
                ),
                {"old": self.old, "f": folders},
            ).fetchall()
        } if folders else set()
        self._unshare()
        self._unfile(folders)
        self._folders(folders)
        self._reown("sources", plan.ids("source"))
        self._reown("prompts", plan.ids("prompt"))
        self._reown("workflows", list(plan.workflows), ", resource_sponsors = '{}'::jsonb, updated_at = now()")
        self._agents()
        self._tools()
        self._slugs()
        self._strip_agents()
        self._strip_nodes()
        self._refile(in_moving_folder)
        self._key_chats()
        self._chats()
        self._audit()

    def _unshare(self) -> None:
        for kind in _ITEM_KINDS:
            ids = self.plan.ids(kind)
            if not ids:
                continue
            self.conn.execute(
                text(
                    "DELETE FROM team_resource_grants WHERE resource_type = :k "
                    "AND resource_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"k": kind, "ids": ids},
            )
            for item_id in ids:
                delete_settings(self.conn, kind, item_id)

    def _unfile(self, folders: list[str]) -> None:
        for kind in _ITEM_KINDS:
            ids = self.plan.ids(kind)
            if not ids:
                continue
            # Other people's personal filings go; the old owner's filing outside the moved folders is
            # replaced below by one in the target folder. Filings inside moved folders move with them.
            self.conn.execute(
                text(
                    "DELETE FROM folder_items WHERE resource_type = :k AND resource_id = ANY(CAST(:ids AS uuid[])) "
                    "AND (user_id <> :old OR NOT (folder_id = ANY(CAST(:f AS uuid[]))))"
                ),
                {"k": kind, "ids": ids, "old": self.old, "f": folders},
            )
        for kind, item_id in self.plan.stays:
            self.conn.execute(
                text(
                    "DELETE FROM folder_items WHERE user_id = :old AND resource_type = :k "
                    "AND resource_id = CAST(:i AS uuid) AND folder_id = ANY(CAST(:f AS uuid[]))"
                ),
                {"old": self.old, "k": kind, "i": item_id, "f": folders},
            )

    def _folders(self, folders: list[str]) -> None:
        roots = self.plan.roots
        for folder_id, (parent, name) in roots.items():
            self._reown(
                "folders", [folder_id], ", parent_id = CAST(:parent AS uuid), name = :name, updated_at = now()",
                {"parent": parent, "name": name},
            )
        self._reown("folders", [f for f in folders if f not in roots], ", updated_at = now()")

    def _agents(self) -> None:
        """Re-own the agents with their slugs cleared (the planned ones are set once all have moved)."""
        for agent_id in self.plan.ids("agent"):
            row = self.plan.moving[("agent", agent_id)].row
            image = row.get("image")
            if image:
                # Avatars live under their owner's upload directory.
                copied = copy_agent_image_for_user(image, self.new, storage)
                if copied and copied != image:
                    self.plan.copied_images.append(copied)
                image = copied
            payer = None
            if self.plan.direction == "in" and has_outside_access(row):
                ra = build_team(
                    "agent", agent_id, self.new, self.plan.role,
                    policy=team_policy(self.conn, team_of_principal(self.new)),
                )
                # The mover pays for the outside access they bring in, whatever the row recorded before.
                fresh = {**row, "access_payer_id": None}
                payer = access_payer_fields(ra, fresh, self.plan.mover, turning_on=True).get("access_payer_id")
            self._reown(
                "agents", [agent_id],
                ", slug = NULL, resource_sponsors = '{}'::jsonb, image = :image, access_payer_id = :payer, "
                "updated_at = now()",
                {"image": image, "payer": payer},
            )

    def _tools(self) -> None:
        prefs = UserToolPreferencesRepository(self.conn)
        sessions = ConnectorSessionsRepository(self.conn)
        mover = self.plan.mover
        for tool_id in self.plan.ids("tool"):
            # The row as it is now, locked: a secret saved since the plan read it is the one re-sealed.
            current = self.conn.execute(
                text("SELECT * FROM user_tools WHERE id = CAST(:i AS uuid) AND user_id = :old FOR UPDATE"),
                {"i": tool_id, "old": self.old},
            ).fetchone()
            if current is None:
                raise MoveError(409, CODE_PLAN_CHANGED, "Something changed while moving. Plan the move again.")
            row = row_to_dict(current)
            config = copy.deepcopy(row.get("config") or {})
            for key in _SECRET_KEYS:
                if config.get(key):
                    try:
                        config[key] = encryption.reseal_for_owner(config[key], self.old, self.new)
                    except encryption.CredentialDecryptionError as err:
                        name = _Entry("tool", tool_id, row).name
                        raise MoveError(409, CODE_UNREADABLE,
                                        f'The saved secret of "{name}" can\'t be read, so it can\'t move. '
                                        "Save it again, or leave the tool out, then move again.",
                                        tools=[{"id": tool_id, "name": name}]) from err
            connection_id = row.get("connection_id")
            if connection_id and row.get("name") == "mcp_tool" and row.get("credential_mode") != "member":
                session = sessions.get(str(connection_id))
                if session is not None and (session.get("auth_kind") or "") == "api_key":
                    # A team's server keeps its secret on the tool: the team has no connections.
                    try:
                        credentials = connector_service.get_credentials(session)
                    except connector_service.ConnectionUnavailable as err:
                        raise MoveError(409, "credentials_unavailable",
                                        "A server's saved key can't be read. Reconnect it, then move again.") from err
                    config["encrypted_credentials"] = encryption.encrypt_credentials(credentials, self.new)
                    if credentials and not config["encrypted_credentials"]:
                        raise MoveError(409, "credentials_unavailable", "A server's saved key can't be re-sealed.")
            if connection_id and (row.get("name") == "mcp_tool" or row.get("credential_mode") == "member"):
                connection_id = None
            if self.plan.direction == "in":
                # A team tool's switch is off; each member's own "in my chats" is their preference row.
                prefs.set_in_chat(mover, tool_id, bool(row.get("status")))
                status = False
            else:
                status = prefs.in_chat_many(mover, [tool_id]).get(tool_id, False)
                self.conn.execute(
                    text("DELETE FROM user_tool_preferences WHERE user_id = :u AND tool_id = CAST(:t AS uuid)"),
                    {"u": mover, "t": tool_id},
                )
            self._reown(
                "user_tools", [tool_id],
                ", config = CAST(:config AS jsonb), connection_id = CAST(:cid AS uuid), status = :status, "
                "updated_at = now()",
                {"config": json.dumps(config), "cid": str(connection_id) if connection_id else None, "status": status},
            )

    def _slugs(self) -> None:
        # The slugs the plan listed (its fingerprint covers them), set once every moved agent's old one is cleared.
        for agent_id, slug in self.plan.slugs.items():
            self.conn.execute(
                text("UPDATE agents SET slug = :slug WHERE id = CAST(:i AS uuid) AND user_id = :new"),
                {"slug": slug, "i": agent_id, "new": self.new},
            )

    def _kept(self, kind: str, item_id: Any) -> bool:
        """Whether an agent may keep a reference: the new owner's, or nobody's (a preset, a builtin tool)."""
        value = str(item_id or "").lower()
        if not looks_like_uuid(value):
            return True
        owner = resource_owner(self.conn, kind, value)
        return owner is None or owner == self.new

    def _strip_agents(self) -> None:
        repo = AgentsRepository(self.conn)
        for agent_id in self.plan.ids("agent"):
            row = _row(self.conn, "agent", agent_id)
            fields: dict[str, Any] = {}
            if row.get("source_id") and not self._kept("source", row["source_id"]):
                fields["source_id"] = None
            extra = [s for s in row.get("extra_source_ids") or [] if self._kept("source", s)]
            if len(extra) != len(row.get("extra_source_ids") or []):
                fields["extra_source_ids"] = extra
            if row.get("prompt_id") and not self._kept("prompt", row["prompt_id"]):
                fields["prompt_id"] = None
            named = row.get("tools") or []
            tools = [self.plan.legacy_tools.get(str(t).lower(), t) for t in named]
            tools = [t for t in tools if self._kept("tool", t)]
            if tools != named:
                fields["tools"] = tools
            folders = [f for f in row.get("knowledge_folder_ids") or [] if self._kept("folder", f)]
            if len(folders) != len(row.get("knowledge_folder_ids") or []):
                fields["knowledge_folder_ids"] = folders
            if self.plan.direction == "in":
                from docsgpt.api.user.workflows.routes import personal_custom_models

                models = [m for m in row.get("models") or [] if isinstance(m, str)]
                custom = {m.lower() for m in personal_custom_models(
                    self.conn, self.new, [row.get("default_model_id"), *models])}
                if str(row.get("default_model_id") or "").lower() in custom:
                    fields["default_model_id"] = None
                kept_models = [m for m in models if m.lower() not in custom]
                if len(kept_models) != len(models):
                    fields["models"] = kept_models
            if fields:
                repo.update(agent_id, self.new, fields)

    def _strip_nodes(self) -> None:
        if not self.plan.workflows:
            return
        # Lazy: the agents routes import much of the API.
        from docsgpt.api.user.agents.routes import _strip_foreign_node_refs

        transform = _strip_foreign_node_refs(self.conn, self.new)
        rows = self.conn.execute(
            text("SELECT id::text, node_type, config FROM workflow_nodes WHERE workflow_id = ANY(CAST(:w AS uuid[]))"),
            {"w": list(self.plan.workflows)},
        ).fetchall()
        for node_id, node_type, config in rows:
            if not isinstance(config, dict):
                continue
            stripped = transform(node_type, self._uuid_node_refs(node_type, copy.deepcopy(config)))
            if stripped != config:
                self.conn.execute(
                    text("UPDATE workflow_nodes SET config = CAST(:c AS jsonb) WHERE id = CAST(:i AS uuid)"),
                    {"c": json.dumps(stripped), "i": node_id},
                )

    def _uuid_node_refs(self, node_type: str, config: dict) -> dict:
        """Rewrite an agent node's tool and source refs that name an item by its Mongo id to the item's uuid.

        The strip that follows keeps only uuids, so an old id the plan resolved would otherwise be dropped.
        """
        if node_type != "agent":
            return config
        nested = config.get("config")
        cfg = nested if isinstance(nested, dict) else config
        for key, legacy in (("tools", self.plan.legacy_tools), ("sources", self.plan.legacy_sources)):
            values = cfg.get(key)
            if not values or not legacy:
                continue
            values = values if isinstance(values, list) else [values]
            cfg[key] = [legacy.get(str(v).lower(), v) if v else v for v in values]
        return config

    def _refile(self, in_moving_folder: set) -> None:
        target = self.plan.target_folder_id
        if not target:
            return
        items = FolderItemsRepository(self.conn)
        for kind, item_id in self.plan.moving:
            if kind != "folder" and (kind, item_id) not in in_moving_folder:
                items.file(self.new, kind, item_id, target)

    def _key_chats(self) -> None:
        """Give the moved agents' key, widget and webhook chats to their new owner, in its workspace.

        Those runs are stored under the agent's owner, and the key reaches its
        chats (and their artifacts) as that owner, so they follow the agent or
        the key can't continue them. Moving in, the mover's listed chats with an agent are their own
        (see :meth:`_chats`); moving out, every chat the team's principal holds
        came from outside.
        """
        plan = self.plan
        agents = plan.ids("agent")
        if not agents:
            return
        keys = [k for k in (plan.moving[("agent", a)].row.get("key") for a in agents) if k]
        team = plan.team_id
        from_team, to_team = (None, team) if plan.direction == "in" else (team, None)
        own = " AND (agent_id IS NULL OR visibility <> 'listed')" if plan.direction == "in" else ""
        ids = [r[0] for r in self.conn.execute(
            text(
                "SELECT id::text FROM conversations WHERE user_id = :old "
                "AND team_id IS NOT DISTINCT FROM CAST(:from_team AS uuid) "
                f"AND (agent_id = ANY(CAST(:agents AS uuid[])) OR api_key = ANY(CAST(:keys AS text[]))){own}"
            ),
            {"old": self.old, "from_team": from_team, "agents": agents, "keys": keys},
        ).fetchall()]
        if not ids:
            return
        self.conn.execute(
            text("UPDATE conversations SET user_id = :new, team_id = CAST(:to_team AS uuid) "
                 "WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"new": self.new, "to_team": to_team, "ids": ids},
        )
        # Copies of the owner that a continuation and a tool resume check.
        for table in ("conversation_messages", "pending_tool_state"):
            self.conn.execute(
                text(f"UPDATE {table} SET user_id = :new WHERE conversation_id = ANY(CAST(:ids AS uuid[]))"),
                {"new": self.new, "ids": ids},
            )
        # The key downloads and lists a chat's artifacts only while they name the agent's owner.
        self.conn.execute(
            text("UPDATE artifacts SET user_id = :new, team_id = CAST(:to_team AS uuid) "
                 "WHERE conversation_id = ANY(CAST(:ids AS uuid[]))"),
            {"new": self.new, "to_team": to_team, "ids": ids},
        )

    def _chats(self) -> None:
        agents = self.plan.ids("agent")
        if not agents:
            return
        # Only the mover's own chats: other people's stay where they started them.
        team = self.plan.team_id
        from_team, to_team = (None, team) if self.plan.direction == "in" else (team, None)
        ConversationsRepository(self.conn).move_agent_chats(
            agents, from_team_id=from_team, to_team_id=to_team, user_ids=[self.plan.mover],
        )

    def _audit(self) -> None:
        plan = self.plan
        for (kind, item_id), entry in plan.moving.items():
            if kind == "folder":
                if item_id not in plan.roots:
                    continue
                record_event(self.conn, FOLDER_EVENTS[plan.direction], actor=plan.mover, team_id=plan.team_id,
                             folder_id=item_id, name=plan.roots[item_id][1])
                continue
            record_event(
                self.conn, ITEM_EVENTS[plan.direction], actor=plan.mover, team_id=plan.team_id,
                resource_type=kind, resource_id=item_id, name=entry.name, reason=entry.reason,
                via_type=entry.via[0] if entry.via else None, via_id=entry.via[1] if entry.via else None,
            )
