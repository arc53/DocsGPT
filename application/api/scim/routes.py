"""SCIM 2.0 user-provisioning endpoints (RFC 7643/7644 subset for IdP clients).

IdPs (Okta, Authentik, Entra) push user lifecycle into DocsGPT through
``/scim/v2``: create users ahead of first login and deactivate them on
offboarding. Deactivation also revokes live sessions via the Redis
denylist; login refuses inactive users elsewhere. Only ``userName`` and
``active`` are honored — everything else IdPs send is ignored.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from typing import Any, Optional

from flask import Blueprint, Response, request
from sqlalchemy import Connection

from application.api.oidc.denylist import allow_user, deny_user
from application.core.settings import settings
from application.storage.db.repositories.auth_events import AuthEventsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)

_SCIM_MEDIA_TYPE = "application/scim+json"
_ERROR_URN = "urn:ietf:params:scim:api:messages:2.0:Error"
_LIST_RESPONSE_URN = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_USER_URN = "urn:ietf:params:scim:schemas:core:2.0:User"

_DEFAULT_COUNT = 100
_MAX_COUNT = 200

# The only filter IdPs need for provisioning: exact userName lookup.
_USERNAME_EQ_FILTER = re.compile(r'^\s*userName\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE)

_SERVICE_PROVIDER_CONFIG = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
    "patch": {"supported": True},
    "bulk": {"supported": False},
    "filter": {"supported": True, "maxResults": _MAX_COUNT},
    "changePassword": {"supported": False},
    "sort": {"supported": False},
    "etag": {"supported": False},
    "authenticationSchemes": [
        {
            "type": "oauthbearertoken",
            "name": "Bearer Token",
            "description": "Authorization header carrying the configured SCIM bearer token",
        }
    ],
}

_USER_RESOURCE_TYPE = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
    "id": "User",
    "name": "User",
    "endpoint": "/scim/v2/Users",
    "schema": _USER_URN,
    "meta": {"resourceType": "ResourceType", "location": "/scim/v2/ResourceTypes/User"},
}

_USER_SCHEMA = {
    "id": _USER_URN,
    "name": "User",
    "description": "DocsGPT user account",
    "attributes": [
        {
            "name": "userName",
            "type": "string",
            "multiValued": False,
            "required": True,
            "caseExact": True,
            "mutability": "immutable",
            "returned": "default",
            "uniqueness": "server",
        },
        {
            "name": "active",
            "type": "boolean",
            "multiValued": False,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
        },
    ],
    "meta": {"resourceType": "Schema", "location": f"/scim/v2/Schemas/{_USER_URN}"},
}


# ----------------------------------------------------------------------
# Response helpers
# ----------------------------------------------------------------------
def _scim_response(payload: Optional[dict], status: int, headers: Optional[dict] = None) -> Response:
    """Build a response with the SCIM media type; ``None`` payload means empty body."""
    body = "" if payload is None else json.dumps(payload)
    response = Response(body, status=status, mimetype=_SCIM_MEDIA_TYPE)
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def _scim_error(status: int, detail: str, scim_type: Optional[str] = None) -> Response:
    """Build an RFC 7644 error response."""
    payload: dict = {"schemas": [_ERROR_URN], "status": str(status), "detail": detail}
    if scim_type:
        payload["scimType"] = scim_type
    return _scim_response(payload, status)


def _static_list_response(resources: list) -> dict:
    """Wrap fixed resources in a SCIM ListResponse."""
    return {
        "schemas": [_LIST_RESPONSE_URN],
        "totalResults": len(resources),
        "startIndex": 1,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def _iso(value: Any) -> Optional[str]:
    """Return an ISO-8601 string (repository rows may carry str or datetime)."""
    if value is None:
        return None
    return value if isinstance(value, str) else value.isoformat()


def _serialize_user(row: dict) -> dict:
    """Map a ``users`` row to a SCIM User resource."""
    pk = str(row["id"])
    user_name = row["user_id"]
    resource = {
        "schemas": [_USER_URN],
        "id": pk,
        "userName": user_name,
        "active": bool(row["active"]),
    }
    if "@" in user_name:
        resource["emails"] = [{"value": user_name, "primary": True}]
    resource["meta"] = {
        "resourceType": "User",
        "created": _iso(row.get("created_at")),
        "lastModified": _iso(row.get("updated_at")),
        "location": f"/scim/v2/Users/{pk}",
    }
    return resource


# ----------------------------------------------------------------------
# Request parsing helpers
# ----------------------------------------------------------------------
def _coerce_active(value: Any) -> Optional[bool]:
    """Coerce a SCIM ``active`` value to bool; ``None`` when invalid (Okta sends strings)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _int_arg(name: str, default: int) -> int:
    """Read an integer query parameter, falling back to ``default``."""
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_filter(raw: Optional[str]) -> tuple[Optional[str], Optional[Response]]:
    """Parse the ``filter`` query param; only ``userName eq "value"`` is supported."""
    if raw is None or not raw.strip():
        return None, None
    match = _USERNAME_EQ_FILTER.match(raw)
    if match is None:
        return None, _scim_error(400, 'Only the filter userName eq "value" is supported', "invalidFilter")
    return match.group(1), None


