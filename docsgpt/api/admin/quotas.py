"""Admin endpoints for usage quotas (RBAC ``admin`` role required).

Policies are set at three layers: the instance default, a team's per-member
allowance and a single user's override. Every write is audited to
``auth_events`` with the acting admin recorded.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from flask import jsonify, make_response, request
from flask_restx import Resource

from docsgpt.api.admin.routes import _actor, admin_ns
from docsgpt.api.user.authz import admin_required
from docsgpt.core.settings import settings
from docsgpt.pricing import is_priced
from docsgpt.quotas.service import REQUEST_BUCKETS, QuotaService
from docsgpt.quotas.windows import window_bounds
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository
from docsgpt.storage.db.repositories.quota_policies import BUCKETS, QuotaPoliciesRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session

_MAX_TOKEN_LIMIT = 2**62
_MAX_COST_LIMIT = 99_999_999.0
_MAX_NOTE_LENGTH = 500


class _BadPolicy(ValueError):
    """The request body does not describe a valid policy."""


def _policy_json(row: dict) -> dict:
    cost = row.get("cost_limit_usd")
    return {
        "scope": row["scope"],
        "subject_id": row.get("subject_id"),
        "bucket": row["bucket"],
        "token_limit": row.get("token_limit"),
        "token_unlimited": bool(row.get("token_unlimited")),
        "cost_limit_usd": float(cost) if cost is not None else None,
        "cost_unlimited": bool(row.get("cost_unlimited")),
        "enabled": bool(row.get("enabled", True)),
        "note": row.get("note"),
        "updated_by": row.get("updated_by"),
        "updated_at": row.get("updated_at"),
    }


def _error(message: str, status: int):
    return make_response(jsonify({"success": False, "message": message}), status)


def _bucket(value: Any) -> str:
    if value is None:
        return "all"
    if value not in BUCKETS:
        raise _BadPolicy(f"bucket must be one of: {', '.join(BUCKETS)}")
    return value


def _flag(data: dict, key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise _BadPolicy(f"{key} must be a boolean")
    return value


def _parse_policy(data: Any) -> dict:
    """Validate a policy body into ``QuotaPoliciesRepository.upsert`` kwargs."""
    if not isinstance(data, dict):
        raise _BadPolicy("Body must be a JSON object")
    token_limit = data.get("token_limit")
    if token_limit is not None:
        if isinstance(token_limit, bool) or not isinstance(token_limit, int):
            raise _BadPolicy("token_limit must be a whole number or null")
        if not 0 <= token_limit <= _MAX_TOKEN_LIMIT:
            raise _BadPolicy("token_limit is out of range")
    cost_limit = data.get("cost_limit_usd")
    if cost_limit is not None:
        if isinstance(cost_limit, bool) or not isinstance(cost_limit, (int, float)):
            raise _BadPolicy("cost_limit_usd must be a number or null")
        if not math.isfinite(cost_limit) or not 0 <= cost_limit <= _MAX_COST_LIMIT:
            raise _BadPolicy("cost_limit_usd is out of range")
        cost_limit = round(float(cost_limit), 4)
    token_unlimited = _flag(data, "token_unlimited", False)
    cost_unlimited = _flag(data, "cost_unlimited", False)
    if token_unlimited and token_limit is not None:
        raise _BadPolicy("Set token_limit or token_unlimited, not both")
    if cost_unlimited and cost_limit is not None:
        raise _BadPolicy("Set cost_limit_usd or cost_unlimited, not both")
    if token_limit is None and cost_limit is None and not token_unlimited and not cost_unlimited:
        raise _BadPolicy("Set a limit or mark a budget unlimited; delete the policy to remove it")
    note = data.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise _BadPolicy("note must be a string")
        note = note.strip()[:_MAX_NOTE_LENGTH] or None
    return {
        "bucket": _bucket(data.get("bucket")),
        "token_limit": token_limit,
        "token_unlimited": token_unlimited,
        "cost_limit_usd": cost_limit,
        "cost_unlimited": cost_unlimited,
        "enabled": _flag(data, "enabled", True),
        "note": note,
    }


def _audit(conn, event: str, scope: str, subject_id: Optional[str], detail: dict) -> None:
    actor = _actor()
    AuthEventsRepository(conn).insert(
        # A user policy is filed under that user; the rest under the acting admin.
        subject_id if scope == "user" else (actor or "unknown"),
        event,
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
        metadata={"by": actor, "via": "admin_api", "scope": scope, "subject_id": subject_id, **detail},
    )


def _put_policy(scope: str, subject_id: Optional[str]):
    try:
        fields = _parse_policy(request.get_json(silent=True))
    except _BadPolicy as exc:
        return _error(str(exc), 400)
    with db_session() as conn:
        row = QuotaPoliciesRepository(conn).upsert(
            scope=scope, subject_id=subject_id, actor=_actor(), **fields
        )
        _audit(conn, "quota_policy_set", scope, subject_id, fields)
    return make_response(jsonify({"success": True, "policy": _policy_json(row)}), 200)


def _delete_policy(scope: str, subject_id: Optional[str]):
    try:
        bucket = _bucket(request.args.get("bucket")) if "bucket" in request.args else None
    except _BadPolicy as exc:
        return _error(str(exc), 400)
    with db_session() as conn:
        deleted = QuotaPoliciesRepository(conn).delete(scope, subject_id, bucket)
        if deleted:
            _audit(conn, "quota_policy_deleted", scope, subject_id, {"bucket": bucket or "*"})
    return make_response(jsonify({"success": True, "deleted": deleted}), 200)


def _unpriced_models(conn) -> list[dict]:
    """Catalog models used this period that no cost limit can see."""
    start, _ = window_bounds(settings.QUOTA_PERIOD)
    return [
        row
        for row in TokenUsageRepository(conn).tokens_by_model(start=start)
        # BYOM ids are UUIDs; those calls are $0 by design, not by omission.
        if not looks_like_uuid(row["model_id"]) and not is_priced(row["model_id"])
    ]


@admin_ns.route("/admin/quotas")
class AdminQuotasResource(Resource):
    @admin_required
    def get(self):
        """Every stored policy, grouped by layer, plus the models cost limits cannot see."""
        start, resets_at = window_bounds(settings.QUOTA_PERIOD)
        with db_readonly() as conn:
            repo = QuotaPoliciesRepository(conn)
            teams = {str(t["id"]): t for t in TeamsRepository(conn).list_all()}
            team_policies = []
            for row in repo.list_by_scope("team"):
                team = teams.get(str(row["subject_id"]), {})
                team_policies.append(
                    {
                        **_policy_json(row),
                        "team_name": team.get("name"),
                        "team_slug": team.get("slug"),
                        "member_count": team.get("member_count"),
                    }
                )
            body = {
                "success": True,
                "period": settings.QUOTA_PERIOD,
                "period_start": start.isoformat(),
                "resets_at": resets_at.isoformat(),
                "instance": [_policy_json(r) for r in repo.list_by_scope("instance")],
                "teams": team_policies,
                "users": [_policy_json(r) for r in repo.list_by_scope("user")],
                "unpriced_models": _unpriced_models(conn),
            }
        return make_response(jsonify(body), 200)


@admin_ns.route("/admin/quotas/instance")
class AdminInstanceQuotaResource(Resource):
    @admin_required
    def put(self):
        """Set the instance default for one bucket."""
        return _put_policy("instance", None)

    @admin_required
    def delete(self):
        """Remove the instance default for ``?bucket=``, or for every bucket."""
        return _delete_policy("instance", None)


@admin_ns.route("/admin/quotas/teams/<string:team_id>")
class AdminTeamQuotaResource(Resource):
    @admin_required
    def get(self, team_id):
        """The per-member allowance of one team."""
        if not looks_like_uuid(team_id):
            return _error("Team not found", 404)
        with db_readonly() as conn:
            if TeamsRepository(conn).get(team_id) is None:
                return _error("Team not found", 404)
            rows = QuotaPoliciesRepository(conn).list_for_subject("team", team_id)
        return make_response(
            jsonify({"success": True, "policies": [_policy_json(r) for r in rows]}), 200
        )

    @admin_required
    def put(self, team_id):
        """Set the allowance each member of the team gets."""
        if not looks_like_uuid(team_id):
            return _error("Team not found", 404)
        with db_readonly() as conn:
            if TeamsRepository(conn).get(team_id) is None:
                return _error("Team not found", 404)
        return _put_policy("team", team_id)

    @admin_required
    def delete(self, team_id):
        """Remove the team's allowance for ``?bucket=``, or for every bucket."""
        if not looks_like_uuid(team_id):
            return _error("Team not found", 404)
        return _delete_policy("team", team_id)


@admin_ns.route("/admin/quotas/users/<string:user_id>")
class AdminUserQuotaResource(Resource):
    @admin_required
    def get(self, user_id):
        """A user's overrides and the limits and usage they resolve to."""
        with db_readonly() as conn:
            if UsersRepository(conn).get(user_id) is None:
                return _error("User not found", 404)
            rows = QuotaPoliciesRepository(conn).list_for_subject("user", user_id)
        statuses = QuotaService.status(user_id, ("all", *REQUEST_BUCKETS))
        return make_response(
            jsonify(
                {
                    "success": True,
                    "period": settings.QUOTA_PERIOD,
                    "policies": [_policy_json(r) for r in rows],
                    "effective": [s.to_dict() for s in statuses],
                }
            ),
            200,
        )

    @admin_required
    def put(self, user_id):
        """Set one user's override, which beats team allowances and the default."""
        with db_readonly() as conn:
            if UsersRepository(conn).get(user_id) is None:
                return _error("User not found", 404)
        return _put_policy("user", user_id)

    @admin_required
    def delete(self, user_id):
        """Remove the user's override for ``?bucket=``, or for every bucket."""
        return _delete_policy("user", user_id)
