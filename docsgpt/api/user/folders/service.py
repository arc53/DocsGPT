"""The folder rules every folder route goes through: names, depth, cycles, filing and delete.

Folders are personal: a user files any agent or source they can see (their
own and team-shared ones) into their own folders of the same type, one folder
per item. The routes (``/api/folders``, the ``/api/agents/folders`` aliases,
the agent and source APIs) call these functions on an open connection and turn
a :class:`FolderError` into ``{"success": false, "error": code, "message"}``.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Iterable, Optional

from flask import Response, jsonify, make_response
from sqlalchemy import Connection, text

from docsgpt.api.user.resource_access import resolve
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.folders import (
    FOLDER_RESOURCE_TYPES,
    FolderItemsRepository,
    FoldersRepository,
)

#: Folders nest this many levels deep; a top-level folder is level 1.
MAX_FOLDER_DEPTH = 3

#: The longest folder name, after trimming.
MAX_FOLDER_NAME = 80

#: The table each folder type files.
_ITEM_TABLE = {"agent": "agents", "source": "sources"}

#: A folder that would hold this many items has a sane ``ids`` list per request.
MAX_FILING_IDS = 500

_UNSET = object()


class FolderError(Exception):
    """A refused folder request: an HTTP status, a stable error code and a message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def response(self) -> Response:
        """The JSON error response for this refusal."""
        return folder_error(self.status, self.code, self.message)


def folder_error(status: int, code: str, message: str) -> Response:
    """``{"success": false, "error": code, "message": message}`` with ``status``."""
    return make_response(jsonify({"success": False, "error": code, "message": message}), status)


