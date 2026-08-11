"""Repository for the ``team_members`` table (membership + team-scoped roles).

Field-for-field on ``user_roles``: grants are keyed by
``(team_id, user_id, role, source)`` so a manual grant and a future IdP-derived
grant for the same user coexist and revoke independently. ``user_id`` is the
auth ``sub``. The ``team_member`` role is NOT implicit — every member has at
least one row (unlike the global ``user`` role). All methods take a
``Connection`` and do not manage their own transactions.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict

ROLE_TEAM_ADMIN = "team_admin"
ROLE_TEAM_MEMBER = "team_member"


class TeamMembersRepository:
    """Team membership grants keyed by the auth ``sub`` (``user_id``)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def role_for(self, user_id: str, team_id: str) -> Optional[str]:
        """Strongest role ``user_id`` holds in ``team_id`` (any source), or None.

        ``team_admin`` outranks ``team_member``. Returns None when the user is
        not a member — the caller treats that as "no team access".
        """
        if not user_id or not team_id:
            return None
        result = self._conn.execute(
            text(
                """
                SELECT CASE WHEN bool_or(role = 'team_admin') THEN 'team_admin'
                            ELSE 'team_member' END AS role
                FROM team_members
                WHERE team_id = CAST(:team_id AS uuid) AND user_id = :user_id
                HAVING count(*) > 0
                """
            ),
            {"team_id": team_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row[0] if row is not None else None

    def is_member(self, user_id: str, team_id: str) -> bool:
        return self.role_for(user_id, team_id) is not None

    def list_team_ids_for(self, user_id: str) -> list[str]:
        """The distinct team ids ``user_id`` belongs to (hot authz reverse lookup)."""
        if not user_id:
            return []
        result = self._conn.execute(
            text("SELECT DISTINCT team_id FROM team_members WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return [str(row[0]) for row in result.fetchall()]

    def list_members(self, team_id: str) -> list[dict]:
        """One row per (user, role, source) in the team, ordered by grant time.

        Left-joins ``users`` to surface each member's ``email`` (when on file)
        so the UI can show a human-readable identity instead of the raw sub.
        """
        result = self._conn.execute(
            text(
                """
                SELECT m.user_id, m.role, m.source, m.granted_by, m.granted_at,
                       u.email
                FROM team_members m
                LEFT JOIN users u ON u.user_id = m.user_id
                WHERE m.team_id = CAST(:team_id AS uuid)
                ORDER BY m.granted_at
                """
            ),
            {"team_id": team_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def count_admins(self, team_id: str) -> int:
        """Distinct users holding ``team_admin`` — for the last-admin guard."""
        result = self._conn.execute(
            text(
                """
                SELECT count(DISTINCT user_id) FROM team_members
                WHERE team_id = CAST(:team_id AS uuid) AND role = 'team_admin'
                """
            ),
            {"team_id": team_id},
        )
        return int(result.scalar() or 0)

    def lock_admins(self, team_id: str) -> list[str]:
        """Lock the team's ``team_admin`` rows and return the distinct admins.

        ``SELECT ... FOR UPDATE`` inside the caller's write transaction
        serializes concurrent demote/remove operations on the team's admins, so
        the last-admin guard can't be raced into orphaning the team (two
        concurrent removes both seeing count=2). ``DISTINCT`` is incompatible
        with ``FOR UPDATE``, so de-dup in Python (a user may hold team_admin via
        multiple sources).
        """
        result = self._conn.execute(
            text(
                """
                SELECT user_id FROM team_members
                WHERE team_id = CAST(:team_id AS uuid) AND role = 'team_admin'
                FOR UPDATE
                """
            ),
            {"team_id": team_id},
        )
        return sorted({str(row[0]) for row in result.fetchall()})

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def add_member(
        self,
        team_id: str,
        user_id: str,
        role: str = ROLE_TEAM_MEMBER,
        source: str = "manual",
        granted_by: Optional[str] = None,
    ) -> bool:
        """Idempotently add a membership grant. Returns True if a row was inserted."""
        result = self._conn.execute(
            text(
                """
                INSERT INTO team_members (team_id, user_id, role, source, granted_by)
                VALUES (CAST(:team_id AS uuid), :user_id, :role, :source, :granted_by)
                ON CONFLICT (team_id, user_id, role, source) DO NOTHING
                """
            ),
            {
                "team_id": team_id,
                "user_id": user_id,
                "role": role,
                "source": source,
                "granted_by": granted_by,
            },
        )
        return bool(result.rowcount)

    def set_manual_role(
        self,
        team_id: str,
        user_id: str,
        role: str,
        granted_by: Optional[str] = None,
    ) -> None:
        """Set the user's ``manual`` role to exactly ``role`` (promote/demote).

        Deletes any other manual role row for the user in this team, then adds
        the target — keeping the single-manual-role invariant. IdP-sourced rows
        are untouched.
        """
        self._conn.execute(
            text(
                """
                DELETE FROM team_members
                WHERE team_id = CAST(:team_id AS uuid)
                  AND user_id = :user_id AND source = 'manual' AND role <> :role
                """
            ),
            {"team_id": team_id, "user_id": user_id, "role": role},
        )
        self.add_member(team_id, user_id, role=role, source="manual", granted_by=granted_by)

    def remove_member(
        self,
        team_id: str,
        user_id: str,
        source: Optional[str] = None,
    ) -> bool:
        """Remove the user's membership rows from the team.

        When ``source`` is given only that source's rows are removed (so an IdP
        sync can't wipe a manual grant); otherwise every role/source row for the
        user in the team is removed. Returns True if anything was deleted.
        """
        sql = "DELETE FROM team_members WHERE team_id = CAST(:team_id AS uuid) AND user_id = :user_id"
        params: dict = {"team_id": team_id, "user_id": user_id}
        if source is not None:
            sql += " AND source = :source"
            params["source"] = source
        result = self._conn.execute(text(sql), params)
        return bool(result.rowcount)
