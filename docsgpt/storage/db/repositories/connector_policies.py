"""Repository for ``connector_policies``: the admin's per-connector switches."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import row_to_dict

CREDENTIAL_POLICIES = ("choose", "owner", "member")
ALLOW_CUSTOM_MCP_KEY = "connectors.allow_custom_mcp"


class ConnectorPoliciesRepository:
    """Whether a connector is enabled and which credential mode it forces."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def all(self) -> dict[str, dict]:
        """Every stored policy, by connector key. Missing keys use the defaults."""
        result = self._conn.execute(text("SELECT * FROM connector_policies"))
        return {row["connector_key"]: row for row in (row_to_dict(r) for r in result.fetchall())}

    def get(self, connector_key: str) -> Optional[dict]:
        row = self._conn.execute(
            text("SELECT * FROM connector_policies WHERE connector_key = :key"), {"key": connector_key},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def upsert(
        self,
        connector_key: str,
        *,
        enabled: Optional[bool] = None,
        credential_mode: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> dict:
        """Set one connector's policy; fields left None keep their value.

        A new row leaves ``enabled`` NULL unless it is given, so changing only
        the credential mode never switches a connector on.
        """
        if credential_mode is not None and credential_mode not in CREDENTIAL_POLICIES:
            raise ValueError(f"unknown credential mode: {credential_mode!r}")
        row = self._conn.execute(
            text(
                """
                INSERT INTO connector_policies (connector_key, enabled, credential_mode, updated_by)
                VALUES (:key, :enabled, COALESCE(:mode, 'choose'), :by)
                ON CONFLICT (connector_key) DO UPDATE SET
                    enabled = COALESCE(:enabled, connector_policies.enabled),
                    credential_mode = COALESCE(:mode, connector_policies.credential_mode),
                    updated_by = :by,
                    updated_at = now()
                RETURNING *
                """
            ),
            {"key": connector_key, "enabled": enabled, "mode": credential_mode, "by": updated_by},
        ).fetchone()
        return row_to_dict(row)
