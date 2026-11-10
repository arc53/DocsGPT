"""Live knowledge folders: a source folder an agent, a workflow step or a chat reads as a whole.

An agent (``agents.knowledge_folder_ids``), a workflow agent node
(``config.folders``) or an agentless chat request (``active_folders``) may name
source folders instead of, or next to, single sources. A folder stays live: a
source filed into it later reaches every holder at its next run.

A folder is personal filing, so it reads as its owner's: the sources its owner
filed anywhere in its subtree, each one the owner may still use
(:func:`docsgpt.api.user.resource_access.can_use_ref`). A folder that no longer
exists adds nothing. Only a folder's owner may attach it to something; one
already attached stays when someone else saves the holder.

On an agent or a workflow owned by someone else (a teammate attached their own
folder), the folder's owner stands in like a sponsor: it feeds a source only
when the holder's owner may use it or the folder's owner may sponsor it
(``can_sponsor_ref``: owns or edits it), and nothing at all once the folder's
owner can no longer edit the holder (``sponsor_cannot_edit_agent``).
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlalchemy import Connection, text

from docsgpt.api.user.resource_access import (
    REASON_CANNOT_EDIT_HOLDER,
    REASON_DELETED,
    can_sponsor_ref,
    can_use_ref,
    holder_editable_by,
    person_labels,
)
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.session import db_readonly

#: The 403 error code of a folder the caller may not attach.
FOLDER_NOT_ACCESSIBLE = "folder_not_accessible"

# Each requested source folder (``root``) and every folder under it, with its
# owner's filed sources. ``level`` stops a corrupt cycle; only the owner's own
# folders of type ``source`` count.
_EXPAND_SQL = """
    WITH RECURSIVE tree(root, id, owner, level) AS (
        SELECT f.id, f.id, f.user_id, 1 FROM folders f
        WHERE f.id = ANY(CAST(:ids AS uuid[])) AND f.resource_type = 'source'
        UNION
        SELECT t.root, c.id, t.owner, t.level + 1
        FROM folders c JOIN tree t ON c.parent_id = t.id
        WHERE c.user_id = t.owner AND c.resource_type = 'source' AND t.level < 64
    )
    SELECT t.root::text, t.owner, s.id::text, s.user_id, min(t.level) AS depth, lower(s.name) AS sort_name
    FROM tree t
    JOIN folder_items fi
      ON fi.folder_id = t.id AND fi.user_id = t.owner AND fi.resource_type = 'source'
    JOIN sources s ON s.id = fi.resource_id
    GROUP BY t.root, t.owner, s.id, s.user_id, s.name
    ORDER BY t.root, depth, sort_name, s.id
"""

_FOLDERS_SQL = """
    SELECT id::text, name, user_id FROM folders
    WHERE id = ANY(CAST(:ids AS uuid[])) AND resource_type = 'source'
