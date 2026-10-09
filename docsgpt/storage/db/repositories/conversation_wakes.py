"""Repository for ``conversation_wakes``: events queued to resume a conversation.

A wake is queued once per ``dedupe_key``. A continuation turn claims a batch
of pending wakes (``claim_batch``), answers them together and marks them
delivered; the user's next message can take them instead (``fold_pending``).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes


def _dump(value: Any) -> Optional[str]:
    """Serialize ``value`` for a jsonb CAST, stripping NULs Postgres rejects."""
    if value is None:
        return None
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


class ConversationWakesRepository:
    """Queue, claim and settle the events that resume a conversation."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def enqueue(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source: str,
        dedupe_key: str,
        ref_id: Optional[str] = None,
        title: str = "",
        body: str = "",
        payload: Optional[dict] = None,
    ) -> Optional[dict]:
        """Queue a wake; None when ``dedupe_key`` was queued before.

        Args:
            user_id: The conversation's owner.
            conversation_id: The conversation to resume.
            source: ``job``, ``monitor``, ``trigger``, ``approval`` or ``lost``.
            dedupe_key: Unique per event; a second report of it is dropped.
            ref_id: What raised it (a job id, a monitor id).
            title: One line naming the event.
            body: What happened, for the continuation turn.
            payload: Untrusted data that came with the event.

        Returns:
            The queued row, or None for a duplicate.
        """
        row = self._conn.execute(
            text(
                """
                INSERT INTO conversation_wakes (
                    user_id, conversation_id, source, ref_id, title, body, payload, dedupe_key
                ) VALUES (
                    :user_id, CAST(:conversation_id AS uuid), :source, :ref_id, :title, :body,
                    CAST(:payload AS jsonb), :dedupe_key
                )
                ON CONFLICT ON CONSTRAINT conversation_wakes_dedupe_uidx DO NOTHING
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "conversation_id": str(conversation_id),
                "source": source,
                "ref_id": ref_id,
                "title": strip_null_bytes(title or ""),
                "body": strip_null_bytes(body or ""),
                "payload": _dump(payload),
                "dedupe_key": dedupe_key,
            },
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, wake_id: str) -> Optional[dict]:
        """Fetch one wake."""
        if not looks_like_uuid(wake_id):
            return None
        row = self._conn.execute(
            text("SELECT * FROM conversation_wakes WHERE id = CAST(:id AS uuid)"), {"id": str(wake_id)}
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def claim_batch(self, conversation_id: str, *, limit: int = 8) -> List[dict]:
        """Claim up to ``limit`` pending wakes of a conversation, oldest first."""
        rows = self._conn.execute(
            text(
                """
                UPDATE conversation_wakes SET status = 'claimed', claimed_at = now(), attempts = attempts + 1
                WHERE id IN (
                    SELECT id FROM conversation_wakes
                    WHERE conversation_id = CAST(:conversation_id AS uuid) AND status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """
            ),
            {"conversation_id": str(conversation_id), "limit": int(limit)},
        ).fetchall()
        return sorted((row_to_dict(r) for r in rows), key=lambda r: str(r.get("created_at") or ""))

    def release(self, wake_ids: Iterable[str]) -> int:
        """Put claimed wakes back to ``pending`` (the turn could not run yet)."""
        ids = [str(i) for i in wake_ids]
        if not ids:
            return 0
        result = self._conn.execute(
            text(
                "UPDATE conversation_wakes SET status = 'pending', claimed_at = NULL "
                "WHERE id = ANY(CAST(:ids AS uuid[])) AND status = 'claimed'"
            ),
            {"ids": ids},
        )
        return result.rowcount or 0

    def mark(
        self,
        wake_ids: Iterable[str],
        status: str,
        *,
        message_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> int:
        """Settle claimed wakes: ``delivered``, ``suppressed``, ``superseded`` or ``failed``.

        Only wakes still ``claimed`` change, so a claim the sweep handed back
        (and someone else took) is never overwritten; the count tells.
        """
        ids = [str(i) for i in wake_ids]
        if not ids:
            return 0
        result = self._conn.execute(
            text(
                "UPDATE conversation_wakes SET status = :status, message_id = CAST(:message_id AS uuid), "
                "error = :error, delivered_at = now() WHERE id = ANY(CAST(:ids AS uuid[])) AND status = 'claimed'"
            ),
            {"ids": ids, "status": status, "message_id": message_id, "error": error},
        )
        return result.rowcount or 0

    def fold_pending(
        self,
        conversation_id: str,
        user_id: str,
        *,
        exclude_sources: Sequence[str] = (),
        exclude_key_suffix: Optional[str] = None,
    ) -> List[dict]:
        """Take every pending wake of a conversation for the user's new message.

        Args:
            conversation_id: The conversation.
            user_id: Its owner.
            exclude_sources: Sources to leave queued.
            exclude_key_suffix: Leave queued the wakes whose dedupe key ends with this.

        Returns:
            The folded rows, oldest first.
        """
        if not looks_like_uuid(conversation_id):
            return []
        rows = self._conn.execute(
            text(
                "UPDATE conversation_wakes SET status = 'folded', delivered_at = now() "
                "WHERE conversation_id = CAST(:conversation_id AS uuid) AND user_id = :user_id "
                "AND status = 'pending' AND NOT (source = ANY(:exclude)) "
                "AND (CAST(:suffix AS text) IS NULL OR right(dedupe_key, length(:suffix)) <> :suffix) RETURNING *"
            ),
            {
                "conversation_id": str(conversation_id),
                "user_id": user_id,
                "exclude": list(exclude_sources),
                "suffix": exclude_key_suffix,
            },
        ).fetchall()
        return sorted((row_to_dict(r) for r in rows), key=lambda r: str(r.get("created_at") or ""))

    def supersede_for_ref(self, source: str, ref_id: str) -> int:
        """Drop the pending wakes of one event source (a job ``check_job`` already delivered)."""
        result = self._conn.execute(
            text(
                "UPDATE conversation_wakes SET status = 'superseded', delivered_at = now() "
                "WHERE source = :source AND ref_id = :ref_id AND status = 'pending'"
            ),
            {"source": source, "ref_id": str(ref_id)},
        )
        return result.rowcount or 0

    def pending_conversations(self, *, older_than_seconds: int, limit: int = 100) -> List[Tuple[str, str]]:
        """Conversations with a wake left pending longer than ``older_than_seconds``."""
        rows = self._conn.execute(
            text(
                "SELECT conversation_id, user_id, min(created_at) AS oldest FROM conversation_wakes "
                "WHERE status = 'pending' AND created_at < now() - make_interval(secs => :age) "
                "GROUP BY conversation_id, user_id ORDER BY oldest ASC LIMIT :limit"
            ),
            {"age": int(older_than_seconds), "limit": int(limit)},
        ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]

    def release_stale_claims(self, *, older_than_seconds: int) -> int:
        """Return claims held longer than ``older_than_seconds`` (a continuation that died) to pending."""
        result = self._conn.execute(
            text(
                "UPDATE conversation_wakes SET status = 'pending', claimed_at = NULL "
                "WHERE status = 'claimed' AND claimed_at < now() - make_interval(secs => :age)"
            ),
            {"age": int(older_than_seconds)},
        )
        return result.rowcount or 0

    def cleanup_older_than(self, days: int) -> int:
        """Delete settled wakes older than ``days``."""
        result = self._conn.execute(
            text(
                "DELETE FROM conversation_wakes WHERE status NOT IN ('pending', 'claimed') "
                "AND created_at < now() - make_interval(days => :days)"
            ),
            {"days": int(days)},
        )
        return result.rowcount or 0