# ----------------------------------------------------------------------
# Side effects
# ----------------------------------------------------------------------
def _audit(conn: Connection, user_id: str, event: str) -> None:
    """Best-effort audit insert in a savepoint; failure never fails the request."""
    try:
        with conn.begin_nested():
            AuthEventsRepository(conn).insert(user_id, event, metadata={"via": "scim"})
    except Exception:
        logger.error("SCIM audit insert failed for user %s event %s", user_id, event, exc_info=True)


def _apply_active(conn: Connection, row: dict, desired: bool) -> dict:
    """Apply an ``active`` transition; side effects run only when the value changes."""
    if bool(row["active"]) == desired:
        return row
    updated = UsersRepository(conn).set_active(str(row["id"]), desired) or row
    user_id = row["user_id"]
    if desired:
        allow_user(user_id)
        _audit(conn, user_id, "scim_reactivated")
    else:
        deny_user(user_id)
        _audit(conn, user_id, "scim_deactivated")
    return updated


# ----------------------------------------------------------------------
# Bearer-token gate
# ----------------------------------------------------------------------
def _enforce_scim_auth() -> Optional[Response]:
    """Gate every SCIM request on SCIM_ENABLED and the shared bearer token."""
    if not settings.SCIM_ENABLED:
        return _scim_error(404, "SCIM provisioning is not enabled")
    token = settings.SCIM_TOKEN
    if not token:
        logger.error("SCIM is enabled but SCIM_TOKEN is not configured — rejecting request")
        return _scim_error(503, "SCIM is enabled but no SCIM_TOKEN is configured")
    scheme, _, presented = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        presented.strip().encode("utf-8"), token.encode("utf-8")
    ):
        return _scim_error(401, "Invalid or missing bearer token")
    return None


# ----------------------------------------------------------------------
# Discovery endpoints
# ----------------------------------------------------------------------
def service_provider_config():
    """Static service-provider capabilities document."""
    return _scim_response(_SERVICE_PROVIDER_CONFIG, 200)


def resource_types():
    """Advertise the User resource type."""
    return _scim_response(_static_list_response([_USER_RESOURCE_TYPE]), 200)


def schemas():
    """Advertise the User schema."""
    return _scim_response(_static_list_response([_USER_SCHEMA]), 200)


# ----------------------------------------------------------------------
# Users
# ----------------------------------------------------------------------
def list_users():
    """List users with optional exact userName filter and 1-based pagination."""
    user_name, error = _parse_filter(request.args.get("filter"))
    if error is not None:
        return error
    start_index = max(1, _int_arg("startIndex", 1))
    count = min(max(0, _int_arg("count", _DEFAULT_COUNT)), _MAX_COUNT)
    with db_readonly() as conn:
        total, rows = UsersRepository(conn).list_paginated(user_name, start_index - 1, count)
    return _scim_response(
        {
            "schemas": [_LIST_RESPONSE_URN],
            "totalResults": total,
            "startIndex": start_index,
            "itemsPerPage": len(rows),
            "Resources": [_serialize_user(row) for row in rows],
        },
        200,
    )


def create_user():
    """Create a user from ``userName`` (+ optional ``active``); 409 on duplicates."""
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return _scim_error(400, "Request body must be a JSON object", "invalidValue")
    user_name = body.get("userName")
    if not isinstance(user_name, str) or not user_name.strip():
        return _scim_error(400, "userName is required", "invalidValue")
    active = _coerce_active(body.get("active", True))
    if active is None:
        return _scim_error(400, "active must be a boolean", "invalidValue")
    with db_session() as conn:
        row = UsersRepository(conn).create(user_name, active=active)
        if row is None:
            return _scim_error(409, f"User {user_name} already exists", "uniqueness")
        _audit(conn, user_name, "scim_created")
    resource = _serialize_user(row)
    return _scim_response(resource, 201, headers={"Location": resource["meta"]["location"]})


def get_user(user_pk: str):
    """Fetch one user by primary key."""
    with db_readonly() as conn:
        row = UsersRepository(conn).get_by_pk(user_pk)
    if not row:
        return _scim_error(404, "User not found")
    return _scim_response(_serialize_user(row), 200)


