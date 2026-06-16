"""Repository for the ``team_resource_grants`` table (resource sharing).

One polymorphic table for all four shareable resource types
(``agent``/``source``/``prompt``/``tool``). A grant makes a resource visible to
a team as additive visibility — never ownership transfer; the resource's
``user_id`` owner is unchanged. ``owner_id`` is denormalised owner-at-share-time.
Per-user effective visibility/access (the JOIN to ``team_members``) lives in
[[team_scope]]. All methods take a ``Connection``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict

VALID_RESOURCE_TYPES = ("agent", "source", "prompt", "tool")
VALID_ACCESS_LEVELS = ("viewer", "editor")


class TeamResourceGrantsRepository:
    """Share grants keyed by ``(team_id, resource_type, resource_id)``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def list_for_team(
        self, team_id: str, resource_type: Optional[str] = None
    ) -> list[dict]:
        """All grants for a team, optionally filtered to one resource type."""
        sql = "SELECT * FROM team_resource_grants WHERE team_id = CAST(:team_id AS uuid)"
        params: dict = {"team_id": team_id}
        if resource_type is not None:
            sql += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type
        sql += " ORDER BY created_at DESC"
        result = self._conn.execute(text(sql), params)
        return [row_to_dict(r) for r in result.fetchall()]

    def list_for_resource(self, resource_type: str, resource_id: str) -> list[dict]:
        """Which teams a resource is shared with (the owner's share-management view)."""
        result = self._conn.execute(
            text(
                """
                SELECT g.*, t.name AS team_name, t.slug AS team_slug
                FROM team_resource_grants g
                JOIN teams t ON t.id = g.team_id
                WHERE g.resource_type = :resource_type
                  AND g.resource_id = CAST(:resource_id AS uuid)
                ORDER BY t.name
                """
            ),
            {"resource_type": resource_type, "resource_id": resource_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def get(
        self,
        team_id: str,
        resource_type: str,
        resource_id: str,
        target_user_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Fetch one grant. ``target_user_id`` None matches the whole-team grant;
        a sub matches that member's grant (NULL/'' coalesced so both compare)."""
        result = self._conn.execute(
            text(
                """
                SELECT * FROM team_resource_grants
                WHERE team_id = CAST(:team_id AS uuid)
                  AND resource_type = :resource_type
                  AND resource_id = CAST(:resource_id AS uuid)
                  AND COALESCE(target_user_id, '') = COALESCE(:target_user_id, '')
                """
            ),
            {
                "team_id": team_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "target_user_id": target_user_id,
            },
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def grant(
        self,
        team_id: str,
        resource_type: str,
        resource_id: str,
        owner_id: str,
        granted_by: str,
        access_level: str = "viewer",
        target_user_id: Optional[str] = None,
    ) -> dict:
        """Share a resource with a team (or one member), upserting the access level.

        ``target_user_id`` None shares with the whole team; a sub shares with
        that one member (the caller must have validated they're a team member).
        ``ON CONFLICT`` on the functional dedup index makes re-sharing
        last-write-wins on ``access_level``. The caller MUST have verified
        ``granted_by`` owns the resource (dispatched by ``resource_type``) — the
        polymorphic table has no FK to catch a type/id mismatch.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO team_resource_grants
                    (team_id, resource_type, resource_id, owner_id, access_level,
                     granted_by, target_user_id)
                VALUES
                    (CAST(:team_id AS uuid), :resource_type, CAST(:resource_id AS uuid),
                     :owner_id, :access_level, :granted_by, :target_user_id)
                ON CONFLICT (team_id, resource_type, resource_id, COALESCE(target_user_id, ''))
                DO UPDATE SET access_level = EXCLUDED.access_level,
                              granted_by = EXCLUDED.granted_by
                RETURNING *
                """
            ),
            {
                "team_id": team_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "owner_id": owner_id,
                "access_level": access_level,
                "granted_by": granted_by,
                "target_user_id": target_user_id,
            },
        )
        return row_to_dict(result.fetchone())

    def revoke(
        self,
        team_id: str,
        resource_type: str,
        resource_id: str,
        target_user_id: Optional[str] = None,
    ) -> bool:
        """Unshare. ``target_user_id`` None removes the whole-team grant; a sub
        removes that member's grant. Access is lost on the next request."""
        result = self._conn.execute(
            text(
                """
                DELETE FROM team_resource_grants
                WHERE team_id = CAST(:team_id AS uuid)
                  AND resource_type = :resource_type
                  AND resource_id = CAST(:resource_id AS uuid)
                  AND COALESCE(target_user_id, '') = COALESCE(:target_user_id, '')
                """
            ),
            {
                "team_id": team_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "target_user_id": target_user_id,
            },
        )
        return result.rowcount > 0

