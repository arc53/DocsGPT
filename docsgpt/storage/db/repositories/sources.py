"""Repository for the ``sources`` table."""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from sqlalchemy import and_, case, Connection, func, or_, select, text

from docsgpt.storage.db.base_repository import like_escape, looks_like_uuid, row_to_dict
from docsgpt.storage.db.models import ingest_chunk_progress_table, sources_table
from docsgpt.storage.db.source_config import SourceConfig


_SCALAR_COLUMNS = {
    "name", "type", "retriever", "sync_frequency", "tokens", "file_path",
    "language", "model", "date",
}
_JSONB_COLUMNS = {
    "metadata", "remote_data", "remote_files", "directory_structure", "file_name_map", "sync_manifest", "config",
}
_ALLOWED_COLUMNS = _SCALAR_COLUMNS | _JSONB_COLUMNS
# Every column a listing returns: all but the sync manifest (``remote_files``).
_LISTED_COLUMNS = tuple(column for column in sources_table.c if column.name != "remote_files")
# What a row read returns: every column but ``remote_files``, which runs to
# megabytes for a large selection and only a sync reads (``get_remote_files``).
_ROW_SELECT = "SELECT " + ", ".join(column.name for column in _LISTED_COLUMNS) + " FROM sources"

# Whitelist for sort columns exposed via ``list_for_user``. Anything not in
# this set falls back to ``date`` so user-supplied sort params can't be
# interpolated into SQL unchecked.
_SORTABLE_COLUMNS = {"date", "name", "tokens", "type", "created_at", "updated_at"}


def _coerce_uuid_ids(extra_ids: Optional[list]) -> list:
    """Coerce id strings to ``uuid.UUID`` for binding against UUID columns.

    Non-UUID-looking ids (e.g. legacy/synthetic) are dropped — they can never
    match a ``sources.id`` value. Used to OR team-shared source ids into the
    owner-scoped queries.
    """
    if not extra_ids:
        return []
    out: list = []
    for raw in extra_ids:
        s = str(raw)
        if looks_like_uuid(s):
            out.append(uuid.UUID(s))
    return out


# Prefix of a team principal's id (``docsgpt.workspaces.principal.PRINCIPAL_PREFIX``); matched with ``left``,
# since ``_`` is a LIKE wildcard.
_PRINCIPAL_PREFIX = "__team__"


def _owned_or_shared_scope(user_id: str, extra_ids: Optional[list], received_ids: Optional[list] = None):
    """WHERE predicate matching the owner's rows plus any ``extra_ids`` and ``received_ids``.

    Lets the paginated/count queries include team-shared sources (passed by id)
    alongside owned ones in a single query, so count/sort/search/pagination
    stay correct across the union. An extra id never brings in a row a team
    workspace owns: those are listed in their team, never by a grant (a stale
    grant row must not open one to a Personal list). ``received_ids`` are
    another team's sources that team shares with the team workspace being
    listed, already checked live by the caller; only teams' rows match them.
    """
    scope = sources_table.c.user_id == user_id
    is_team_row = func.left(sources_table.c.user_id, len(_PRINCIPAL_PREFIX)) == _PRINCIPAL_PREFIX
    ids = _coerce_uuid_ids(extra_ids)
    if ids:
        scope = or_(scope, and_(sources_table.c.id.in_(ids), ~is_team_row))
    received = _coerce_uuid_ids(received_ids)
    if received:
        scope = or_(scope, and_(sources_table.c.id.in_(received), is_team_row))
    return scope



def _name_search(search_term: Optional[str]):
    """The case-insensitive substring predicate on ``name``, or None for no search.

    ``%`` and ``_`` in the term are escaped so they match literally.
    """
    if not search_term:
        return None
    return sources_table.c.name.ilike(f"%{like_escape(search_term)}%", escape="\\")


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


def _normalize_config(config: Any) -> dict:
    """Strict-validate the write-path ``config`` and return a plain dict.

    ``None`` becomes ``{}`` (classic defaults). A dict is validated through
    ``SourceConfig`` (raises on bad input, D7 strict-on-write) and dumped
    back to a normalized dict for JSONB storage.
    """
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("config must be a dict")
    return SourceConfig.model_validate(config).model_dump()


