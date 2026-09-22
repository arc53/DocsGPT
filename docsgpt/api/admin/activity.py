"""Admin activity feed: one timeline over all three audit journals.

``GET /api/admin/audit`` remains the ``auth_events``-only feed. These endpoints
add the merged view an incident review actually wants — identity, access,
configuration, data-plane, remote-device and guardrail activity in one ordered
list — plus the filters and the export that make a review possible without
shelling into the database.

Every resource here is ``@admin_required``, like the rest of the namespace.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Iterator, Optional

from flask import Response, jsonify, make_response, request, stream_with_context
from flask_restx import Resource

from docsgpt.api.admin.routes import _int_arg, _page, admin_ns
from docsgpt.api.user.authz import admin_required
from docsgpt.audit_events import ACTIVITY_CATEGORIES
from docsgpt.storage.db.repositories.activity import (
    ACTIVITY_COLUMNS,
    ActivityRepository,
)
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

_FEEDS = ("auth", "device", "guardrail")
_EXPORT_FORMATS = ("csv", "ndjson")

# An export runs against a live instance, so it is bounded. Operators needing
# the full history take a database dump, not an HTTP request.
_EXPORT_MAX_ROWS = 100_000
_EXPORT_CHUNK = 1_000

_MAX_SEARCH_LENGTH = 200


def _csv_list(name: str, allowed: tuple[str, ...]) -> Optional[list[str]]:
    """Parse a repeated/comma-separated query arg, dropping unknown values.

    Args:
        name: Query parameter name.
        allowed: The permitted values; anything else is ignored rather than
            rejected, so an old bookmark degrades instead of erroring.

    Returns:
        The distinct valid values in the order given, or None when absent.
    """
    raw: list[str] = []
    for value in request.args.getlist(name):
        raw.extend(part.strip() for part in value.split(","))
    seen: list[str] = []
    for value in raw:
        if value in allowed and value not in seen:
            seen.append(value)
    return seen or None


def _event_list() -> Optional[list[str]]:
    """Event names to filter on. Unconstrained — the catalogue is data, not an enum."""
    names: list[str] = []
    for value in request.args.getlist("event"):
        for part in value.split(","):
            part = part.strip()
            if part and part not in names:
                names.append(part)
    return names or None


def _time_arg(name: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp query arg, or None when absent/unparseable."""
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A naive bound is read as UTC, matching how the feed stores timestamps.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _search_arg() -> Optional[str]:
    value = (request.args.get("search") or "").strip()
    return value[:_MAX_SEARCH_LENGTH] or None


def _filters() -> dict:
    """The filter set shared by the feed and the export."""
    return {
        "feeds": _csv_list("feed", _FEEDS),
        "categories": _csv_list("category", ACTIVITY_CATEGORIES),
        "events": _event_list(),
        "actor_id": request.args.get("actor_id") or None,
        "user_id": request.args.get("user_id") or None,
        "since": _time_arg("since"),
        "until": _time_arg("until"),
        "search": _search_arg(),
    }


def _serialize(row: dict) -> dict:
    """Make one feed row JSON-safe (timestamps to ISO-8601)."""
    created = row.get("created_at")
    return {
        **row,
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


@admin_ns.route("/admin/activity")
class AdminActivityResource(Resource):
    @admin_required
    def get(self):
        """Merged audit feed, newest first, with filters and a total."""
        page, page_size, offset = _page()
        filters = _filters()
        with db_readonly() as conn:
            repo = ActivityRepository(conn)
            total = repo.count(**filters)
            rows = repo.list(limit=page_size, offset=offset, **filters)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "activity": [_serialize(row) for row in rows],
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "has_more": offset + len(rows) < total,
                }
            ),
            200,
        )


@admin_ns.route("/admin/activity/events")
class AdminActivityCatalogueResource(Resource):
    @admin_required
    def get(self):
        """Distinct ``(event, category)`` pairs this instance has recorded.

        The filter UI offers these instead of a free-text box, so an operator
        never has to guess that denied logins are ``oidc_login_denied``.
        """
        with db_readonly() as conn:
            catalogue = ActivityRepository(conn).event_names()
        return make_response(
            jsonify(
                {
                    "success": True,
                    "events": catalogue,
                    "categories": list(ACTIVITY_CATEGORIES),
                    "feeds": list(_FEEDS),
                }
            ),
            200,
        )


@admin_ns.route("/admin/activity/export")
class AdminActivityExportResource(Resource):
    @admin_required
    def get(self):
        """Stream the filtered feed as CSV or NDJSON.

        Streamed, not buffered: a compliance export of a busy instance should
        not be built in memory first. Capped at ``_EXPORT_MAX_ROWS``; the
        response header says whether the cap was reached.
        """
        fmt = (request.args.get("format") or "csv").lower()
        if fmt not in _EXPORT_FORMATS:
            return make_response(
                jsonify({"success": False, "message": "Invalid format"}), 400
            )
        limit = max(1, min(_EXPORT_MAX_ROWS, _int_arg("max_rows", _EXPORT_MAX_ROWS)))
        filters = _filters()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        generator = _csv_rows if fmt == "csv" else _ndjson_rows
        return Response(
            stream_with_context(generator(filters, limit)),
            mimetype="text/csv" if fmt == "csv" else "application/x-ndjson",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="docsgpt-activity-{stamp}.{fmt}"'
                ),
                # Partial content would otherwise be indistinguishable from a
                # complete export.
                "X-Export-Max-Rows": str(limit),
                "Cache-Control": "no-store",
            },
        )


def _export_rows(filters: dict, limit: int) -> Iterator[dict]:
    """Walk the filtered feed, holding the connection open for the whole stream."""
    with db_readonly() as conn:
        yield from ActivityRepository(conn).iter_all(
            chunk_size=_EXPORT_CHUNK, max_rows=limit, **filters
        )


def _csv_rows(filters: dict, limit: int) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(ACTIVITY_COLUMNS))
    writer.writeheader()
    yield _drain(buffer)
    for row in _export_rows(filters, limit):
        serialized = _serialize(row)
        # ``detail`` is a JSON object; a CSV cell holds its compact encoding.
        serialized["detail"] = json.dumps(serialized.get("detail") or {})
        writer.writerow(serialized)
        yield _drain(buffer)


def _ndjson_rows(filters: dict, limit: int) -> Iterator[str]:
    for row in _export_rows(filters, limit):
        yield json.dumps(_serialize(row), default=str) + "\n"


def _drain(buffer: io.StringIO) -> str:
    """Return and clear the writer's buffer, so each row streams as written."""
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value
