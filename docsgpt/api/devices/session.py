"""Device session endpoints: poll, me, ack, output.

The SSE command stream itself is a native-async route (``session_events.py``).
"""

from __future__ import annotations

import gzip
import io
import json
import logging

from flask import Response, jsonify, make_response, request

from docsgpt.api.agent_origins import reads_raw_body
from docsgpt.api.devices.auth import verify_device_session
from docsgpt.devices.broker import get_broker
from docsgpt.storage.db.repositories.device_audit_log import (
    DeviceAuditLogRepository,
)
from docsgpt.storage.db.session import db_session


logger = logging.getLogger(__name__)


# Window (seconds) the CLI has to upgrade a poll-issued ticket to an SSE
# stream. Advertised to the CLI as ``expires_in`` and used as the broker
# ticket TTL so the two never drift.
_SESSION_TICKET_TTL_SECONDS = 30


def poll() -> Response:
    """``GET /api/devices/poll`` — long-poll for queued invocations.

    Returns ``202`` with empty body when nothing is queued and ``200`` with
    a session ticket payload when work is waiting.
    """
    device, err = verify_device_session()
    if err is not None:
        return err
    broker = get_broker()
    ticket = broker.claim_ticket(device["id"], _SESSION_TICKET_TTL_SECONDS)
    if ticket is None:
        return make_response("", 202)
    return make_response(
        jsonify(
            {
                "session_ticket": ticket,
                "session_url": f"/api/devices/sessions/{ticket}/events",
                "expires_in": _SESSION_TICKET_TTL_SECONDS,
            }
        ),
        200,
    )


def me() -> Response:
    """``GET /api/devices/me`` — return the calling device's own record.

    Auth: device session token (same as ``/poll``). Used by ``docsgpt-cli
    host status`` to show live server state.
    """
    device, err = verify_device_session()
    if err is not None:
        return err
    out = {
        "id": device.get("id"),
        "name": device.get("name"),
        "hostname": device.get("hostname"),
        "os": device.get("os"),
        "status": device.get("status"),
        "approval_mode": device.get("approval_mode"),
        "description": device.get("description"),
        "paired_at": device.get("paired_at"),
        "last_seen_at": device.get("last_seen_at"),
    }
    for key in ("paired_at", "last_seen_at"):
        value = out.get(key)
        if value is not None and not isinstance(value, str):
            out[key] = value.isoformat()
    return make_response(jsonify(out), 200)


def ack_invocation(session_id: str, invocation_id: str) -> Response:
    """CLI acks (accepted / denied / auto_approved) the invocation."""
    device, err = verify_device_session()
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    reason = body.get("reason")
    if decision not in {"accepted", "denied", "auto_approved"}:
        return make_response(
            jsonify({"success": False, "error": "invalid_decision"}), 400
        )
    broker = get_broker()
    inv, unavailable = _owned_invocation(broker, invocation_id)
    if unavailable is not None:
        return unavailable
    if inv is None or inv.device_id != device["id"]:
        return make_response(
            jsonify({"success": False, "error": "invocation_not_found"}), 404
        )
    if not broker.submit_ack(invocation_id, decision, reason):
        return _broker_unavailable()
    if decision == "denied":
        # A denial is terminal and produces no device output, so submit_output's
        # audit write is never reached. Record the outcome here from locally
        # known facts (not re-read Redis state the agent's drain races to clean
        # up), so the audit row reflects the denial instead of staying
        # "dispatched". Accepted/auto_approved runs record via submit_output.
        from datetime import datetime, timezone
        try:
            with db_session() as conn:
                DeviceAuditLogRepository(conn).record_result(
                    invocation_id,
                    finished_at=datetime.now(timezone.utc),
                    error="denied",
                )
        except Exception:
            logger.exception("audit record_result (denied) failed for %s", invocation_id)
    return make_response(jsonify({"success": True}), 200)


