# tests/core/test_json_schema_utils.py
# NEW FILE — does not exist in the repo yet.
# Run with: pytest tests/core/test_json_schema_utils.py -v
import pytest

from docsgpt.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)


class TestNormalizeJsonSchemaPayload:
    def test_none_returns_none(self):
        assert normalize_json_schema_payload(None) is None

    def test_non_dict_raises(self):
        for bad_input in ["a string", 123, [1, 2, 3], True]:
            with pytest.raises(JsonSchemaValidationError, match="must be a valid JSON object"):
                normalize_json_schema_payload(bad_input)

    def test_raw_schema_with_type_passes_through(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        assert normalize_json_schema_payload(schema) == schema

    def test_raw_schema_without_type_raises(self):
        with pytest.raises(
            JsonSchemaValidationError,
            match='must include either a "type" or "schema" field',
        ):
            normalize_json_schema_payload({"properties": {}})

    def test_wrapped_schema_is_unwrapped(self):
        inner = {"type": "string"}
        assert normalize_json_schema_payload({"schema": inner}) == inner

    def test_wrapped_schema_non_dict_raises(self):
        with pytest.raises(
            JsonSchemaValidationError, match='field "schema" must be a valid JSON object'
        ):
            normalize_json_schema_payload({"schema": "not-an-object"})

    def test_wrapped_empty_schema_object_is_returned_as_is(self):
        # An empty object is a legitimate (if permissive) JSON schema.
        # The function uses `wrapped_schema is not None` (not truthiness),
        # so {} must NOT be treated as absent — this is the trickiest edge case.
        assert normalize_json_schema_payload({"schema": {}}) == {}

    def test_empty_dict_raises_missing_type_or_schema(self):
        with pytest.raises(JsonSchemaValidationError):
            normalize_json_schema_payload({})
