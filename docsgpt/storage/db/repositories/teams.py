"""Repository for the ``teams`` table.

A team is owned by ``owner_id`` (the creator's auth ``sub``), which is the
durable "who can delete the team" anchor. Membership and role grants live in
``team_members`` ([[team_members]]); shared resources in ``team_resource_grants``.
The team's own items are owned by its principal ``users`` row
(``docsgpt/workspaces/principal.py``), created here with the team.
All methods take a ``Connection`` and do not manage their own transactions.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import like_escape, looks_like_uuid, row_to_dict
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

#: The outside policies a team may have (``docsgpt/workspaces/outside.py::POLICIES``).
_OUTSIDE_POLICIES = ("admins", "editors", "locked")

#: The item tables a team workspace owns, by kind (the counts of a refused delete).
_ITEM_KINDS = {
    "agents": "agent",
    "sources": "source",
    "user_tools": "tool",
    "prompts": "prompt",
    "workflows": "workflow",
    "folders": "folder",
    "connector_sessions": "connection",
}

# Every single-column FK onto ``users(user_id)``: the tables that can hold a principal's rows, and
# whether each row may hang off a conversation (and so goes with a principal's chat).
_USER_FK_SQL = """
    SELECT c.conrelid::regclass::text AS tbl, a.attname AS col,
           EXISTS (SELECT 1 FROM pg_attribute ca WHERE ca.attrelid = c.conrelid
                   AND ca.attname = 'conversation_id' AND NOT ca.attisdropped) AS in_chat
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass AND array_length(c.conkey, 1) = 1
    ORDER BY 1, 2
