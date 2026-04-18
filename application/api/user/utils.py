"""Centralized utilities for API routes.

Post-Mongo-cutover slim: the old Mongo-shaped helpers (``validate_object_id``,
``check_resource_ownership``, ``paginated_response``, ``serialize_object_id``,
``safe_db_operation``, ``validate_enum``, ``extract_sort_params``) have been
removed — they carried ``bson`` / ``pymongo`` imports and had zero callers.
"""

from functools import wraps
from typing import Callable, Optional

from flask import (
    Response,
    jsonify,
    make_response,
    request,
)


def get_user_id() -> Optional[str]:
    """Extract user ID from decoded JWT token, or None if unauthenticated."""
    decoded_token = getattr(request, "decoded_token", None)
    return decoded_token.get("sub") if decoded_token else None


def require_auth(func: Callable) -> Callable:
    """Decorator to require authentication. Returns 401 when absent."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        user_id = get_user_id()
        if not user_id:
            return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
        return func(*args, **kwargs)

    return wrapper


def success_response(
    data=None, message: Optional[str] = None, status: int = 200
) -> Response:
    """Shape a successful JSON response."""
    body = {"success": True}
    if data is not None:
        body["data"] = data
    if message is not None:
        body["message"] = message
    return make_response(jsonify(body), status)


def error_response(message: str, status: int = 400, **kwargs) -> Response:
    """Shape an error JSON response; any kwargs are merged into the body."""
    body = {"success": False, "error": message, **kwargs}
    return make_response(jsonify(body), status)


def require_fields(required: list) -> Callable:
    """Decorator: return 400 if any listed field is missing/falsy in the JSON body."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            data = request.get_json()
            if not data:
                return error_response("Request body required")
            missing = [field for field in required if not data.get(field)]
            if missing:
                return error_response(
                    f"Missing required fields: {', '.join(missing)}"
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator
