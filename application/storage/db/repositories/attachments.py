"""Repository for the ``attachments`` table."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import looks_like_uuid, row_to_dict


_UPDATABLE_SCALARS = {
    "filename", "upload_path", "mime_type", "size",
    "content", "token_count", "openai_file_id", "google_file_uri",
}
_UPDATABLE_JSONB = {"metadata"}


def _attachment_to_dict(row: Any) -> dict:
    """row_to_dict + ``upload_path``→``path`` alias.

    Pre-Postgres, the Mongo attachment shape used ``path``. The PG column
    is ``upload_path``; LLM provider code (google_ai/openai/anthropic and
    handlers/base) still reads ``attachment.get("path")``. Mirroring the
    ``id``/``_id`` dual-emit in row_to_dict so consumers don't need to
    know which storage backend produced the dict.
    """
    out = row_to_dict(row)
    if "upload_path" in out and out.get("path") is None:
        out["path"] = out["upload_path"]
    return out


class AttachmentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        filename: str,
        upload_path: str,
        *,
        mime_type: Optional[str] = None,
        size: Optional[int] = None,
        content: Optional[str] = None,
        token_count: Optional[int] = None,
        openai_file_id: Optional[str] = None,
        google_file_uri: Optional[str] = None,
        metadata: Any = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO attachments (
                    user_id, filename, upload_path, mime_type, size,
                    content, token_count, openai_file_id, google_file_uri,
                    metadata, legacy_mongo_id
                )
                VALUES (
                    :user_id, :filename, :upload_path, :mime_type, :size,
                    :content, :token_count, :openai_file_id, :google_file_uri,
                    CAST(:metadata AS jsonb), :legacy_mongo_id
                )
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "filename": filename,
                "upload_path": upload_path,
                "mime_type": mime_type,
                "size": size,
                "content": content,
                "token_count": token_count,
                "openai_file_id": openai_file_id,
                "google_file_uri": google_file_uri,
                "metadata": json.dumps(metadata) if metadata is not None else None,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return _attachment_to_dict(result.fetchone())

    def get(self, attachment_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM attachments WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": attachment_id, "user_id": user_id},
        )
        row = result.fetchone()
        return _attachment_to_dict(row) if row is not None else None

    def get_any(self, attachment_id: str, user_id: str) -> Optional[dict]:
        """Resolve an attachment by either PG UUID or legacy Mongo ObjectId string."""
        if looks_like_uuid(attachment_id):
            row = self.get(attachment_id, user_id)
            if row is not None:
                return row
        return self.get_by_legacy_id(attachment_id, user_id)

    def resolve_ids(self, ids: list[str]) -> dict[str, str]:
        """Batch-resolve a list of attachment ids (PG UUID *or* Mongo
        ObjectId or post-cutover route-minted UUID stored only in
        ``legacy_mongo_id``) to their canonical PG ``attachments.id``.

        Returns a ``{input_id: pg_uuid}`` map. Inputs that don't match
        any row are simply absent from the map (caller decides whether
        to drop or keep). Single round-trip via ``= ANY(:ids)`` to
        avoid N+1.

        Resolution prefers ``legacy_mongo_id`` matches first, since
        the post-cutover ``/store_attachment`` route mints a UUID that
        is UUID-shaped but only ever lives in ``legacy_mongo_id``
        (the row's own ``id`` is a fresh PG-generated UUID). A
        UUID-shaped input that is *also* a real ``attachments.id``
        falls back to the direct PK match.
        """
        if not ids:
            return {}
        # Deduplicate while preserving order for stable output mapping.
        unique_ids: list[str] = []
        seen: set[str] = set()
        for raw in ids:
            if raw is None:
                continue
            s = str(raw)
            if s in seen:
                continue
            seen.add(s)
            unique_ids.append(s)
        if not unique_ids:
            return {}
        result = self._conn.execute(
            text(
                "SELECT id::text AS id, legacy_mongo_id "
                "FROM attachments "
                "WHERE legacy_mongo_id = ANY(:ids) "
                "OR id::text = ANY(:ids)"
            ),
            {"ids": unique_ids},
        )
        rows = result.fetchall()
        # Build two indexes so we can apply the legacy-first preference.
        by_legacy: dict[str, str] = {}
        by_pk: dict[str, str] = {}
        for row in rows:
            pg_id = str(row[0])
            legacy = row[1]
            by_pk[pg_id] = pg_id
            if legacy is not None:
                by_legacy[str(legacy)] = pg_id
        out: dict[str, str] = {}
        for s in unique_ids:
            if s in by_legacy:
                out[s] = by_legacy[s]
            elif s in by_pk:
                out[s] = by_pk[s]
        return out

    def get_by_legacy_id(self, legacy_mongo_id: str, user_id: str | None = None) -> Optional[dict]:
        """Fetch an attachment by the original Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM attachments WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return _attachment_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM attachments WHERE user_id = :user_id ORDER BY created_at DESC"),
            {"user_id": user_id},
        )
        return [_attachment_to_dict(r) for r in result.fetchall()]

    def update(self, attachment_id: str, user_id: str, fields: dict) -> bool:
        """Partial update. Used by the LLM providers to cache their
        uploaded file IDs (``openai_file_id`` / ``google_file_uri``) so we
        don't re-upload the same blob every call.
        """
        filtered = {
            k: v for k, v in fields.items()
            if k in _UPDATABLE_SCALARS | _UPDATABLE_JSONB
        }
        if not filtered:
            return False
        set_clauses: list[str] = []
        params: dict = {"id": attachment_id, "user_id": user_id}
        for col, val in filtered.items():
            if col in _UPDATABLE_JSONB:
                set_clauses.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = json.dumps(val) if val is not None else None
            else:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val
        result = self._conn.execute(
            text(
                f"UPDATE attachments SET {', '.join(set_clauses)} "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            params,
        )
        return result.rowcount > 0

    def update_any(self, attachment_id: str, user_id: str, fields: dict) -> bool:
        """Partial update addressed by either PG UUID or legacy Mongo ObjectId.

        Cutover helper used by the LLM provider file-ID caching hot path:
        the attachment dict in hand may carry a UUID (post-cutover shape)
        or an ObjectId-string ``_id`` (legacy). Try the UUID path first
        when the id looks like a UUID; otherwise fall back to the
        ``legacy_mongo_id`` update. Both branches are user-scoped: the
        caller must pass the authenticated ``user_id`` so cross-tenant
        writes are prevented even when the fallback legacy path fires.
        """
        if looks_like_uuid(attachment_id):
            if self.update(attachment_id, user_id, fields):
                return True
        return self.update_by_legacy_id(attachment_id, user_id, fields)

    def update_by_legacy_id(
        self, legacy_mongo_id: str, user_id: str, fields: dict
    ) -> bool:
        """Like ``update`` but addressed by the Mongo ObjectId string.

        Used by the LLM file-ID caching path which, at dual-write time,
        only has the Mongo ``_id`` in hand (the PG UUID hasn't been
        looked up yet). Scoped by ``user_id`` so a caller that happens to
        pass an id matching another user's ``legacy_mongo_id`` cannot
        mutate the wrong row (IDOR).
        """
        if user_id is None:
            return False
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        filtered = {
            k: v for k, v in fields.items()
            if k in _UPDATABLE_SCALARS | _UPDATABLE_JSONB
        }
        if not filtered:
            return False
        set_clauses: list[str] = []
        params: dict = {"legacy_id": legacy_mongo_id, "user_id": user_id}
        for col, val in filtered.items():
            if col in _UPDATABLE_JSONB:
                set_clauses.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = json.dumps(val) if val is not None else None
            else:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val
        result = self._conn.execute(
            text(
                f"UPDATE attachments SET {', '.join(set_clauses)} "
                "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
            ),
            params,
        )
        return result.rowcount > 0
