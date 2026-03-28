"""Tests for application/agents/tools/spec_parser.py"""

import json

import pytest

from application.agents.tools.spec_parser import (
    _extract_metadata,
    _generate_action_name,
    _get_base_url,
    _load_spec,
    _param_to_property,
    _resolve_ref,
    _validate_spec,
    parse_spec,
)


MINIMAL_OPENAPI = json.dumps(
    {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List all users",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
)

MINIMAL_SWAGGER = json.dumps(
    {
        "swagger": "2.0",
        "info": {"title": "Swagger API", "version": "2.0.0"},
        "host": "api.example.com",
        "basePath": "/v1",
        "schemes": ["https"],
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "summary": "List pets",
                    "parameters": [],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
)


@pytest.mark.unit
class TestLoadSpec:
    def test_load_json(self):
        spec = _load_spec('{"openapi": "3.0.0"}')
        assert spec["openapi"] == "3.0.0"

    def test_load_yaml(self):
        spec = _load_spec("openapi: '3.0.0'\ninfo:\n  title: Test")
        assert spec["openapi"] == "3.0.0"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Empty"):
            _load_spec("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Empty"):
            _load_spec("   \n  ")

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _load_spec("{invalid json}")


@pytest.mark.unit
class TestValidateSpec:
    def test_valid_openapi(self):
        spec = json.loads(MINIMAL_OPENAPI)
        _validate_spec(spec)  # should not raise

    def test_valid_swagger(self):
        spec = json.loads(MINIMAL_SWAGGER)
        _validate_spec(spec)

    def test_missing_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            _validate_spec({"paths": {"/a": {}}})

    def test_no_paths_raises(self):
        with pytest.raises(ValueError, match="No API paths"):
            _validate_spec({"openapi": "3.0.0"})

    def test_empty_paths_raises(self):
        with pytest.raises(ValueError, match="No API paths"):
            _validate_spec({"openapi": "3.0.0", "paths": {}})

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="valid object"):
            _validate_spec("not a dict")


@pytest.mark.unit
class TestExtractMetadata:
    def test_openapi_metadata(self):
        spec = json.loads(MINIMAL_OPENAPI)
        meta = _extract_metadata(spec, is_swagger=False)
        assert meta["title"] == "Test API"
        assert meta["version"] == "1.0.0"
        assert meta["base_url"] == "https://api.example.com"

    def test_swagger_metadata(self):
        spec = json.loads(MINIMAL_SWAGGER)
        meta = _extract_metadata(spec, is_swagger=True)
        assert meta["title"] == "Swagger API"
        assert meta["base_url"] == "https://api.example.com/v1"

    def test_missing_info(self):
        spec = {"openapi": "3.0.0", "paths": {"/a": {}}}
        meta = _extract_metadata(spec, is_swagger=False)
        assert meta["title"] == "Untitled API"

    def test_description_truncated(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "T", "description": "x" * 1000},
            "paths": {"/a": {}},
        }
        meta = _extract_metadata(spec, is_swagger=False)
        assert len(meta["description"]) <= 500


@pytest.mark.unit
class TestGetBaseUrl:
    def test_openapi_servers(self):
        spec = {"servers": [{"url": "https://api.example.com/v2/"}]}
        assert _get_base_url(spec, is_swagger=False) == "https://api.example.com/v2"

    def test_openapi_no_servers(self):
        assert _get_base_url({}, is_swagger=False) == ""

    def test_swagger_with_host(self):
        spec = {"host": "api.test.com", "basePath": "/v1", "schemes": ["https"]}
        assert _get_base_url(spec, is_swagger=True) == "https://api.test.com/v1"

    def test_swagger_no_host(self):
        assert _get_base_url({}, is_swagger=True) == ""

    def test_swagger_default_scheme(self):
        spec = {"host": "api.test.com", "basePath": ""}
        assert _get_base_url(spec, is_swagger=True) == "https://api.test.com"


@pytest.mark.unit
class TestGenerateActionName:
    def test_uses_operation_id(self):
        assert _generate_action_name({"operationId": "getUser"}, "get", "/users") == "getUser"

    def test_fallback_to_method_path(self):
        name = _generate_action_name({}, "get", "/users/{id}")
        assert name.startswith("get_")
        assert "users" in name

    def test_truncates_long_names(self):
        name = _generate_action_name({}, "get", "/" + "a" * 200)
        assert len(name) <= 64

    def test_sanitizes_special_chars(self):
        name = _generate_action_name({"operationId": "get.user@v2"}, "get", "/")
        assert "." not in name
        assert "@" not in name


