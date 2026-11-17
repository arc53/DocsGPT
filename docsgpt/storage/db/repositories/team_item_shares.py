"""Repository for the ``team_item_shares`` table: a team's items shared with whole other teams.

A row says that the team ``owner_team_id`` shares one of its agents, sources,
tools or prompts with every member of ``team_id``. It is separate from
``team_resource_grants`` (a person's items): a team's share outlives whoever
made it (``shared_by``, kept for the record). Rows are raw facts: whether a
share is live (the owning team not locked, the item still the owning team's)
is decided by ``docsgpt/api/user/resource_access.py`` when it is read. Triggers
drop an item's rows when it is deleted or changes owner. All methods take a
``Connection`` and do not manage their own transactions.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict

#: The kinds of item a team may share with another team.
SHAREABLE_TYPES = ("agent", "source", "tool", "prompt")


class TeamItemSharesRepository:
    """Shares keyed by ``(team_id, resource_type, resource_id)``: one per receiving team and item."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def share(
        self, owner_team_id: str, team_id: str, resource_type: str, resource_id: str, shared_by: str
    ) -> dict:
        """Share an item of ``owner_team_id`` with the whole of ``team_id``; a repeat keeps the first row.

        Args:
            owner_team_id: The team that owns the item.
            team_id: The receiving team.
            resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
            resource_id: The item's id.
            shared_by: The person sharing it.

        Returns:
            dict: The share row, plus ``created`` (False when it was already shared with that team).

        Raises:
            ValueError: An unknown kind.
        """
        if resource_type not in SHAREABLE_TYPES:
            raise ValueError(f"not a shareable kind: {resource_type!r}")
        params = {
            "owner": str(owner_team_id), "team": str(team_id), "type": resource_type,
            "id": str(resource_id), "by": shared_by,
        }
        row = self._conn.execute(
            text(
                """
                INSERT INTO team_item_shares (owner_team_id, team_id, resource_type, resource_id, shared_by)
                VALUES (CAST(:owner AS uuid), CAST(:team AS uuid), :type, CAST(:id AS uuid), :by)
                ON CONFLICT (team_id, resource_type, resource_id) DO NOTHING
                RETURNING *
                """
            ),
            params,
        ).fetchone()
        if row is not None:
            return {**row_to_dict(row), "created": True}
        existing = self.get(team_id, resource_type, resource_id)
        return {**(existing or {}), "created": False}

    def get(self, team_id: str, resource_type: str, resource_id: str) -> Optional[dict]:
        """The share of one item with one receiving team, or None."""
        if not looks_like_uuid(str(team_id)) or not looks_like_uuid(str(resource_id)):
            return None
        row = self._conn.execute(
            text(
                "SELECT * FROM team_item_shares WHERE team_id = CAST(:team AS uuid) AND resource_type = :type "
                "AND resource_id = CAST(:id AS uuid)"
            ),
            {"team": str(team_id), "type": resource_type, "id": str(resource_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def revoke(self, team_id: str, resource_type: str, resource_id: str) -> bool:
        """Stop sharing an item with a receiving team.

        Returns:
            bool: True when a share was removed.
        """
        if not looks_like_uuid(str(team_id)) or not looks_like_uuid(str(resource_id)):
            return False
        result = self._conn.execute(
            text(
                "DELETE FROM team_item_shares WHERE team_id = CAST(:team AS uuid) AND resource_type = :type "
                "AND resource_id = CAST(:id AS uuid)"
            ),
            {"team": str(team_id), "type": resource_type, "id": str(resource_id)},
        )
        return result.rowcount > 0

    def list_from(self, owner_team_id: str) -> list[dict]:
        """Every share a team made, newest first, each with the receiving team's ``team_name``."""
        if not looks_like_uuid(str(owner_team_id)):
            return []
        rows = self._conn.execute(
            text(
                """
                SELECT s.*, t.name AS team_name FROM team_item_shares s JOIN teams t ON t.id = s.team_id
                WHERE s.owner_team_id = CAST(:owner AS uuid)
                ORDER BY s.created_at DESC, s.id
                """
            ),
            {"owner": str(owner_team_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_into(self, team_id: str, resource_type: Optional[str] = None) -> list[dict]:
        """Every share a team received, newest first, each with the owning team's ``owner_team_name``.

        Args:
            team_id: The receiving team.
            resource_type: Only this kind, when given.
        """
        if not looks_like_uuid(str(team_id)):
            return []
        sql = (
            "SELECT s.*, t.name AS owner_team_name FROM team_item_shares s JOIN teams t ON t.id = s.owner_team_id "
            "WHERE s.team_id = CAST(:team AS uuid)"
        )
        params: dict = {"team": str(team_id)}
        if resource_type is not None:
            sql += " AND s.resource_type = :type"
            params["type"] = resource_type
        rows = self._conn.execute(text(sql + " ORDER BY s.created_at DESC, s.id"), params).fetchall()
        return [row_to_dict(r) for r in rows]

    def teams_for(self, resource_type: str, resource_id: str) -> list[dict]:
        """The teams one item is shared with, by name, each row with ``team_name``."""
        if not looks_like_uuid(str(resource_id)):
            return []
        rows = self._conn.execute(
            text(
                """
                SELECT s.*, t.name AS team_name FROM team_item_shares s JOIN teams t ON t.id = s.team_id
                WHERE s.resource_type = :type AND s.resource_id = CAST(:id AS uuid)
                ORDER BY t.name, s.team_id
                """
            ),
            {"type": resource_type, "id": str(resource_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def reaching(self, user_id: str, resource_type: str, resource_id: str) -> list[dict]:
        """The shares of an item into teams the person is in (a member, or the team's Owner).

        Rows come oldest first, each with the receiving ``team_name`` and the ``owner_team_name``.
        Whether a share is live (owning team not locked, item still that team's) is not checked here.
        """
        if not user_id or not looks_like_uuid(str(resource_id)):
            return []
        rows = self._conn.execute(
            text(
                """
                SELECT s.*, t.name AS team_name, o.name AS owner_team_name
                FROM team_item_shares s
                JOIN teams t ON t.id = s.team_id
                JOIN teams o ON o.id = s.owner_team_id
                WHERE s.resource_type = :type AND s.resource_id = CAST(:id AS uuid)
                  AND (t.owner_id = :user
                       OR EXISTS (SELECT 1 FROM team_members m WHERE m.team_id = s.team_id AND m.user_id = :user))
                ORDER BY s.created_at, s.team_id
                """
            ),
            {"type": resource_type, "id": str(resource_id), "user": user_id},
        ).fetchall()
        return [row_to_dict(r) for r in rows]
