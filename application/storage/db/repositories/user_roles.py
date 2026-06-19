"""Repository for the ``user_roles`` RBAC grant table.

The table stores only elevated grants; the ``user`` role is implicit. Grants
are keyed by ``(user_id, role, source)`` so a manual grant and an
OIDC-group-derived grant for the same user coexist and revoke independently.
All methods take a ``Connection`` and do not manage their own transactions.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict

VALID_SOURCES = ("manual", "oidc_group")


class UserRolesRepository:
    """Persisted role grants keyed by the auth ``sub`` (``user_id``)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def role_names_for(self, user_id: str) -> list[str]:
        """Return the distinct elevated roles granted to ``user_id`` (any source)."""
        if not user_id:
            return []
        result = self._conn.execute(
            text("SELECT DISTINCT role FROM user_roles WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return [row[0] for row in result.fetchall()]

    def list_admins(self) -> list[dict]:
        """Return one row per user holding ``admin``, with earliest grant + sources."""
        result = self._conn.execute(
            text(
                """
                SELECT user_id,
                       min(granted_at) AS granted_at,
                       array_agg(DISTINCT source ORDER BY source) AS sources
                FROM user_roles
                WHERE role = 'admin'
                GROUP BY user_id
                ORDER BY min(granted_at)
                """
            )
        )
        return [
            {"user_id": row[0], "granted_at": row[1], "sources": list(row[2])}
            for row in result.fetchall()
        ]

    def list_for(self, user_id: str) -> list[dict]:
        """Return all grant rows for ``user_id`` (for audit/inspection)."""
        result = self._conn.execute(
            text("SELECT * FROM user_roles WHERE user_id = :user_id ORDER BY granted_at"),
            {"user_id": user_id},
        )
        return [row_to_dict(row) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def grant(
        self,
        user_id: str,
        role: str = "admin",
        source: str = "manual",
        granted_by: Optional[str] = None,
    ) -> bool:
        """Idempotently grant ``role`` to ``user_id`` from ``source``.

        Returns True when a new row was inserted, False when it already existed.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO user_roles (user_id, role, source, granted_by)
                VALUES (:user_id, :role, :source, :granted_by)
                ON CONFLICT (user_id, role, source) DO NOTHING
                """
            ),
            {"user_id": user_id, "role": role, "source": source, "granted_by": granted_by},
        )
        return bool(result.rowcount)

    def revoke(self, user_id: str, role: str = "admin", source: str = "manual") -> bool:
        """Revoke ``role`` from ``user_id`` for ``source``. Returns True if removed."""
        result = self._conn.execute(
            text(
                """
                DELETE FROM user_roles
                WHERE user_id = :user_id AND role = :role AND source = :source
                """
            ),
            {"user_id": user_id, "role": role, "source": source},
        )
        return bool(result.rowcount)

    def reconcile_oidc_admin(self, user_id: str, is_admin: bool) -> Optional[str]:
        """Sync the ``oidc_group`` admin grant for ``user_id``; never touches manual grants.

        Returns ``"granted"`` / ``"revoked"`` when a change occurred, else ``None``.
        """
        if is_admin:
            granted = self.grant(user_id, "admin", source="oidc_group", granted_by="oidc")
            return "granted" if granted else None
        revoked = self.revoke(user_id, "admin", source="oidc_group")
        return "revoked" if revoked else None
