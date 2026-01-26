"""Centralized utilities for API routes."""

from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from bson.errors import InvalidId
from bson.objectid import ObjectId
from flask import jsonify, make_response, request, Response
from pymongo.collection import Collection


def get_user_id() -> Optional[str]:
    """
    Extract user ID from decoded JWT token.

    Returns:
        User ID string or None if not authenticated
    """
    decoded_token = getattr(request, "decoded_token", None)
    return decoded_token.get("sub") if decoded_token else None


def require_auth(func: Callable) -> Callable:
    """
    Decorator to require authentication for route handlers.

    Usage:
        @require_auth
        def get(self):
            user_id = get_user_id()
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        user_id = get_user_id()
        if not user_id:
            return error_response("Unauthorized", 401)
        return func(*args, **kwargs)

    return wrapper


def success_response(
    data: Optional[Dict[str, Any]] = None, status: int = 200
) -> Response:
    """
    Create a standardized success response.

    Args:
        data: Optional data dictionary to include in response
        status: HTTP status code (default: 200)

    Returns:
        Flask Response object

    Example:
        return success_response({"users": [...], "total": 10})
    """
    response = {"success": True}
    if data:
        response.update(data)
    return make_response(jsonify(response), status)


def error_response(message: str, status: int = 400, **kwargs) -> Response:
    """
    Create a standardized error response.

    Args:
        message: Error message string
        status: HTTP status code (default: 400)
        **kwargs: Additional fields to include in response

    Returns:
        Flask Response object

    Example:
        return error_response("Resource not found", 404)
        return error_response("Invalid input", 400, errors=["field1", "field2"])
    """
    response = {"success": False, "message": message}
    response.update(kwargs)
    return make_response(jsonify(response), status)


def validate_object_id(
    id_string: str, resource_name: str = "Resource"
) -> Tuple[Optional[ObjectId], Optional[Response]]:
    """
    Validate and convert string to ObjectId.

    Args:
        id_string: String to convert
        resource_name: Name of resource for error message

    Returns:
        Tuple of (ObjectId or None, error_response or None)

    Example:
        obj_id, error = validate_object_id(workflow_id, "Workflow")
        if error:
            return error
    """
    try:
        return ObjectId(id_string), None
    except (InvalidId, TypeError):
        return None, error_response(f"Invalid {resource_name} ID format")


def validate_pagination(
    default_limit: int = 20, max_limit: int = 100
) -> Tuple[int, int, Optional[Response]]:
    """
    Extract and validate pagination parameters from request.

    Args:
        default_limit: Default items per page
        max_limit: Maximum allowed items per page

    Returns:
        Tuple of (limit, skip, error_response or None)

    Example:
        limit, skip, error = validate_pagination()
        if error:
            return error
    """
    try:
        limit = min(int(request.args.get("limit", default_limit)), max_limit)
        skip = int(request.args.get("skip", 0))
        if limit < 1 or skip < 0:
            return 0, 0, error_response("Invalid pagination parameters")
        return limit, skip, None
    except ValueError:
        return 0, 0, error_response("Invalid pagination parameters")


def check_resource_ownership(
    collection: Collection,
    resource_id: ObjectId,
    user_id: str,
    resource_name: str = "Resource",
) -> Tuple[Optional[Dict], Optional[Response]]:
    """
    Check if resource exists and belongs to user.

    Args:
        collection: MongoDB collection
        resource_id: Resource ObjectId
        user_id: User ID string
        resource_name: Name of resource for error messages

    Returns:
        Tuple of (resource_dict or None, error_response or None)

    Example:
        workflow, error = check_resource_ownership(
            workflows_collection,
            workflow_id,
            user_id,
            "Workflow"
        )
        if error:
            return error
    """
    resource = collection.find_one({"_id": resource_id, "user": user_id})
    if not resource:
        return None, error_response(f"{resource_name} not found", 404)
    return resource, None


def serialize_object_id(
    obj: Dict[str, Any], id_field: str = "_id", new_field: str = "id"
) -> Dict[str, Any]:
    """
    Convert ObjectId to string in a dictionary.

    Args:
        obj: Dictionary containing ObjectId
        id_field: Field name containing ObjectId
        new_field: New field name for string ID

    Returns:
        Modified dictionary

    Example:
        user = serialize_object_id(user_doc)
        # user["id"] = "507f1f77bcf86cd799439011"
    """
    if id_field in obj:
        obj[new_field] = str(obj[id_field])
        if id_field != new_field:
            obj.pop(id_field, None)
    return obj


def serialize_list(items: List[Dict], serializer: Callable[[Dict], Dict]) -> List[Dict]:
    """
    Apply serializer function to list of items.

    Args:
        items: List of dictionaries
        serializer: Function to apply to each item

    Returns:
        List of serialized items

    Example:
        workflows = serialize_list(workflow_docs, serialize_workflow)
    """
    return [serializer(item) for item in items]


def paginated_response(
    collection: Collection,
    query: Dict[str, Any],
    serializer: Callable[[Dict], Dict],
    limit: int,
    skip: int,
    sort_field: str = "created_at",
    sort_order: int = -1,
    response_key: str = "items",
) -> Response:
    """
    Create paginated response for collection query.

    Args:
        collection: MongoDB collection
        query: Query dictionary
        serializer: Function to serialize each item
        limit: Items per page
        skip: Number of items to skip
        sort_field: Field to sort by
        sort_order: Sort order (1=asc, -1=desc)
        response_key: Key name for items in response

    Returns:
        Flask Response with paginated data

    Example:
        return paginated_response(
            workflows_collection,
            {"user": user_id},
            serialize_workflow,
            limit, skip,
            response_key="workflows"
        )
    """
    items = list(
        collection.find(query).sort(sort_field, sort_order).skip(skip).limit(limit)
    )
    total = collection.count_documents(query)

    return success_response(
        {
            response_key: serialize_list(items, serializer),
            "total": total,
            "limit": limit,
            "skip": skip,
        }
    )


def require_fields(required: List[str]) -> Callable:
    """
    Decorator to validate required fields in request JSON.

    Args:
        required: List of required field names

    Returns:
        Decorator function

    Example:
        @require_fields(["name", "description"])
        def post(self):
            data = request.get_json()
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            data = request.get_json()
            if not data:
                return error_response("Request body required")
            missing = [field for field in required if not data.get(field)]
            if missing:
                return error_response(f"Missing required fields: {', '.join(missing)}")
            return func(*args, **kwargs)

        return wrapper

    return decorator


