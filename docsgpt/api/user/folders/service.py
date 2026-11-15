"""The folder rules every folder route goes through: trees, names, depth, cycles, filing and delete.

Each owner has one folder tree: a person, or a team's principal. A folder
holds agents, sources, tools and prompts alike, and sibling names are unique
ignoring case across kinds. A list or a create works in the request's
workspace (``X-DocsGPT-Workspace``): the caller's own tree in Personal, the
team's one tree in a team, the same for every member. A route about one folder
goes by the folder's own owner instead.

In a team, any member lists the tree; creating, renaming, moving, filing and
deleting need Editor (``WORKSPACE_ACTIONS["folder"]``). A team's tree holds
only the team's own items, and a person's tree holds their own items plus
personal items shared with them; a team's item is never filed in a personal
folder (pin it instead).

The routes (``/api/folders``, the ``/api/agents/folders`` aliases, the agent,
source, tool and prompt APIs) call these functions on an open connection and
turn a :class:`FolderError` into ``{"success": false, "error": code, "message"}``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from flask import Response, jsonify, make_response
from sqlalchemy import Connection, text

from docsgpt.api.user.resource_access import (
    WORKSPACE_ACTIONS,
    created_by_payload,
    creator_payloads,
    resolve,
    resource_owner,
    workspace_allowed_actions,
)
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.folders import (
    FOLDER_RESOURCE_TYPES,
    FolderItemsRepository,
    FoldersRepository,
)
from docsgpt.workspaces.context import Workspace
from docsgpt.workspaces.principal import is_principal_id, team_of_principal
from docsgpt.workspaces.roles import team_role_for

#: Folders nest this many levels deep; a top-level folder is level 1.
MAX_FOLDER_DEPTH = 3

#: The longest folder name, after trimming.
MAX_FOLDER_NAME = 80

#: The table of each kind a folder holds.
_ITEM_TABLE = {"agent": "agents", "source": "sources", "tool": "user_tools", "prompt": "prompts"}

#: A folder that would hold this many items has a sane ``ids`` list per request.
MAX_FILING_IDS = 500

#: 409 code: a team's item can't be filed in a personal folder.
TEAM_ITEM_NOT_FILEABLE = "team_item_not_fileable"

#: 409 code: a team's folder holds only that team's own items.
ITEM_NOT_IN_TEAM = "item_not_in_team"

_UNSET = object()


class FolderError(Exception):
    """A refused folder request: an HTTP status, a stable error code, a message and optional extra fields."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def response(self) -> Response:
        """The JSON error response for this refusal."""
        return folder_error(self.status, self.code, self.message, **self.extra)


def folder_error(status: int, code: str, message: str, **extra: Any) -> Response:
    """``{"success": false, "error": code, "message": message, **extra}`` with ``status``."""
    return make_response(jsonify({"success": False, "error": code, "message": message, **extra}), status)


def parse_resource_type(raw: Any) -> str:
    """The item kind a request names.

    Args:
        raw: ``agent``, ``source``, ``tool`` or ``prompt``.

    Returns:
        str: The kind.

    Raises:
        FolderError: 400 ``invalid_type`` for anything else.
    """
    value = str(raw or "").strip().lower()
    if value not in FOLDER_RESOURCE_TYPES:
        raise FolderError(400, "invalid_type", "type must be agent, source, tool or prompt")
    return value


def parse_optional_type(raw: Any) -> Optional[str]:
    """The item kind a request names, or None when it names none (see :func:`parse_resource_type`)."""
    if raw is None or not str(raw).strip():
        return None
    return parse_resource_type(raw)


@dataclass(frozen=True)
class FolderTree:
    """One owner's folder tree as the caller reaches it.

    Attributes:
        owner_id: Whose tree it is: the caller in Personal, the team's principal in a team. Folders and
            filings in it are written as this id.
        team_id: The team, for a team's tree; None for a person's.
        role: The caller's role in that team; None for a person's tree.
    """

    owner_id: str
    team_id: Optional[str] = None
    role: Optional[str] = None

    @property
    def is_team(self) -> bool:
        """Whether a team owns the tree."""
        return self.team_id is not None

    def can(self, action: str) -> bool:
        """Whether the caller may do ``action`` (``list``, ``create``, ``rename``, ``move``, ``file``, ``delete``).

        A person may do anything in their own tree; in a team's the caller's role decides.
        """
        if not self.is_team:
            return True
        return action in workspace_allowed_actions("folder", self.role)

    def require(self, action: str) -> None:
        """Refuse unless the caller may do ``action`` here.

        Raises:
            FolderError: 403 ``workspace_role_required``.
        """
        if not self.can(action):
            minimum = WORKSPACE_ACTIONS["folder"].get(action, "admin")
            raise FolderError(403, "workspace_role_required", f"This needs the {minimum} role in the team")


