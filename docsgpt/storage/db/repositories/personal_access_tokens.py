"""Repository for the ``personal_access_tokens`` table."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import row_to_dict


# token_hash never leaves the repository except through find_active_by_hash.
_PUBLIC_COLUMNS = (
    "id, user_id, name, token_prefix, scopes, resource_filter, status, "
    "expires_at, last_used_at, last_used_ip, created_at, revoked_at, revoke_reason"
)


class PersonalAccessTokensRepository:
    """CRUD for personal access tokens. Callers hash the secret; only the hash is stored."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        name: str,
        *,
        token_hash: str,
        token_prefix: str,
        scopes: list[str],
        resource_filter: Optional[dict] = None,
        expires_at: Optional[datetime] = None,
    ) -> dict:
        row = self._conn.execute(
            text(
                f"""
                INSERT INTO personal_access_tokens (
                    user_id, name, token_hash, token_prefix, scopes,
                    resource_filter, expires_at
                ) VALUES (
                    :user_id, :name, :token_hash, :token_prefix, :scopes,
                    CAST(:resource_filter AS jsonb), :expires_at
                ) RETURNING {_PUBLIC_COLUMNS}
                """
            ),
            {
                "user_id": user_id,
                "name": name,
                "token_hash": token_hash,
                "token_prefix": token_prefix,
                "scopes": list(scopes),
                "resource_filter": json.dumps(resource_filter or {}),
                "expires_at": expires_at,
            },
        ).fetchone()
        return row_to_dict(row)

    def get(self, token_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        sql = f"SELECT {_PUBLIC_COLUMNS} FROM personal_access_tokens WHERE id = CAST(:id AS uuid)"
        params: dict = {"id": token_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        row = self._conn.execute(text(sql), params).fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str, *, include_revoked: bool = False) -> list[dict]:
        sql = f"SELECT {_PUBLIC_COLUMNS} FROM personal_access_tokens WHERE user_id = :user_id"
        if not include_revoked:
            sql += " AND status = 'active'"
        sql += " ORDER BY created_at DESC"
        result = self._conn.execute(text(sql), {"user_id": user_id})
        return [row_to_dict(r) for r in result.fetchall()]

    def lock_user(self, user_id: str) -> None:
        """Hold a per-user advisory lock until the transaction ends."""
        self._conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"personal_access_tokens:{user_id}"},
        )

    def count_active(self, user_id: str) -> int:
        """Live tokens only: revoked and expired rows don't count against the per-user cap."""
        return self._conn.execute(
            text(
                "SELECT count(*) FROM personal_access_tokens "
                "WHERE user_id = :user_id AND status = 'active' "
                "AND (expires_at IS NULL OR expires_at > now())"
            ),
            {"user_id": user_id},
        ).scalar_one()

    def retire_expired_name(self, user_id: str, name: str) -> int:
        """Revoke an expired token holding ``name`` so the name can be reused.

        An expired token can no longer authenticate but keeps ``status = 'active'``,
        and the unique index on live names would otherwise reserve its name forever.
        """
        result = self._conn.execute(
            text(
                "UPDATE personal_access_tokens "
                "SET status = 'revoked', revoked_at = now(), revoke_reason = 'expired' "
                "WHERE user_id = :user_id AND name = :name AND status = 'active' "
                "AND expires_at IS NOT NULL AND expires_at <= now()"
            ),
            {"user_id": user_id, "name": name},
        )
        return result.rowcount

    def name_in_use(self, user_id: str, name: str) -> bool:
        return (
            self._conn.execute(
                text(
                    "SELECT 1 FROM personal_access_tokens "
                    "WHERE user_id = :user_id AND name = :name AND status = 'active' LIMIT 1"
                ),
                {"user_id": user_id, "name": name},
            ).fetchone()
            is not None
        )

    def find_active_by_hash(self, token_hash: str) -> Optional[dict]:
        """Resolve the credential on each request.

        Revoked and expired tokens never match, and neither do the tokens of a
        deactivated user (admin or SCIM), so deactivation needs no token sweep
        and reactivation restores them.
        """
        row = self._conn.execute(
            text(
                f"SELECT {_PUBLIC_COLUMNS} FROM personal_access_tokens pat "
                "WHERE token_hash = :token_hash AND status = 'active' "
                "AND (expires_at IS NULL OR expires_at > now()) "
                "AND NOT EXISTS (SELECT 1 FROM users u "
                "WHERE u.user_id = pat.user_id AND u.active = false) "
                "LIMIT 1"
            ),
            {"token_hash": token_hash},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def touch_last_used(self, token_id: str, ip: Optional[str], *, min_interval_seconds: int = 60) -> None:
        """Record use, at most once per ``min_interval_seconds`` so hot tokens don't write per request."""
        self._conn.execute(
            text(
                "UPDATE personal_access_tokens "
                "SET last_used_at = now(), last_used_ip = :ip "
                "WHERE id = CAST(:id AS uuid) AND (last_used_at IS NULL "
                "OR last_used_at <= now() - make_interval(secs => :min_interval))"
            ),
            {"id": token_id, "ip": ip, "min_interval": min_interval_seconds},
        )

    def revoke(self, token_id: str, user_id: Optional[str] = None, *, reason: str = "user_revoked") -> bool:
        """Revoke one token. ``user_id=None`` is the admin path (any owner)."""
        sql = (
            "UPDATE personal_access_tokens "
            "SET status = 'revoked', revoked_at = now(), revoke_reason = :reason "
            "WHERE id = CAST(:id AS uuid) AND status = 'active'"
        )
        params: dict = {"id": token_id, "reason": reason}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        return self._conn.execute(text(sql), params).rowcount > 0

    def revoke_all_for_user(self, user_id: str, *, reason: str = "admin_revoked") -> list[str]:
        """Revoke every live token of a user. Returns the revoked token ids (for the audit trail)."""
        result = self._conn.execute(
            text(
                "UPDATE personal_access_tokens "
                "SET status = 'revoked', revoked_at = now(), revoke_reason = :reason "
                "WHERE user_id = :user_id AND status = 'active' RETURNING id"
            ),
            {"user_id": user_id, "reason": reason},
        )
        return [str(row[0]) for row in result.fetchall()]