def replace_user(user_pk: str):
    """Full replace; only ``active`` is honored and ``userName`` is immutable."""
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return _scim_error(400, "Request body must be a JSON object", "invalidValue")
    desired: Optional[bool] = None
    if "active" in body:
        desired = _coerce_active(body["active"])
        if desired is None:
            return _scim_error(400, "active must be a boolean", "invalidValue")
    with db_session() as conn:
        row = UsersRepository(conn).get_by_pk(user_pk)
        if not row:
            return _scim_error(404, "User not found")
        if "userName" in body and body["userName"] != row["user_id"]:
            return _scim_error(400, "userName is immutable", "mutability")
        if desired is not None:
            row = _apply_active(conn, row, desired)
    return _scim_response(_serialize_user(row), 200)


def patch_user(user_pk: str):
    """Apply PatchOp replace operations targeting ``active``."""
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return _scim_error(400, "Request body must be a JSON object", "invalidValue")
    operations = body.get("Operations")
    if not isinstance(operations, list) or not operations:
        return _scim_error(400, "PatchOp body with Operations is required", "invalidValue")
    desired: Optional[bool] = None
    for operation in operations:
        if not isinstance(operation, dict) or str(operation.get("op", "")).strip().lower() != "replace":
            return _scim_error(400, "Only the replace operation is supported", "invalidPath")
        path = str(operation.get("path") or "").strip()
        if not path:
            value = operation.get("value")
            if not isinstance(value, dict):
                return _scim_error(400, "replace without path requires an object value", "invalidValue")
            if "active" not in value:
                continue  # Only "active" is honored; other attributes are ignored.
            candidate = value["active"]
        elif path.lower() == "active":
            candidate = operation.get("value")
        else:
            return _scim_error(400, f"Unsupported path: {path}", "invalidPath")
        coerced = _coerce_active(candidate)
        if coerced is None:
            return _scim_error(400, "active must be a boolean", "invalidValue")
        desired = coerced
    with db_session() as conn:
        row = UsersRepository(conn).get_by_pk(user_pk)
        if not row:
            return _scim_error(404, "User not found")
        if desired is not None:
            row = _apply_active(conn, row, desired)
    return _scim_response(_serialize_user(row), 200)


def delete_user(user_pk: str):
    """Soft delete: deactivate the user and revoke live sessions."""
    with db_session() as conn:
        row = UsersRepository(conn).get_by_pk(user_pk)
        if not row:
            return _scim_error(404, "User not found")
        _apply_active(conn, row, False)
    return _scim_response(None, 204)


# ----------------------------------------------------------------------
# Groups (not supported — answered so IdP probes don't hard-fail)
# ----------------------------------------------------------------------
def list_groups():
    """Groups are not provisioned; always an empty ListResponse."""
    return _scim_response(_static_list_response([]), 200)


def create_group():
    """Group creation is not supported."""
    return _scim_error(501, "Group provisioning is not supported")


def group_detail(group_id: str):
    """Individual groups never exist; mutations are unsupported."""
    if request.method == "GET":
        return _scim_error(404, "Group not found")
    return _scim_error(501, "Group provisioning is not supported")


def register(bp: Blueprint) -> None:
    """Attach the SCIM routes and bearer-token gate to ``bp``."""
    bp.before_request(_enforce_scim_auth)
    bp.add_url_rule(
        "/scim/v2/ServiceProviderConfig", view_func=service_provider_config, methods=["GET"],
        endpoint="service_provider_config",
    )
    bp.add_url_rule(
        "/scim/v2/ResourceTypes", view_func=resource_types, methods=["GET"], endpoint="resource_types",
    )
    bp.add_url_rule(
        "/scim/v2/Schemas", view_func=schemas, methods=["GET"], endpoint="schemas",
    )
    bp.add_url_rule(
        "/scim/v2/Users", view_func=list_users, methods=["GET"], endpoint="list_users",
    )
    bp.add_url_rule(
        "/scim/v2/Users", view_func=create_user, methods=["POST"], endpoint="create_user",
    )
    bp.add_url_rule(
        "/scim/v2/Users/<user_pk>", view_func=get_user, methods=["GET"], endpoint="get_user",
    )
    bp.add_url_rule(
        "/scim/v2/Users/<user_pk>", view_func=replace_user, methods=["PUT"], endpoint="replace_user",
    )
    bp.add_url_rule(
        "/scim/v2/Users/<user_pk>", view_func=patch_user, methods=["PATCH"], endpoint="patch_user",
    )
    bp.add_url_rule(
        "/scim/v2/Users/<user_pk>", view_func=delete_user, methods=["DELETE"], endpoint="delete_user",
    )
    bp.add_url_rule(
        "/scim/v2/Groups", view_func=list_groups, methods=["GET"], endpoint="list_groups",
    )
    bp.add_url_rule(
        "/scim/v2/Groups", view_func=create_group, methods=["POST"], endpoint="create_group",
    )
    bp.add_url_rule(
        "/scim/v2/Groups/<group_id>", view_func=group_detail,
        methods=["GET", "PUT", "PATCH", "DELETE"], endpoint="group_detail",
    )
