"""
API Specification Parser

Parses OpenAPI 3.x and Swagger 2.0 specifications and converts them
to API Tool action definitions for use in DocsGPT.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

SUPPORTED_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options"}
)


def parse_spec(spec_content: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Parse an API specification and convert operations to action definitions.

    Supports OpenAPI 3.x and Swagger 2.0 formats in JSON or YAML.

    Args:
        spec_content: Raw specification content as string

    Returns:
        Tuple of (metadata dict, list of action dicts)

    Raises:
        ValueError: If the spec is invalid or uses an unsupported format
    """
    spec = _load_spec(spec_content)
    _validate_spec(spec)

    is_swagger = "swagger" in spec
    metadata = _extract_metadata(spec, is_swagger)
    actions = _extract_actions(spec, is_swagger)

    return metadata, actions


def _load_spec(content: str) -> Dict[str, Any]:
    """Parse spec content from JSON or YAML string."""
    content = content.strip()
    if not content:
        raise ValueError("Empty specification content")
    try:
        if content.startswith("{"):
            return json.loads(content)
        return yaml.safe_load(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e.msg}")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML format: {e}")


def _validate_spec(spec: Dict[str, Any]) -> None:
    """Validate spec version and required fields."""
    if not isinstance(spec, dict):
        raise ValueError("Specification must be a valid object")
    openapi_version = spec.get("openapi", "")
    swagger_version = spec.get("swagger", "")

    if not (openapi_version.startswith("3.") or swagger_version == "2.0"):
        raise ValueError(
            "Unsupported specification version. Expected OpenAPI 3.x or Swagger 2.0"
        )
    if "paths" not in spec or not spec["paths"]:
        raise ValueError("No API paths defined in the specification")


def _extract_metadata(spec: Dict[str, Any], is_swagger: bool) -> Dict[str, Any]:
    """Extract API metadata from specification."""
    info = spec.get("info", {})
    base_url = _get_base_url(spec, is_swagger)

    return {
        "title": info.get("title", "Untitled API"),
        "description": (info.get("description", "") or "")[:500],
        "version": info.get("version", ""),
        "base_url": base_url,
    }


def _get_base_url(spec: Dict[str, Any], is_swagger: bool) -> str:
    """Extract base URL from spec (handles both OpenAPI 3.x and Swagger 2.0)."""
    if is_swagger:
        schemes = spec.get("schemes", ["https"])
        host = spec.get("host", "")
        base_path = spec.get("basePath", "")
        if host:
            scheme = schemes[0] if schemes else "https"
            return f"{scheme}://{host}{base_path}".rstrip("/")
        return ""
    servers = spec.get("servers", [])
    if servers and isinstance(servers, list) and servers[0].get("url"):
        return servers[0]["url"].rstrip("/")
    return ""


def _extract_actions(spec: Dict[str, Any], is_swagger: bool) -> List[Dict[str, Any]]:
    """Extract all API operations as action definitions."""
    actions = []
    paths = spec.get("paths", {})
    base_url = _get_base_url(spec, is_swagger)

    components = spec.get("components", {})
    definitions = spec.get("definitions", {})

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_params = path_item.get("parameters", [])

        for method in SUPPORTED_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            try:
                action = _build_action(
                    path=path,
                    method=method,
                    operation=operation,
                    path_params=path_params,
                    base_url=base_url,
                    components=components,
                    definitions=definitions,
                    is_swagger=is_swagger,
                )
                actions.append(action)
            except Exception as e:
                logger.warning(
                    f"Failed to parse operation {method.upper()} {path}: {e}"
                )
                continue
    return actions


def _build_action(
    path: str,
    method: str,
    operation: Dict[str, Any],
    path_params: List[Dict],
    base_url: str,
    components: Dict[str, Any],
    definitions: Dict[str, Any],
    is_swagger: bool,
) -> Dict[str, Any]:
    """Build a single action from an API operation."""
    action_name = _generate_action_name(operation, method, path)
    full_url = f"{base_url}{path}" if base_url else path

    all_params = path_params + operation.get("parameters", [])
    query_params, headers = _categorize_parameters(all_params, components, definitions)

    body, body_content_type = _extract_request_body(
        operation, components, definitions, is_swagger
    )

    description = operation.get("summary", "") or operation.get("description", "")

    return {
        "name": action_name,
        "url": full_url,
        "method": method.upper(),
        "description": (description or "")[:500],
        "query_params": {"type": "object", "properties": query_params},
        "headers": {"type": "object", "properties": headers},
        "body": {"type": "object", "properties": body},
        "body_content_type": body_content_type,
        "active": True,
    }


