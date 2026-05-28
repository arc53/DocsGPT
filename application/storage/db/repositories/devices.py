"""Repository for the ``devices`` table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


_ALLOWED_UPDATES = frozenset(
    {
        "name", "description", "approval_mode", "cli_version", "hostname",
        "os", "arch",
    }
)


class DevicesRepository:
    """CRUD for paired remote devices."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        device_id: str,
        user_id: str,
        name: str,
        *,
        machine_pubkey_fingerprint: str,
        token_hash: str,
        hostname: Optional[str] = None,
        os: Optional[str] = None,
        arch: Optional[str] = None,
        cli_version: Optional[str] = None,
        approval_mode: str = "ask",
        description: Optional[str] = None,
    ) -> dict:
        row = self._conn.execute(
            text(
                """
                INSERT INTO devices (
                    id, user_id, name, hostname, os, arch, cli_version,
                    machine_pubkey_fingerprint, token_hash, approval_mode,
                    description
                ) VALUES (
                    :id, :user_id, :name, :hostname, :os, :arch, :cli_version,
                    :fp, :token_hash, :approval_mode, :description
                ) RETURNING *
                """
            ),
            {
                "id": device_id,
                "user_id": user_id,
                "name": name,
                "hostname": hostname,
                "os": os,
                "arch": arch,
                "cli_version": cli_version,
                "fp": machine_pubkey_fingerprint,
                "token_hash": token_hash,
                "approval_mode": approval_mode,
                "description": description,
            },
        ).fetchone()
        return row_to_dict(row)

    def get(self, device_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        sql = "SELECT * FROM devices WHERE id = :id"
        params: dict = {"id": device_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        row = self._conn.execute(text(sql), params).fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(
        self, user_id: str, *, include_revoked: bool = False
    ) -> list[dict]:
        sql = "SELECT * FROM devices WHERE user_id = :user_id"
        if not include_revoked:
            sql += " AND status = 'active'"
        sql += " ORDER BY paired_at DESC"
        result = self._conn.execute(text(sql), {"user_id": user_id})
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, device_id: str, user_id: str, fields: dict) -> bool:
        """Update name/description/approval_mode (and cli/host metadata)."""
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATES}
        if not filtered:
            return False
        set_clauses = [f"{col} = :{col}" for col in filtered]
        params = {**filtered, "id": device_id, "user_id": user_id}
        result = self._conn.execute(
            text(
                f"""
                UPDATE devices
                SET {', '.join(set_clauses)}
                WHERE id = :id AND user_id = :user_id
                """
            ),
            params,
        )
        return result.rowcount > 0

    def touch_last_seen(self, device_id: str) -> None:
        """Bump ``last_seen_at`` to now(). Called on every poll/SSE open."""
        self._conn.execute(
            text("UPDATE devices SET last_seen_at = now() WHERE id = :id"),
            {"id": device_id},
        )

    def revoke(
        self, device_id: str, user_id: str, *, reason: str = "user_revoked"
    ) -> bool:
        result = self._conn.execute(
            text(
                """
                UPDATE devices
                SET status = 'revoked',
                    revoked_at = now(),
                    revoke_reason = :reason
                WHERE id = :id AND user_id = :user_id AND status = 'active'
                """
            ),
            {"id": device_id, "user_id": user_id, "reason": reason},
        )
        return result.rowcount > 0

    def find_by_token_hash(self, token_hash: str) -> Optional[dict]:
        """Used by the session-token verifier on each device request."""
        row = self._conn.execute(
            text(
                "SELECT * FROM devices "
                "WHERE token_hash = :token_hash AND status = 'active' "
                "LIMIT 1"
            ),
            {"token_hash": token_hash},
        ).fetchone()
        return row_to_dict(row) if row is not None else None
