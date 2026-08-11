"""Per-user team visibility resolution.

This is the read-side authorization helper for team sharing: it answers "which
resources of type X can ``user_id`` see via their team memberships?" and "what
access level does ``user_id`` effectively have on resource R?". Membership is
JOINed LIVE against ``team_members`` on every call — never cached, never read
from the JWT — so revoking a membership or a grant drops access on the very next
request (closes the revocation race by construction). All methods take a
``Connection``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import looks_like_uuid


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
                GROUP BY g.resource_id
                """
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
                HAVING count(*) > 0
                """
            ),
            {"user_id": user_id, "resource_type": resource_type, "resource_id": resource_id},
        )
        row = result.fetchone()
        return row[0] if row is not None else None

    def can_read(self, user_id: str, resource_type: str, resource_id: str) -> bool:
        return self.effective_access(user_id, resource_type, resource_id) is not None

    def can_write(self, user_id: str, resource_type: str, resource_id: str) -> bool:
        return self.effective_access(user_id, resource_type, resource_id) == "editor"