def _generate_action_name(operation: Dict[str, Any], method: str, path: str) -> str:
    """Generate a valid action name from operationId or method+path."""
    if operation.get("operationId"):
        name = operation["operationId"]
    else:
        path_slug = re.sub(r"[{}]", "", path)
        path_slug = re.sub(r"[^a-zA-Z0-9]", "_", path_slug)
        path_slug = re.sub(r"_+", "_", path_slug).strip("_")
        name = f"{method}_{path_slug}"
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return name[:64]


def _categorize_parameters(
    parameters: List[Dict],
    components: Dict[str, Any],
    definitions: Dict[str, Any],
) -> Tuple[Dict, Dict]:
    """Categorize parameters into query params and headers."""
    query_params = {}
    headers = {}

    for param in parameters:
        resolved = _resolve_ref(param, components, definitions)
        if not resolved or "name" not in resolved:
            continue
        location = resolved.get("in", "query")
        prop = _param_to_property(resolved)

        if location in ("query", "path"):
            query_params[resolved["name"]] = prop
        elif location == "header":
            headers[resolved["name"]] = prop
    return query_params, headers


def _param_to_property(param: Dict) -> Dict[str, Any]:
    """Convert an API parameter to an action property definition."""
    schema = param.get("schema", {})
    param_type = schema.get("type", param.get("type", "string"))

    mapped_type = "integer" if param_type in ("integer", "number") else "string"

    return {
        "type": mapped_type,
        "description": (param.get("description", "") or "")[:200],
        "value": "",
        "filled_by_llm": param.get("required", False),
        "required": param.get("required", False),
    }


def _extract_request_body(
    operation: Dict[str, Any],
    components: Dict[str, Any],
    definitions: Dict[str, Any],
    is_swagger: bool,
) -> Tuple[Dict, str]:
    """Extract request body schema and content type."""
    content_types = [
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "text/plain",
        "application/xml",
    ]

    if is_swagger:
        consumes = operation.get("consumes", [])
        body_param = next(
            (p for p in operation.get("parameters", []) if p.get("in") == "body"), None
        )
        if not body_param:
            return {}, "application/json"
        selected_type = consumes[0] if consumes else "application/json"
        schema = body_param.get("schema", {})
    else:
        request_body = operation.get("requestBody", {})
        if not request_body:
            return {}, "application/json"
        request_body = _resolve_ref(request_body, components, definitions)
        content = request_body.get("content", {})

        selected_type = "application/json"
        schema = {}

        for ct in content_types:
            if ct in content:
                selected_type = ct
                schema = content[ct].get("schema", {})
                break
        if not schema and content:
            first_type = next(iter(content))
            selected_type = first_type
            schema = content[first_type].get("schema", {})
    properties = _schema_to_properties(schema, components, definitions)
    return properties, selected_type


def _schema_to_properties(
    schema: Dict,
    components: Dict[str, Any],
    definitions: Dict[str, Any],
    depth: int = 0,
) -> Dict[str, Any]:
    """Convert schema to action body properties (limited depth to prevent recursion)."""
    if depth > 3:
        return {}
    schema = _resolve_ref(schema, components, definitions)
    if not schema or not isinstance(schema, dict):
        return {}
    properties = {}
    schema_type = schema.get("type", "object")

    if schema_type == "object":
        required_fields = set(schema.get("required", []))
        for prop_name, prop_schema in schema.get("properties", {}).items():
            resolved = _resolve_ref(prop_schema, components, definitions)
            if not isinstance(resolved, dict):
                continue
            prop_type = resolved.get("type", "string")
            mapped_type = "integer" if prop_type in ("integer", "number") else "string"

            properties[prop_name] = {
                "type": mapped_type,
                "description": (resolved.get("description", "") or "")[:200],
                "value": "",
                "filled_by_llm": prop_name in required_fields,
                "required": prop_name in required_fields,
            }
    return properties


def _resolve_ref(
    obj: Any,
    components: Dict[str, Any],
    definitions: Dict[str, Any],
) -> Optional[Dict]:
    """Resolve $ref references in the specification."""
    if not isinstance(obj, dict):
        return obj if isinstance(obj, dict) else None
    if "$ref" not in obj:
        return obj
    ref_path = obj["$ref"]

    if ref_path.startswith("#/components/"):
        parts = ref_path.replace("#/components/", "").split("/")
        return _traverse_path(components, parts)
    elif ref_path.startswith("#/definitions/"):
        parts = ref_path.replace("#/definitions/", "").split("/")
        return _traverse_path(definitions, parts)
    logger.debug(f"Unsupported ref path: {ref_path}")
    return None


def _traverse_path(obj: Dict, parts: List[str]) -> Optional[Dict]:
    """Traverse a nested dictionary using path parts."""
    try:
        for part in parts:
            obj = obj[part]
        return obj if isinstance(obj, dict) else None
    except (KeyError, TypeError):
        return None