@reads_raw_body
def submit_output(session_id: str, invocation_id: str) -> Response:
    """CLI streams stdout/stderr/control chunks (NDJSON, gzip-aware; one or more lines per POST).

    A client that resends (``X-Device-Capabilities: outbox``) may post the
    same batch twice when a response is lost: its chunks are deduplicated by
    ``seq``, and the closing control chunk is taken once for every client.
    The response counts what was new (``received``) and what was a repeat
    (``duplicates``); both are a 200, so the client stops resending.
    """
    device, err = verify_device_session()
    if err is not None:
        return err
    broker = get_broker()
    inv, unavailable = _owned_invocation(broker, invocation_id)
    if unavailable is not None:
        return unavailable
    if inv is None or inv.device_id != device["id"]:
        return make_response(
            jsonify({"success": False, "error": "invocation_not_found"}), 404
        )

    body = request.get_data() or b""
    if request.headers.get("Content-Encoding", "").lower() == "gzip":
        try:
            body = gzip.decompress(body)
        except OSError:
            return make_response(
                jsonify({"success": False, "error": "invalid_gzip"}), 400
            )

    from docsgpt.devices import capabilities

    dedupe = capabilities.has(capabilities.from_headers(request.headers), capabilities.OUTBOX)
    received = 0
    duplicates = 0
    control_chunk = None
    resent_control = False
    for line in io.BytesIO(body):
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(chunk, dict):
            continue
        outcome = broker.accept_output_chunk(invocation_id, chunk, dedupe=dedupe)
        if outcome == "duplicate":
            duplicates += 1
            if chunk.get("stream") == "control":
                resent_control = True
            continue
        if outcome == "gone":
            # Expired or cleaned up since the lookup: the client stops resending.
            return make_response(
                jsonify({"success": False, "error": "invocation_not_found"}), 404
            )
        if outcome != "accepted":
            # Nothing was stored: the client resends the batch, and what this POST
            # already took comes back as duplicates.
            return _broker_unavailable()
        if chunk.get("stream") == "control":
            # Only the control chunk the broker took is the outcome; a resent one changes nothing.
            control_chunk = chunk
        received += 1

    # Persist the outcome when the closing control chunk arrived in this POST.
    # Its fields are captured locally so the audit write survives the draining
    # (worker) process racing to delete the invocation's Redis state. Byte
    # totals / started_at live in the hash, read best-effort (the functional
    # exit_code/error/duration still land even if the hash is already gone).
    if control_chunk is None and resent_control:
        # The report was taken before, perhaps by a request whose reply was lost before
        # its audit write: record the outcome again from what the broker stored (never
        # from the resent chunk). The write is idempotent.
        _audit_from_state(broker, invocation_id)
    if control_chunk is not None:
        from datetime import datetime, timezone
        snap = broker.get_invocation(invocation_id)
        try:
            with db_session() as conn:
                DeviceAuditLogRepository(conn).record_result(
                    invocation_id,
                    started_at=(
                        datetime.fromtimestamp(snap.started_at, tz=timezone.utc)
                        if snap is not None and snap.started_at else None
                    ),
                    finished_at=datetime.now(timezone.utc),
                    exit_code=_as_opt_int(control_chunk.get("exit_code")),
                    duration_ms=_as_opt_int(control_chunk.get("duration_ms")),
                    stdout_bytes=(snap.stdout_bytes if snap is not None else 0),
                    stderr_bytes=(snap.stderr_bytes if snap is not None else 0),
                    error=_audit_error(control_chunk),
                )
        except Exception:
            logger.exception("audit record_result failed for %s", invocation_id)

    return make_response(
        jsonify({"success": True, "received": received, "duplicates": duplicates}), 200
    )


def _as_opt_int(value) -> int | None:
    """Coerce a CLI-supplied JSON value to int for an INTEGER audit column."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _audit_error(chunk: dict) -> str | None:
    """The control chunk's error for the audit row, with its detail (``interrupted``: the pid)."""
    error = chunk.get("error")
    if not error:
        return None
    detail = chunk.get("detail")
    return f"{error}: {detail}"[:500] if detail else str(error)[:500]


def _broker_unavailable() -> Response:
    """503 with ``Retry-After``: the device broker couldn't store this, so the client should send it again."""
    response = make_response(jsonify({"success": False, "error": "broker_unavailable"}), 503)
    response.headers["Retry-After"] = "5"
    return response


def _owned_invocation(broker, invocation_id: str):
    """``(invocation or None, error response or None)``: a broker that can't answer is a 503, never a 404.

    A 404 tells the client the invocation is gone for good, so it is kept for
    an invocation that really doesn't exist.
    """
    try:
        return broker.get_invocation(invocation_id, strict=True), None
    except Exception:
        logger.exception("device broker lookup failed for %s", invocation_id)
        return None, _broker_unavailable()


def _audit_from_state(broker, invocation_id: str) -> None:
    """Record an invocation's outcome in the audit log from the broker's stored result (best-effort)."""
    from datetime import datetime, timezone

    snap = broker.get_invocation(invocation_id)
    if snap is None or not snap.completed:
        return
    try:
        with db_session() as conn:
            DeviceAuditLogRepository(conn).record_result(
                invocation_id,
                started_at=(
                    datetime.fromtimestamp(snap.started_at, tz=timezone.utc) if snap.started_at else None
                ),
                finished_at=(
                    datetime.fromtimestamp(snap.finished_at, tz=timezone.utc)
                    if snap.finished_at
                    else datetime.now(timezone.utc)
                ),
                exit_code=snap.exit_code,
                duration_ms=snap.duration_ms,
                stdout_bytes=snap.stdout_bytes,
                stderr_bytes=snap.stderr_bytes,
                error=_audit_error({"error": snap.error, "detail": snap.detail}),
            )
    except Exception:
        logger.exception("audit record_result (from broker state) failed for %s", invocation_id)
