"""Per-user team visibility resolution.

This is the read-side authorization helper for team sharing: it answers "which
resources of type X can ``user_id`` see via their team memberships?" and "what
access level does ``user_id`` effectively have on resource R?". Membership is
JOINed LIVE against ``team_members`` on every call — never cached, never read
from the JWT — so revoking a membership or a grant drops access on the very next
request (closes the revocation race by construction). The item owner's
membership of the grant's team is JOINed the same way (:func:`live_grant_sql`):
a grant pauses while its owner is out of that team. All methods take a
``Connection``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid

# The item table of each grantable kind.
_TABLES = {"agent": "agents", "source": "sources", "prompt": "prompts", "tool": "user_tools"}


def live_grant_sql(resource_type: str, alias: str = "g") -> str:
    """SQL condition that keeps only the grants that give access right now.

    A grant gives access only while the item's owner is in the grant's team,
    so a member's shares to a team pause while they are out of it (removed or
    left: their ``team_members`` rows are gone) and work again once they are
    re-added; the grant row itself is never touched. Being in the team reads
    as ``team_role_for`` does: any membership row, manual or from the identity
    provider, or being the team's owner. Deactivation keeps the rows, so it
    pauses nothing here. Grants also count on personal items only: an item a
    team workspace owns (moved there after it was granted) is never reached
    through a grant; access there comes from the team role alone
    (``resource_access.resolve``). A grant whose item is gone, or of an
    unknown kind, matches nothing.

    Args:
        resource_type: ``agent``, ``source``, ``prompt`` or ``tool``.
        alias: The ``team_resource_grants`` alias in the surrounding query.

    Returns:
        str: A condition to AND into the query.
    """
    table = _TABLES.get(resource_type)
    if table is None:
        return "FALSE"
    return (
        f"EXISTS (SELECT 1 FROM {table} r WHERE r.id = {alias}.resource_id"
        " AND left(r.user_id, 8) <> '__team__'"
        f" AND (EXISTS (SELECT 1 FROM team_members om WHERE om.team_id = {alias}.team_id"
        " AND om.user_id = r.user_id)"
        f" OR EXISTS (SELECT 1 FROM teams ot WHERE ot.id = {alias}.team_id AND ot.owner_id = r.user_id)))"
    )


def _live(resource_type: str) -> str:
    return " AND " + live_grant_sql(resource_type)


class TeamScopeRepository:
    """Live JOIN of ``team_members`` × ``team_resource_grants`` for one user."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def visible_resource_ids(self, user_id: str, resource_type: str) -> set[str]:
        """The set of ``resource_type`` ids shared to any team ``user_id`` is in.

        Returned as canonical-string UUIDs so callers can build an
        ``id = ANY(:ids)`` union clause against the resource table.
        """
        if not user_id:
            return set()
        result = self._conn.execute(
            text(
                """
                SELECT DISTINCT g.resource_id
                FROM team_resource_grants g
                JOIN team_members m ON m.team_id = g.team_id
                WHERE m.user_id = :user_id AND g.resource_type = :resource_type
                  AND (g.target_user_id IS NULL OR g.target_user_id = :user_id)
                """
                + _live(resource_type)
            ),
            {"user_id": user_id, "resource_type": resource_type},
        )
        return {str(row[0]) for row in result.fetchall()}

    def visible_with_access(self, user_id: str, resource_type: str) -> dict[str, str]:
        """Map of ``resource_id -> strongest access`` shared to the user's teams.

        One query for the whole list path — ``editor`` outranks ``viewer`` per
        resource. Keys are canonical-string UUIDs.
        """
        if not user_id:
            return {}
        result = self._conn.execute(
            text(
                """
                SELECT g.resource_id,
                       CASE WHEN bool_or(g.access_level = 'editor') THEN 'editor'
                            ELSE 'viewer' END AS access_level
                FROM team_resource_grants g
                JOIN team_members m ON m.team_id = g.team_id
                WHERE m.user_id = :user_id AND g.resource_type = :resource_type
                  AND (g.target_user_id IS NULL OR g.target_user_id = :user_id)
                """
                + _live(resource_type)
                + " GROUP BY g.resource_id"
            ),
            {"user_id": user_id, "resource_type": resource_type},
        )
        return {str(row[0]): row[1] for row in result.fetchall()}

    def effective_access(
        self, user_id: str, resource_type: str, resource_id: str
    ) -> Optional[str]:
        """Strongest access ``user_id`` has on a resource via teams, or None.

        ``editor`` outranks ``viewer``. None means no team grant reaches the user
        (they may still be the owner — that is checked separately by the repo's
        dual-key path). Used for both read authz (any value → visible) and write
        authz (``editor`` → may edit).
        """
        # Grant rows only ever hold canonical UUIDs; a non-UUID id (e.g. a
        # legacy Mongo ObjectId reaching the single-fetch fallback) can never
        # match a grant, and CASTing it would raise and poison the txn — so
        # short-circuit to None instead.
        if not user_id or not looks_like_uuid(resource_id):
            return None
        result = self._conn.execute(
            text(
                """
                SELECT CASE WHEN bool_or(g.access_level = 'editor') THEN 'editor'
                            ELSE 'viewer' END AS access_level
                FROM team_resource_grants g
                JOIN team_members m ON m.team_id = g.team_id
                WHERE m.user_id = :user_id
                  AND g.resource_type = :resource_type
                  AND g.resource_id = CAST(:resource_id AS uuid)
                  AND (g.target_user_id IS NULL OR g.target_user_id = :user_id)
                """
                + _live(resource_type)
                + " HAVING count(*) > 0"
            ),
            {"user_id": user_id, "resource_type": resource_type, "resource_id": resource_id},
        )
        row = result.fetchone()
        return row[0] if row is not None else None

    def can_read(self, user_id: str, resource_type: str, resource_id: str) -> bool:
        return self.effective_access(user_id, resource_type, resource_id) is not None

    def can_write(self, user_id: str, resource_type: str, resource_id: str) -> bool:
        return self.effective_access(user_id, resource_type, resource_id) == "editor"