def safe_db_operation(
    operation: Callable, error_message: str = "Database operation failed"
) -> Tuple[Any, Optional[Response]]:
    """
    Safely execute database operation with error handling.

    Args:
        operation: Function to execute
        error_message: Error message if operation fails

    Returns:
        Tuple of (result or None, error_response or None)

    Example:
        result, error = safe_db_operation(
            lambda: collection.insert_one(doc),
            "Failed to create resource"
        )
        if error:
            return error
    """
    try:
        result = operation()
        return result, None
    except Exception as e:
        return None, error_response(f"{error_message}: {str(e)}")


def validate_enum(
    value: Any, allowed: List[Any], field_name: str
) -> Optional[Response]:
    """
    Validate that value is in allowed list.

    Args:
        value: Value to validate
        allowed: List of allowed values
        field_name: Field name for error message

    Returns:
        error_response if invalid, None if valid

    Example:
        error = validate_enum(status, ["draft", "published"], "status")
        if error:
            return error
    """
    if value not in allowed:
        allowed_str = ", ".join(f"'{v}'" for v in allowed)
        return error_response(f"Invalid {field_name}. Must be one of: {allowed_str}")
    return None


def extract_sort_params(
    default_field: str = "created_at",
    default_order: str = "desc",
    allowed_fields: Optional[List[str]] = None,
) -> Tuple[str, int]:
    """
    Extract and validate sort parameters from request.

    Args:
        default_field: Default sort field
        default_order: Default sort order ("asc" or "desc")
        allowed_fields: List of allowed sort fields (None = no validation)

    Returns:
        Tuple of (sort_field, sort_order)

    Example:
        sort_field, sort_order = extract_sort_params(
            allowed_fields=["name", "date", "status"]
        )
    """
    sort_field = request.args.get("sort", default_field)
    sort_order_str = request.args.get("order", default_order).lower()

    if allowed_fields and sort_field not in allowed_fields:
        sort_field = default_field
    sort_order = -1 if sort_order_str == "desc" else 1
    return sort_field, sort_order
