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
_FLAG_DEFAULTS = {"token_unlimited": False, "cost_unlimited": False, "enabled": True}
_BUCKET_MESSAGE = f"bucket must be one of: {', '.join(BUCKETS)}"
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


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


def _limit_error(value: Any, name: str, whole: bool, maximum: float) -> Optional[str]:
    """Return why ``value`` is not a valid limit, or ``None``."""
    if value is None:
        return None
    number = (int,) if whole else (int, float)
    if isinstance(value, bool) or not isinstance(value, number):
        return f"{name} must be a {'whole number' if whole else 'number'} or null"
    # Range first: ``isfinite`` overflows on an int too large for a float.
    if not 0 <= value <= maximum or not math.isfinite(value):
        return f"{name} is out of range"
    return None


def _parse_policy(data: Any) -> tuple[Optional[dict], Optional[str]]:
    """Validate a policy body.

    Returns:
        ``(fields, None)`` with ``QuotaPoliciesRepository.upsert`` kwargs, or
        ``(None, message)`` describing the first problem.
    """
    if not isinstance(data, dict):
        return None, "Body must be a JSON object"
    token_limit, cost_limit = data.get("token_limit"), data.get("cost_limit_usd")
    problem = _limit_error(token_limit, "token_limit", True, _MAX_TOKEN_LIMIT) or _limit_error(
        cost_limit, "cost_limit_usd", False, _MAX_COST_LIMIT
    )
    if problem:
        return None, problem
    flags = {key: data.get(key, default) for key, default in _FLAG_DEFAULTS.items()}
    for key, value in flags.items():
        if not isinstance(value, bool):
            return None, f"{key} must be a boolean"
    bucket = data.get("bucket", "all")
    if bucket not in BUCKETS:
        return None, _BUCKET_MESSAGE
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        return None, "note must be a string"
    if flags["token_unlimited"] and token_limit is not None:
        return None, "Set token_limit or token_unlimited, not both"
    if flags["cost_unlimited"] and cost_limit is not None:
        return None, "Set cost_limit_usd or cost_unlimited, not both"
    if token_limit is None and cost_limit is None and not flags["token_unlimited"] and not flags["cost_unlimited"]:
        return None, "Set a limit or mark a budget unlimited; delete the policy to remove it"
    return {
        "bucket": bucket,
        "token_limit": token_limit,
        "token_unlimited": flags["token_unlimited"],
        "cost_limit_usd": round(float(cost_limit), 4) if cost_limit is not None else None,
        "cost_unlimited": flags["cost_unlimited"],
        "enabled": flags["enabled"],
        "note": (note.strip()[:_MAX_NOTE_LENGTH] or None) if note else None,
    }, None


def _audit(conn, event: str, scope: str, subject_id: Optional[str], detail: dict) -> None:
    actor = _actor()
    AuthEventsRepository(conn).insert(
        # A user policy is filed under that user; the rest under the acting admin.
        subject_id if scope == "user" else (actor or "unknown"),
        event,
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
        metadata={"by": actor, "via": "admin_api", "scope": scope, "subject_id": subject_id, **detail},
        actor_id=actor or "unknown",
        # Only a user-scoped policy targets a user; instance and team policies
        # change configuration, not an account.
        target_id=subject_id if scope == "user" else None,
    )


def _put_policy(scope: str, subject_id: Optional[str]):
    fields, problem = _parse_policy(request.get_json(silent=True))
    if fields is None:
        return _error(problem or "Invalid policy", 400)
    with db_session() as conn:
        row = QuotaPoliciesRepository(conn).upsert(
            scope=scope, subject_id=subject_id, actor=_actor(), **fields
        )
        _audit(conn, "quota_policy_set", scope, subject_id, fields)
    return make_response(jsonify({"success": True, "policy": _policy_json(row)}), 200)


def _delete_policy(scope: str, subject_id: Optional[str]):
    bucket = request.args.get("bucket")
    if bucket is not None and bucket not in BUCKETS:
        return _error(_BUCKET_MESSAGE, 400)
    with db_session() as conn:
        deleted = QuotaPoliciesRepository(conn).delete(scope, subject_id, bucket)
        if deleted:
            _audit(conn, "quota_policy_deleted", scope, subject_id, {"bucket": bucket or "*"})
    return make_response(jsonify({"success": True, "deleted": deleted}), 200)