"""


class TeamNotEmpty(Exception):
    """A team delete refused because its principal still owns rows.

    Attributes:
        counts: ``{kind: n}`` for item tables (``agent``, ``source``, ``tool``, ``prompt``, ``workflow``,
            ``folder``) and ``{table: n}`` for any other table that holds the principal's rows.
    """

    def __init__(self, counts: dict[str, int]) -> None:
        super().__init__(f"team still owns {counts}")
        self.counts = counts


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
                            ELSE 'team_member' END AS member_role,
                       (SELECT count(DISTINCT mm.user_id) FROM team_members mm
                        WHERE mm.team_id = t.id) AS member_count,
                       (SELECT count(DISTINCT g.resource_id)
                        FROM team_resource_grants g
                        WHERE g.team_id = t.id) AS shared_count
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

    def search(self, q: Optional[str] = None, without_quota: bool = False, limit: int = 20) -> list[dict]:
        """Teams matching a picker query, shaped like :meth:`list_all` — global-admin only.

        Args:
            q: Case-insensitive substring of the team name or slug; ``None`` or
                blank matches every team.
            without_quota: Only teams with no team-scope ``all``-bucket quota
                policy (enabled or not) — the teams an admin can still give an
                allowance to.
            limit: The most rows to return.

        Returns:
            Team rows with ``member_count``, newest first (ties broken by id).
        """
        clauses = []
        params: dict = {"limit": limit}
        if q and q.strip():
            clauses.append("(t.name ILIKE :pattern ESCAPE '\\' OR t.slug ILIKE :pattern ESCAPE '\\')")
            params["pattern"] = f"%{like_escape(q.strip())}%"
        if without_quota:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM quota_policies p WHERE p.scope = 'team' "
                "AND p.bucket = 'all' AND p.subject_id = CAST(t.id AS text))"
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        result = self._conn.execute(
            text(
                f"""
                SELECT t.*,
                       (SELECT count(DISTINCT user_id) FROM team_members m
                        WHERE m.team_id = t.id) AS member_count
                FROM teams t
                {where}
                ORDER BY t.created_at DESC, t.id
                LIMIT :limit
                """
            ),
            params,
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
        """Insert a team and its principal row, in the caller's transaction.

        Args:
            name: Display name.
            slug: Unique slug.
            owner_id: The creator's ``sub``.
            description: Optional description.

        Returns:
            The team row.
        """
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
        team = row_to_dict(result.fetchone())
        UsersRepository(self._conn).create_team_principal(str(team["id"]))
        return team

    # Each updatable column maps to a CONSTANT SQL fragment. The SET clause is
    # assembled only from these literals (selected by whitelisted keys), so no
    # user-controlled string ever reaches the query text — values travel as
    # bound parameters. Keeps the query injection-free by construction.
    _UPDATABLE_COLUMNS = {
        "name": "name = :name",
        "description": "description = :description",
    }

    def update(self, team_id: str, fields: dict) -> bool:
        """Update mutable team fields (``name``, ``description``). updated_at is
        bumped by the ``teams_set_updated_at`` trigger."""
        values = {k: v for k, v in fields.items() if k in self._UPDATABLE_COLUMNS}
        if not values:
            return False
        set_clause = ", ".join(self._UPDATABLE_COLUMNS[k] for k in values)
        params = dict(values)
        params["id"] = team_id
        result = self._conn.execute(
            text(f"UPDATE teams SET {set_clause} WHERE id = CAST(:id AS uuid)"),
            params,
        )
        return result.rowcount > 0

    def get_outside_policy(self, team_id: str, *, lock: Optional[str] = None) -> Optional[str]:
        """A team's outside policy as stored, or None for no such team.

        Args:
            team_id: The team.
            lock: ``share`` or ``update`` to lock the team row until the transaction ends.

        Returns:
            Optional[str]: ``admins``, ``editors`` or ``locked``.
        """
        if not looks_like_uuid(str(team_id)):
            return None
        suffix = {"share": " FOR SHARE", "update": " FOR UPDATE"}.get(lock or "", "")
        return self._conn.execute(
            text(f"SELECT outside_policy FROM teams WHERE id = CAST(:id AS uuid){suffix}"), {"id": str(team_id)}
        ).scalar()

    def set_outside_policy(self, team_id: str, policy: str) -> Optional[str]:
        """Set a team's outside policy (who may check is the caller's business).

        Args:
            team_id: The team.
            policy: ``admins``, ``editors`` or ``locked``.

        Returns:
            Optional[str]: The policy before, or None when there is no such team.

        Raises:
            ValueError: An unknown policy.
        """
        if policy not in _OUTSIDE_POLICIES:
            raise ValueError(f"not an outside policy: {policy!r}")
        if not looks_like_uuid(str(team_id)):
            return None
        row = self._conn.execute(
            text(
                """
                UPDATE teams t SET outside_policy = :policy
                FROM (SELECT id, outside_policy FROM teams WHERE id = CAST(:id AS uuid) FOR UPDATE) before
                WHERE t.id = before.id
                RETURNING before.outside_policy
                """
            ),
            {"id": str(team_id), "policy": policy},
        ).fetchone()
        return row[0] if row is not None else None

    def reassign_owner(self, team_id: str, new_owner_id: str) -> bool:
        """Transfer the deletion-anchor owner to another user (team_admin action)."""
        result = self._conn.execute(
            text("UPDATE teams SET owner_id = :owner_id WHERE id = CAST(:id AS uuid)"),
            {"id": team_id, "owner_id": new_owner_id},
        )
        return result.rowcount > 0

    def admin_ids(self, team_id: str) -> list[str]:
        """The team's owner and every person holding ``team_admin`` (any source), sorted.

        Args:
            team_id: Team UUID.

        Returns:
            The distinct person ids; empty for an unknown team.
        """
        rows = self._conn.execute(
            text(
                """
                SELECT owner_id FROM teams WHERE id = CAST(:id AS uuid)
                UNION
                SELECT user_id FROM team_members WHERE team_id = CAST(:id AS uuid) AND role = 'team_admin'
                """
            ),
            {"id": team_id},
        ).fetchall()
        return sorted({str(r[0]) for r in rows if r[0]})

    def workspaces_for(self, user_id: str) -> list[dict]:
        """The teams a person is in (as owner or member), by name, for the workspace switcher.

        Args:
            user_id: The person's id.

        Returns:
            Team rows with ``is_owner``, ``stored_roles`` (their ``team_members.role`` values) and
            ``member_count`` (distinct people, the owner included).
        """
        if not user_id:
            return []
        rows = self._conn.execute(
            text(
                """
                SELECT t.*, t.owner_id = :user_id AS is_owner,
                       (SELECT array_agg(DISTINCT m.role) FROM team_members m
                        WHERE m.team_id = t.id AND m.user_id = :user_id) AS stored_roles,
                       (SELECT count(*) FROM (SELECT mm.user_id FROM team_members mm WHERE mm.team_id = t.id
                                              UNION SELECT t.owner_id) people) AS member_count
                FROM teams t
                WHERE t.owner_id = :user_id
                   OR EXISTS (SELECT 1 FROM team_members m WHERE m.team_id = t.id AND m.user_id = :user_id)
                ORDER BY lower(t.name), t.id
                """
            ),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in rows.fetchall()]

    def principal_holdings(self, team_id: str) -> dict[str, int]:
        """What the team's principal still owns, apart from its chats (which go with the team).

        Args:
            team_id: Team UUID.

        Returns:
            ``{kind: n}`` for item tables and ``{table: n}`` for any other table, non-zero entries only.
        """
        principal = principal_id(team_id)
        counts: dict[str, int] = {}
        for table, column, in_chat in self._conn.execute(text(_USER_FK_SQL)).fetchall():
            if table == "conversations":
                continue
            # Rows of the principal's own chats cascade with them.
            not_in_its_chats = (
                " AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id = t.conversation_id "
                "AND c.user_id = :principal)"
                if in_chat
                else ""
            )
            # The table and column names come from the catalog, not from a request.
            n = self._conn.execute(
                text(f'SELECT count(*) FROM {table} t WHERE t."{column}" = :principal{not_in_its_chats}'),
                {"principal": principal},
            ).scalar()
            if n:
                key = _ITEM_KINDS.get(table, table)
                counts[key] = counts.get(key, 0) + int(n)
        return counts

    def delete(self, team_id: str) -> bool:
        """Delete an empty team, its principal and its chats.

        Refused while the principal owns anything (an Admin moves or deletes
        items first). Then the principal's own chats (a deleted team agent's
        widget or key chats) and the members' chats in the team
        (``conversations.team_id ON DELETE CASCADE``) go with it;
        ``team_members`` and ``team_resource_grants`` cascade, and personal
        items shared to the team revert to owner-only visibility.

        Args:
            team_id: Team UUID.

        Returns:
            True when the team was deleted; False when it doesn't exist.

        Raises:
            TeamNotEmpty: The principal still owns rows (``counts`` says which).
        """
        if self.get(team_id) is None:
            return False
        holdings = self.principal_holdings(team_id)
        if holdings:
            raise TeamNotEmpty(holdings)
        principal = principal_id(team_id)
        self._conn.execute(text("DELETE FROM conversations WHERE user_id = :p"), {"p": principal})
        self._conn.execute(text("DELETE FROM users WHERE user_id = :p AND kind = 'team'"), {"p": principal})
        result = self._conn.execute(
            text("DELETE FROM teams WHERE id = CAST(:id AS uuid)"),
            {"id": team_id},
        )
        return result.rowcount > 0
