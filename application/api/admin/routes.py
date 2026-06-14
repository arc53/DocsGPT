"""Admin-gated management endpoints (RBAC ``admin`` role required).

Every resource here is behind ``@admin_required``. The frontend route guard is
cosmetic — this server-side decorator is the actual security boundary, so any
new endpoint added to this namespace MUST carry it.
"""

from __future__ import annotations

import logging

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from application.api.user.authz import admin_required
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

admin_ns = Namespace("admin", description="Admin-only management endpoints", path="/api")

_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 100


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


@admin_ns.route("/admin/users")
class AdminUsersResource(Resource):
    @admin_required
    def get(self):
        """List users, paginated. Optional exact ``user_id`` filter."""
        page = max(1, _int_arg("page", 1))
        page_size = max(1, min(_MAX_PAGE_SIZE, _int_arg("page_size", _DEFAULT_PAGE_SIZE)))
        offset = (page - 1) * page_size
        user_id_filter = request.args.get("user_id") or None
        with db_readonly() as conn:
            total, rows = UsersRepository(conn).list_paginated(user_id_filter, offset, page_size)
        users = [
            {
                "user_id": row.get("user_id"),
                "active": bool(row.get("active", True)),
                "created_at": row.get("created_at"),
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
