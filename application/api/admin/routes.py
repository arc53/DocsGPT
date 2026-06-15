"""Admin-gated management endpoints (RBAC ``admin`` role required).

Every resource here is behind ``@admin_required``. The frontend route guard is
cosmetic — this server-side decorator is the actual security boundary, so any
new endpoint added to this namespace MUST carry it.

Reads are cross-user aggregates/feeds (deliberately *not* scoped to the
caller's ``sub``, unlike the rest of the API). Mutations (role grant/revoke,
deactivate, force-logout) are written through the existing repositories and
audited to ``auth_events`` with the acting admin recorded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from application.api.oidc import denylist
from application.api.user.authz import ROLE_ADMIN, admin_required
from application.storage.db.repositories.admin_stats import AdminStatsRepository
from application.storage.db.repositories.auth_events import AuthEventsRepository
from application.storage.db.repositories.device_audit_log import DeviceAuditLogRepository
from application.storage.db.repositories.token_usage import TokenUsageRepository
from application.storage.db.repositories.user_roles import UserRolesRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

admin_ns = Namespace("admin", description="Admin-only management endpoints", path="/api")

_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 100


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def _page() -> tuple[int, int, int]:
    page = max(1, _int_arg("page", 1))
    page_size = max(1, min(_MAX_PAGE_SIZE, _int_arg("page_size", _DEFAULT_PAGE_SIZE)))
    return page, page_size, (page - 1) * page_size


def _actor() -> str | None:
    token = getattr(request, "decoded_token", None)
    return token.get("sub") if isinstance(token, dict) else None


def _since_arg(default_days: int) -> datetime | None:
    """``?since_days=N`` → a UTC cutoff datetime, or None for 'all time'."""
    days = _int_arg("since_days", default_days)
    if days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


@admin_ns.route("/admin/overview")
class AdminOverviewResource(Resource):
    @admin_required
    def get(self):
        """Top-line KPIs for the dashboard home."""
        with db_readonly() as conn:
            stats = AdminStatsRepository(conn).overview()
        return make_response(jsonify({"success": True, **stats}), 200)


@admin_ns.route("/admin/users")
class AdminUsersResource(Resource):
    @admin_required
    def get(self):
        """List users, paginated, most-recently-seen first.

        Each row carries ``last_seen`` (max auth-event time). Admin status is
        intentionally not joined here; the dashboard cross-references
        GET /api/admin/admins for badges.
        """
        page, page_size, offset = _page()
        user_id_filter = request.args.get("user_id") or None
        with db_readonly() as conn:
            total, rows = AdminStatsRepository(conn).list_users(
                user_id_filter, offset, page_size
            )
        users = [
            {
                "user_id": row.get("user_id"),
                "active": bool(row.get("active", True)),
                "created_at": row.get("created_at"),
                "last_seen": row.get("last_seen"),
            }
            for row in rows
        ]
        return make_response(
            jsonify(
                {
                    "success": True,
                    "users": users,
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "has_more": offset + len(rows) < total,
                }
            ),
            200,
        )


@admin_ns.route("/admin/users/<string:user_id>")
class AdminUserResource(Resource):
    @admin_required
    def get(self, user_id):
        """Per-user drill-down: profile, roles, recent auth events, counts."""
        with db_readonly() as conn:
            user = UsersRepository(conn).get(user_id)
            if user is None:
                return make_response(jsonify({"success": False}), 404)
            roles_repo = UserRolesRepository(conn)
            body = {
                "success": True,
                "user": {
                    "user_id": user.get("user_id"),
                    "active": bool(user.get("active", True)),
                    "created_at": user.get("created_at"),
                    "updated_at": user.get("updated_at"),
                },
                "roles": sorted({"user", *roles_repo.role_names_for(user_id)}),
                "grants": roles_repo.list_for(user_id),
                "recent_events": AuthEventsRepository(conn).list_recent(
                    user_id, limit=20
                ),
                "counts": AdminStatsRepository(conn).user_counts(user_id),
            }
        return make_response(jsonify(body), 200)

    @admin_required
    def patch(self, user_id):
        """Activate/deactivate a user. Deactivation also revokes live sessions."""
        actor = _actor()
        data = request.get_json(silent=True) or {}
        if "active" not in data or not isinstance(data["active"], bool):
            return make_response(
                jsonify({"success": False, "message": "Body requires boolean 'active'"}),
                400,
            )
        active = data["active"]
        if not active and user_id == actor:
            return make_response(
                jsonify(
                    {"success": False, "message": "You cannot deactivate yourself"}
                ),
                409,
            )
        with db_session() as conn:
            user = UsersRepository(conn).get(user_id)
            if user is None:
                return make_response(jsonify({"success": False}), 404)
            updated = UsersRepository(conn).set_active(str(user["id"]), active)
            AuthEventsRepository(conn).insert(
                user_id,
                "admin_user_activated" if active else "admin_user_deactivated",
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
                metadata={"by": actor, "via": "admin_api"},
            )
        if not active:
            # Best-effort live-session revocation (mirrors SCIM deactivation).
            denylist.deny_user(user_id)
        return make_response(
            jsonify({"success": True, "active": bool(updated.get("active", active))}),
            200,
        )


@admin_ns.route("/admin/users/<string:user_id>/role")
class AdminUserRoleResource(Resource):
    @admin_required
    def post(self, user_id):
        """Grant the admin role to ``user_id`` (manual source). Idempotent."""
        actor = _actor()
        with db_session() as conn:
            inserted = UserRolesRepository(conn).grant(
                user_id, ROLE_ADMIN, source="manual", granted_by=actor
            )
            if inserted:
                AuthEventsRepository(conn).insert(
                    user_id,
                    "role_granted",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata={
                        "role": ROLE_ADMIN,
                        "source": "manual",
                        "granted_by": actor,
                        "via": "admin_api",
                    },
                )
        return make_response(
            jsonify({"success": True, "granted": inserted, "role": ROLE_ADMIN}), 200
        )

    @admin_required
    def delete(self, user_id):
        """Revoke the manual admin grant. Refuses to remove the last admin."""
        actor = _actor()
        with db_session() as conn:
            roles_repo = UserRolesRepository(conn)
            admins = roles_repo.list_admins()
            if len(admins) <= 1 and any(a["user_id"] == user_id for a in admins):
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Cannot remove the last admin",
                        }
                    ),
                    409,
                )
            removed = roles_repo.revoke(user_id, ROLE_ADMIN, source="manual")
            if removed:
                AuthEventsRepository(conn).insert(
                    user_id,
                    "role_revoked",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata={
                        "role": ROLE_ADMIN,
                        "source": "manual",
                        "revoked_by": actor,
                        "via": "admin_api",
                    },
                )
        return make_response(jsonify({"success": True, "revoked": removed}), 200)


@admin_ns.route("/admin/users/<string:user_id>/revoke-sessions")
class AdminUserSessionsResource(Resource):
    @admin_required
    def post(self, user_id):
        """Force-logout: revoke the user's live OIDC sessions (best-effort)."""
        ok = denylist.deny_user(user_id)
        with db_session() as conn:
            AuthEventsRepository(conn).insert(
                user_id,
                "admin_sessions_revoked",
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
                metadata={"by": _actor(), "via": "admin_api", "persisted": ok},
            )
        return make_response(jsonify({"success": True, "revoked": ok}), 200)


