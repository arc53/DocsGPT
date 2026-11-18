"""Live knowledge folders: a source folder an agent, a workflow step or a chat reads as a whole.

An agent (``agents.knowledge_folder_ids``), a workflow agent node
(``config.folders``) or an agentless chat request (``active_folders``) may name
source folders instead of, or next to, single sources. A folder stays live: a
source filed into it later reaches every holder at its next run.

A folder reads as its tree's owner's: the sources filed anywhere in its
subtree of that tree, each one the owner may still use
(:func:`docsgpt.api.user.resource_access.can_use_ref`). A folder that no longer
exists adds nothing. A person's folder is attached only by that person; one
already attached stays when someone else saves the holder.

A team's agent or workflow reads the team's one tree: any of the team's
folders is attachable by an Editor, and it feeds every team source any Editor
filed there (a filing in a team's tree is the team principal's, whoever made
it). Nothing is confirmed there, since nothing runs as a person; a source
that isn't the team's feeds nothing even when filed there.

A holder that people outside its shares reach (an API key, a public link or a
webhook) reads no *borrowed* source through a folder: one its owner doesn't
own and uses only through a grant. Attaching such a folder is refused at save,
but a borrowed source filed into an attached folder later would otherwise
reach the key at the next run. The publish check itself still sees them
(``keep_borrowed``).

On a personal agent or workflow owned by someone else (a teammate attached their own
folder), the folder's owner stands in like a sponsor: it feeds a source only
when the holder's owner may use it or the folder's owner may sponsor it
(``can_sponsor_ref``: owns or edits it), and nothing at all once the folder's
owner can no longer edit the holder (``sponsor_cannot_edit_agent``). So
attaching one asks first, like a sponsored source: the save is refused (409)
until ``confirm_sponsor`` lists ``folder:<id>`` (:func:`plan_folder_confirmations`).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from sqlalchemy import Connection, text

from docsgpt.api.user.resource_access import (
    REASON_CANNOT_EDIT_HOLDER,
    REASON_DELETED,
    SponsorPlan,
    can_sponsor_ref,
    can_use_ref,
    holder_editable_by,
    holder_has_outside_access,
    person_labels,
)
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.session import db_readonly
from docsgpt.workspaces.principal import is_principal_id

#: The 403 error code of a folder the caller may not attach.
FOLDER_NOT_ACCESSIBLE = "folder_not_accessible"

#: The ``confirm_sponsor`` key type of a knowledge folder (``folder:<id>``).
FOLDER_KEY_TYPE = "folder"

# Each requested folder (``root``) and every folder under it, with the sources
# filed in its owner's tree (a team's principal for a team folder). ``level``
# stops a corrupt cycle; only folders of the same tree count (a folder holds
# every kind; its sources are what an agent reads).
_EXPAND_SQL = """
    WITH RECURSIVE tree(root, id, owner, level) AS (
        SELECT f.id, f.id, f.user_id, 1 FROM folders f
        WHERE f.id = ANY(CAST(:ids AS uuid[]))
        UNION
        SELECT t.root, c.id, t.owner, t.level + 1
        FROM folders c JOIN tree t ON c.parent_id = t.id
        WHERE c.user_id = t.owner AND t.level < 64
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
    WHERE id = ANY(CAST(:ids AS uuid[]))
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


def holder_owned_folders(conn: Connection, folder_ids: Iterable[Any], holder_owner: Optional[str]) -> list[str]:
    """The ids among ``folder_ids`` in the holder owner's own tree, in order: the attach rule of a team holder.

    A team's agent or workflow reads the team's one folder tree, so a folder
    is attachable when the team's principal owns it, whoever files into it.
    The route has already checked the caller is an Editor or above there.

    Args:
        conn: Open connection.
        folder_ids: Folder ids.
        holder_owner: The holder's owner (a team's principal).

    Returns:
        list[str]: Lower-case ids.
    """
    return owned_source_folders(conn, folder_ids, holder_owner)


def unattachable_folder(
    conn: Connection,
    folder_ids: Iterable[Any],
    caller: Optional[str],
    existing: Iterable[Any] = (),
    *,
    holder_owner: Optional[str] = None,
) -> Optional[str]:
    """The first folder ``caller`` newly attaches but may not, or ``None``.

    A folder is attached by its owner only (the caller's own source folder).
    On a team holder it must be the team's own folder instead
    (:func:`holder_owned_folders`). Folders already on the holder
    (``existing``) stay whoever saves it.

    Args:
        conn: Open connection.
        folder_ids: The holder's folders after the save.
        caller: The user saving.
        existing: The holder's folders before the save.
        holder_owner: The holder's owner; a team's principal switches to the team rule.

    Returns:
        Optional[str]: The refused folder id.
    """
    before = set(_ids(existing))
    new = [fid for fid in _ids(folder_ids) if fid not in before]
    if not new:
        return None
    if is_principal_id(holder_owner):
        owned = set(holder_owned_folders(conn, new, holder_owner))
    else:
        owned = set(owned_source_folders(conn, new, caller))
    for fid in new:
        if fid not in owned:
            return fid
    return None


def folder_confirmations(raw: Any) -> set[str]:
    """The folder ids a request's ``confirm_sponsor`` confirms (its ``folder:<id>`` keys).

    Takes the shapes ``parse_confirmations`` takes (a list, a JSON-encoded
    list, a comma-separated string); every other key is left to it, and it
    drops these, so a folder key never reads as an unexpected sponsor.

    Args:
        raw: The request's ``confirm_sponsor`` value, or None.

    Returns:
        set[str]: Lower-case folder ids.
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
        key_type, _, folder_id = str(item).strip().partition(":")
        if key_type == FOLDER_KEY_TYPE:
            out.update(_ids([folder_id]))
    return out


def plan_folder_confirmations(
    plan: SponsorPlan,
    owner_id: Optional[str],
    caller: Optional[str],
    folder_ids: Optional[Iterable[Any]],
    previous: Optional[Iterable[Any]] = (),
    confirmed: Iterable[str] = (),
) -> SponsorPlan:
    """Add the folders a save would newly run as ``caller`` to ``plan.needs_confirmation``.

    A folder attached to someone else's agent or workflow feeds it its
    owner's sources, ones filed there later too, so like a sponsored source
    it waits for the caller's confirmation: ``("folder", id)`` lands in
    ``needs_confirmation`` until ``confirmed`` lists it, and
    ``sponsor_refusal`` then answers 409 naming it. Nothing is stored for a
    confirmed folder: it runs as its owner (see :func:`expand_folders`).
    Folders already on the holder, and the holder owner's own saves, never ask.
    Call it after :func:`unattachable_folder` passed (every new folder is the
    caller's own).

    Args:
        plan: The holder's sponsor plan; extended in place.
        owner_id: The holder's owner.
        caller: The user saving.
        folder_ids: The holder's folders after the save.
        previous: Its folders before the save.
        confirmed: Folder ids from :func:`folder_confirmations`.

    Returns:
        SponsorPlan: ``plan``.
    """
    if not caller or caller == owner_id or is_principal_id(owner_id):
        # A team holder reads only the team's own folders: nothing runs as the caller.
        return plan
    before = set(_ids(previous))
    confirmed = set(confirmed)
    for fid in _ids(folder_ids):
        if fid not in before and fid not in confirmed:
            plan.needs_confirmation.append((FOLDER_KEY_TYPE, fid))
    return plan


def _expand(
    conn: Connection,
    folder_ids: Optional[Iterable[Any]],
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
    *,
    keep_borrowed: bool = False,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Each existing folder's sources, and why each stopped folder feeds none.

    Args:
        conn: Open connection.
        folder_ids: Folder ids.
        holder_type: ``agent`` or ``workflow`` when a holder reads them.
        holder: The holder row.
        keep_borrowed: Keep the sources the holder's owner only borrows even
            when the holder has outside access (the publish check lists them).

    Returns:
        tuple: ``(folder_id -> [source_id], folder_id -> reason)``.
    """
    ids = _ids(folder_ids)
    if not ids:
        return {}, {}
    owners, filings = _load_folders(conn, ids)
    return _judge(conn, ids, owners, filings, holder_type, holder, keep_borrowed=keep_borrowed)


def _load_folders(conn: Connection, ids: list[str]) -> tuple[dict[str, str], list[tuple]]:
    """Who owns each folder, and the sources filed across each one's subtree, in two queries for all of them.

    Args:
        conn: Open connection.
        ids: Lower-case folder ids (from :func:`_ids`).

    Returns:
        tuple: ``(folder_id -> owner, filings)``; each filing is ``(root, owner, source_id,
        source_owner, depth, sort_name)``, every root's in folder order.
    """
    owners = {r[0].lower(): r[2] for r in conn.execute(text(_FOLDERS_SQL), {"ids": ids}).fetchall()}
    return owners, [tuple(row) for row in conn.execute(text(_EXPAND_SQL), {"ids": ids})]


def _judge(
    conn: Connection,
    ids: list[str],
    owners: dict[str, str],
    filings: Iterable[tuple],
    holder_type: Optional[str],
    holder: Optional[dict],
    *,
    keep_borrowed: bool = False,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """What :func:`_expand` returns, from folders already loaded by :func:`_load_folders`.

    Args:
        conn: Open connection (the feed checks still read access).
        ids: The holder's lower-case folder ids.
        owners: ``folder_id -> owner`` for those of ``ids`` that exist, and no other folder.
        filings: The filings of those folders' subtrees, in folder order; filings of other roots are skipped.
        holder_type: ``agent`` or ``workflow`` when a holder reads them.
        holder: The holder row.
        keep_borrowed: See :func:`_expand`.

    Returns:
        tuple: ``(folder_id -> [source_id], folder_id -> reason)``.
    """
    wanted = set(ids)
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
    outside: list[bool] = []

    def _borrowed(source_id: str) -> bool:
        # Read the holder's access lazily: only a source someone else owns can be borrowed.
        if not outside:
            outside.append(not keep_borrowed and holder_has_outside_access(conn, holder_type, holder))
        return outside[0] and can_use_ref(conn, "source", source_id, holder_owner)

    def _feeds(owner: str, source_id: str, source_owner: str) -> bool:
        if not (source_owner == owner or can_use_ref(conn, "source", source_id, owner)):
            return False
        if holder_owner and source_owner != holder_owner and _borrowed(source_id):
            return False
        if not holder_owner or owner == holder_owner:
            return True
        # A teammate's folder extends their sources to the owner's holder: like a sponsor.
        return can_use_ref(conn, "source", source_id, holder_owner) or can_sponsor_ref(
            conn, "source", source_id, owner
        )

    for root, owner, source_id, source_owner, _level, _name in filings:
        root, source_id = root.lower(), source_id.lower()
        if root in stopped or root not in wanted:
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
    *,
    keep_borrowed: bool = False,
) -> dict[str, list[str]]:
    """Each existing source folder's sources: its owner's filings across its subtree, usable by the owner.

    A holder with outside access gets none its owner only borrows, unless
    ``keep_borrowed``.

    Args:
        conn: Open connection.
        folder_ids: Folder ids; ones that don't exist (or aren't source folders) are left out.
        holder_type: ``agent`` or ``workflow`` when a holder reads them; None for the folder owner's own
            chat (no holder rules).
        holder: The holder row (its ``user_id`` is the holder's owner).
        keep_borrowed: Keep borrowed sources whatever the holder's access (for the publish check).

    Returns:
        dict[str, list[str]]: ``folder_id -> [source_id, ...]`` (lower-case), in
        folder order, shallower filings first, then by source name. A stopped
        teammate's folder maps to ``[]``.
    """
    return _expand(conn, folder_ids, holder_type, holder, keep_borrowed=keep_borrowed)[0]


def expand_folders_of_holders(
    conn: Connection, holders: list[tuple[str, dict, Iterable[Any]]]
) -> list[dict[str, list[str]]]:
    """:func:`expand_folders` for several holders at once: every folder and its filings are read once.

    Each holder's answer is the one ``expand_folders(conn, folder_ids, holder_type, holder)`` gives; only
    the loading is shared, the holder rules are still applied holder by holder.

    Args:
        conn: Open connection.
        holders: ``(holder_type, holder row, folder ids)`` per holder.

    Returns:
        list[dict[str, list[str]]]: One ``folder_id -> [source_id, ...]`` per holder, in order.
    """
    per_holder = [_ids(folder_ids) for _type, _holder, folder_ids in holders]
    every = _ids(fid for ids in per_holder for fid in ids)
    if not every:
        return [{} for _ in holders]
    owners, filings = _load_folders(conn, every)
    out = []
    for (holder_type, holder, _folder_ids), ids in zip(holders, per_holder):
        if not ids:
            out.append({})
            continue
        wanted = set(ids)
        mine = {fid: owner for fid, owner in owners.items() if fid in wanted}
        out.append(_judge(conn, ids, mine, filings, holder_type, holder)[0])
    return out


def folder_source_ids(
    conn: Connection,
    folder_ids: Optional[Iterable[Any]],
    holder_type: Optional[str] = None,
    holder: Optional[dict] = None,
    *,
    keep_borrowed: bool = False,
) -> list[str]:
    """Every source the folders feed (see :func:`expand_folders`), each once, in folder order.

    Args:
        conn: Open connection.
        folder_ids: Folder ids.
        holder_type: ``agent`` or ``workflow`` when a holder reads them.
        holder: The holder row.
        keep_borrowed: Keep borrowed sources whatever the holder's access (for the publish check).

    Returns:
        list[str]: Lower-case source ids.
    """
    out: list[str] = []
    seen: set[str] = set()
    for sources in expand_folders(conn, folder_ids, holder_type, holder, keep_borrowed=keep_borrowed).values():
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
    # A team holder's own folder is the team's tree, not someone else's: it names no owner.
    team_owner = (holder or {}).get("user_id") if is_principal_id((holder or {}).get("user_id")) else None
    labels = person_labels(
        conn, viewer, holder, [owner for _, owner in rows.values() if owner not in (viewer, team_owner)]
    )
    out = []
    for fid in ids:
        name, owner = rows.get(fid, (None, None))
        entry: dict[str, Any] = {"id": fid, "name": name, "source_count": len(expanded.get(fid, []))}
        if owner and owner not in (viewer, team_owner) and owner in labels:
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
