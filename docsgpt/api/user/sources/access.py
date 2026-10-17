"""Role checks shared by the source routes (sources, chunks, upload, search).

Thin wrappers over :mod:`docsgpt.api.user.resource_access` so every source
endpoint resolves the row the same way and answers denials with the same
JSON shape: 404 when the caller can't see the source, 403 when they can but
their role may not perform the action.
"""

from __future__ import annotations

from typing import Optional

from flask import jsonify, make_response
from sqlalchemy import Connection

from docsgpt.api.user.resource_access import AccessDenied, ResourceAccess, require
from docsgpt.storage.db.repositories.sources import SourcesRepository


def load_source(
    conn: Connection, source_id: Optional[str], user: str, action: str
) -> tuple[dict, ResourceAccess]:
    """Check ``action`` on a source and return its row with the caller's access.

    The row is fetched by the canonical id only after the check passes, so a
    team member gets the owner's row without ownership scoping.

    Args:
        conn: Open database connection.
        source_id: Source id from the request (UUID or legacy id).
        user: The caller's ``sub``.
        action: A ``source`` action from ``resource_access.ACTIONS``.

    Returns:
        tuple: ``(source_row, ResourceAccess)``; write as ``ra.owner_id``.

    Raises:
        AccessDenied: 404 when not visible, 403 when the role can't do it.
    """
    if not source_id:
        raise AccessDenied(404, "Source not found")
    ra = require(conn, "source", str(source_id), user, action)
    doc = SourcesRepository(conn).get_by_id(ra.resource_id)
    if doc is None:
        raise AccessDenied(404, "Source not found")
    return doc, ra


def denied_response(err: AccessDenied):
    """The JSON error response for an :class:`AccessDenied`."""
    return make_response(
        jsonify({"success": False, "message": err.message}), err.status
    )
