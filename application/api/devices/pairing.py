"""Pairing flow (RFC 8628 device authorization grant)."""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from typing import Optional

from flask import jsonify, make_response, request

from application.api.devices.auth import fingerprint_pubkey, hash_session_token
from application.cache import get_redis_instance
from application.core.settings import settings
from application.storage.db.repositories.devices import DevicesRepository
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.session import db_session


logger = logging.getLogger(__name__)


_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_USER_CODE_LEN = 8  # ABCD-WXYZ (8 chars, displayed with a single dash)
_PAIRING_REDIS_PREFIX = "docsgpt:device_pairing:"
_ALLOWED_APPROVAL_MODES = {"ask", "full"}

# Atomic redeem claim: read the pairing JSON, and only if its ``status`` is
# ``pending`` flip it to ``redeemed`` and write it back (TTL preserved).
# Returns 1 if this caller won the claim, 0 otherwise (missing/not pending).
# Run server-side so two concurrent redeems of one code can't both win.
_CLAIM_PAIRING_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
local ok, state = pcall(cjson.decode, raw)
if not ok then
    return 0
end
if state['status'] ~= 'pending' then
    return 0
end
state['status'] = 'redeemed'
local ttl = redis.call('TTL', KEYS[1])
local encoded = cjson.encode(state)
if ttl and ttl > 0 then
    redis.call('SET', KEYS[1], encoded, 'EX', ttl)
else
    redis.call('SET', KEYS[1], encoded)