"""


class FolderRefError(ValueError):
    """A request's folder list that can't be read (400)."""


def parse_folder_refs(raw: Any) -> list[str]:
    """The folder ids a request names, lower-case, each once, in order.

    Args:
        raw: The request's ``folders`` (or ``active_folders``) value: a list of
            folder ids. ``None`` and ``""`` mean none.

    Returns:
        list[str]: The ids.

    Raises:
        FolderRefError: When it isn't a list, or an entry isn't a folder id.
    """
    if raw is None or raw == "":
        return []
    if not isinstance(raw, list):
        raise FolderRefError("Folders must be a list")
    out: list[str] = []
    for item in raw:
        value = str(item).strip() if isinstance(item, str) else ""
        if not looks_like_uuid(value):
            raise FolderRefError(f"Invalid folder ID in list: {item}")
        value = value.lower()
        if value not in out:
            out.append(value)
    return out


def _ids(folder_ids: Optional[Iterable[Any]]) -> list[str]:
    """Lower-case UUIDs, each once, in order; anything else dropped."""
    out: list[str] = []
    for fid in folder_ids or []:
        value = str(fid).strip().lower() if fid else ""
        if looks_like_uuid(value) and value not in out:
            out.append(value)
    return out


def owned_source_folders(conn: Connection, folder_ids: Iterable[Any], user: Optional[str]) -> list[str]:
    """The ids among ``folder_ids`` that are ``user``'s own source folders, in order.

    Args:
        conn: Open connection.
        folder_ids: Folder ids.
        user: The would-be owner.

    Returns:
        list[str]: Lower-case ids.
    """
    ids = _ids(folder_ids)
    if not ids or not user:
        return []
    rows = conn.execute(text(_FOLDERS_SQL), {"ids": ids}).fetchall()
    owned = {r[0].lower() for r in rows if r[2] == user}
    return [fid for fid in ids if fid in owned]


def unattachable_folder(
    conn: Connection, folder_ids: Iterable[Any], caller: Optional[str], existing: Iterable[Any] = ()
) -> Optional[str]:
    """The first folder ``caller`` newly attaches but may not, or ``None``.

    A folder is attached by its owner only (the caller's own source folder).
    Folders already on the holder (``existing``) stay whoever saves it.

    Args:
        conn: Open connection.
        folder_ids: The holder's folders after the save.
        caller: The user saving.
        existing: The holder's folders before the save.

    Returns:
        Optional[str]: The refused folder id.
    """
    before = set(_ids(existing))
    new = [fid for fid in _ids(folder_ids) if fid not in before]
    if not new:
        return None
    owned = set(owned_source_folders(conn, new, caller))
    for fid in new:
        if fid not in owned:
            return fid
    return None


def _expand(
    conn: Connection,
    folder_ids: Optional[Iterable[Any]],
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Each existing folder's sources, and why each stopped folder feeds none.

    Returns:
        tuple: ``(folder_id -> [source_id], folder_id -> reason)``.
    """
    ids = _ids(folder_ids)
    if not ids:
        return {}, {}
    owners = {r[0].lower(): r[2] for r in conn.execute(text(_FOLDERS_SQL), {"ids": ids}).fetchall()}
    out: dict[str, list[str]] = {fid: [] for fid in ids if fid in owners}
    holder_owner = (holder or {}).get("user_id") if holder_type else None
    stopped: dict[str, str] = {}
    if holder_owner:
        editors: dict[str, bool] = {}
        for fid, owner in owners.items():
            if owner == holder_owner:
                continue
            if owner not in editors:
                editors[owner] = holder_editable_by(conn, holder_type, holder, owner)
            if not editors[owner]:
                stopped[fid] = REASON_CANNOT_EDIT_HOLDER
    usable: dict[tuple[str, str], bool] = {}

    def _feeds(owner: str, source_id: str, source_owner: str) -> bool:
        if not (source_owner == owner or can_use_ref(conn, "source", source_id, owner)):
            return False
        if not holder_owner or owner == holder_owner:
            return True
        # A teammate's folder extends their sources to the owner's holder: like a sponsor.
        return can_use_ref(conn, "source", source_id, holder_owner) or can_sponsor_ref(
            conn, "source", source_id, owner
        )

    for root, owner, source_id, source_owner, _level, _name in conn.execute(text(_EXPAND_SQL), {"ids": ids}):
        root, source_id = root.lower(), source_id.lower()
        if root in stopped:
            continue
        key = (owner, source_id)
        if key not in usable:
            usable[key] = _feeds(owner, source_id, source_owner)
        bucket = out.setdefault(root, [])
        if usable[key] and source_id not in bucket:
            bucket.append(source_id)
    return out, stopped


def expand_folders(
    conn: Connection,
    folder_ids: Optional[Iterable[Any]],
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
) -> dict[str, list[str]]:
    """Each existing source folder's sources: its owner's filings across its subtree, usable by the owner.

    Args:
        conn: Open connection.
        folder_ids: Folder ids; ones that don't exist (or aren't source folders) are left out.
        holder_type: ``agent`` or ``workflow`` when a holder reads them; None for the folder owner's own
            chat (no holder rules).
        holder: The holder row (its ``user_id`` is the holder's owner).

    Returns:
        dict[str, list[str]]: ``folder_id -> [source_id, ...]`` (lower-case), in
        folder order, shallower filings first, then by source name. A stopped
        teammate's folder maps to ``[]``.
    """
    return _expand(conn, folder_ids, holder_type, holder)[0]


def folder_source_ids(
    conn: Connection,
    folder_ids: Optional[Iterable[Any]],
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
) -> list[str]:
    """Every source the folders feed (see :func:`expand_folders`), each once, in folder order.

    Args:
        conn: Open connection.
        folder_ids: Folder ids.
        holder_type: ``agent`` or ``workflow`` when a holder reads them.
        holder: The holder row.

    Returns:
        list[str]: Lower-case source ids.
    """
    out: list[str] = []
    seen: set[str] = set()
    for sources in expand_folders(conn, folder_ids, holder_type, holder).values():
        for sid in sources:
            if sid not in seen:
                seen.add(sid)
                out.append(sid)
    return out


def caller_folder_source_ids(conn: Connection, folder_ids: Optional[Iterable[Any]], user: Optional[str]) -> list[str]:
    """The sources of the caller's own folders among ``folder_ids``; others' folders add nothing.

    Args:
        conn: Open connection.
        folder_ids: The request's folder ids.
        user: The caller.

    Returns:
        list[str]: Lower-case source ids, each once.
    """
    return folder_source_ids(conn, owned_source_folders(conn, folder_ids, user))


def folder_details(
    conn: Connection,
    folder_ids: Optional[Iterable[Any]],
    viewer: Optional[str],
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
) -> list[dict]:
    """``[{id, name, owner_id?, owner_name?, source_count, stopped?, reason?}]`` for a holder's folders, in order.

    Looked up whoever owns them, so an editor sees (and may remove) a teammate's
    folder. ``owner_id`` and ``owner_name`` name an owner other than ``viewer``
    the way the sponsor list does (``resource_access.person_labels``): only
    someone the reader knows, by their email when on file, else their user id. ``source_count`` counts what the folder
    feeds the holder. A folder that feeds nothing because it is gone, or its
    owner no longer edits the holder, reads ``stopped: True`` with a
    ``reason`` (``deleted`` or ``sponsor_cannot_edit_agent``, as in
    ``resource_states``); a gone one also reads ``name: None``.

    Args:
        conn: Open connection.
        folder_ids: The folder ids.
        viewer: Who reads them.
        holder_type: ``agent`` or ``workflow`` when the folders sit on a holder.
        holder: The holder row.

    Returns:
        list[dict]: One entry per id.
    """
    ids = _ids(folder_ids)
    if not ids:
        return []
    rows = {r[0].lower(): (r[1], r[2]) for r in conn.execute(text(_FOLDERS_SQL), {"ids": ids}).fetchall()}
    expanded, stopped = _expand(conn, ids, holder_type, holder)
    labels = person_labels(conn, viewer, holder, [owner for _, owner in rows.values() if owner != viewer])
    out = []
    for fid in ids:
        name, owner = rows.get(fid, (None, None))
        entry: dict[str, Any] = {"id": fid, "name": name, "source_count": len(expanded.get(fid, []))}
        if owner and owner != viewer and owner in labels:
            entry["owner_id"] = owner
            entry["owner_name"] = labels[owner]
        reason = REASON_DELETED if fid not in rows else stopped.get(fid)
        if reason:
            entry["stopped"] = True
            entry["reason"] = reason
        out.append(entry)
    return out


def resolve_folder_details(
    folder_ids: Optional[Iterable[Any]],
    viewer: Optional[str],
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
) -> list[dict]:
    """:func:`folder_details` on its own read connection (for response shaping).

    Args:
        folder_ids: The folder ids.
        viewer: Who reads them.
        holder_type: ``agent`` or ``workflow`` when the folders sit on a holder.
        holder: The holder row.

    Returns:
        list[dict]: One entry per id.
    """
    if not _ids(folder_ids):
        return []
    with db_readonly() as conn:
        return folder_details(conn, folder_ids, viewer, holder_type, holder)