def _ingest_status_case():
    """Derive a user-facing ingest status from the joined progress row.

    ``failed`` — reconciler-escalated stall. ``processing`` — embed in
    flight. ``None`` — no progress row, or the embed completed.
    """
    icp = ingest_chunk_progress_table
    return case(
        (icp.c.source_id.is_(None), None),
        (icp.c.status == "stalled", "failed"),
        (icp.c.embedded_chunks < icp.c.total_chunks, "processing"),
        else_=None,
    ).label("ingest_status")


class AllowlistFull(ValueError):
    """A source's prompt-injection allowlist already holds as many chunks as it may."""


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
        config: Optional[dict] = None,
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
        created_by: Optional[str] = None,
    ) -> dict:
        """Insert a source.

        ``created_by`` names the person who added it. Without it the
        ``fill_created_by`` trigger records the owner, except for a team
        principal owner, so a create in a team passes the uploader. A
        principal is never recorded as a creator.
        """
        if created_by is not None and str(created_by).startswith(_PRINCIPAL_PREFIX):
            created_by = None
        result = self._conn.execute(
            text(
                """
                INSERT INTO sources (
                    id, user_id, name, type, metadata, config,
                    retriever, sync_frequency, tokens, file_path,
                    remote_data, directory_structure, file_name_map,
                    language, model, date, legacy_mongo_id, created_by
                )
                VALUES (
                    COALESCE(CAST(:source_id AS uuid), gen_random_uuid()),
                    :user_id, :name, :type, CAST(:metadata AS jsonb),
                    CAST(:config AS jsonb),
                    :retriever, :sync_frequency, :tokens, :file_path,
                    CAST(:remote_data AS jsonb),
                    CAST(:directory_structure AS jsonb),
                    CAST(:file_name_map AS jsonb),
                    :language, :model,
                    COALESCE(:date, now()),
                    :legacy_mongo_id, :created_by
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
                "config": json.dumps(_normalize_config(config)),
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
                "created_by": created_by,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, source_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(_ROW_SELECT + " WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": source_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_for_update(self, source_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """Read a source and lock its row until the transaction ends.

        A read-modify-write of ``remote_data`` or ``directory_structure``
        (a Website page change, a sync's final write) re-reads the row with
        this inside its write transaction, so a concurrent change waits
        rather than being overwritten.

        Args:
            source_id: The source's UUID.
            user_id: The owner to scope to; ``None`` only after the caller has
                checked access itself (a team member edits the owner's row).

        Returns:
            The row, or ``None`` when it doesn't exist (or isn't the owner's).
        """
        if not looks_like_uuid(str(source_id)):
            return None
        sql = _ROW_SELECT + " WHERE id = CAST(:id AS uuid)"
        params = {"id": str(source_id)}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        row = self._conn.execute(text(sql + " FOR UPDATE"), params).fetchone()
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

    def get_by_id(self, source_id: str) -> Optional[dict]:
        """Fetch a source by id with NO ownership scoping.

        Used ONLY after a team-grant authorization check (team sharing). Never
        call on a raw user-supplied id without that check.
        """
        if not looks_like_uuid(source_id):
            return None
        result = self._conn.execute(
            text(_ROW_SELECT + " WHERE id = CAST(:id AS uuid)"),
            {"id": source_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_by_ids(self, source_ids) -> list[dict]:
        """Fetch sources whose id is in ``source_ids`` (team-shared listing path)."""
        ids = [str(s) for s in source_ids if looks_like_uuid(str(s))]
        if not ids:
            return []
        result = self._conn.execute(
            text(_ROW_SELECT + " WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY created_at DESC"),
            {"ids": ids},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def injection_allowed(self, source_ids) -> dict[str, set[str]]:
        """The text hashes each source's owner marked safe from prompt-injection screening.

        Read from ``metadata.injection_review.allowed`` (sha256 hex digests of
        chunk texts) with no ownership scoping: the caller already resolved
        these sources for the request. Kept per source: an allowance covers
        that source's chunk, never the same text from another source.

        Args:
            source_ids: Source UUIDs; anything else is ignored.

        Returns:
            Source id to its allowed hashes; sources that allowed none are absent.
        """
        ids = sorted({str(s) for s in source_ids if looks_like_uuid(str(s))})
        if not ids:
            return {}
        result = self._conn.execute(
            text(
                "SELECT id, metadata -> 'injection_review' -> 'allowed' AS allowed FROM sources "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": ids},
        )
        allowed: dict[str, set[str]] = {}
        for row in result.fetchall():
            hashes = {h for h in row.allowed if isinstance(h, str)} if isinstance(row.allowed, list) else set()
            if hashes:
                allowed[str(row.id)] = hashes
        return allowed

    def review_injection(self, source_id: str, content_hash: str, allow: bool, cap: int) -> Optional[list[str]]:
        """Add a text hash to the source's owner allowlist, or take it out.

        The list is ``metadata.injection_review.allowed``, read under a row
        lock so two reviews at once both land. Not scoped by owner: the route
        checked the caller may edit the source.

        Args:
            source_id: The source's UUID.
            content_hash: The sha256 hex digest of the chunk text.
            allow: True to mark it safe, False to clear that.
            cap: The most hashes the list may hold.

        Returns:
            The list as stored, or ``None`` when the source does not exist.

        Raises:
            AllowlistFull: ``allow`` on a full list.
        """
        if not looks_like_uuid(str(source_id)):
            return None
        row = self._conn.execute(
            text(
                "SELECT metadata -> 'injection_review' -> 'allowed' AS allowed FROM sources "
                "WHERE id = CAST(:id AS uuid) FOR UPDATE"
            ),
            {"id": str(source_id)},
        ).fetchone()
        if row is None:
            return None
        allowed = [h for h in row.allowed if isinstance(h, str)] if isinstance(row.allowed, list) else []
        if allow and content_hash not in allowed:
            if len(allowed) >= cap:
                raise AllowlistFull(f"At most {cap} chunks of a source can be marked safe")
            allowed.append(content_hash)
        elif not allow:
            allowed = [h for h in allowed if h != content_hash]
        self._conn.execute(
            text(
                "UPDATE sources SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{injection_review}', "
                "jsonb_build_object('allowed', CAST(:allowed AS jsonb))) "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(source_id), "allowed": json.dumps(allowed)},
        )
        return allowed

    def find_by_name(self, user_id: str, name: str) -> Optional[dict]:
        """Return a user's source whose name matches ``name`` (case-insensitive).

        Used by agent YAML import to map a portable source name back to a
        concrete source id. Returns the oldest match when names collide.
        """
        if not name:
            return None
        result = self._conn.execute(
            text(
                _ROW_SELECT + " "
                "WHERE user_id = :user_id AND lower(name) = lower(:name) "
                "ORDER BY created_at LIMIT 1"
            ),
            {"user_id": user_id, "name": name},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        search_term: Optional[str] = None,
        sort_field: str = "created_at",
        sort_order: str = "desc",
        extra_ids: Optional[list] = None,
        only_ids: Optional[list] = None,
        received_ids: Optional[list] = None,
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
            extra_ids: Ids of other users' sources (team-shared) to list too.
            only_ids: When given, keep only these ids (an empty list keeps
                none); the paginated listing narrows by kind and usage this way.
            received_ids: Ids of other teams' sources shared with the team
                workspace ``user_id`` (its principal), to list too.

        Returns:
            A list of source rows as plain dicts (via ``row_to_dict``),
            each carrying a derived ``ingest_status`` (``failed`` /
            ``processing`` / ``None``) from the joined progress row.
        """
        column_name = sort_field if sort_field in _SORTABLE_COLUMNS else "date"
        sort_column = sources_table.c[column_name]
        ascending = sort_order.lower() == "asc"

        stmt = (
            # Not ``remote_files``: a large selection's manifest runs to
            # megabytes, and no listing reads it.
            select(*_LISTED_COLUMNS, _ingest_status_case())
            .select_from(
                sources_table.outerjoin(
                    ingest_chunk_progress_table,
                    ingest_chunk_progress_table.c.source_id
                    == sources_table.c.id,
                )
            )
            .where(_owned_or_shared_scope(user_id, extra_ids, received_ids))
        )
        search = _name_search(search_term)
        if search is not None:
            stmt = stmt.where(search)
        if only_ids is not None:
            stmt = stmt.where(sources_table.c.id.in_(_coerce_uuid_ids(only_ids)))

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

    def list_ids_for_user(self, user_id: str, *, extra_ids: Optional[list] = None) -> list[dict]:
        """Every source ``list_for_user`` lists, as ``{id, user_id}`` only, in its default order (newest first).

        For a caller that filters and caps the rows itself and then reads
        the few it keeps (:meth:`list_brief`), without loading any source's
        JSONB columns.

        Args:
            user_id: The owner whose rows are listed.
            extra_ids: Ids of other users' sources (team-shared) to list too.

        Returns:
            ``{"id", "user_id"}`` dicts with string ids.
        """
        stmt = (
            select(sources_table.c.id, sources_table.c.user_id)
            .where(_owned_or_shared_scope(user_id, extra_ids))
            .order_by(sources_table.c.created_at.desc(), sources_table.c.id.desc())
        )
        return [{"id": str(row.id), "user_id": row.user_id} for row in self._conn.execute(stmt)]

    def list_brief(self, ids: list) -> list[dict]:
        """The scalar fields of the sources ``ids`` names, with their ingest status, newest first.

        The caller decides which ids it may read (:meth:`list_ids_for_user`); ids that are not uuids are skipped.

        Args:
            ids: Source ids.

        Returns:
            ``{"id", "user_id", "name", "type", "tokens", "ingest_status"}`` dicts with string ids.
        """
        uuids = _coerce_uuid_ids(ids)
        if not uuids:
            return []
        stmt = (
            select(
                sources_table.c.id, sources_table.c.user_id, sources_table.c.name, sources_table.c.type,
                sources_table.c.tokens, _ingest_status_case(),
            )
            .select_from(
                sources_table.outerjoin(
                    ingest_chunk_progress_table, ingest_chunk_progress_table.c.source_id == sources_table.c.id
                )
            )
            .where(sources_table.c.id.in_(uuids))
            .order_by(sources_table.c.created_at.desc(), sources_table.c.id.desc())
        )
        return [
            {"id": str(row.id), "user_id": row.user_id, "name": row.name, "type": row.type,
             "tokens": row.tokens, "ingest_status": row.ingest_status}
            for row in self._conn.execute(stmt)
        ]

    def get_remote_files(self, source_id: str) -> Any:
        """A source's sync manifest (``remote_files``), which the other reads leave out.

        Args:
            source_id: The source's uuid.

        Returns:
            The manifest as stored, or ``None`` (no manifest, or no such source).
        """
        if not looks_like_uuid(str(source_id)):
            return None
        return self._conn.execute(
            text("SELECT remote_files FROM sources WHERE id = CAST(:id AS uuid)"), {"id": str(source_id)},
        ).scalar()

    def get_directory_structure(self, source_id: str) -> Optional[dict]:
        """One source's ``directory_structure``, with no access check: the caller has already made one.

        Args:
            source_id: The source's id.

        Returns:
            The stored tree, or None when it has none or there is no such source.
        """
        if not looks_like_uuid(str(source_id)):
            return None
        return self._conn.execute(
            text("SELECT directory_structure FROM sources WHERE id = CAST(:id AS uuid)"), {"id": str(source_id)}
        ).scalar()

    def count_for_user(
        self,
        user_id: str,
        *,
        search_term: Optional[str] = None,
        extra_ids: Optional[list] = None,
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
            .where(_owned_or_shared_scope(user_id, extra_ids))
        )
        search = _name_search(search_term)
        if search is not None:
            stmt = stmt.where(search)
        result = self._conn.execute(stmt)
        row = result.fetchone()
        return int(row[0]) if row is not None else 0

    def list_facets_for_user(
        self,
        user_id: str,
        *,
        search_term: Optional[str] = None,
        extra_ids: Optional[list] = None,
        received_ids: Optional[list] = None,
    ) -> list[dict]:
        """Every row ``list_for_user`` would match, with only the columns that decide its kind.

        The paginated listing counts sources per kind and per usage over the
        whole match, not one page, so it reads these light rows (no directory
        tree or metadata) for all of them.

        Args:
            user_id: Scope rows to this owner.
            search_term: Same substring filter as ``list_for_user``.
            extra_ids: Same union of team-shared ids as ``list_for_user``.
            received_ids: Same union of other teams' shared ids as ``list_for_user``.

        Returns:
            Dicts with ``id``, ``user_id``, ``type``, ``remote_data``,
            ``config``, ``sync_frequency`` and ``connection_id``.
        """
        t = sources_table
        stmt = select(
            t.c.id, t.c.user_id, t.c.type, t.c.remote_data, t.c.config, t.c.sync_frequency, t.c.connection_id,
        ).where(_owned_or_shared_scope(user_id, extra_ids, received_ids))
        search = _name_search(search_term)
        if search is not None:
            stmt = stmt.where(search)
        return [row_to_dict(r) for r in self._conn.execute(stmt).fetchall()]

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

    def mark_sync_indexed(self, source_id: str, generation: Optional[str]) -> bool:
        """Record that the index was built from the files of ``generation``.

        Sets ``sync_manifest.indexed_generation``, and only while the
        manifest's generation is still ``generation`` and no request is
        changing the files (``writing``): files changed since the reingest
        read them leave the index marked stale.

        Args:
            source_id: The source's UUID.
            generation: The ``sync_manifest.generation`` the reingest read
                before it looked at the files; ``None`` does nothing.

        Returns:
            bool: Whether the mark was set.
        """
        if not generation or not looks_like_uuid(str(source_id)):
            return False
        result = self._conn.execute(
            text(
                "UPDATE sources SET sync_manifest = jsonb_set(sync_manifest, '{indexed_generation}', "
                "to_jsonb(CAST(:generation AS text))) "
                "WHERE id = CAST(:sid AS uuid) AND sync_manifest ->> 'generation' = :generation "
                "AND COALESCE(sync_manifest ->> 'writing', 'false') <> 'true'"
            ),
            {"sid": str(source_id), "generation": generation},
        )
        return result.rowcount > 0

    def clear_sync_indexed(self, source_id: str) -> None:
        """Forget that the index was built from any generation of the files.

        A reingest calls this before it changes chunks, so a run that stops
        part way leaves the index marked stale. A source without a sync
        manifest is left alone.

        Args:
            source_id: The source's UUID.
        """
        if not looks_like_uuid(str(source_id)):
            return
        self._conn.execute(
            text(
                "UPDATE sources SET sync_manifest = jsonb_set(sync_manifest, '{indexed_generation}', 'null'::jsonb) "
                "WHERE id = CAST(:sid AS uuid) AND jsonb_typeof(sync_manifest) = 'object'"
            ),
            {"sid": str(source_id)},
        )

    def set_metadata_key(self, source_id: str, user_id: str, key: str, value: Any) -> bool:
        """Set one top-level key of ``metadata``, keeping the others.

        ``update`` replaces the whole column, which would drop keys other
        writers own (``sync_state``, ``injection_review``).

        Args:
            source_id: The source's UUID.
            user_id: The owner's id; the row is scoped to it.
            key: The metadata key.
            value: Any JSON-serialisable value.

        Returns:
            bool: Whether a row was updated.
        """
        result = self._conn.execute(
            text(
                "UPDATE sources SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), "
                "CAST(:path AS text[]), CAST(:value AS jsonb)), updated_at = now() "
                "WHERE id = CAST(:sid AS uuid) AND user_id = :uid"
            ),
            {"path": "{" + key + "}", "value": json.dumps(value), "sid": str(source_id), "uid": user_id},
        )
        return result.rowcount > 0

    def remove_metadata_key(self, source_id: str, user_id: str, key: str) -> bool:
        """Drop one top-level key of ``metadata``, keeping the others.

        Args:
            source_id: The source's UUID.
            user_id: The owner's id; the row is scoped to it.
            key: The metadata key.

        Returns:
            bool: Whether a row was updated.
        """
        result = self._conn.execute(
            text(
                "UPDATE sources SET metadata = COALESCE(metadata, '{}'::jsonb) - CAST(:key AS text), "
                "updated_at = now() WHERE id = CAST(:sid AS uuid) AND user_id = :uid"
            ),
            {"key": key, "sid": str(source_id), "uid": user_id},
        )
        return result.rowcount > 0

    def set_wiki_outside_edits(self, source_id: str, user_id: str, allowed: bool) -> bool:
        """Record whether API-key and widget runs may edit this wiki.

        Kept out of :meth:`update`'s columns so no route that forwards a
        request body can change it; only the owner-checked wiki settings
        route calls this.

        Args:
            source_id: The source's UUID.
            user_id: The owner's id; the row is scoped to it.
            allowed: The new value.

        Returns:
            bool: Whether a row was updated.
        """
        t = sources_table
        result = self._conn.execute(
            t.update()
            .where(t.c.id == source_id)
            .where(t.c.user_id == user_id)
            .values(wiki_outside_edits=bool(allowed), updated_at=func.now())
        )
        return result.rowcount > 0

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: Optional[str] = None,
    ) -> Optional[dict]:
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = _ROW_SELECT + " WHERE legacy_mongo_id = :legacy_id"
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