def workspace_tree(workspace: Workspace) -> FolderTree:
    """The folder tree of a request's workspace (``workspaces.context.current_workspace``).

    Args:
        workspace: The request's workspace, membership already checked.

    Returns:
        FolderTree: The caller's own tree in Personal, the team's in a team.
    """
    if workspace.is_team:
        return FolderTree(workspace.owner_id, workspace.team_id, workspace.role)
    return FolderTree(workspace.owner_id)


def folder_by_id(conn: Connection, folder_id: Any, caller: str) -> tuple[dict, FolderTree]:
    """A folder by id and the caller's place in its tree, whatever workspace the request names.

    The caller's own folder, or a folder of a team they belong to. A legacy
    Mongo id names only one of the caller's own folders.

    Args:
        conn: Open connection.
        folder_id: The requested id.
        caller: The person asking.

    Returns:
        tuple: ``(folder row, tree)``.

    Raises:
        FolderError: 404 ``folder_not_found`` for anyone else's folder, a team the caller isn't in, or no folder.
    """
    raw = str(folder_id or "").strip()
    if raw and looks_like_uuid(raw):
        owner = resource_owner(conn, "folder", raw)
        if owner is not None and owner != caller and is_principal_id(owner) and not is_principal_id(caller):
            team_id = team_of_principal(owner)
            role = team_role_for(conn, caller, team_id) if team_id else None
            if role is not None:
                return resolve_folder(conn, raw, owner), FolderTree(owner, team_id, role)
            raise FolderError(404, "folder_not_found", "Folder not found")
    return resolve_folder(conn, raw, caller), FolderTree(caller)


def clean_folder_name(raw: Any) -> str:
    """A folder name, trimmed and checked.

    Args:
        raw: The requested name.

    Returns:
        str: The trimmed name.

    Raises:
        FolderError: 400 ``invalid_folder_name`` when it isn't a string, is
            empty or longer than :data:`MAX_FOLDER_NAME` once trimmed, or holds
            a control character.
    """
    if not isinstance(raw, str):
        raise FolderError(400, "invalid_folder_name", "Folder name is required")
    name = raw.strip()
    if not name:
        raise FolderError(400, "invalid_folder_name", "Folder name is required")
    if len(name) > MAX_FOLDER_NAME:
        raise FolderError(400, "invalid_folder_name", f"Folder name can be at most {MAX_FOLDER_NAME} characters")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise FolderError(400, "invalid_folder_name", "Folder name can't hold control characters")
    return name


def resolve_folder(conn: Connection, folder_id: Any, user: str, resource_type: Optional[str] = None) -> dict:
    """A folder of ``user``'s tree by id (a UUID or a legacy Mongo id).

    Args:
        conn: Open connection.
        folder_id: The requested id.
        user: The tree's owner: a person, or a team's principal (access already checked).
        resource_type: Kept for callers; any folder of the tree matches (folders hold every kind).

    Returns:
        dict: The folder row.

    Raises:
        FolderError: 404 ``folder_not_found`` when it isn't in that tree.
    """
    repo = FoldersRepository(conn)
    folder = None
    if folder_id:
        raw = str(folder_id).strip()
        folder = repo.get(raw, user, resource_type) if looks_like_uuid(raw) else None
        if folder is None and not looks_like_uuid(raw):
            folder = repo.get_by_legacy_id(raw, user, resource_type)
    if folder is None:
        raise FolderError(404, "folder_not_found", "Folder not found")
    return folder


def _check_name_free(
    conn: Connection, user: str, resource_type: str, parent_id: Optional[str], name: str, exclude_id: Optional[str]
) -> None:
    if FoldersRepository(conn).sibling_named(user, resource_type, parent_id, name, exclude_id) is not None:
        raise FolderError(409, "folder_name_taken", "A folder with this name already exists here")


