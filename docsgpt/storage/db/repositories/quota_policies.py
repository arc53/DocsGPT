"""Repository for the ``quota_policies`` table.

One row per ``(scope, subject, bucket)``: the instance default (no subject), a
team's per-member allowance (``teams.id``) or a user's override (auth ``sub``).
All methods take a ``Connection`` and do not manage their own transactions.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import row_to_dict

SCOPES = ("instance", "team", "user")
BUCKETS = ("all", "direct", "agent")

_COLUMNS = (
    "id, scope, subject_id, bucket, token_limit, token_unlimited, cost_limit_usd, "
    "cost_unlimited, enabled, note, created_by, updated_by, created_at, updated_at"
)


def _validate(scope: str, subject_id: Optional[str], bucket: str) -> None:
    if scope not in SCOPES:
        raise ValueError(f"unknown quota scope: {scope!r}")
    if bucket not in BUCKETS:
        raise ValueError(f"unknown quota bucket: {bucket!r}")
    if (scope == "instance") != (subject_id is None):
        raise ValueError("subject_id is required for team and user policies and must be omitted for instance")


class QuotaPoliciesRepository:
    """Admin-set usage limits."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def policies_for_user(self, user_id: str) -> list[dict]:
        """Return every enabled row that applies to ``user_id``.

        That is the instance rows, the user's own rows, and the rows of each
        team the user belongs to (once per team, whatever roles or sources
        the membership has).
        """
        result = self._conn.execute(
            text(
                f"""
                SELECT {_COLUMNS} FROM quota_policies
                WHERE enabled AND (
                    scope = 'instance'
                    OR (scope = 'user' AND subject_id = :user_id)
                    OR (scope = 'team' AND subject_id IN (
                        SELECT DISTINCT team_id::text FROM team_members WHERE user_id = :user_id
                    ))
                )
                """
            ),
            {"user_id": user_id},
        )
        return [row_to_dict(row) for row in result.fetchall()]

    def get(self, scope: str, subject_id: Optional[str], bucket: str = "all") -> Optional[dict]:
        """Return one policy row, or ``None``."""
        _validate(scope, subject_id, bucket)
        row = self._conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM quota_policies "
                "WHERE scope = :scope AND COALESCE(subject_id, '') = :subject AND bucket = :bucket"
            ),
            {"scope": scope, "subject": subject_id or "", "bucket": bucket},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_subject(self, scope: str, subject_id: Optional[str]) -> list[dict]:
        """Return a subject's rows across buckets, ``all`` first."""
        _validate(scope, subject_id, "all")
        result = self._conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM quota_policies "
                "WHERE scope = :scope AND COALESCE(subject_id, '') = :subject "
                "ORDER BY array_position(ARRAY['all', 'direct', 'agent'], bucket)"
            ),
            {"scope": scope, "subject": subject_id or ""},
        )
        return [row_to_dict(row) for row in result.fetchall()]

    def list_by_scope(self, scope: str) -> list[dict]:
        """Return every row of a scope, ordered by subject then bucket."""
        if scope not in SCOPES:
            raise ValueError(f"unknown quota scope: {scope!r}")
        result = self._conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM quota_policies WHERE scope = :scope "
                "ORDER BY subject_id NULLS FIRST, array_position(ARRAY['all', 'direct', 'agent'], bucket)"
            ),
            {"scope": scope},
        )
        return [row_to_dict(row) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def upsert(
        self,
        *,
        scope: str,
        subject_id: Optional[str],
        bucket: str = "all",
        token_limit: Optional[int] = None,
        token_unlimited: bool = False,
        cost_limit_usd: Optional[float] = None,
        cost_unlimited: bool = False,
        enabled: bool = True,
        note: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Create or replace the policy for ``(scope, subject_id, bucket)``.

        Raises:
            ValueError: On an unknown scope or bucket, a subject that does not
                match the scope, a negative limit, or a budget that is both
                limited and unlimited.
        """
        _validate(scope, subject_id, bucket)
        if token_unlimited and token_limit is not None:
            raise ValueError("token budget cannot be both limited and unlimited")
        if cost_unlimited and cost_limit_usd is not None:
            raise ValueError("cost budget cannot be both limited and unlimited")
        if (token_limit is not None and token_limit < 0) or (cost_limit_usd is not None and cost_limit_usd < 0):
            raise ValueError("limits must not be negative")
        row = self._conn.execute(
            text(
                f"""
                INSERT INTO quota_policies (
                    scope, subject_id, bucket, token_limit, token_unlimited,
                    cost_limit_usd, cost_unlimited, enabled, note, created_by, updated_by
                )
                VALUES (
                    :scope, :subject_id, :bucket, :token_limit, :token_unlimited,
                    :cost_limit_usd, :cost_unlimited, :enabled, :note, :actor, :actor
                )
                ON CONFLICT (scope, COALESCE(subject_id, ''), bucket) DO UPDATE SET
                    token_limit = EXCLUDED.token_limit,
                    token_unlimited = EXCLUDED.token_unlimited,
                    cost_limit_usd = EXCLUDED.cost_limit_usd,
                    cost_unlimited = EXCLUDED.cost_unlimited,
                    enabled = EXCLUDED.enabled,
                    note = EXCLUDED.note,
                    updated_by = EXCLUDED.updated_by
                RETURNING {_COLUMNS}
                """
            ),
            {
                "scope": scope,
                "subject_id": subject_id,
                "bucket": bucket,
                "token_limit": token_limit,
                "token_unlimited": token_unlimited,
                "cost_limit_usd": cost_limit_usd,
                "cost_unlimited": cost_unlimited,
                "enabled": enabled,
                "note": note,
                "actor": actor,
            },
        ).one()
        return row_to_dict(row)

    def delete(self, scope: str, subject_id: Optional[str], bucket: Optional[str] = None) -> int:
        """Delete a subject's policy for ``bucket``, or all of them; return the count."""
        _validate(scope, subject_id, bucket or "all")
        clauses = ["scope = :scope", "COALESCE(subject_id, '') = :subject"]
        params = {"scope": scope, "subject": subject_id or ""}
        if bucket is not None:
            clauses.append("bucket = :bucket")
            params["bucket"] = bucket
        result = self._conn.execute(
            text(f"DELETE FROM quota_policies WHERE {' AND '.join(clauses)}"), params
        )
        return result.rowcount
