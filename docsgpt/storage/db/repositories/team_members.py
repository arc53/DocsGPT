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

from docsgpt.storage.db.base_repository import like_escape, row_to_dict

ROLE_TEAM_ADMIN = "team_admin"
ROLE_TEAM_MEMBER = "team_member"


class MembershipChangeRefused(Exception):
    """A role change or removal that would break a team's invariants.

    Raised by :meth:`TeamMembersRepository.change_membership` before anything is
    written. The team owner keeps their membership and admin role until
    ownership is transferred, and a team always keeps at least one admin.

    Attributes:
        reason: ``OWNER`` (the target owns the team) or ``LAST_ADMIN``.
        change: ``"demote"`` or ``"remove"``.
        self_change: True when the caller is changing their own membership.
    """

    OWNER = "owner"
    LAST_ADMIN = "last_admin"

    def __init__(self, reason: str, change: str, self_change: bool) -> None:
        super().__init__(f"{change} refused: {reason}")
        self.reason = reason
        self.change = change
        self.self_change = self_change


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

    @staticmethod
    def _member_filter(team_id: str, q: Optional[str]) -> tuple[str, dict]:
        """WHERE clause + params for the team's members, optionally searched.

        Args:
            team_id: Team UUID.
            q: Literal, case-insensitive substring matched against the member's
                email and user id; ``None``/blank means no search.

        Returns:
            The ``WHERE`` clause and its bind params.
        """
        where = "WHERE m.team_id = CAST(:team_id AS uuid)"
        params: dict = {"team_id": team_id}
        if q:
            where += (
                " AND (m.user_id ILIKE :q ESCAPE '\\'"
                " OR COALESCE(u.email, '') ILIKE :q ESCAPE '\\')"
            )
            params["q"] = f"%{like_escape(q)}%"
        return where, params

    def list_members(
        self,
        team_id: str,
        *,
        q: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict]:
        """One row per (user, role, source) in the team, ordered by grant time.

        Left-joins ``users`` to surface each member's ``email`` (when on file)
        so the UI can show a human-readable identity instead of the raw sub.
        Ties on ``granted_at`` break on the primary key so paging is stable.

        Args:
            team_id: Team UUID.
            q: Optional case-insensitive substring over email and user id.
            limit: Page size; ``None`` returns every matching row.
            offset: Rows to skip (only applied with ``limit``).

        Returns:
            The member rows as dicts.
        """
        where, params = self._member_filter(team_id, q)
        page = ""
        if limit is not None:
            page = " LIMIT :limit OFFSET :offset"
            params.update({"limit": int(limit), "offset": max(0, int(offset))})
        result = self._conn.execute(
            text(
                f"""
                SELECT m.user_id, m.role, m.source, m.granted_by, m.granted_at,
                       u.email
                FROM team_members m
                LEFT JOIN users u ON u.user_id = m.user_id
                {where}
                ORDER BY m.granted_at, m.user_id, m.role, m.source{page}
                """
            ),
            params,
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def count_members(self, team_id: str, *, q: Optional[str] = None) -> int:
        """Count the rows ``list_members`` would return with the same ``q``.

        Args:
            team_id: Team UUID.
            q: Optional case-insensitive substring over email and user id.

        Returns:
            The number of matching (user, role, source) rows.
        """
        where, params = self._member_filter(team_id, q)
        result = self._conn.execute(
            text(
                f"""
                SELECT count(*) FROM team_members m
                LEFT JOIN users u ON u.user_id = m.user_id
                {where}
                """
            ),
            params,
        )
        return int(result.scalar() or 0)

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
    def change_membership(
        self,
        team_id: str,
        user_id: str,
        role: Optional[str],
        *,
        actor: Optional[str],
    ) -> bool:
        """Set ``user_id``'s manual role, or remove them, keeping the team valid.

        The one guarded write for membership changes: every route that adds,
        re-adds, re-roles or removes a member goes through here. It refuses to
        demote or remove the team owner (ownership is transferred first) and
        to leave the team with no admin. The team row and its admin rows are
        locked (``FOR UPDATE``) so concurrent changes, and an ownership
        transfer, serialize instead of racing past the checks.

        ``add_member`` / ``set_manual_role`` / ``remove_member`` stay
        unguarded primitives for team creation, ownership transfer and tests.

        Args:
            team_id: Team UUID.
            user_id: The member's auth ``sub`` (need not be a member yet).
            role: The manual role to set, or ``None`` to remove every row the
                user holds in the team.
            actor: The caller's ``sub``; recorded as ``granted_by``.

        Returns:
            True. A removal that found no rows returns False.

        Raises:
            MembershipChangeRefused: The change would demote or remove the
                owner, or leave the team with no admin.
        """
        if role != ROLE_TEAM_ADMIN:
            change = "remove" if role is None else "demote"
            owner = self._conn.execute(
                text("SELECT owner_id FROM teams WHERE id = CAST(:team_id AS uuid) FOR UPDATE"),
                {"team_id": team_id},
            ).scalar()
            if owner is not None and owner == user_id:
                raise MembershipChangeRefused(
                    MembershipChangeRefused.OWNER, change, actor == user_id
                )
            admins = self.lock_admins(team_id)
            if user_id in admins and len(admins) <= 1:
                raise MembershipChangeRefused(
                    MembershipChangeRefused.LAST_ADMIN, change, actor == user_id
                )
        if role is None:
            return self.remove_member(team_id, user_id)
        self.set_manual_role(team_id, user_id, role, granted_by=actor)
        return True

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
        are untouched. Unguarded: routes use :meth:`change_membership`.
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
        Unguarded: routes use :meth:`change_membership`.
        """
        sql = "DELETE FROM team_members WHERE team_id = CAST(:team_id AS uuid) AND user_id = :user_id"
        params: dict = {"team_id": team_id, "user_id": user_id}
        if source is not None:
            sql += " AND source = :source"
            params["source"] = source
        result = self._conn.execute(text(sql), params)
        return bool(result.rowcount)