def _depth(conn: Connection, folder_id: Optional[str], user: str) -> int:
    """How deep a folder sits (top level is 1); 0 for the root."""
    if not folder_id:
        return 0
    return len(FoldersRepository(conn).ancestors(str(folder_id), user))


def create_folder(
    conn: Connection,
    user: str,
    resource_type: Optional[str],
    name: Any,
    parent_id: Any = None,
    description: Optional[str] = None,
    *,
    created_by: Optional[str] = None,
) -> dict:
    """Create a folder in ``user``'s tree.

    Args:
        conn: Open connection.
        user: The tree's owner (the new folder's owner): the caller, or a team's principal.
        resource_type: The kind the request named, echoed as ``type``; it doesn't shape the folder.
        name: The requested name.
        parent_id: The parent folder (in the same tree), or None for the top level.
        description: Optional description.
        created_by: The person creating it; required in a team's tree (nothing fills it there).

    Returns:
        dict: The new folder row.

    Raises:
        FolderError: ``invalid_folder_name``, ``folder_not_found`` (the parent),
            ``folder_too_deep`` or ``folder_name_taken``.
    """
    clean = clean_folder_name(name)
    parent = resolve_folder(conn, parent_id, user, resource_type) if parent_id else None
    parent_pg = str(parent["id"]) if parent else None
    if _depth(conn, parent_pg, user) + 1 > MAX_FOLDER_DEPTH:
        raise FolderError(400, "folder_too_deep", f"Folders nest at most {MAX_FOLDER_DEPTH} levels deep")
    _check_name_free(conn, user, resource_type, parent_pg, clean, None)
    folder = FoldersRepository(conn).create(
        user, clean, description=description, parent_id=parent_pg, created_by=created_by,
    )
    # The row has no type; echo the requested one so the response keeps today's ``type``.
    return {**folder, "resource_type": resource_type} if resource_type else folder


def update_folder(
    conn: Connection,
    user: str,
    folder: dict,
    *,
    name: Any = _UNSET,
    parent_id: Any = _UNSET,
    description: Any = _UNSET,
) -> dict:
    """Rename and/or move a folder within its tree.

    A move checks the target is a folder of the same tree, is not
    the folder or one of its descendants, and keeps every folder it carries
    within :data:`MAX_FOLDER_DEPTH`. Folders already deeper than that keep
    working; only the move is checked.

    Args:
        conn: Open connection.
        user: The tree's owner (the folder's ``user_id``).
        folder: The folder row (from :func:`resolve_folder` or :func:`folder_by_id`).
        name: A new name, if given.
        parent_id: A new parent (None or ``""`` for the top level), if given.
        description: A new description, if given.

    Returns:
        dict: The updated row.

    Raises:
        FolderError: ``invalid_folder_name``, ``folder_not_found`` (the
            parent), ``folder_cycle``, ``folder_too_deep`` or ``folder_name_taken``.
    """
    repo = FoldersRepository(conn)
    folder_pg = str(folder["id"])
    resource_type = folder.get("resource_type") or "agent"
    fields: dict[str, Any] = {}
    target_parent = str(folder["parent_id"]) if folder.get("parent_id") else None
    if parent_id is not _UNSET:
        new_parent = str(resolve_folder(conn, parent_id, user, resource_type)["id"]) if parent_id else None
        if new_parent is not None and new_parent != target_parent:
            levels = repo.subtree_levels(folder_pg, user)
            if new_parent in levels:
                raise FolderError(400, "folder_cycle", "A folder can't move into itself or one of its folders")
            if _depth(conn, new_parent, user) + max(levels.values(), default=1) > MAX_FOLDER_DEPTH:
                raise FolderError(400, "folder_too_deep", f"Folders nest at most {MAX_FOLDER_DEPTH} levels deep")
        if new_parent != target_parent:
            fields["parent_id"] = new_parent
            target_parent = new_parent
    target_name = folder.get("name") or ""
    if name is not _UNSET:
        target_name = clean_folder_name(name)
        if target_name != folder.get("name"):
            fields["name"] = target_name
    if "name" in fields or "parent_id" in fields:
        _check_name_free(conn, user, resource_type, target_parent, target_name, folder_pg)
    if description is not _UNSET:
        fields["description"] = description
    if fields:
        repo.update(folder_pg, user, fields)
    return repo.get(folder_pg, user) or folder