def parse_resource_type(raw: Any) -> str:
    """The folder type a request names.

    Args:
        raw: ``agent`` or ``source``.

    Returns:
        str: The type.

    Raises:
        FolderError: 400 ``invalid_type`` for anything else.
    """
    value = str(raw or "").strip().lower()
    if value not in FOLDER_RESOURCE_TYPES:
        raise FolderError(400, "invalid_type", "type must be agent or source")
    return value


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
    """The caller's folder by id (a UUID or a legacy Mongo id).

    Args:
        conn: Open connection.
        folder_id: The requested id.
        user: The caller.
        resource_type: The type it must hold, or ``None`` for any.

    Returns:
        dict: The folder row.

    Raises:
        FolderError: 404 ``folder_not_found`` when it isn't the caller's (or is of another type).
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
    resource_type: str,
    name: Any,
    parent_id: Any = None,
    description: Optional[str] = None,
) -> dict:
    """Create one of the caller's folders.

    Args:
        conn: Open connection.
        user: The caller (the new folder's owner).
        resource_type: ``agent`` or ``source``.
        name: The requested name.
        parent_id: The parent folder (the caller's, of the same type), or None for the top level.
        description: Optional description.

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
    return FoldersRepository(conn).create(
        user, clean, resource_type=resource_type, description=description, parent_id=parent_pg,
    )


def update_folder(
    conn: Connection,
    user: str,
    folder: dict,
    *,
    name: Any = _UNSET,
    parent_id: Any = _UNSET,
    description: Any = _UNSET,
) -> dict:
    """Rename and/or move one of the caller's folders.

    A move checks the target is the caller's folder of the same type, is not
    the folder or one of its descendants, and keeps every folder it carries
    within :data:`MAX_FOLDER_DEPTH`. Folders already deeper than that keep
    working; only the move is checked.

    Args:
        conn: Open connection.
        user: The caller.
        folder: The folder row (from :func:`resolve_folder`).
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


def delete_folder(conn: Connection, folder: dict) -> dict[str, int]:
    """Delete a folder; its folders and items move to its parent (top level and unfiled without one).

    Agents that read the folder live lose it (the ``folders_cleanup_agent_knowledge_refs`` trigger).

    Args:
        conn: Open connection.
        folder: The caller's folder row.

    Returns:
        dict: ``{"moved_items": n, "moved_folders": n}``.
    """
    return FoldersRepository(conn).delete_into_parent(folder)


def visible_item_id(conn: Connection, resource_type: str, resource_id: Any, user: str) -> Optional[str]:
    """The canonical id of an agent or source the caller can see, or ``None``.

    Args:
        conn: Open connection.
        resource_type: ``agent`` or ``source``.
        resource_id: The requested id (a UUID or a legacy id).
        user: The caller.

    Returns:
        Optional[str]: The item's UUID when the caller owns it or a team shares it with them.
    """
    if not resource_id or not isinstance(resource_id, str):
        return None
    ra = resolve(conn, resource_type, resource_id, user)
    if ra is None or not looks_like_uuid(ra.resource_id):
        return None
    return ra.resource_id.lower()


def file_items(
    conn: Connection, user: str, resource_type: str, folder_id: Any, ids: Iterable[Any]
) -> tuple[list[str], list[str]]:
    """File items the caller can see into one of their folders (``None`` unfiles them).

    Filing writes only the caller's ``folder_items`` row, never the item.

    Args:
        conn: Open connection.
        user: The caller.
        resource_type: ``agent`` or ``source``.
        folder_id: The target folder (the caller's, of this type), or None to unfile.
        ids: The items, as the request sent them.

    Returns:
        tuple: ``(moved, skipped)``, each the ids as sent; skipped ones are not visible to the caller.

    Raises:
        FolderError: 404 ``folder_not_found`` when the folder isn't the caller's of this type.
    """
    folder_pg = str(resolve_folder(conn, folder_id, user, resource_type)["id"]) if folder_id else None
    items = FolderItemsRepository(conn)
    moved: list[str] = []
    skipped: list[str] = []
    for raw in ids:
        canonical = visible_item_id(conn, resource_type, raw, user)
        if canonical is None:
            skipped.append(str(raw))
            continue
        items.file(user, resource_type, canonical, folder_pg)
        moved.append(str(raw))
    return moved, skipped


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_folder(folder: dict) -> dict:
    """The outward shape of a folder row (without counts)."""
    return {
        "id": str(folder["id"]),
        "name": folder.get("name"),
        "parent_id": str(folder["parent_id"]) if folder.get("parent_id") else None,
        "type": folder.get("resource_type") or "agent",
        "created_at": _iso(folder.get("created_at")),
        "updated_at": _iso(folder.get("updated_at")),
    }


def visible_item_counts(conn: Connection, user: str, resource_type: str) -> dict[str, int]:
    """``folder_id -> number of items in it`` the caller can still see (own or team-shared).

    A filing of an item whose team share ended stays, hidden, and counts again once it is shared back.
    """
    table = _ITEM_TABLE[resource_type]
    visible = sorted(visible_with_access(conn, user, resource_type))
    rows = conn.execute(
        text(
            f"""
            SELECT fi.folder_id::text, count(*) FROM folder_items fi
            JOIN {table} r ON r.id = fi.resource_id
            WHERE fi.user_id = :user_id AND fi.resource_type = :resource_type
              AND (r.user_id = :user_id OR r.id = ANY(CAST(:visible AS uuid[])))
            GROUP BY fi.folder_id
            """
        ),
        {"user_id": user, "resource_type": resource_type, "visible": visible},
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def list_folders(conn: Connection, user: str, resource_type: str) -> list[dict]:
    """The caller's folders of one type, each with ``item_count`` and ``folder_count`` (direct children).

    Args:
        conn: Open connection.
        user: The caller.
        resource_type: ``agent`` or ``source``.

    Returns:
        list[dict]: Serialized folders, oldest first.
    """
    folders = FoldersRepository(conn).list_for_user(user, resource_type)
    counts = visible_item_counts(conn, user, resource_type)
    children: dict[str, int] = {}
    for folder in folders:
        if folder.get("parent_id"):
            key = str(folder["parent_id"])
            children[key] = children.get(key, 0) + 1
    out = []
    for folder in folders:
        fid = str(folder["id"])
        out.append({**serialize_folder(folder), "item_count": counts.get(fid, 0), "folder_count": children.get(fid, 0)})
    return out


def folder_paths(folders: Iterable[dict]) -> dict[str, list[dict]]:
    """``folder_id -> [{id, name}, ...]`` from the top-level folder down to it (cycle-safe).

    Args:
        folders: Folder rows of one user and type.

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


class SourceFiling:
    """The caller's source folders and filings, read once per listing.

    Attributes:
        folders: The caller's source folder rows.
        filings: ``source_id -> folder_id`` (lower-case ids).
        paths: ``folder_id -> [{id, name}]``, top-level folder first.
    """

    def __init__(self, conn: Connection, user: str) -> None:
        self.folders = FoldersRepository(conn).list_for_user(user, "source")
        self.paths = folder_paths(self.folders)
        self.filings = {
            sid: fid for sid, fid in FolderItemsRepository(conn).filings(user, "source").items() if fid in self.paths
        }

    def folder_of(self, source_id: Any) -> Optional[str]:
        """The folder the caller filed a source into, or ``None``."""
        return self.filings.get(str(source_id).lower())

    def fields(self, source_id: Any) -> dict:
        """``{"folder_id", "folder_path"}`` for one listed source."""
        folder_id = self.folder_of(source_id)
        return {"folder_id": folder_id, "folder_path": self.paths.get(folder_id, []) if folder_id else []}


def ingest_folder(conn: Connection, user: str, raw: Any) -> Optional[str]:
    """The source folder an ingest request files its new source into.

    Args:
        conn: Open connection.
        user: The uploader.
        raw: The request's ``folder_id`` (empty for none).

    Returns:
        Optional[str]: The folder's UUID, or None.

    Raises:
        FolderError: 404 ``folder_not_found`` when it isn't one of the caller's source folders.
    """
    if raw in (None, "", "null"):
        return None
    return str(resolve_folder(conn, raw, user, "source")["id"])


def file_new_source(conn: Connection, user: str, source_id: str, folder_id: Optional[str]) -> bool:
    """File a just-created source into the uploader's folder, when it still exists.

    Args:
        conn: Open connection.
        user: The uploader (the source's owner).
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