end
return 1
"""


def _redis():
    return get_redis_instance()


def _generate_user_code() -> str:
    return "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(_USER_CODE_LEN))


def _format_user_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _normalize_user_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def _user_code_index_key(user_code: str) -> str:
    return f"docsgpt:device_pairing_code:{user_code}"


def create_pairing() -> tuple:
    """Create a new pairing code for the calling user.

    Optional body fields ``name``, ``description``, and ``approval_mode``
    are stashed in Redis alongside the pairing state and consumed by
    ``redeem_pairing`` when the device row is created. Unknown values
    fall back to: name -> CLI hostname; description -> empty; approval_mode
    -> ``ask``.
    """
    decoded = getattr(request, "decoded_token", None)
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return _error("authentication_required", 401)

    body = request.get_json(silent=True) or {}
    raw_name = body.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        return _error("invalid_name", 400)
    requested_name = (raw_name or "").strip() or None
    requested_description = body.get("description")
    if isinstance(requested_description, str):
        requested_description = requested_description.strip() or None
    else:
        requested_description = None
    requested_mode = body.get("approval_mode")
    if requested_mode is not None and requested_mode not in _ALLOWED_APPROVAL_MODES:
        return _error("invalid_approval_mode", 400)

    redis_client = _redis()
    if redis_client is None:
        return _error("redis_unavailable", 503)

    device_code = f"dc_{uuid.uuid4().hex}"
    user_code = _generate_user_code()
    ttl = int(settings.REMOTE_DEVICE_PAIRING_TTL_SECONDS)

    state = {
        "device_code": device_code,
        "user_code": _format_user_code(user_code),
        "user_code_raw": user_code,
        "user_id": user_id,
        "status": "pending",
        "created_at": int(time.time()),
        "requested_name": requested_name,
        "requested_description": requested_description,
        "requested_approval_mode": requested_mode,
    }
    try:
        redis_client.setex(
            _PAIRING_REDIS_PREFIX + device_code, ttl, json.dumps(state)
        )
        redis_client.setex(_user_code_index_key(user_code), ttl, device_code)
    except Exception:
        logger.exception("redis setex failed during pairing create")
        return _error("redis_unavailable", 503)

    base_url = settings.API_URL or ""
    return make_response(
        jsonify(
            {
                "device_code": device_code,
                "user_code": _format_user_code(user_code),
                "verification_uri": base_url,
                "expires_in": ttl,
                "interval": 3,
            }
        ),
        200,
    )


def get_pairing(device_code: str) -> tuple:
    """Poll pairing status (UI side)."""
    decoded = getattr(request, "decoded_token", None)
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return _error("authentication_required", 401)

    state = _load_pairing(device_code)
    if state is None:
        return _error("pairing_not_found", 404)
    if state.get("user_id") != user_id:
        return _error("pairing_not_found", 404)

    return make_response(
        jsonify(
            {
                "device_code": state["device_code"],
                "user_code": state.get("user_code"),
                "status": state.get("status", "pending"),
                "device_id": state.get("device_id"),
                "device_name": state.get("device_name"),
            }
        ),
        200,
    )


def delete_pairing(device_code: str) -> tuple:
    decoded = getattr(request, "decoded_token", None)
    user_id = decoded.get("sub") if isinstance(decoded, dict) else None
    if not user_id:
        return _error("authentication_required", 401)
    state = _load_pairing(device_code)
    if state is None:
        return _error("pairing_not_found", 404)
    if state.get("user_id") != user_id:
        return _error("pairing_not_found", 404)
    redis_client = _redis()
    if redis_client is None:
        return _error("redis_unavailable", 503)
    try:
        redis_client.delete(_PAIRING_REDIS_PREFIX + device_code)
        if state.get("user_code_raw"):
            redis_client.delete(_user_code_index_key(state["user_code_raw"]))
    except Exception:
        logger.exception("redis delete failed during pairing cancel")
    return make_response(jsonify({"success": True}), 200)


def redeem_pairing() -> tuple:
    """CLI submits the user_code and machine info to claim a device row.

    Returns ``device_id`` + opaque ``session_token`` (shown once). The
    token is stored only as ``token_hash`` so a Redis snapshot leak +
    DB snapshot leak still can't reconstruct it.
    """
    body = request.get_json(silent=True) or {}
    user_code_raw = _normalize_user_code(str(body.get("user_code", "")))
    if not user_code_raw or len(user_code_raw) != _USER_CODE_LEN:
        return _error("invalid_user_code", 400)
    hostname = body.get("hostname") or "unknown"
    os_name = body.get("os") or ""
    arch = body.get("arch") or ""
    cli_version = body.get("cli_version") or ""
    pubkey_b64 = body.get("machine_pubkey")
    if not pubkey_b64:
        return _error("missing_machine_pubkey", 400)

    redis_client = _redis()
    if redis_client is None:
        return _error("redis_unavailable", 503)
    try:
        device_code = redis_client.get(_user_code_index_key(user_code_raw))
        if device_code is None:
            return _error("pairing_not_found", 404)
        if isinstance(device_code, (bytes, bytearray)):
            device_code = device_code.decode("utf-8")
    except Exception:
        logger.exception("redis get failed during pairing redeem")
        return _error("redis_unavailable", 503)

    state = _load_pairing(device_code)
    if state is None:
        return _error("pairing_not_found", 404)
    if state.get("status") != "pending":
        return _error("pairing_already_redeemed", 409)

    # Atomically claim the pairing before doing any work. Two concurrent
    # redeems of the same code can both pass the check above; only the one
    # that flips ``pending`` -> ``redeemed`` here proceeds to create a device.
    claimed = _claim_pairing(redis_client, device_code)
    if claimed is None:
        return _error("redis_unavailable", 503)
    if not claimed:
        return _error("pairing_already_redeemed", 409)

    user_id = state["user_id"]

    try:
        fingerprint = fingerprint_pubkey(pubkey_b64)
    except Exception:
        return _error("invalid_machine_pubkey", 400)
    session_token = "tok_" + secrets.token_urlsafe(32)
    token_hash = hash_session_token(session_token)
    device_id = "dev_" + uuid.uuid4().hex

    # Apply UI-side overrides stashed at pairing create time, with
    # sensible fallbacks.
    requested_name = state.get("requested_name") or None
    description = state.get("requested_description") or None
    approval_mode = state.get("requested_approval_mode") or "ask"
    if approval_mode not in _ALLOWED_APPROVAL_MODES:
        approval_mode = "ask"

    name_source = requested_name or hostname
    name = _next_device_name(user_id, name_source)
    try:
        with db_session() as conn:
            DevicesRepository(conn).create(
                device_id=device_id,
                user_id=user_id,
                name=name,
                machine_pubkey_fingerprint=fingerprint,
                token_hash=token_hash,
                hostname=hostname,
                os=os_name,
                arch=arch,
                cli_version=cli_version,
                approval_mode=approval_mode,
                description=description,
            )
            _upsert_remote_device_user_tool(
                conn, user_id=user_id, device_id=device_id,
                device_name=name, description=description,
            )
    except Exception:
        logger.exception("failed to create device row during redeem")
        return _error("internal_error", 500)

    state["status"] = "redeemed"
    state["device_id"] = device_id
    state["device_name"] = name
    try:
        redis_client.setex(
            _PAIRING_REDIS_PREFIX + device_code, 300, json.dumps(state)
        )
        if state.get("user_code_raw"):
            redis_client.delete(_user_code_index_key(state["user_code_raw"]))
    except Exception:
        logger.exception("redis update failed after redeem (non-fatal)")

    return make_response(
        jsonify(
            {
                "device_id": device_id,
                "session_token": session_token,
                "name": name,
            }
        ),
        200,
    )


def _claim_pairing(redis_client, device_code: str) -> Optional[bool]:
    """Atomically transition a pairing from ``pending`` to ``redeemed``.

    Returns ``True`` if this caller won the claim, ``False`` if the pairing
    is already non-pending or gone, and ``None`` if the atomic op itself
    failed (caller should treat that as Redis-unavailable rather than
    proceeding, to avoid a non-atomic double-redeem).
    """
    key = _PAIRING_REDIS_PREFIX + device_code
    try:
        result = redis_client.eval(_CLAIM_PAIRING_LUA, 1, key)
    except Exception:
        logger.exception("redis eval failed during pairing claim")
        return None
    return bool(result)


def _load_pairing(device_code: str) -> Optional[dict]:
    redis_client = _redis()
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(_PAIRING_REDIS_PREFIX + device_code)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except Exception:
        return None


def _next_device_name(user_id: str, hostname: str) -> str:
    """Return a unique name for the new device row (collide-safe)."""
    base = hostname or "device"
    base = base.strip() or "device"
    # The DB UNIQUE (user_id, name) constraint will reject collisions; pick
    # a suffix proactively rather than retrying.
    return f"{base}-{os.urandom(2).hex()}"


def _upsert_remote_device_user_tool(
    conn, *, user_id: str, device_id: str,
    device_name: str, description: Optional[str],
) -> None:
    """Create or update the ``user_tools`` row that fronts this device."""
    repo = UserToolsRepository(conn)
    existing = _find_remote_device_tool_row(conn, user_id, device_id)
    actions = [
        {
            "name": "run_command",
            "description": (
                f"Execute a shell command on the remote device '{device_name}'. "
                f"{description or ''}".strip()
            ),
            "active": True,
            # ``tool_executor`` consults ``RemoteDeviceTool.preview_requires_approval``
            # live for ``remote_device`` calls, so the static snapshot must
            # stay neutral. The tool's own ``execute_action`` still yields
            # the awaiting-approval pause when the live decision says so.
            "require_approval": False,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run.",
                        "filled_by_llm": True,
                        "value": "",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Working directory on the remote.",
                        "filled_by_llm": True,
                        "value": "",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Timeout in milliseconds (max 600000).",
                        "filled_by_llm": True,
                        "value": "",
                    },
                },
                "required": ["command"],
            },
        }
    ]
    config = {"device_id": device_id}
    display_name = f"Remote device — {device_name}"
    if existing:
        repo.update(
            str(existing["id"]),
            user_id,
            {
                "display_name": display_name,
                "description": description or "",
                "config": config,
                "actions": actions,
                "status": True,
            },
        )
    else:
        repo.create(
            user_id=user_id,
            name="remote_device",
            display_name=display_name,
            description=description or "",
            config=config,
            actions=actions,
            status=True,
        )


def _find_remote_device_tool_row(conn, user_id: str, device_id: str):
    """Locate the user_tools row whose config.device_id matches."""
    from sqlalchemy import text
    row = conn.execute(
        text(
            """
            SELECT *
            FROM user_tools
            WHERE user_id = :user_id
              AND name    = 'remote_device'
              AND config ->> 'device_id' = :device_id
            LIMIT 1
            """
        ),
        {"user_id": user_id, "device_id": device_id},
    ).fetchone()
    if row is None:
        return None
    return dict(row._mapping)


def _error(code: str, status: int) -> tuple:
    return make_response(jsonify({"success": False, "error": code}), status)
