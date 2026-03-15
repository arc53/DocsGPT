from typing import Any, Dict, Optional


class JsonSchemaValidationError(ValueError):
    """Raised when a JSON schema payload is invalid."""


def normalize_json_schema_payload(json_schema: Any) -> Optional[Dict[str, Any]]:
    """
    Normalize accepted JSON schema payload shapes to a plain schema object.

    Accepted inputs:
    - None
    - A raw schema object with a top-level "type"
    - A wrapped payload with a top-level "schema" object
    """
    if json_schema is None:
        return None

    if not isinstance(json_schema, dict):
        raise JsonSchemaValidationError("must be a valid JSON object")

    wrapped_schema = json_schema.get("schema")
    if wrapped_schema is not None:
        if not isinstance(wrapped_schema, dict):
            raise JsonSchemaValidationError('field "schema" must be a valid JSON object')
        return wrapped_schema

    if "type" not in json_schema:
        raise JsonSchemaValidationError(
            'must include either a "type" or "schema" field'
        )

    return json_schema
