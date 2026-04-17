"""Repository for the ``sources`` table."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, func, select, text

from application.storage.db.base_repository import looks_like_uuid, row_to_dict
from application.storage.db.models import sources_table


_SCALAR_COLUMNS = {
    "name", "type", "retriever", "sync_frequency", "tokens", "file_path",
    "language", "model", "date",
}
_JSONB_COLUMNS = {"metadata", "remote_data", "directory_structure", "file_name_map"}
_ALLOWED_COLUMNS = _SCALAR_COLUMNS | _JSONB_COLUMNS

# Whitelist for sort columns exposed via ``list_for_user``. Anything not in
# this set falls back to ``date`` so user-supplied sort params can't be
# interpolated into SQL unchecked.
_SORTABLE_COLUMNS = {"date", "name", "tokens", "type", "created_at", "updated_at"}


def _escape_like(pattern: str) -> str:
    """Escape wildcards so a user-supplied substring is matched literally.

    We use ``LIKE ESCAPE '\\'`` on the query side so backslash, percent, and
    underscore in the input don't accidentally turn into regex-like wildcards.
    """
    return (
        pattern
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _coerce_jsonb(value: Any) -> Any:
    """Normalize incoming JSONB values for the Core ``Table.update()`` path.

    ``remote_data`` in particular arrives as either a dict or a JSON string
    (the legacy Mongo docs stored both shapes). Strings are parsed so the
    stored representation is always structured JSONB; dicts/lists pass
    through untouched for the SQLAlchemy JSONB type processor.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return {"raw": value}
    return value


class SourcesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        name: str,
        *,
        source_id: Optional[str] = None,
        user_id: str,
        type: Optional[str] = None,
        metadata: Optional[dict] = None,
        retriever: Optional[str] = None,
        sync_frequency: Optional[str] = None,
        tokens: Optional[str] = None,
        file_path: Optional[str] = None,
        remote_data: Any = None,
        directory_structure: Any = None,
        file_name_map: Any = None,
        language: Optional[str] = None,
        model: Optional[str] = None,
        date: Any = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO sources (
                    id, user_id, name, type, metadata,
                    retriever, sync_frequency, tokens, file_path,
                    remote_data, directory_structure, file_name_map,
                    language, model, date, legacy_mongo_id
                )
                VALUES (
                    COALESCE(CAST(:source_id AS uuid), gen_random_uuid()),
                    :user_id, :name, :type, CAST(:metadata AS jsonb),
                    :retriever, :sync_frequency, :tokens, :file_path,
                    CAST(:remote_data AS jsonb),
                    CAST(:directory_structure AS jsonb),
                    CAST(:file_name_map AS jsonb),
                    :language, :model,
                    COALESCE(:date, now()),
                    :legacy_mongo_id
                )
                RETURNING *
                """
            ),
            {
                "source_id": source_id,
                "user_id": user_id,
                "name": name,
                "type": type,
                "metadata": json.dumps(metadata or {}),
                "retriever": retriever,
                "sync_frequency": sync_frequency,
                "tokens": tokens,
                "file_path": file_path,
                "remote_data": (
                    None if remote_data is None
                    else json.dumps(_coerce_jsonb(remote_data))
                ),
                "directory_structure": (
                    None if directory_structure is None
                    else json.dumps(_coerce_jsonb(directory_structure))
                ),
                "file_name_map": (
                    None if file_name_map is None
                    else json.dumps(_coerce_jsonb(file_name_map))
                ),
                "language": language,
                "model": model,
                "date": date,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, source_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM sources WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": source_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_any(self, source_id: str, user_id: str) -> Optional[dict]:
        """Resolve a source by either PG UUID or legacy Mongo ObjectId string.

        Cutover helper: URLs / bookmarks may still hold Mongo ObjectIds.
        Tries the UUID path first, then falls back to ``legacy_mongo_id``.
        Both paths are scoped by ``user_id``.
        """
        if looks_like_uuid(source_id):
            row = self.get(source_id, user_id)
            if row is not None:
                return row
        return self.get_by_legacy_id(source_id, user_id)

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        search_term: Optional[str] = None,
        sort_field: str = "created_at",
        sort_order: str = "desc",
    ) -> list[dict]:
        """Return sources owned by ``user_id``, paginated and optionally filtered.

        All pagination, filtering, and sorting are pushed into SQL so large
        accounts don't materialize their full source list in Python for every
        page. See ``PaginatedSources`` in the sources routes for the matching
        call site.

        Args:
            user_id: Scope rows to this owner.
            limit: Page size. ``None`` returns every matching row (legacy
                full-list path used by ``CombinedJson``).
            offset: Rows to skip before collecting ``limit`` results.
            search_term: Case-insensitive substring filter on ``name``.
                ``%`` and ``_`` in the input are escaped so they match
                literally rather than as LIKE wildcards.
            sort_field: Column to sort by. Unknown values fall back to
                ``date``. Resolved against ``sources_table.c`` so the
                column identity is bound by SQLAlchemy — user input never
                reaches the emitted SQL as a string.
            sort_order: ``"asc"`` or ``"desc"``; anything else is treated
                as ``"desc"``.

        Returns:
            A list of source rows as plain dicts (via ``row_to_dict``).
        """
        column_name = sort_field if sort_field in _SORTABLE_COLUMNS else "date"
        sort_column = sources_table.c[column_name]
        ascending = sort_order.lower() == "asc"

        stmt = select(sources_table).where(sources_table.c.user_id == user_id)
        if search_term:
            stmt = stmt.where(
                sources_table.c.name.ilike(
                    f"%{_escape_like(search_term)}%",
                    escape="\\",
                )
            )

        # ``id`` is appended as a stable tiebreaker so paginated windows
        # are deterministic across equal sort keys.
        id_column = sources_table.c.id
        if ascending:
            stmt = stmt.order_by(sort_column.asc(), id_column.asc())
        else:
            stmt = stmt.order_by(sort_column.desc(), id_column.desc())

        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)

        result = self._conn.execute(stmt)
        return [row_to_dict(r) for r in result.fetchall()]

    def count_for_user(
        self,
        user_id: str,
        *,
        search_term: Optional[str] = None,
    ) -> int:
        """Return the count of rows that ``list_for_user`` would produce.

        The filter mirrors ``list_for_user`` exactly so ``total`` and the
        paginated window stay consistent page-to-page.

        Args:
            user_id: Scope rows to this owner.
            search_term: Same substring filter semantics as
                ``list_for_user``; ``None``/empty disables the filter.

        Returns:
            The total number of matching rows.
        """
        stmt = (
            select(func.count())
            .select_from(sources_table)
            .where(sources_table.c.user_id == user_id)
        )
        if search_term:
            stmt = stmt.where(
                sources_table.c.name.ilike(
                    f"%{_escape_like(search_term)}%",
                    escape="\\",
                )
            )
        result = self._conn.execute(stmt)
        row = result.fetchone()
        return int(row[0]) if row is not None else 0

    def update(self, source_id: str, user_id: str, fields: dict) -> None:
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_COLUMNS}
        if not filtered:
            return

        values: dict = {}
        for col, val in filtered.items():
            values[col] = _coerce_jsonb(val) if col in _JSONB_COLUMNS else val
        values["updated_at"] = func.now()

        t = sources_table
        stmt = (
            t.update()
            .where(t.c.id == source_id)
            .where(t.c.user_id == user_id)
            .values(**values)
        )
        self._conn.execute(stmt)

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: Optional[str] = None,
    ) -> Optional[dict]:
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM sources WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def update_by_legacy_id(
        self, legacy_mongo_id: str, user_id: str, fields: dict,
    ) -> bool:
        """Update a source addressed by the Mongo ObjectId string.

        Used by dual_write call sites that hold the Mongo ``_id`` but
        haven't resolved the PG UUID yet. Returns ``True`` if a row was
        updated (i.e. the legacy id was found).
        """
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        row = self.get_by_legacy_id(legacy_mongo_id, user_id)
        if row is None:
            return False
        self.update(str(row["id"]), user_id, fields)
        return True

    def delete_by_legacy_id(self, legacy_mongo_id: str, user_id: str) -> bool:
        """Delete by Mongo ObjectId. Used by dual_write in DeleteOldIndexes."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        result = self._conn.execute(
            text(
                "DELETE FROM sources "
                "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
            ),
            {"legacy_id": legacy_mongo_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def delete(self, source_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM sources WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": source_id, "user_id": user_id},
        )
        return result.rowcount > 0
