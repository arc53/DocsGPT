"""Repository for the ``wiki_pages`` table.

Authoritative, source-scoped storage for an LLM-editable wiki source. Mirrors
``MemoriesRepository`` but is keyed on ``source_id`` (not ``user_id``/``tool_id``)
and adds wiki-specific semantics: ``content_hash`` short-circuit on identical
writes, a monotonically increasing ``version``, and an ``embed_status`` setter
driving the async per-page re-embed.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict
from application.utils import num_tokens_from_string


class WikiPageConflict(Exception):
    """Raised when a version-checked upsert loses an optimistic-lock race."""


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class WikiPagesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        source_id: str,
        path: str,
        content: str,
        title: Optional[str] = None,
        updated_by: Optional[str] = None,
        updated_via: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> dict:
        """Create or overwrite a page.

        Short-circuits (no write, returns the row unchanged) when an existing
        page already has the same ``content_hash``. Otherwise inserts, or on
        conflict updates content/title/hash/updated_by, bumps ``version``, and
        resets ``embed_status`` to ``pending``.

        When ``expected_version`` is given, the update on an existing row is
        conditional on its ``version`` still matching; a concurrent write that
        changed the version causes zero rows to update and raises
        :class:`WikiPageConflict` so the caller can re-read and retry.
        """
        content_hash = _content_hash(content)

        existing = self.get_by_path(source_id, path)
        if existing is not None and existing.get("content_hash") == content_hash:
            return existing

        if expected_version is not None and existing is not None:
            result = self._conn.execute(
                text(
                    """
                    UPDATE wiki_pages SET
                        title = :title,
                        content = :content,
                        token_count = :token_count,
                        content_hash = :content_hash,
                        updated_by = :updated_by,
                        updated_via = :updated_via,
                        version = version + 1,
                        embed_status = 'pending',
                        updated_at = now()
                    WHERE source_id = CAST(:source_id AS uuid)
                        AND path = :path
                        AND version = :expected_version
                    RETURNING *
                    """
                ),
                {
                    "source_id": source_id,
                    "path": path,
                    "title": title,
                    "content": content,
                    "token_count": num_tokens_from_string(content),
                    "content_hash": content_hash,
                    "updated_by": updated_by,
                    "updated_via": updated_via,
                    "expected_version": expected_version,
                },
            )
            row = result.fetchone()
            if row is None:
                raise WikiPageConflict(
                    f"Page {path} changed underneath the edit (expected version "
                    f"{expected_version})."
                )
            return row_to_dict(row)

        result = self._conn.execute(
            text(
                """
                INSERT INTO wiki_pages
                    (source_id, path, title, content, token_count,
                     content_hash, updated_by, updated_via, embed_status)
                VALUES
                    (CAST(:source_id AS uuid), :path, :title, :content, :token_count,
                     :content_hash, :updated_by, :updated_via, 'pending')
                ON CONFLICT (source_id, path)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    token_count = EXCLUDED.token_count,
                    content_hash = EXCLUDED.content_hash,
                    updated_by = EXCLUDED.updated_by,
                    updated_via = EXCLUDED.updated_via,
                    version = wiki_pages.version + 1,
                    embed_status = 'pending',
                    updated_at = now()
                RETURNING *
                """
            ),
            {
                "source_id": source_id,
                "path": path,
                "title": title,
                "content": content,
                "token_count": num_tokens_from_string(content),
                "content_hash": content_hash,
                "updated_by": updated_by,
                "updated_via": updated_via,
            },
        )
        return row_to_dict(result.fetchone())

    def get_by_path(self, source_id: str, path: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM wiki_pages "
                "WHERE source_id = CAST(:source_id AS uuid) AND path = :path"
            ),
            {"source_id": source_id, "path": path},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_by_prefix(self, source_id: str, prefix: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM wiki_pages "
                "WHERE source_id = CAST(:source_id AS uuid) AND path LIKE :prefix "
                "ORDER BY path"
            ),
            {"source_id": source_id, "prefix": prefix + "%"},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def list_for_source(self, source_id: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM wiki_pages "
                "WHERE source_id = CAST(:source_id AS uuid) ORDER BY path"
            ),
            {"source_id": source_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def delete_by_path(self, source_id: str, path: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM wiki_pages "
                "WHERE source_id = CAST(:source_id AS uuid) AND path = :path"
            ),
            {"source_id": source_id, "path": path},
        )
        return result.rowcount

    def delete_by_prefix(self, source_id: str, prefix: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM wiki_pages "
                "WHERE source_id = CAST(:source_id AS uuid) AND path LIKE :prefix"
            ),
            {"source_id": source_id, "prefix": prefix + "%"},
        )
        return result.rowcount

    def update_path(self, source_id: str, old_path: str, new_path: str) -> bool:
        """Move a page. Rejects (returns ``False``) if ``new_path`` already exists."""
        if self.get_by_path(source_id, new_path) is not None:
            return False
        result = self._conn.execute(
            text(
                "UPDATE wiki_pages SET path = :new_path, updated_at = now() "
                "WHERE source_id = CAST(:source_id AS uuid) AND path = :old_path"
            ),
            {"source_id": source_id, "old_path": old_path, "new_path": new_path},
        )
        return result.rowcount > 0

    def set_embed_status(self, source_id: str, path: str, status: str) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE wiki_pages SET embed_status = :status "
                "WHERE source_id = CAST(:source_id AS uuid) AND path = :path"
            ),
            {"source_id": source_id, "path": path, "status": status},
        )
        return result.rowcount > 0


def build_wiki_directory_structure(pages: list[dict]) -> dict:
    """Build the nested ``directory_structure`` tree from wiki page rows.

    Mirrors the ingest pipeline's tree shape so ``internal_search.list_files``
    and the UI file tree work unchanged: leaf files carry ``type``,
    ``size_bytes`` and ``token_count`` metadata.
    """
    tree: dict = {}
    for page in pages:
        path = (page.get("path") or "").lstrip("/")
        if not path:
            continue
        parts = path.split("/")
        current = tree
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                content = page.get("content") or ""
                current[part] = {
                    "type": "text/markdown",
                    "size_bytes": len(content.encode("utf-8")),
                    "token_count": page.get("token_count") or 0,
                }
            else:
                current = current.setdefault(part, {})
    return tree


def rebuild_wiki_directory_structure(
    conn: Connection, source_id: str, owner_id: str
) -> dict:
    """Recompute ``sources.directory_structure`` from the source's wiki pages.

    Returns the rebuilt tree. The write is owner-scoped so it matches the
    ``sources`` repo's ``WHERE id AND user_id`` update contract.
    """
    from application.storage.db.repositories.sources import SourcesRepository

    pages = WikiPagesRepository(conn).list_for_source(source_id)
    tree = build_wiki_directory_structure(pages)
    SourcesRepository(conn).update(
        source_id, owner_id, {"directory_structure": tree}
    )
    return tree
