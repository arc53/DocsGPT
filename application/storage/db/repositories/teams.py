"""Repository for the ``teams`` table.

A team is owned by ``owner_id`` (the creator's auth ``sub``), which is the
durable "who can delete the team" anchor. Membership and role grants live in
``team_members`` ([[team_members]]); shared resources in ``team_resource_grants``.
All methods take a ``Connection`` and do not manage their own transactions.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class TeamsRepository:
    """CRUD for teams keyed by the team UUID."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, team_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM teams WHERE id = CAST(:id AS uuid)"),
            {"id": team_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_slug(self, slug: str) -> Optional[dict]:
        if not slug:
            return None
        result = self._conn.execute(
            text("SELECT * FROM teams WHERE slug = :slug"),
            {"slug": slug},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def slug_exists(self, slug: str) -> bool:
        result = self._conn.execute(
            text("SELECT 1 FROM teams WHERE slug = :slug"),
            {"slug": slug},
        )
        return result.fetchone() is not None

    def list_for_user(self, user_id: str) -> list[dict]:
        """Teams ``user_id`` belongs to, each annotated with the member's role.

        ``role`` is the strongest grant (team_admin > team_member). Ordered by
        team name for stable UI listing.
        """
        if not user_id:
            return []
        result = self._conn.execute(
            text(
                """
                SELECT t.*,
                       CASE WHEN bool_or(m.role = 'team_admin') THEN 'team_admin'
                            ELSE 'team_member' END AS member_role
                FROM teams t
                JOIN team_members m ON m.team_id = t.id
                WHERE m.user_id = :user_id
                GROUP BY t.id
                ORDER BY t.name
                """
            ),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def list_all(self) -> list[dict]:
        """All teams with member counts — global-admin oversight only."""
        result = self._conn.execute(
            text(
                """
                SELECT t.*,
                       (SELECT count(DISTINCT user_id) FROM team_members m
                        WHERE m.team_id = t.id) AS member_count
                FROM teams t
                ORDER BY t.created_at DESC
                """
            )
        )
        return [row_to_dict(r) for r in result.fetchall()]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def create(
        self,
        name: str,
        slug: str,
        owner_id: str,
        description: Optional[str] = None,
    ) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO teams (name, slug, owner_id, description)
                VALUES (:name, :slug, :owner_id, :description)
                RETURNING *
                """
            ),
            {"name": name, "slug": slug, "owner_id": owner_id, "description": description},
        )
        return row_to_dict(result.fetchone())

    def update(self, team_id: str, fields: dict) -> bool:
        """Update mutable team fields (``name``, ``description``). updated_at is
        bumped by the ``teams_set_updated_at`` trigger."""
        allowed = {"name", "description"}
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return False
        set_clause = ", ".join(f"{k} = :{k}" for k in values)
        params = dict(values)
        params["id"] = team_id
        result = self._conn.execute(
            text(f"UPDATE teams SET {set_clause} WHERE id = CAST(:id AS uuid)"),
            params,
        )
        return result.rowcount > 0

    def reassign_owner(self, team_id: str, new_owner_id: str) -> bool:
        """Transfer the deletion-anchor owner to another user (team_admin action)."""
        result = self._conn.execute(
            text("UPDATE teams SET owner_id = :owner_id WHERE id = CAST(:id AS uuid)"),
            {"id": team_id, "owner_id": new_owner_id},
        )
        return result.rowcount > 0

    def delete(self, team_id: str) -> bool:
        """Delete the team. ``team_members`` and ``team_resource_grants`` cascade;
        shared resources revert to owner-only visibility."""
        result = self._conn.execute(
            text("DELETE FROM teams WHERE id = CAST(:id AS uuid)"),
            {"id": team_id},
        )
        return result.rowcount > 0
