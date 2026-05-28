"""Device CRUD + auto-approve pattern routes."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, make_response, request

from application.api.devices.pairing import (
    create_pairing,
    delete_pairing,
    get_pairing,
    redeem_pairing,
)
from application.api.devices.session import (
    ack_invocation,
    me,
    poll,
    session_events,
    submit_output,
)
from application.devices.normalizer import normalize_command
from application.storage.db.repositories.device_audit_log import (
    DeviceAuditLogRepository,
)
from application.storage.db.repositories.device_auto_approve_patterns import (
    DeviceAutoApprovePatternsRepository,
)
from application.storage.db.repositories.devices import DevicesRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


_ALLOWED_APPROVAL_MODES = {"ask", "full"}


def _authed_user_id():
    decoded = getattr(request, "decoded_token", None)
    if isinstance(decoded, dict):
        return decoded.get("sub")
    return None


def _serialize_device(row: dict) -> dict:
    """Strip server-internal fields before returning to the UI."""
    out = {
        "id": row.get("id"),
        "name": row.get("name"),
        "hostname": row.get("hostname"),
        "os": row.get("os"),
        "arch": row.get("arch"),
        "cli_version": row.get("cli_version"),
        "approval_mode": row.get("approval_mode"),
        "description": row.get("description"),
        "status": row.get("status"),
        "paired_at": row.get("paired_at"),
        "last_seen_at": row.get("last_seen_at"),
        "revoked_at": row.get("revoked_at"),
    }
    # JSON-ify datetimes if SQLAlchemy returned them raw.
    for key in ("paired_at", "last_seen_at", "revoked_at"):
        value = out.get(key)
        if value is not None and not isinstance(value, str):
            out[key] = value.isoformat()
    return out


def list_devices():
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    with db_readonly() as conn:
        rows = DevicesRepository(conn).list_for_user(user_id)
    return make_response(
        jsonify({"devices": [_serialize_device(r) for r in rows]}),
        200,
    )


def get_device(device_id: str):
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    with db_readonly() as conn:
        row = DevicesRepository(conn).get(device_id, user_id=user_id)
    if row is None:
        return make_response(jsonify({"success": False, "error": "not_found"}), 404)
    return make_response(jsonify(_serialize_device(row)), 200)


def update_device(device_id: str):
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    body = request.get_json(silent=True) or {}
    update_fields: dict = {}
    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name.strip():
            return make_response(
                jsonify({"success": False, "error": "invalid_name"}), 400
            )
        update_fields["name"] = name.strip()
    if "description" in body:
        description = body["description"]
        if not isinstance(description, str):
            return make_response(
                jsonify({"success": False, "error": "invalid_description"}), 400
            )
        update_fields["description"] = description.strip()
    if "approval_mode" in body:
        mode = body["approval_mode"]
        if mode not in _ALLOWED_APPROVAL_MODES:
            return make_response(
                jsonify({"success": False, "error": "invalid_approval_mode"}), 400
            )
        update_fields["approval_mode"] = mode
    if not update_fields:
        return make_response(jsonify({"success": False, "error": "no_fields"}), 400)
    with db_session() as conn:
        ok = DevicesRepository(conn).update(device_id, user_id, update_fields)
        if not ok:
            return make_response(
                jsonify({"success": False, "error": "not_found"}), 404
            )
        # Reflect name/description into the user_tools row that fronts this device.
        if "name" in update_fields or "description" in update_fields:
            from application.api.devices.pairing import (
                _upsert_remote_device_user_tool,
            )
            row = DevicesRepository(conn).get(device_id, user_id=user_id)
            if row is not None:
                _upsert_remote_device_user_tool(
                    conn,
                    user_id=user_id,
                    device_id=device_id,
                    device_name=row.get("name") or "device",
                    description=row.get("description"),
                )
        row = DevicesRepository(conn).get(device_id, user_id=user_id)
    return make_response(jsonify(_serialize_device(row)), 200)


def delete_device(device_id: str):
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    with db_session() as conn:
        ok = DevicesRepository(conn).revoke(device_id, user_id)
        if not ok:
            return make_response(
                jsonify({"success": False, "error": "not_found"}), 404
            )
        # Drop the corresponding user_tools row so the tool picker stops showing it.
        from sqlalchemy import text
        conn.execute(
            text(
                """
                DELETE FROM user_tools
                WHERE user_id = :user_id
                  AND name    = 'remote_device'
                  AND config ->> 'device_id' = :device_id
                """
            ),
            {"user_id": user_id, "device_id": device_id},
        )
        DeviceAutoApprovePatternsRepository(conn).clear_for_device(device_id)
    return make_response(jsonify({"success": True}), 200)


def add_auto_approve_pattern(device_id: str):
    """Server-side normalization: client sends the raw command, we store the pattern."""
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    body = request.get_json(silent=True) or {}
    command = body.get("command") or body.get("pattern")
    if not command:
        return make_response(
            jsonify({"success": False, "error": "missing_command"}), 400
        )
    if not isinstance(command, str):
        return make_response(
            jsonify({"success": False, "error": "invalid_command"}), 400
        )
    pattern = normalize_command(command)
    if not pattern:
        return make_response(
            jsonify({"success": False, "error": "invalid_command"}), 400
        )
    with db_session() as conn:
        if DevicesRepository(conn).get(device_id, user_id=user_id) is None:
            return make_response(
                jsonify({"success": False, "error": "not_found"}), 404
            )
        DeviceAutoApprovePatternsRepository(conn).add(device_id, user_id, pattern)
    return make_response(jsonify({"pattern": pattern}), 200)


def list_auto_approve_patterns(device_id: str):
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    with db_readonly() as conn:
        if DevicesRepository(conn).get(device_id, user_id=user_id) is None:
            return make_response(
                jsonify({"success": False, "error": "not_found"}), 404
            )
        patterns = DeviceAutoApprovePatternsRepository(conn).list_for_device(
            device_id, user_id
        )
    return make_response(jsonify({"patterns": patterns}), 200)


def delete_auto_approve_pattern(device_id: str):
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    body = request.get_json(silent=True) or {}
    pattern = body.get("pattern")
    if not pattern:
        return make_response(
            jsonify({"success": False, "error": "missing_pattern"}), 400
        )
    with db_session() as conn:
        ok = DeviceAutoApprovePatternsRepository(conn).remove(
            device_id, user_id, pattern
        )
    return make_response(jsonify({"success": ok}), 200)


def list_audit(device_id: str):
    user_id = _authed_user_id()
    if not user_id:
        return make_response(jsonify({"success": False, "error": "auth"}), 401)
    with db_readonly() as conn:
        if DevicesRepository(conn).get(device_id, user_id=user_id) is None:
            return make_response(
                jsonify({"success": False, "error": "not_found"}), 404
            )
        rows = DeviceAuditLogRepository(conn).list_for_device(device_id, user_id)
    # Normalize datetimes to ISO strings.
    serialized = []
    for row in rows:
        out = dict(row)
        for key in ("issued_at", "started_at", "finished_at", "created_at"):
            v = out.get(key)
            if v is not None and not isinstance(v, str):
                out[key] = v.isoformat()
        serialized.append(out)
    return make_response(jsonify({"entries": serialized}), 200)


def register(bp: Blueprint) -> None:
    """Attach all device routes to ``bp``."""
    bp.add_url_rule(
        "/api/devices", view_func=list_devices, methods=["GET"], endpoint="list_devices",
    )
    bp.add_url_rule(
        "/api/devices/<device_id>", view_func=get_device, methods=["GET"],
        endpoint="get_device",
    )
    bp.add_url_rule(
        "/api/devices/<device_id>", view_func=update_device, methods=["PATCH"],
        endpoint="update_device",
    )
    bp.add_url_rule(
        "/api/devices/<device_id>", view_func=delete_device, methods=["DELETE"],
        endpoint="delete_device",
    )
    bp.add_url_rule(
        "/api/devices/<device_id>/auto-approve",
        view_func=add_auto_approve_pattern, methods=["POST"],
        endpoint="add_auto_approve_pattern",
    )
    bp.add_url_rule(
        "/api/devices/<device_id>/auto-approve",
        view_func=list_auto_approve_patterns, methods=["GET"],
        endpoint="list_auto_approve_patterns",
    )
    bp.add_url_rule(
        "/api/devices/<device_id>/auto-approve",
        view_func=delete_auto_approve_pattern, methods=["DELETE"],
        endpoint="delete_auto_approve_pattern",
    )
    bp.add_url_rule(
        "/api/devices/<device_id>/audit", view_func=list_audit, methods=["GET"],
        endpoint="list_audit",
    )
    # Pairing endpoints
    bp.add_url_rule(
        "/api/devices/pairings", view_func=create_pairing, methods=["POST"],
        endpoint="create_pairing",
    )
    bp.add_url_rule(
        "/api/devices/pairings/redeem", view_func=redeem_pairing, methods=["POST"],
        endpoint="redeem_pairing",
    )
    bp.add_url_rule(
        "/api/devices/pairings/<device_code>", view_func=get_pairing, methods=["GET"],
        endpoint="get_pairing",
    )
    bp.add_url_rule(
        "/api/devices/pairings/<device_code>", view_func=delete_pairing,
        methods=["DELETE"], endpoint="delete_pairing",
    )
    # Session endpoints (device-token auth)
    bp.add_url_rule(
        "/api/devices/poll", view_func=poll, methods=["GET"], endpoint="device_poll",
    )
    bp.add_url_rule(
        "/api/devices/me", view_func=me, methods=["GET"], endpoint="device_me",
    )
    bp.add_url_rule(
        "/api/devices/sessions/<session_id>/events", view_func=session_events,
        methods=["GET"], endpoint="device_session_events",
    )
    bp.add_url_rule(
        "/api/devices/sessions/<session_id>/invocations/<invocation_id>/ack",
        view_func=ack_invocation, methods=["POST"], endpoint="device_ack",
    )
    bp.add_url_rule(
        "/api/devices/sessions/<session_id>/invocations/<invocation_id>/output",
        view_func=submit_output, methods=["POST"], endpoint="device_output",
    )