@admin_ns.route("/admin/admins")
class AdminAdminsResource(Resource):
    @admin_required
    def get(self):
        """List all admins with earliest grant time + grant sources."""
        with db_readonly() as conn:
            admins = UserRolesRepository(conn).list_admins()
        return make_response(jsonify({"success": True, "admins": admins}), 200)


@admin_ns.route("/admin/usage")
class AdminUsageResource(Resource):
    _GROUP_BY = ("none", "model", "agent", "source")
    _BUCKETS = ("day", "hour")

    @admin_required
    def get(self):
        """Global token usage: time-bucketed series + total + top users."""
        days = max(1, min(365, _int_arg("days", 30)))
        bucket = request.args.get("bucket", "day")
        group_by = request.args.get("group_by", "none")
        if bucket not in self._BUCKETS or group_by not in self._GROUP_BY:
            return make_response(jsonify({"success": False, "message": "Invalid option"}), 400)
        start = datetime.now(timezone.utc) - timedelta(days=days)
        with db_readonly() as conn:
            usage_repo = TokenUsageRepository(conn)
            series = usage_repo.bucketed_totals(
                bucket_unit=bucket,
                timestamp_gte=start,
                group_by=None if group_by == "none" else group_by,
            )
            total = usage_repo.sum_tokens_in_range(
                start=start, end=datetime.now(timezone.utc)
            )
            top_users = AdminStatsRepository(conn).top_token_users(since=start, limit=10)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "days": days,
                    "bucket": bucket,
                    "group_by": group_by,
                    "series": series,
                    "total_tokens": int(total),
                    "top_users": top_users,
                }
            ),
            200,
        )


@admin_ns.route("/admin/audit")
class AdminAuditResource(Resource):
    @admin_required
    def get(self):
        """Global auth-events feed, newest first. Filter by event/user/since."""
        page, page_size, offset = _page()
        event = request.args.get("event") or None
        user_id = request.args.get("user_id") or None
        since = _since_arg(default_days=0)  # 0 = all time
        with db_readonly() as conn:
            repo = AuthEventsRepository(conn)
            total = repo.count_all(event=event, user_id=user_id, since=since)
            events = repo.list_all(
                event=event,
                user_id=user_id,
                since=since,
                limit=page_size,
                offset=offset,
            )
        return make_response(
            jsonify(
                {
                    "success": True,
                    "events": events,
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "has_more": offset + len(events) < total,
                }
            ),
            200,
        )


@admin_ns.route("/admin/devices/audit")
class AdminDeviceAuditResource(Resource):
    @admin_required
    def get(self):
        """Global remote-device command audit feed. Filter by decision/user/since."""
        page, page_size, offset = _page()
        decision = request.args.get("decision") or None
        user_id = request.args.get("user_id") or None
        since = _since_arg(default_days=0)
        with db_readonly() as conn:
            repo = DeviceAuditLogRepository(conn)
            total = repo.count_global(decision=decision, user_id=user_id, since=since)
            rows = repo.list_global(
                decision=decision,
                user_id=user_id,
                since=since,
                limit=page_size,
                offset=offset,
            )
        return make_response(
            jsonify(
                {
                    "success": True,
                    "invocations": rows,
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "has_more": offset + len(rows) < total,
                }
            ),
            200,
        )