def delete_folder(conn: Connection, folder: dict) -> dict[str, Any]:
    """Delete a folder; its folders and items move to its parent (top level and unfiled without one).

    Agents that read the folder live lose it (the ``folders_cleanup_agent_knowledge_refs`` trigger).

    Args:
        conn: Open connection.
        folder: The folder row (its tree's access already checked).

    Returns:
        dict: ``{"moved_items": n, "moved_folders": n, "renamed": [{"id", "from", "to"}]}`` (child folders
        renamed so their names stay unique where they land).
    """
    return FoldersRepository(conn).delete_into_parent(folder)


def visible_item_id(conn: Connection, resource_type: str, resource_id: Any, user: str) -> Optional[str]:
    """The canonical id of an item the caller can see, or ``None``.

    Args:
        conn: Open connection.
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        resource_id: The requested id (a UUID or a legacy id).
        user: The caller.

    Returns:
        Optional[str]: The item's UUID when the caller owns it, a team shares it with them, or it is
        their team's.
    """
    if not resource_id or not isinstance(resource_id, str):
        return None
    ra = resolve(conn, resource_type, resource_id, user)
    if ra is None or not looks_like_uuid(ra.resource_id):
        return None
    return ra.resource_id.lower()


def file_items(
    conn: Connection,
    user: str,
    resource_type: str,
    folder_id: Any,
    ids: Iterable[Any],
    *,
    tree: Optional[FolderTree] = None,
) -> tuple[list[str], list[str]]:
    """File items the caller can see into a folder (``None`` unfiles them).

    With a folder, its own tree decides where the filing goes and whether the
    caller may file there. With ``None`` the filing is taken out of ``tree``
    (the request's workspace; the caller's own tree when not given). A team's
    tree takes only that team's items and a person's tree no team's item: the
    whole request is refused (409) before anything is written when one doesn't
    fit. Filing writes only a ``folder_items`` row, never the item.

    Args:
        conn: Open connection.
        user: The caller.
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        folder_id: The target folder, or None to unfile.
        ids: The items, as the request sent them.
        tree: The tree to unfile from when ``folder_id`` is None.

    Returns:
        tuple: ``(moved, skipped)``, each the ids as sent; skipped ones are not visible to the caller (a
        builtin tool, which has no row, included).

    Raises:
        FolderError: 404 ``folder_not_found`` when the folder isn't the caller's or their team's; 403
            ``workspace_role_required`` for a team Viewer; 409 ``team_item_not_fileable`` (a team's item into
            a personal folder) or ``item_not_in_team`` (anything else into a team's folder), with ``ids``.
    """
    if folder_id:
        folder, tree = folder_by_id(conn, folder_id, user)
        folder_pg: Optional[str] = str(folder["id"])
    else:
        tree = tree or FolderTree(user)
        folder_pg = None
    tree.require("file")
    planned: list[tuple[str, str]] = []
    skipped: list[str] = []
    misfiled: list[str] = []
    for raw in ids:
        ra = resolve(conn, resource_type, raw, user) if raw and isinstance(raw, str) else None
        if ra is None or not looks_like_uuid(ra.resource_id) or not ra.can("move_folder"):
            skipped.append(str(raw))
            continue
        # Taking a filing out never misplaces anything; filing in must fit the tree.
        if folder_pg is not None and (ra.owner_id != tree.owner_id if tree.is_team else ra.is_team_item):
            misfiled.append(str(raw))
            continue
        planned.append((str(raw), ra.resource_id.lower()))
    if misfiled and tree.is_team:
        raise FolderError(
            409, ITEM_NOT_IN_TEAM,
            "A team's folders hold only the team's own items. Move the item to the team first.", ids=misfiled,
        )
    if misfiled:
        raise FolderError(
            409, TEAM_ITEM_NOT_FILEABLE, "A team's items aren't filed in personal folders; pin them instead.",
            ids=misfiled,
        )
    items = FolderItemsRepository(conn)
    for _raw, canonical in planned:
        items.file(tree.owner_id, resource_type, canonical, folder_pg)
    return [raw for raw, _ in planned], skipped


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_folder(folder: dict, resource_type: Optional[str] = None) -> dict:
    """The outward shape of a folder row (without counts).

    Args:
        folder: The row.
        resource_type: The kind the request named; ``type`` falls back to ``agent`` (a folder has no kind of
            its own any more, and today's UI reads one).

    Returns:
        dict: ``id``, ``name``, ``parent_id``, ``type``, ``created_at``, ``updated_at``.
    """
    return {
        "id": str(folder["id"]),
        "name": folder.get("name"),
        "parent_id": str(folder["parent_id"]) if folder.get("parent_id") else None,
        "type": resource_type or folder.get("resource_type") or "agent",
        "created_at": _iso(folder.get("created_at")),
        "updated_at": _iso(folder.get("updated_at")),
    }


