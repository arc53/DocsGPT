"""Repositories for the ``folders`` and ``folder_items`` tables (migration 0063).

A folder belongs to one user and holds one ``resource_type`` (``agent`` or
``source``). Folders nest through ``parent_id``; the self-FK is
``ON DELETE SET NULL``, but the folder service moves a deleted folder's
children and items to its parent first (``FoldersRepository.delete_into_parent``).

``folder_items`` is personal filing: a user files an item they can see into
one of their own folders of the same type, at most once per item. Filing
never touches the item's own row. A deleted agent or source loses its filings
through the ``*_cleanup_folder_items`` triggers.

The repositories trust their callers on access: the folder service checks
that the item is visible and that the folder is the caller's, of the item's type.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlalchemy import Connection, func, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.models import folders_table

#: The kinds of item a folder can hold.
FOLDER_RESOURCE_TYPES = ("agent", "source")

_ALLOWED_UPDATE_COLUMNS = {"name", "description", "parent_id"}

# The ancestor chain of one folder, nearest first; ``depth`` stops a corrupt cycle.
_ANCESTORS_SQL = """
    WITH RECURSIVE chain(id, parent_id, depth) AS (
        SELECT id, parent_id, 1 FROM folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id
        UNION ALL
        SELECT f.id, f.parent_id, c.depth + 1
        FROM folders f JOIN chain c ON f.id = c.parent_id
        WHERE f.user_id = :user_id AND c.depth < 64
    )
    SELECT id::text, depth FROM chain ORDER BY depth
"""

# One folder and everything under it, with each folder's level below it (the folder itself is 1).
_SUBTREE_SQL = """
    WITH RECURSIVE tree(id, level) AS (
        SELECT id, 1 FROM folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id
        UNION
        SELECT f.id, t.level + 1
        FROM folders f JOIN tree t ON f.parent_id = t.id
        WHERE f.user_id = :user_id AND t.level < 64
    )
    SELECT id::text, max(level) AS level FROM tree GROUP BY id