def _unpriced_models(conn) -> list[dict]:
    """Models used this period whose calls were all recorded at $0 for want of a price."""
    start, _ = window_bounds(settings.QUOTA_PERIOD)
    return [
        row
        for row in TokenUsageRepository(conn).tokens_by_model(start=start)
        # Judged by what was recorded, so a priced model whose provider has since
        # been disabled is not listed. BYOM ids are UUIDs and $0 by design; a
        # model explicitly priced at $0 is free, not unpriced.
        if row["cost"] == 0 and not looks_like_uuid(row["model_id"]) and not is_priced(row["model_id"])
    ]


def _int_arg(name: str, default: int, low: int, high: Optional[int] = None) -> int:
    """Read an integer query arg, falling back to ``default`` and clamping to ``[low, high]``."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(low, value)
    return min(value, high) if high is not None else value


def _search_term(name: str) -> Optional[str]:
    """Return the lower-cased, trimmed query arg ``name``, or ``None`` when blank or absent."""
    term = (request.args.get(name) or "").strip().lower()
    return term or None


def _subject_count(rows: list[dict]) -> int:
    """The number of distinct subjects (teams or users) among ``rows``."""
    return len({r["subject_id"] for r in rows})


def _page(rows: list[dict], page_arg: str) -> list[dict]:
    """Slice ``rows`` to the page named by ``page_arg`` when the caller asked for one.

    A page holds ``page_size`` subjects, not rows: every bucket row of a team or
    user stays on the same page, so its ``all`` row is never apart from the rest.

    Args:
        rows: The already filtered rows, each subject's rows next to each other.
        page_arg: The 1-based page query arg (``teams_page`` / ``users_page``);
            absent means the whole list.

    Returns:
        The rows of the subjects on the requested page, or every row.
    """
    if page_arg not in request.args:
        return rows
    size = _int_arg("page_size", _DEFAULT_PAGE_SIZE, 1, _MAX_PAGE_SIZE)
    offset = (_int_arg(page_arg, 1, 1) - 1) * size
    subjects = list(dict.fromkeys(r["subject_id"] for r in rows))
    on_page = set(subjects[offset : offset + size])
    return [r for r in rows if r["subject_id"] in on_page]


def _matches(term: Optional[str], *values: Optional[str]) -> bool:
    """Whether ``term`` (already lower-cased) is a substring of any non-null value."""
    return term is None or any(term in value.lower() for value in values if value)


@admin_ns.route("/admin/quotas")
class AdminQuotasResource(Resource):
    @admin_required
    def get(self):
        """Every stored policy, grouped by layer, plus the models cost limits cannot see.

        Query args (all optional; without them every row is returned):
            teams_q: Case-insensitive substring of the team name or slug.
            users_q: Case-insensitive substring of the user's subject id or email.
            teams_page / users_page: 1-based page of that list; only a list whose
                page arg is given is paginated.
            page_size: Teams or users per page, clamped to 1-100 (default 20); a
                page carries every bucket row of each of them.

        ``teams_total`` and ``users_total`` count the teams and users after
        filtering and before paging. Rows keep the repository order (subject,
        then bucket).
        """
        start, resets_at = window_bounds(settings.QUOTA_PERIOD)
        teams_q, users_q = _search_term("teams_q"), _search_term("users_q")
        with db_readonly() as conn:
            repo = QuotaPoliciesRepository(conn)
            teams = {str(t["id"]): t for t in TeamsRepository(conn).list_all()}
            team_policies = []
            for row in repo.list_by_scope("team"):
                team = teams.get(str(row["subject_id"]), {})
                if not _matches(teams_q, team.get("name"), team.get("slug")):
                    continue
                team_policies.append(
                    {
                        **_policy_json(row),
                        "team_name": team.get("name"),
                        "team_slug": team.get("slug"),
                        "member_count": team.get("member_count"),
                    }
                )
            user_rows = repo.list_by_scope("user")
            if users_q is not None:
                emails = UsersRepository(conn).emails_for(r["subject_id"] for r in user_rows)
                user_rows = [
                    r for r in user_rows if _matches(users_q, r["subject_id"], emails.get(r["subject_id"]))
                ]
            user_policies = [_policy_json(r) for r in user_rows]
            body = {
                "success": True,
                "period": settings.QUOTA_PERIOD,
                "period_start": start.isoformat(),
                "resets_at": resets_at.isoformat(),
                "instance": [_policy_json(r) for r in repo.list_by_scope("instance")],
                "teams": _page(team_policies, "teams_page"),
                "users": _page(user_policies, "users_page"),
                "unpriced_models": _unpriced_models(conn),
                "teams_total": _subject_count(team_policies),
                "users_total": _subject_count(user_policies),
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
