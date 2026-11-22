"""Repository for ``parsed_files``: a user's parsed source files, keyed by content hash and parser settings."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder

#: ``last_used_at`` is bumped at most once a day per row, so a lookup is a read on most days.
_TOUCH_AFTER = "interval '1 day'"


class ParsedFilesRepository:
    """Read/write helpers for ``parsed_files``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find(self, user_id: str, content_sha256: str, parser_key: str) -> Optional[Dict[str, Any]]:
        """The user's stored parse of this content under this parser key, marking it used.

        Args:
            user_id: The owner; another user's identical file is never returned.
            content_sha256: SHA-256 of the file's bytes.
            parser_key: ``docsgpt.parser.parse_cache.parser_key`` of the parser that would read it.

        Returns:
            The row, or ``None``.
        """
        params = {"user_id": user_id, "sha": content_sha256, "key": parser_key}
        row = self._conn.execute(
            text(
                "SELECT * FROM parsed_files "
                "WHERE user_id = :user_id AND content_sha256 = :sha AND parser_key = :key"
            ),
            params,
        ).fetchone()
        if row is None:
            return None
        self._conn.execute(
            text(
                "UPDATE parsed_files SET last_used_at = now() "
                "WHERE user_id = :user_id AND content_sha256 = :sha AND parser_key = :key "
                f"AND last_used_at < now() - {_TOUCH_AFTER}"
            ),
            params,
        )
        return row_to_dict(row)

    def store(
        self,
        user_id: str,
        content_sha256: str,
        parser_key: str,
        *,
        content: Any = None,
        parser_metadata: Optional[Dict[str, Any]] = None,
        storage_path: Optional[str] = None,
        page_count: Optional[int] = None,
        billed_pages: Optional[int] = None,
    ) -> Optional[str]:
        """Insert a parse, or replace the one stored under the same user, content and parser key.

        Args:
            user_id: The owner.
            content_sha256: SHA-256 of the file's bytes.
            parser_key: The parser key.
            content: The parser's output (a string or a list of strings); ``None`` when it is in storage.
            parser_metadata: What the parser reported for the file.
            storage_path: Where a large output is kept instead of ``content``.
            page_count: Pages in the file, when the parser said.
            billed_pages: Pages sent to a paid OCR service, when the parser said.

        Returns:
            The storage path of the parse this replaced, when it had one other
            than ``storage_path``: nothing refers to that file any more.
        """
        previous = self._conn.execute(
            text(
                "SELECT storage_path FROM parsed_files "
                "WHERE user_id = :user_id AND content_sha256 = :sha AND parser_key = :key FOR UPDATE"
            ),
            {"user_id": user_id, "sha": content_sha256, "key": parser_key},
        ).scalar()
        self._conn.execute(
            text(
                """
                INSERT INTO parsed_files (
                    user_id, content_sha256, parser_key, content, parser_metadata,
                    storage_path, page_count, billed_pages
                )
                VALUES (
                    :user_id, :sha, :key, CAST(:content AS jsonb), CAST(:metadata AS jsonb),
                    :storage_path, :page_count, :billed_pages
                )
                ON CONFLICT (user_id, content_sha256, parser_key) DO UPDATE SET
                    content = EXCLUDED.content,
                    parser_metadata = EXCLUDED.parser_metadata,
                    storage_path = EXCLUDED.storage_path,
                    page_count = EXCLUDED.page_count,
                    billed_pages = EXCLUDED.billed_pages,
                    last_used_at = now()
                """
            ),
            {
                "user_id": user_id,
                "sha": content_sha256,
                "key": parser_key,
                "content": None if content is None else json.dumps(content, cls=PGNativeJSONEncoder),
                "metadata": json.dumps(parser_metadata or {}, cls=PGNativeJSONEncoder),
                "storage_path": storage_path,
                "page_count": page_count,
                "billed_pages": billed_pages,
            },
        )
        return previous if previous and previous != storage_path else None

    def delete_stale(self, days: int) -> List[Optional[str]]:
        """Delete rows unused for ``days`` days.

        Returns:
            The deleted rows' ``storage_path`` values (``None`` for an inline row), for the caller to remove.
        """
        result = self._conn.execute(
            text(
                "DELETE FROM parsed_files WHERE last_used_at < now() - CAST(:days || ' days' AS interval) "
                "RETURNING storage_path"
            ),
            {"days": str(max(1, int(days)))},
        )
        return [row[0] for row in result.fetchall()]

    def delete_for_user(self, user_id: str) -> List[Optional[str]]:
        """Delete every parse a user holds.

        Returns:
            The deleted rows' ``storage_path`` values, for the caller to remove once the transaction commits.
        """
        result = self._conn.execute(
            text("DELETE FROM parsed_files WHERE user_id = :user_id RETURNING storage_path"),
            {"user_id": user_id},
        )
        return [row[0] for row in result.fetchall()]

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Every parse a user holds, oldest first, for an export of their data."""
        result = self._conn.execute(
            text("SELECT * FROM parsed_files WHERE user_id = :user_id ORDER BY created_at, content_sha256, parser_key"),
            {"user_id": user_id},
        )
        return [row_to_dict(row) for row in result.fetchall()]
