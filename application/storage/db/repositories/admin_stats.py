"""Read-only cross-table aggregations for the admin dashboard.

Unlike the per-table repositories, this one answers operator-level questions
that span tables (counts, engagement, spend). All methods are read-only and
time-bounded where they touch large tables, so they are safe to call from an
admin-gated dashboard but should not be put on any hot path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class AdminStatsRepository:
    """Global aggregates for the admin overview and per-user drill-down."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def _scalar(self, sql: str, params: dict | None = None) -> int:
        return int(self._conn.execute(text(sql), params or {}).scalar() or 0)

    def overview(self) -> dict:
        """Top-line counts + recent-window engagement for the dashboard home."""
        now = datetime.now(timezone.utc)
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)

        users_total = self._scalar("SELECT count(*) FROM users")
        users_active = self._scalar("SELECT count(*) FROM users WHERE active")
        return {
            "users": {
                "total": users_total,
                "active": users_active,
                "inactive": users_total - users_active,
            },
            "admins": self._scalar(
                "SELECT count(DISTINCT user_id) FROM user_roles WHERE role = 'admin'"
            ),
            "agents": self._scalar("SELECT count(*) FROM agents"),
            "sources": self._scalar("SELECT count(*) FROM sources"),
            "conversations": self._scalar("SELECT count(*) FROM conversations"),
            "new_users_7d": self._scalar(
                "SELECT count(*) FROM users WHERE created_at >= :c", {"c": cutoff_7d}
            ),
            "active_users_30d": self._scalar(
                "SELECT count(DISTINCT user_id) FROM token_usage "
                "WHERE timestamp >= :c AND user_id IS NOT NULL",
                {"c": cutoff_30d},
            ),
            "failed_logins_7d": self._scalar(
                "SELECT count(*) FROM auth_events "
                "WHERE event = 'oidc_login_denied' AND created_at >= :c",
                {"c": cutoff_7d},
            ),
            "tokens_30d": self._scalar(
                "SELECT COALESCE(SUM(prompt_tokens + generated_tokens), 0) "
                "FROM token_usage WHERE timestamp >= :c",
                {"c": cutoff_30d},
            ),
        }

    def top_token_users(self, *, since: datetime, limit: int = 10) -> list[dict]:
        """Highest token consumers since ``since`` (admin usage view)."""
        result = self._conn.execute(
            text(
                """
                SELECT user_id, SUM(prompt_tokens + generated_tokens) AS tokens
                FROM token_usage
                WHERE timestamp >= :since AND user_id IS NOT NULL
                GROUP BY user_id
                ORDER BY tokens DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": int(limit)},
        )
        return [{"user_id": r[0], "tokens": int(r[1])} for r in result.fetchall()]

    def list_users(
        self, user_id_filter: Optional[str], offset: int, limit: int
    ) -> tuple[int, list[dict]]:
        """Paginated users with their last auth-event time, most-recently-seen first.

        ``last_seen`` is max(auth_events.created_at) for the user (NULL = never).
        Ordering surfaces active accounts first, dormant ones last — the natural
        triage order for an operator.
        """
        where = ""
        count_params: dict = {}
        if user_id_filter is not None:
            where = "WHERE u.user_id ILIKE '%' || :uid || '%'"
            count_params["uid"] = user_id_filter
        total = self._conn.execute(
            text(f"SELECT count(*) FROM users u {where}"), count_params
        ).scalar_one()
        result = self._conn.execute(
            text(
                f"""
                SELECT u.user_id, u.active, u.created_at,
                       max(ae.created_at) AS last_seen
                FROM users u
                LEFT JOIN auth_events ae ON ae.user_id = u.user_id
                {where}
                GROUP BY u.user_id, u.active, u.created_at
                ORDER BY max(ae.created_at) DESC NULLS LAST, u.created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**count_params, "limit": int(limit), "offset": int(offset)},
        )
        return int(total), [row_to_dict(row) for row in result.fetchall()]

    def user_counts(self, user_id: str) -> dict:
        """Per-user resource counts for the drill-down view."""
        cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
        return {
            "agents": self._scalar(
                "SELECT count(*) FROM agents WHERE user_id = :u", {"u": user_id}
            ),
            "sources": self._scalar(
                "SELECT count(*) FROM sources WHERE user_id = :u", {"u": user_id}
            ),
            "conversations": self._scalar(
                "SELECT count(*) FROM conversations WHERE user_id = :u", {"u": user_id}
            ),
            "tokens_30d": self._scalar(
                "SELECT COALESCE(SUM(prompt_tokens + generated_tokens), 0) "
                "FROM token_usage WHERE user_id = :u AND timestamp >= :c",
                {"u": user_id, "c": cutoff_30d},
            ),
        }
