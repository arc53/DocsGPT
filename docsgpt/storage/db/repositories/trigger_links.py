"""Repositories for ``trigger_links`` (public webhook and approval links) and ``trigger_hits``.

A link is found by the sha256 of its token; the raw token is never stored.
A link stops working when it is revoked, expires or reaches ``max_hits``,
and every lookup that serves the public routes applies all three at once,
so an unknown, expired and revoked token are indistinguishable.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes


def _dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


#: The live-link predicate shared by every public lookup.
_LIVE = "revoked_at IS NULL AND expires_at > now()"


class TriggerLinksRepository:
    """Create, look up, hit and revoke trigger and approval links."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        *,
        monitor_id: str,
        user_id: str,
        conversation_id: str,
        token_hash: str,
        kind: str,
        expires_at: datetime,
        max_hits: int,
        signature_scheme: str = "none",
        secret_encrypted: Optional[str] = None,
        approval_spec: Optional[Dict[str, Any]] = None,
        ref: Optional[str] = None,
        expose_secret: bool = False,
        allow_get: bool = False,
        signature_header: Optional[str] = None,
    ) -> dict:
        """Insert a link; returns the row (which never holds the raw token).

        ``ref`` is the signed link's short reference id (``{{link_secret:REF}}``),
        unique per user; ``expose_secret`` records that the owner let the model
        see the raw secret; ``allow_get`` lets a webhook link take GET calls;
        ``signature_header`` is the header a ``header_token`` link reads.
        """
        row = self._conn.execute(
            text(
                """
                INSERT INTO trigger_links (
                    monitor_id, user_id, conversation_id, token_hash, kind, secret_encrypted,
                    signature_scheme, approval_spec, expires_at, max_hits, ref, expose_secret, allow_get,
                    signature_header
                ) VALUES (
                    CAST(:monitor_id AS uuid), :user_id, CAST(:conversation_id AS uuid), :token_hash, :kind,
                    :secret_encrypted, :signature_scheme, CAST(:approval_spec AS jsonb), :expires_at, :max_hits,
                    :ref, :expose_secret, :allow_get, :signature_header
                ) RETURNING *
                """
            ),
            {
                "ref": ref,
                "expose_secret": bool(expose_secret),
                "allow_get": bool(allow_get),
                "signature_header": signature_header,
                "monitor_id": str(monitor_id),
                "user_id": user_id,
                "conversation_id": str(conversation_id),
                "token_hash": token_hash,
                "kind": kind,
                "secret_encrypted": secret_encrypted,
                "signature_scheme": signature_scheme,
                "approval_spec": _dump(approval_spec),
                "expires_at": expires_at,
                "max_hits": int(max_hits),
            },
        ).fetchone()
        return row_to_dict(row)

    def get_live(self, token_hash: str, kind: str) -> Optional[dict]:
        """A link that still works: not revoked, not expired, under ``max_hits``."""
        row = self._conn.execute(
            text(
                f"SELECT * FROM trigger_links WHERE token_hash = :h AND kind = :kind AND {_LIVE} "
                "AND hit_count < max_hits"
            ),
            {"h": token_hash, "kind": kind},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get_unexpired(self, token_hash: str, kind: str) -> Optional[dict]:
        """A link that is not revoked or expired, used up or not (an approval link already decided)."""
        row = self._conn.execute(
            text(f"SELECT * FROM trigger_links WHERE token_hash = :h AND kind = :kind AND {_LIVE}"),
            {"h": token_hash, "kind": kind},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, link_id: str) -> Optional[dict]:
        """A link by id (workers)."""
        if not looks_like_uuid(str(link_id)):
            return None
        row = self._conn.execute(
            text("SELECT * FROM trigger_links WHERE id = CAST(:id AS uuid)"), {"id": str(link_id)}
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def ref_taken(self, user_id: str, ref: str) -> bool:
        """Whether the user already has a link with this reference id."""
        row = self._conn.execute(
            text("SELECT 1 FROM trigger_links WHERE user_id = :u AND ref = :ref LIMIT 1"),
            {"u": user_id, "ref": ref},
        ).fetchone()
        return row is not None

    def find_by_refs(self, user_id: str, refs: List[str]) -> List[dict]:
        """The user's links with these reference ids, in any state (the caller decides what counts)."""
        wanted = [str(ref).upper() for ref in refs if ref]
        if not wanted:
            return []
        rows = self._conn.execute(
            text("SELECT * FROM trigger_links WHERE user_id = :u AND ref = ANY(:refs)"),
            {"u": user_id, "refs": wanted},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_live_signed(self, monitor_id: str) -> Optional[dict]:
        """A monitor's live signed webhook link (its secret is what the owner may reveal), or None."""
        if not looks_like_uuid(str(monitor_id)):
            return None
        row = self._conn.execute(
            text(
                "SELECT * FROM trigger_links WHERE monitor_id = CAST(:m AS uuid) AND kind = 'webhook' "
                f"AND secret_encrypted IS NOT NULL AND {_LIVE} AND hit_count < max_hits "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"m": str(monitor_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get_live_webhook(self, monitor_id: str) -> Optional[dict]:
        """A monitor's live webhook link, with or without a secret yet (one waiting for the sender's), or None."""
        if not looks_like_uuid(str(monitor_id)):
            return None
        row = self._conn.execute(
            text(
                "SELECT * FROM trigger_links WHERE monitor_id = CAST(:m AS uuid) AND kind = 'webhook' "
                f"AND {_LIVE} AND hit_count < max_hits ORDER BY created_at DESC LIMIT 1"
            ),
            {"m": str(monitor_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def set_secret(self, link_id: str, sealed: str) -> bool:
        """Store a live link's (encrypted) signing secret, replacing any it had."""
        result = self._conn.execute(
            text(
                "UPDATE trigger_links SET secret_encrypted = :sealed "
                f"WHERE id = CAST(:id AS uuid) AND kind = 'webhook' AND {_LIVE}"
            ),
            {"id": str(link_id), "sealed": sealed},
        )
        return (result.rowcount or 0) > 0

    def list_for_monitor(self, monitor_id: str) -> List[dict]:
        """A monitor's links, oldest first."""
        rows = self._conn.execute(
            text("SELECT * FROM trigger_links WHERE monitor_id = CAST(:id AS uuid) ORDER BY created_at"),
            {"id": str(monitor_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_for_monitors(self, monitor_ids: List[str]) -> Dict[str, List[dict]]:
        """Links of several monitors at once, keyed by monitor id (oldest first)."""
        ids = [str(i) for i in monitor_ids if looks_like_uuid(str(i))]
        if not ids:
            return {}
        rows = self._conn.execute(
            text(
                "SELECT * FROM trigger_links WHERE monitor_id = ANY(CAST(:ids AS uuid[])) ORDER BY created_at"
            ),
            {"ids": ids},
        ).fetchall()
        out: Dict[str, List[dict]] = {}
        for row in rows:
            link = row_to_dict(row)
            out.setdefault(str(link["monitor_id"]), []).append(link)
        return out

    def count_hit(self, link_id: str) -> Optional[dict]:
        """Count one accepted request on a live link; None when it no longer works."""
        row = self._conn.execute(
            text(
                "UPDATE trigger_links SET hit_count = hit_count + 1, last_hit_at = now() "
                f"WHERE id = CAST(:id AS uuid) AND {_LIVE} AND hit_count < max_hits RETURNING *"
            ),
            {"id": str(link_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def decide(self, token_hash: str, decision: Dict[str, Any]) -> Optional[dict]:
        """Record an approval link's decision; only the first one wins.

        Returns:
            The decided link, or None when it was decided before, used up or no longer works.
        """
        row = self._conn.execute(
            text(
                "UPDATE trigger_links SET decision = CAST(:decision AS jsonb), hit_count = hit_count + 1, "
                "last_hit_at = now() "
                f"WHERE token_hash = :h AND kind = 'approval' AND {_LIVE} AND decision IS NULL "
                "AND hit_count < max_hits RETURNING *"
            ),
            {"h": token_hash, "decision": _dump(decision)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def revoke_for_monitor(self, monitor_id: str, *, kinds: Optional[List[str]] = None) -> int:
        """Revoke a monitor's live links; returns how many."""
        sql = (
            "UPDATE trigger_links SET revoked_at = now() WHERE monitor_id = CAST(:id AS uuid) "
            "AND revoked_at IS NULL"
        )
        params: Dict[str, Any] = {"id": str(monitor_id)}
        if kinds:
            sql += " AND kind = ANY(:kinds)"
            params["kinds"] = list(kinds)
        return int(self._conn.execute(text(sql), params).rowcount or 0)


class TriggerHitsRepository:
    """Accepted webhook deliveries, waiting for (or done with) the check pipeline."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, link_id: str, dedupe_key: str, payload: Dict[str, Any]) -> Optional[dict]:
        """Store a delivery once per ``(link, dedupe_key)``; None for a repeat."""
        row = self._conn.execute(
            text(
                """
                INSERT INTO trigger_hits (link_id, dedupe_key, payload)
                VALUES (CAST(:link_id AS uuid), :dedupe_key, CAST(:payload AS jsonb))
                ON CONFLICT ON CONSTRAINT trigger_hits_link_dedupe_uidx DO NOTHING
                RETURNING *
                """
            ),
            {"link_id": str(link_id), "dedupe_key": dedupe_key, "payload": _dump(payload) or "{}"},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def received_since(self, link_id: str, dedupe_key: str, seconds: int) -> bool:
        """Whether the link stored a delivery with this key in the last ``seconds``."""
        row = self._conn.execute(
            text(
                "SELECT 1 FROM trigger_hits WHERE link_id = CAST(:link_id AS uuid) AND dedupe_key = :key "
                "AND received_at > now() - make_interval(secs => :seconds) LIMIT 1"
            ),
            {"link_id": str(link_id), "key": dedupe_key, "seconds": int(seconds)},
        ).fetchone()
        return row is not None

    def get(self, hit_id: str) -> Optional[dict]:
        if not looks_like_uuid(str(hit_id)):
            return None
        row = self._conn.execute(
            text("SELECT * FROM trigger_hits WHERE id = CAST(:id AS uuid)"), {"id": str(hit_id)}
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def claim(self, hit_id: str) -> Optional[dict]:
        """Take a pending hit for processing (exactly once)."""
        row = self._conn.execute(
            text(
                "UPDATE trigger_hits SET status = 'processed', processed_at = now() "
                "WHERE id = CAST(:id AS uuid) AND status = 'pending' RETURNING *"
            ),
            {"id": str(hit_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def release(self, hit_id: str) -> None:
        """Hand a claimed hit back to ``pending`` (its check could not be decided yet)."""
        self._conn.execute(
            text(
                "UPDATE trigger_hits SET status = 'pending', processed_at = NULL "
                "WHERE id = CAST(:id AS uuid) AND status = 'processed'"
            ),
            {"id": str(hit_id)},
        )

    def mark(self, hit_id: str, status: str, error: Optional[str] = None) -> None:
        """Record how a hit ended (``processed``, ``ignored`` or ``failed``)."""
        self._conn.execute(
            text(
                "UPDATE trigger_hits SET status = :status, error = :error, processed_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(hit_id), "status": status, "error": (error or None) and strip_null_bytes(error)[:500]},
        )

    def delete(self, hit_id: str) -> None:
        """Forget a hit (its task could not be queued, so a retry may store it again)."""
        self._conn.execute(text("DELETE FROM trigger_hits WHERE id = CAST(:id AS uuid)"), {"id": str(hit_id)})

    def list_stuck(self, *, age_seconds: int, limit: int = 50) -> List[dict]:
        """Pending hits older than ``age_seconds`` (their task was lost)."""
        rows = self._conn.execute(
            text(
                "SELECT * FROM trigger_hits WHERE status = 'pending' "
                "AND received_at < now() - make_interval(secs => :age) ORDER BY received_at LIMIT :limit"
            ),
            {"age": int(age_seconds), "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def cleanup_older_than(self, days: int) -> int:
        """Delete settled hits older than ``days``; returns how many."""
        result = self._conn.execute(
            text(
                "DELETE FROM trigger_hits WHERE status <> 'pending' "
                "AND received_at < now() - make_interval(days => :days)"
            ),
            {"days": int(days)},
        )
        return int(result.rowcount or 0)