"""


class FoldersRepository:
    """The ``folders`` table: one user's folders of one type."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        name: str,
        *,
        resource_type: str = "agent",
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        """Insert a folder.

        Args:
            user_id: Its owner.
            name: Its name, already validated.
            resource_type: ``agent`` or ``source``.
            description: Optional description (agent folders of old).
            parent_id: The parent folder, already checked to be the owner's, of the same type.
            legacy_mongo_id: The Mongo ObjectId of a backfilled folder.

        Returns:
            dict: The new row.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO folders (user_id, name, description, parent_id, legacy_mongo_id, resource_type)
                VALUES (:user_id, :name, :description, CAST(:parent_id AS uuid), :legacy_mongo_id, :resource_type)
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "name": name,
                "description": description,
                "parent_id": str(parent_id) if parent_id else None,
                "legacy_mongo_id": legacy_mongo_id,
                "resource_type": resource_type,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, folder_id: str, user_id: str, resource_type: Optional[str] = None) -> Optional[dict]:
        """The user's folder by id (``None`` when it isn't theirs, or of another type)."""
        if not looks_like_uuid(str(folder_id or "")):
            return None
        sql = "SELECT * FROM folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
        params: dict[str, Any] = {"id": str(folder_id), "user_id": user_id}
        if resource_type is not None:
            sql += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type
        row = self._conn.execute(text(sql), params).fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: Optional[str] = None, resource_type: Optional[str] = None
    ) -> Optional[dict]:
        """A backfilled folder by its Mongo ObjectId, optionally scoped to its owner and type."""
        sql = "SELECT * FROM folders WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, Any] = {"legacy_id": str(legacy_mongo_id)}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        if resource_type is not None:
            sql += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type
        row = self._conn.execute(text(sql), params).fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str, resource_type: Optional[str] = "agent") -> list[dict]:
        """Every folder the user has of one type (all types for ``None``), oldest first."""
        sql = "SELECT * FROM folders WHERE user_id = :user_id"
        params: dict[str, Any] = {"user_id": user_id}
        if resource_type is not None:
            sql += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type
        result = self._conn.execute(text(sql + " ORDER BY created_at, id"), params)
        return [row_to_dict(r) for r in result.fetchall()]

    def list_children(self, parent_id: str, user_id: str) -> list[dict]:
        """The immediate children of ``parent_id``, oldest first."""
        result = self._conn.execute(
            text(
                "SELECT * FROM folders WHERE parent_id = CAST(:parent_id AS uuid) AND user_id = :user_id "
                "ORDER BY created_at, id"
            ),
            {"parent_id": parent_id, "user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def sibling_named(
        self,
        user_id: str,
        resource_type: str,
        parent_id: Optional[str],
        name: str,
        exclude_id: Optional[str] = None,
    ) -> Optional[dict]:
        """A folder under ``parent_id`` (top level for ``None``) whose name matches ``name`` ignoring case."""
        row = self._conn.execute(
            text(
                """
                SELECT * FROM folders
                WHERE user_id = :user_id AND resource_type = :resource_type
                  AND parent_id IS NOT DISTINCT FROM CAST(:parent_id AS uuid)
                  AND lower(name) = lower(:name)
                  AND (CAST(:exclude_id AS uuid) IS NULL OR id <> CAST(:exclude_id AS uuid))
                LIMIT 1
                """
            ),
            {
                "user_id": user_id,
                "resource_type": resource_type,
                "parent_id": str(parent_id) if parent_id else None,
                "name": name,
                "exclude_id": str(exclude_id) if exclude_id else None,
            },
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def ancestors(self, folder_id: str, user_id: str) -> list[str]:
        """The folder's id and its ancestors' ids, nearest first (its depth is the length)."""
        rows = self._conn.execute(text(_ANCESTORS_SQL), {"id": str(folder_id), "user_id": user_id}).fetchall()
        return [r[0] for r in rows]

    def subtree_levels(self, folder_id: str, user_id: str) -> dict[str, int]:
        """The folder and every folder under it, each with its level below it (the folder itself is 1)."""
        rows = self._conn.execute(text(_SUBTREE_SQL), {"id": str(folder_id), "user_id": user_id}).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def update(self, folder_id: str, user_id: str, fields: dict[str, Any]) -> bool:
        """Partial update of ``name``, ``description`` and ``parent_id``; the service validates them."""
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATE_COLUMNS}
        if not filtered:
            return False
        values: dict = {}
        for col, val in filtered.items():
            values[col] = (str(val) if val else None) if col == "parent_id" else val
        values["updated_at"] = func.now()
        t = folders_table
        stmt = t.update().where(t.c.id == folder_id).where(t.c.user_id == user_id).values(**values)
        return self._conn.execute(stmt).rowcount > 0

    def delete_into_parent(self, folder: dict) -> dict[str, int]:
        """Delete a folder after moving its child folders and items to its parent.

        With no parent, the children become top-level folders and the items
        are unfiled.

        Args:
            folder: The folder row (its owner's).

        Returns:
            dict: ``{"moved_items": n, "moved_folders": n}``.
        """
        params = {
            "id": str(folder["id"]),
            "user_id": folder["user_id"],
            "parent_id": str(folder["parent_id"]) if folder.get("parent_id") else None,
        }
        moved_folders = self._conn.execute(
            text(
                "UPDATE folders SET parent_id = CAST(:parent_id AS uuid), updated_at = now() "
                "WHERE parent_id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            params,
        ).rowcount
        if params["parent_id"]:
            moved_items = self._conn.execute(
                text(
                    "UPDATE folder_items SET folder_id = CAST(:parent_id AS uuid) "
                    "WHERE folder_id = CAST(:id AS uuid)"
                ),
                params,
            ).rowcount
        else:
            moved_items = self._conn.execute(
                text("DELETE FROM folder_items WHERE folder_id = CAST(:id AS uuid)"), params
            ).rowcount
        self._conn.execute(
            text("DELETE FROM folders WHERE id = CAST(:id AS uuid) AND user_id = :user_id"), params
        )
        return {"moved_items": moved_items, "moved_folders": moved_folders}


class FolderItemsRepository:
    """The ``folder_items`` table: which of a user's folders holds each item they filed."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def file(self, user_id: str, resource_type: str, resource_id: str, folder_id: Optional[str]) -> None:
        """File an item into ``folder_id``, or unfile it with ``None``. Replaces the user's previous filing."""
        params = {
            "user_id": user_id,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "folder_id": str(folder_id) if folder_id else None,
        }
        if folder_id is None:
            self._conn.execute(
                text(
                    "DELETE FROM folder_items WHERE user_id = :user_id AND resource_type = :resource_type "
                    "AND resource_id = CAST(:resource_id AS uuid)"
                ),
                params,
            )
            return
        self._conn.execute(
            text(
                """
                INSERT INTO folder_items (user_id, resource_type, resource_id, folder_id)
                VALUES (:user_id, :resource_type, CAST(:resource_id AS uuid), CAST(:folder_id AS uuid))
                ON CONFLICT (user_id, resource_type, resource_id)
                DO UPDATE SET folder_id = EXCLUDED.folder_id, created_at = now()
                WHERE folder_items.folder_id IS DISTINCT FROM EXCLUDED.folder_id
                """
            ),
            params,
        )

    def filings(
        self, user_id: str, resource_type: str, resource_ids: Optional[Iterable[str]] = None
    ) -> dict[str, str]:
        """``resource_id -> folder_id`` for the user's filings of one type (all of them for ``None``)."""
        sql = (
            "SELECT resource_id::text, folder_id::text FROM folder_items "
            "WHERE user_id = :user_id AND resource_type = :resource_type"
        )
        params: dict[str, Any] = {"user_id": user_id, "resource_type": resource_type}
        if resource_ids is not None:
            ids = [str(r).lower() for r in resource_ids if looks_like_uuid(str(r))]
            if not ids:
                return {}
            sql += " AND resource_id = ANY(CAST(:ids AS uuid[]))"
            params["ids"] = ids
        return {r[0]: r[1] for r in self._conn.execute(text(sql), params).fetchall()}

    def filing(self, user_id: str, resource_type: str, resource_id: Optional[str]) -> Optional[str]:
        """The folder the user filed one item into, or ``None``."""
        if not resource_id:
            return None
        return self.filings(user_id, resource_type, [str(resource_id)]).get(str(resource_id).lower())

    def resource_ids_in(self, user_id: str, folder_ids: Iterable[str]) -> list[str]:
        """The ids of the items the user filed into any of ``folder_ids``."""
        ids = [str(f) for f in folder_ids if looks_like_uuid(str(f))]
        if not ids:
            return []
        rows = self._conn.execute(
            text(
                "SELECT resource_id::text FROM folder_items "
                "WHERE user_id = :user_id AND folder_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"user_id": user_id, "ids": ids},
        ).fetchall()
        return [r[0] for r in rows]