@pytest.mark.unit
class TestParamToProperty:
    def test_string_param(self):
        param = {"name": "q", "in": "query", "schema": {"type": "string"}}
        prop = _param_to_property(param)
        assert prop["type"] == "string"
        assert prop["required"] is False

    def test_integer_param(self):
        param = {
            "name": "limit",
            "in": "query",
            "required": True,
            "schema": {"type": "integer"},
        }
        prop = _param_to_property(param)
        assert prop["type"] == "integer"
        assert prop["required"] is True
        assert prop["filled_by_llm"] is True

    def test_number_maps_to_integer(self):
        param = {"name": "score", "in": "query", "schema": {"type": "number"}}
        prop = _param_to_property(param)
        assert prop["type"] == "integer"


@pytest.mark.unit
class TestResolveRef:
    def test_no_ref(self):
        obj = {"type": "string"}
        assert _resolve_ref(obj, {}, {}) == obj

    def test_components_ref(self):
        components = {"schemas": {"User": {"type": "object", "properties": {"name": {"type": "string"}}}}}
        obj = {"$ref": "#/components/schemas/User"}
        result = _resolve_ref(obj, components, {})
        assert result["type"] == "object"

    def test_definitions_ref(self):
        definitions = {"Pet": {"type": "object"}}
        obj = {"$ref": "#/definitions/Pet"}
        result = _resolve_ref(obj, {}, definitions)
        assert result["type"] == "object"

    def test_unsupported_ref(self):
        obj = {"$ref": "#/external/something"}
        assert _resolve_ref(obj, {}, {}) is None

    def test_non_dict_returns_none(self):
        assert _resolve_ref("string", {}, {}) is None
        assert _resolve_ref(42, {}, {}) is None


@pytest.mark.unit
class TestParseSpec:
    def test_openapi_full_parse(self):
        metadata, actions = parse_spec(MINIMAL_OPENAPI)
        assert metadata["title"] == "Test API"
        assert len(actions) == 1
        assert actions[0]["name"] == "listUsers"
        assert actions[0]["method"] == "GET"
        assert actions[0]["url"] == "https://api.example.com/users"
        assert "limit" in actions[0]["query_params"]["properties"]

    def test_swagger_full_parse(self):
        metadata, actions = parse_spec(MINIMAL_SWAGGER)
        assert metadata["title"] == "Swagger API"
        assert len(actions) == 1
        assert actions[0]["name"] == "listPets"
        assert actions[0]["method"] == "GET"

    def test_multiple_methods(self):
        spec = json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "T", "version": "1"},
                "paths": {
                    "/items": {
                        "get": {"operationId": "listItems", "responses": {}},
                        "post": {
                            "operationId": "createItem",
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"}
                                            },
                                            "required": ["name"],
                                        }
                                    }
                                }
                            },
                            "responses": {},
                        },
                    }
                },
            }
        )
        metadata, actions = parse_spec(spec)
        assert len(actions) == 2
        names = {a["name"] for a in actions}
        assert "listItems" in names
        assert "createItem" in names

        create = next(a for a in actions if a["name"] == "createItem")
        assert "name" in create["body"]["properties"]

    def test_header_params(self):
        spec = json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "T", "version": "1"},
                "paths": {
                    "/data": {
                        "get": {
                            "operationId": "getData",
                            "parameters": [
                                {"name": "X-API-Key", "in": "header", "schema": {"type": "string"}}
                            ],
                            "responses": {},
                        }
                    }
                },
            }
        )
        _, actions = parse_spec(spec)
        assert "X-API-Key" in actions[0]["headers"]["properties"]

    def test_invalid_spec_raises(self):
        with pytest.raises(ValueError):
            parse_spec("")

    def test_yaml_spec(self):
        yaml_spec = """
openapi: "3.0.0"
info:
  title: YAML API
  version: "1.0"
paths:
  /health:
    get:
      operationId: healthCheck
      responses:
        "200":
          description: OK
"""
        metadata, actions = parse_spec(yaml_spec)
        assert metadata["title"] == "YAML API"
        assert actions[0]["name"] == "healthCheck"
