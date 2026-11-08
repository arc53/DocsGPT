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
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlalchemy import Connection, text

from docsgpt.api.user.resource_access import can_use_ref
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


def expand_folders(conn: Connection, folder_ids: Optional[Iterable[Any]]) -> dict[str, list[str]]:
    """Each existing source folder's sources: its owner's filings across its subtree, usable by the owner.

    Args:
        conn: Open connection.
        folder_ids: Folder ids; ones that don't exist (or aren't source folders) are left out.

    Returns:
        dict[str, list[str]]: ``folder_id -> [source_id, ...]`` (lower-case), in
        folder order, shallower filings first, then by source name.
    """
    ids = _ids(folder_ids)
    if not ids:
        return {}
    existing = {r[0].lower() for r in conn.execute(text(_FOLDERS_SQL), {"ids": ids}).fetchall()}
    out: dict[str, list[str]] = {fid: [] for fid in ids if fid in existing}
    usable: dict[tuple[str, str], bool] = {}
    for root, owner, source_id, source_owner, _level, _name in conn.execute(text(_EXPAND_SQL), {"ids": ids}):
        root, source_id = root.lower(), source_id.lower()
        key = (owner, source_id)
        if key not in usable:
            usable[key] = source_owner == owner or can_use_ref(conn, "source", source_id, owner)
        bucket = out.setdefault(root, [])
        if usable[key] and source_id not in bucket:
            bucket.append(source_id)
    return out


def folder_source_ids(conn: Connection, folder_ids: Optional[Iterable[Any]]) -> list[str]:
    """Every source the folders hold (see :func:`expand_folders`), each once, in folder order.

    Args:
        conn: Open connection.
        folder_ids: Folder ids.

    Returns:
        list[str]: Lower-case source ids.
    """
    out: list[str] = []
    seen: set[str] = set()
    for sources in expand_folders(conn, folder_ids).values():
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


def _owner_labels(conn: Connection, owners: Iterable[str]) -> dict[str, str]:
    ids = sorted({o for o in owners if o})
    if not ids:
        return {}
    rows = conn.execute(
        text("SELECT user_id, email FROM users WHERE user_id = ANY(:ids) AND email IS NOT NULL AND email <> ''"),
        {"ids": ids},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def folder_details(conn: Connection, folder_ids: Optional[Iterable[Any]], viewer: Optional[str]) -> list[dict]:
    """``[{id, name, owner_name?, source_count}]`` for a holder's folders, in order.

    Looked up whoever owns them, so an editor sees (and may remove) a teammate's
    folder. ``owner_name`` (the owner's email) is set when the owner is not
    ``viewer`` and has one on file. A folder that no longer exists reads
    ``name: None`` and ``source_count: 0``.

    Args:
        conn: Open connection.
        folder_ids: The folder ids.
        viewer: Who reads them.

    Returns:
        list[dict]: One entry per id.
    """
    ids = _ids(folder_ids)
    if not ids:
        return []
    rows = {r[0].lower(): (r[1], r[2]) for r in conn.execute(text(_FOLDERS_SQL), {"ids": ids}).fetchall()}
    expanded = expand_folders(conn, ids)
    labels = _owner_labels(conn, [owner for _, owner in rows.values() if owner != viewer])
    out = []
    for fid in ids:
        name, owner = rows.get(fid, (None, None))
        entry: dict[str, Any] = {"id": fid, "name": name, "source_count": len(expanded.get(fid, []))}
        if owner and owner != viewer and labels.get(owner):
            entry["owner_name"] = labels[owner]
        out.append(entry)
    return out


def resolve_folder_details(folder_ids: Optional[Iterable[Any]], viewer: Optional[str]) -> list[dict]:
    """:func:`folder_details` on its own read connection (for response shaping).

    Args:
        folder_ids: The folder ids.
        viewer: Who reads them.

    Returns:
        list[dict]: One entry per id.
    """
    if not _ids(folder_ids):
        return []
    with db_readonly() as conn:
        return folder_details(conn, folder_ids, viewer)
