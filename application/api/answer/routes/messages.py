"""GET /api/messages/<message_id>/events — chat-stream reconnect endpoint.

The Phase 2 reconnect path. A client that drops mid-answer reopens
this endpoint with the last ``sequence_no`` it saw in the
``Last-Event-ID`` header (or ``last_event_id`` query param). The
handler:

1. Authenticates via the standard ``request.decoded_token`` middleware.
2. Verifies the requested ``message_id`` belongs to the authenticated
   user (defence against id enumeration; even though the journal is
   keyed by an unguessable UUID, we still don't want a stolen id to
   leak across users).
3. Hands off to ``build_message_event_stream`` which yields a
   snapshot from ``message_events`` followed by a live tail on
   ``channel:{message_id}``.

The response shape mirrors the user-events SSE endpoint
(``application/api/events/routes.py``): ``Cache-Control: no-store``,
``X-Accel-Buffering: no``, and a ``Connection: keep-alive`` header.
Reconnects are GET-only; the originating POST to ``/api/stream``
already created the message row and started the stream.
"""

from __future__ import annotations

import logging
import re
from typing import Iterator, Optional

from flask import Blueprint, Response, jsonify, make_response, request, stream_with_context
from sqlalchemy import text

from application.core.settings import settings
from application.storage.db.session import db_readonly
from application.streaming.event_replay import (
    DEFAULT_KEEPALIVE_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    build_message_event_stream,
)

logger = logging.getLogger(__name__)

messages_bp = Blueprint("message_stream", __name__)

# A message_id is the canonical UUID hex format. Reject anything else
# before the SQL layer so a malformed cookie can't surface as a 500.
_MESSAGE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Phase 2 sequence_no is a non-negative decimal integer. Anything else
# is corrupt client state — fall through to a fresh-replay cursor and
# let the snapshot reader catch the client up.
_SEQUENCE_NO_RE = re.compile(r"^\d+$")


def _normalise_last_event_id(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or not _SEQUENCE_NO_RE.match(raw):
        return None
    return int(raw)


def _user_owns_message(message_id: str, user_id: str) -> bool:
    """Return True iff ``message_id`` belongs to ``user_id``."""
    try:
        with db_readonly() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT 1 FROM conversation_messages
                    WHERE id = CAST(:id AS uuid)
                      AND user_id = :u
                    LIMIT 1
                    """
                ),
                {"id": message_id, "u": user_id},
            ).first()
        return row is not None
    except Exception:
        logger.exception(
            "Ownership lookup failed for message_id=%s user_id=%s",
            message_id,
            user_id,
        )
        return False


@messages_bp.route("/api/messages/<message_id>/events", methods=["GET"])
def stream_message_events(message_id: str) -> Response:
    decoded = getattr(request, "decoded_token", None)
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return make_response(
            jsonify({"success": False, "message": "Authentication required"}),
            401,
        )

    if not _MESSAGE_ID_RE.match(message_id):
        return make_response(
            jsonify({"success": False, "message": "Invalid message id"}),
            400,
        )

    if not _user_owns_message(message_id, user_id):
        # Don't disclose whether the row exists — a malicious caller
        # gets the same 404 whether the id is bogus, taken by another
        # user, or simply gone.
        return make_response(
            jsonify({"success": False, "message": "Not found"}),
            404,
        )

    raw_cursor = request.headers.get("Last-Event-ID") or request.args.get(
        "last_event_id"
    )
    last_event_id = _normalise_last_event_id(raw_cursor)
    keepalive_seconds = float(
        getattr(settings, "SSE_KEEPALIVE_SECONDS", DEFAULT_KEEPALIVE_SECONDS)
    )

    @stream_with_context
    def generate() -> Iterator[str]:
        try:
            yield from build_message_event_stream(
                message_id,
                last_event_id=last_event_id,
                keepalive_seconds=keepalive_seconds,
                poll_timeout_seconds=DEFAULT_POLL_TIMEOUT_SECONDS,
            )
        except GeneratorExit:
            return
        except Exception:
            logger.exception(
                "Reconnect stream crashed for message_id=%s user_id=%s",
                message_id,
                user_id,
            )

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    logger.info(
        "message.event.connect message_id=%s user_id=%s last_event_id=%s",
        message_id,
        user_id,
        last_event_id if last_event_id is not None else "-",
    )
    return response