def visible_item_counts(conn: Connection, user: str, resource_type: str, owner: Optional[str] = None) -> dict[str, int]:
    """``folder_id -> number of items of one kind`` filed in a tree that the caller can still see.

    In a team's tree that is the team's own items (anything else filed there
    is not counted). In a person's tree it is their own items plus personal
    items shared with them; a filing of an item whose share ended stays,
    hidden, and counts again once it is shared back.

    Args:
        conn: Open connection.
        user: The caller.
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        owner: The tree's owner; the caller when None.

    Returns:
        dict[str, int]: Folders with no visible item are left out.
    """
    owner = owner or user
    table = _ITEM_TABLE[resource_type]
    visible = [] if is_principal_id(owner) else sorted(visible_with_access(conn, user, resource_type))
    rows = conn.execute(
        text(
            f"""
            SELECT fi.folder_id::text, count(*) FROM folder_items fi
            JOIN {table} r ON r.id = fi.resource_id
            WHERE fi.user_id = :owner AND fi.resource_type = :resource_type
              AND (r.user_id = :owner OR r.id = ANY(CAST(:visible AS uuid[])))
            GROUP BY fi.folder_id
            """
        ),
        {"owner": owner, "resource_type": resource_type, "visible": visible},
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def list_folders(
    conn: Connection, user: str, resource_type: Optional[str] = None, *, tree: Optional[FolderTree] = None
) -> list[dict]:
    """Every folder of a tree with what it holds, oldest first.

    Each folder carries ``counts`` (``{agent, source, tool, prompt}``: items
    filed directly in it that the caller can see), ``item_count`` (of
    ``resource_type``, or of every kind without one), ``folder_count`` (its
    child folders) and ``created_by`` (``{user_id, label}``, or None).

    Args:
        conn: Open connection.
        user: The caller.
        resource_type: The kind ``item_count`` counts (and ``type`` echoes); every kind when None.
        tree: The tree; the caller's own when None.

    Returns:
        list[dict]: Serialized folders.
    """
    tree = tree or FolderTree(user)
    folders = FoldersRepository(conn).list_for_user(tree.owner_id)
    if not folders:
        return []
    counts = {kind: visible_item_counts(conn, user, kind, tree.owner_id) for kind in FOLDER_RESOURCE_TYPES}
    creators = creator_payloads(conn, user, folders)
    children: dict[str, int] = {}
    for folder in folders:
        if folder.get("parent_id"):
            key = str(folder["parent_id"])
            children[key] = children.get(key, 0) + 1
    out = []
    for folder in folders:
        fid = str(folder["id"])
        per_kind = {kind: counts[kind].get(fid, 0) for kind in FOLDER_RESOURCE_TYPES}
        out.append(
            {
                **serialize_folder(folder, resource_type),
                "created_by": created_by_payload(folder, creators),
                "counts": per_kind,
                "item_count": per_kind[resource_type] if resource_type else sum(per_kind.values()),
                "folder_count": children.get(fid, 0),
            }
        )
    return out


def folder_paths(folders: Iterable[dict]) -> dict[str, list[dict]]:
    """``folder_id -> [{id, name}, ...]`` from the top-level folder down to it (cycle-safe).

    Args:
        folders: The folder rows of one tree.

    Returns:
        dict: The path of every folder.
    """
    by_id = {str(f["id"]): f for f in folders}
    paths: dict[str, list[dict]] = {}
    for fid in by_id:
        chain: list[dict] = []
        seen: set[str] = set()
        current: Optional[str] = fid
        while current and current in by_id and current not in seen:
            seen.add(current)
            row = by_id[current]
            chain.append({"id": current, "name": row.get("name")})
            current = str(row["parent_id"]) if row.get("parent_id") else None
        paths[fid] = list(reversed(chain))
    return paths


def subtree_ids(folders: Iterable[dict], root_id: str) -> set[str]:
    """``root_id`` and the ids of every folder under it (cycle-safe)."""
    children: dict[str, list[str]] = {}
    for f in folders:
        if f.get("parent_id"):
            children.setdefault(str(f["parent_id"]), []).append(str(f["id"]))
    out: set[str] = set()
    stack = [str(root_id)]
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.add(current)
        stack.extend(children.get(current, []))
    return out


class ItemFiling:
    """One tree's folders and its filings of one kind, read once per listing.

    Attributes:
        folders: The tree's folder rows.
        filings: ``item_id -> folder_id`` (lower-case ids).
        paths: ``folder_id -> [{id, name}]``, top-level folder first.
    """

    def __init__(self, conn: Connection, owner: str, resource_type: str) -> None:
        self.folders = FoldersRepository(conn).list_for_user(owner)
        self.paths = folder_paths(self.folders)
        self.filings = {
            item_id: fid
            for item_id, fid in FolderItemsRepository(conn).filings(owner, resource_type).items()
            if fid in self.paths
        }

    def folder_of(self, item_id: Any) -> Optional[str]:
        """The folder an item is filed in, or ``None``."""
        return self.filings.get(str(item_id).lower())

    def fields(self, item_id: Any) -> dict:
        """``{"folder_id", "folder_path"}`` for one listed item."""
        folder_id = self.folder_of(item_id)
        return {"folder_id": folder_id, "folder_path": self.paths.get(folder_id, []) if folder_id else []}


class SourceFiling(ItemFiling):
    """One tree's folders and source filings (see :class:`ItemFiling`)."""

    def __init__(self, conn: Connection, user: str) -> None:
        super().__init__(conn, user, "source")


def filing_folder(conn: Connection, owner: str, raw: Any) -> Optional[str]:
    """The folder of ``owner``'s tree a save asks to file its item in.

    Args:
        conn: Open connection.
        owner: The tree's owner: the caller in Personal, the team's principal for a team item.
        raw: The request's ``folder_id`` (empty or ``"null"`` for none).

    Returns:
        Optional[str]: The folder's UUID, or None.

    Raises:
        FolderError: 404 ``folder_not_found`` when it isn't in that tree.
    """
    if raw in (None, "", "null"):
        return None
    return str(resolve_folder(conn, raw, owner)["id"])


def filing_owner(ra: Any, user: str) -> str:
    """Whose tree a save files an item in: the team's for a team item, else the caller's own.

    Args:
        ra: The caller's :class:`~docsgpt.api.user.resource_access.ResourceAccess` on the item.
        user: The caller.

    Returns:
        str: The tree's owner.
    """
    return ra.owner_id if ra is not None and ra.is_team_item else user


def ingest_folder(conn: Connection, user: str, raw: Any) -> Optional[str]:
    """The source folder an ingest request files its new source into.

    Args:
        conn: Open connection.
        user: The new source's owner: the uploader, or the team's principal for a team upload.
        raw: The request's ``folder_id`` (empty for none).

    Returns:
        Optional[str]: The folder's UUID, or None.

    Raises:
        FolderError: 404 ``folder_not_found`` when it isn't in that owner's tree.
    """
    return filing_folder(conn, user, raw)


def file_new_source(conn: Connection, user: str, source_id: str, folder_id: Optional[str]) -> bool:
    """File a just-created source into its owner's folder, when it still exists.

    Args:
        conn: Open connection.
        user: The source's owner (a team's principal for a team upload).
        source_id: The new source.
        folder_id: The folder the upload asked for.

    Returns:
        bool: True when filed.
    """
    if not folder_id or not looks_like_uuid(str(source_id)):
        return False
    if FoldersRepository(conn).get(str(folder_id), user, "source") is None:
        return False
    FolderItemsRepository(conn).file(user, "source", str(source_id), str(folder_id))
    return True
