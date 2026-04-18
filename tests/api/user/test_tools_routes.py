"""Unit tests for application.api.user.tools.routes."""

from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


# ---------------------------------------------------------------------------
# Helper: _encrypt_secret_fields
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEncryptSecretFields:
    pass

    def test_encrypts_secret_keys(self):
        from application.api.user.tools.routes import _encrypt_secret_fields

        config = {"api_key": "my-secret", "base_url": "https://example.com"}
        config_requirements = {
            "api_key": {"secret": True},
            "base_url": {"secret": False},
        }
        with patch(
            "application.api.user.tools.routes.encrypt_credentials",
            return_value="encrypted-blob",
        ):
            result = _encrypt_secret_fields(config, config_requirements, "user1")

        assert "api_key" not in result
        assert result["encrypted_credentials"] == "encrypted-blob"
        assert result["base_url"] == "https://example.com"

    def test_returns_config_unchanged_when_no_secrets(self):
        from application.api.user.tools.routes import _encrypt_secret_fields

        config = {"base_url": "https://example.com"}
        config_requirements = {"base_url": {"secret": False}}
        result = _encrypt_secret_fields(config, config_requirements, "user1")
        assert result == config

    def test_skips_empty_secret_values(self):
        from application.api.user.tools.routes import _encrypt_secret_fields

        config = {"api_key": "", "base_url": "https://example.com"}
        config_requirements = {"api_key": {"secret": True}}
        result = _encrypt_secret_fields(config, config_requirements, "user1")
        assert result == config

    def test_skips_secret_key_not_in_config(self):
        from application.api.user.tools.routes import _encrypt_secret_fields

        config = {"base_url": "https://example.com"}
        config_requirements = {"api_key": {"secret": True}}
        result = _encrypt_secret_fields(config, config_requirements, "user1")
        assert result == config


# ---------------------------------------------------------------------------
# Helper: _validate_config
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestValidateConfig:
    pass

    def test_returns_empty_on_valid_config(self):
        from application.api.user.tools.routes import _validate_config

        config = {"api_key": "abc123"}
        config_requirements = {
            "api_key": {"required": True, "label": "API Key"},
        }
        errors = _validate_config(config, config_requirements)
        assert errors == {}

    def test_reports_missing_required_field(self):
        from application.api.user.tools.routes import _validate_config

        config = {}
        config_requirements = {
            "api_key": {"required": True, "label": "API Key"},
        }
        errors = _validate_config(config, config_requirements)
        assert "api_key" in errors

    def test_skips_required_secret_when_existing_secrets(self):
        from application.api.user.tools.routes import _validate_config

        config = {}
        config_requirements = {
            "api_key": {"required": True, "secret": True, "label": "API Key"},
        }
        errors = _validate_config(config, config_requirements, has_existing_secrets=True)
        assert errors == {}

    def test_validates_number_type(self):
        from application.api.user.tools.routes import _validate_config

        config = {"timeout": "abc"}
        config_requirements = {
            "timeout": {"type": "number", "label": "Timeout"},
        }
        errors = _validate_config(config, config_requirements)
        assert "timeout" in errors

    def test_validates_timeout_range_too_low(self):
        from application.api.user.tools.routes import _validate_config

        config = {"timeout": "0"}
        config_requirements = {
            "timeout": {"type": "number", "label": "Timeout"},
        }
        errors = _validate_config(config, config_requirements)
        assert "timeout" in errors
        assert "between 1 and 300" in errors["timeout"]

    def test_validates_timeout_range_too_high(self):
        from application.api.user.tools.routes import _validate_config

        config = {"timeout": "500"}
        config_requirements = {
            "timeout": {"type": "number", "label": "Timeout"},
        }
        errors = _validate_config(config, config_requirements)
        assert "timeout" in errors

    def test_valid_timeout(self):
        from application.api.user.tools.routes import _validate_config

        config = {"timeout": "60"}
        config_requirements = {
            "timeout": {"type": "number", "label": "Timeout"},
        }
        errors = _validate_config(config, config_requirements)
        assert errors == {}

    def test_validates_enum_value(self):
        from application.api.user.tools.routes import _validate_config

        config = {"mode": "invalid"}
        config_requirements = {
            "mode": {"enum": ["fast", "slow"], "label": "Mode"},
        }
        errors = _validate_config(config, config_requirements)
        assert "mode" in errors

    def test_valid_enum_value(self):
        from application.api.user.tools.routes import _validate_config

        config = {"mode": "fast"}
        config_requirements = {
            "mode": {"enum": ["fast", "slow"], "label": "Mode"},
        }
        errors = _validate_config(config, config_requirements)
        assert errors == {}

    def test_depends_on_skips_when_condition_not_met(self):
        from application.api.user.tools.routes import _validate_config

        config = {"mode": "simple"}
        config_requirements = {
            "mode": {"required": True, "label": "Mode"},
            "advanced_key": {
                "required": True,
                "label": "Advanced Key",
                "depends_on": {"mode": "advanced"},
            },
        }
        errors = _validate_config(config, config_requirements)
        assert errors == {}

    def test_depends_on_validates_when_condition_met(self):
        from application.api.user.tools.routes import _validate_config

        config = {"mode": "advanced"}
        config_requirements = {
            "mode": {"required": True, "label": "Mode"},
            "advanced_key": {
                "required": True,
                "label": "Advanced Key",
                "depends_on": {"mode": "advanced"},
            },
        }
        errors = _validate_config(config, config_requirements)
        assert "advanced_key" in errors

    def test_empty_string_not_treated_as_value_for_required(self):
        from application.api.user.tools.routes import _validate_config

        config = {"api_key": ""}
        config_requirements = {
            "api_key": {"required": True, "label": "API Key"},
        }
        errors = _validate_config(config, config_requirements)
        assert "api_key" in errors

    def test_uses_key_name_when_no_label(self):
        from application.api.user.tools.routes import _validate_config

        config = {}
        config_requirements = {
            "api_key": {"required": True},
        }
        errors = _validate_config(config, config_requirements)
        assert "api_key" in errors
        assert "api_key is required" in errors["api_key"]


# ---------------------------------------------------------------------------
# Helper: _merge_secrets_on_update
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMergeSecretsOnUpdate:
    pass

    def test_no_secret_keys_returns_new_config(self):
        from application.api.user.tools.routes import _merge_secrets_on_update

        new_config = {"base_url": "https://new.example.com"}
        existing_config = {"base_url": "https://old.example.com"}
        config_requirements = {"base_url": {"secret": False}}

        result = _merge_secrets_on_update(
            new_config, existing_config, config_requirements, "user1"
        )
        assert result == new_config

    def test_merges_existing_encrypted_with_new_secret(self):
        from application.api.user.tools.routes import _merge_secrets_on_update

        new_config = {"api_key": "new-key", "base_url": "https://example.com"}
        existing_config = {
            "base_url": "https://old.com",
            "encrypted_credentials": "old-blob",
        }
        config_requirements = {
            "api_key": {"secret": True},
            "base_url": {"secret": False},
        }
        with patch(
            "application.api.user.tools.routes.decrypt_credentials",
            return_value={"api_key": "old-key"},
        ), patch(
            "application.api.user.tools.routes.encrypt_credentials",
            return_value="new-blob",
        ) as mock_encrypt:
            result = _merge_secrets_on_update(
                new_config, existing_config, config_requirements, "user1"
            )

        assert result["encrypted_credentials"] == "new-blob"
        assert "api_key" not in result
        assert result["base_url"] == "https://example.com"
        encrypted_call = mock_encrypt.call_args[0][0]
        assert encrypted_call["api_key"] == "new-key"

    def test_keeps_existing_secret_when_not_in_new_config(self):
        from application.api.user.tools.routes import _merge_secrets_on_update

        new_config = {"base_url": "https://example.com"}
        existing_config = {
            "base_url": "https://old.com",
            "encrypted_credentials": "old-blob",
        }
        config_requirements = {
            "api_key": {"secret": True},
            "base_url": {"secret": False},
        }
        with patch(
            "application.api.user.tools.routes.decrypt_credentials",
            return_value={"api_key": "old-key"},
        ), patch(
            "application.api.user.tools.routes.encrypt_credentials",
            return_value="new-blob",
        ) as mock_encrypt:
            _merge_secrets_on_update(
                new_config, existing_config, config_requirements, "user1"
            )

        encrypted_call = mock_encrypt.call_args[0][0]
        assert encrypted_call["api_key"] == "old-key"

    def test_removes_encrypted_credentials_when_no_secrets(self):
        from application.api.user.tools.routes import _merge_secrets_on_update

        new_config = {"base_url": "https://example.com"}
        existing_config = {"base_url": "https://old.com"}
        config_requirements = {
            "api_key": {"secret": True},
            "base_url": {"secret": False},
        }
        with patch(
            "application.api.user.tools.routes.decrypt_credentials",
            return_value={},
        ):
            result = _merge_secrets_on_update(
                new_config, existing_config, config_requirements, "user1"
            )

        assert "encrypted_credentials" not in result

    def test_strips_has_encrypted_credentials_flag(self):
        from application.api.user.tools.routes import _merge_secrets_on_update

        new_config = {"api_key": "k", "has_encrypted_credentials": True}
        existing_config = {"encrypted_credentials": "blob"}
        config_requirements = {"api_key": {"secret": True}}

        with patch(
            "application.api.user.tools.routes.decrypt_credentials",
            return_value={},
        ), patch(
            "application.api.user.tools.routes.encrypt_credentials",
            return_value="blob2",
        ):
            result = _merge_secrets_on_update(
                new_config, existing_config, config_requirements, "user1"
            )

        assert "has_encrypted_credentials" not in result


# ---------------------------------------------------------------------------
# Helper: transform_actions
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTransformActions:
    pass

    def test_sets_active_and_param_defaults(self):
        from application.api.user.tools.routes import transform_actions

        actions = [
            {
                "name": "search",
                "parameters": {
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    }
                },
            }
        ]
        result = transform_actions(actions)
        assert len(result) == 1
        assert result[0]["active"] is True
        props = result[0]["parameters"]["properties"]
        assert props["query"]["filled_by_llm"] is True
        assert props["query"]["value"] == ""
        assert props["limit"]["filled_by_llm"] is True

    def test_handles_action_without_parameters(self):
        from application.api.user.tools.routes import transform_actions

        actions = [{"name": "ping"}]
        result = transform_actions(actions)
        assert result[0]["active"] is True
        assert "parameters" not in result[0]

    def test_handles_empty_properties(self):
        from application.api.user.tools.routes import transform_actions

        actions = [{"name": "noop", "parameters": {"properties": {}}}]
        result = transform_actions(actions)
        assert result[0]["active"] is True

    def test_handles_empty_list(self):
        from application.api.user.tools.routes import transform_actions

        assert transform_actions([]) == []


# ---------------------------------------------------------------------------
# Route: AvailableTools
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAvailableTools:
    pass

    def test_returns_tools_metadata(self, app):
        from application.api.user.tools.routes import AvailableTools

        mock_tool = Mock()
        mock_tool.__doc__ = "My Tool\nA great tool description"
        mock_tool.get_config_requirements.return_value = {"key": {"required": True}}
        mock_tool.get_actions_metadata.return_value = [{"name": "do_thing"}]

        mock_manager = Mock()
        mock_manager.tools = {"my_tool": mock_tool}

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context("/api/available_tools"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AvailableTools().get()

        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "my_tool"
        assert data["data"][0]["displayName"] == "My Tool"
        assert data["data"][0]["description"] == "A great tool description"

    def test_returns_400_on_error(self, app):
        from application.api.user.tools.routes import AvailableTools

        mock_tool = Mock()
        mock_tool.__doc__ = "Bad Tool"
        mock_tool.get_config_requirements.side_effect = Exception("fail")

        mock_manager = Mock()
        mock_manager.tools = {"bad_tool": mock_tool}

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context("/api/available_tools"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AvailableTools().get()

        assert response.status_code == 400

    def test_single_line_docstring(self, app):
        from application.api.user.tools.routes import AvailableTools

        mock_tool = Mock()
        mock_tool.__doc__ = "Simple Tool"
        mock_tool.get_config_requirements.return_value = {}
        mock_tool.get_actions_metadata.return_value = []

        mock_manager = Mock()
        mock_manager.tools = {"simple": mock_tool}

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context("/api/available_tools"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AvailableTools().get()

        assert response.status_code == 200
        assert response.json["data"][0]["displayName"] == "Simple Tool"
        assert response.json["data"][0]["description"] == ""


# ---------------------------------------------------------------------------
# Route: GetTools
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetTools:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import GetTools

        with app.test_request_context("/api/get_tools"):
            from flask import request

            request.decoded_token = None
            response = GetTools().get()

        assert response.status_code == 401





# ---------------------------------------------------------------------------
# Route: CreateTool
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCreateTool:
    pass

    def _make_tool_instance(self):
        tool_instance = Mock()
        tool_instance.get_actions_metadata.return_value = [
            {
                "name": "search",
                "parameters": {
                    "properties": {"q": {"type": "string"}}
                },
            }
        ]
        tool_instance.get_config_requirements.return_value = {
            "api_key": {"required": True, "secret": True, "label": "API Key"},
        }
        return tool_instance


    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import CreateTool

        with app.test_request_context(
            "/api/create_tool", method="POST", json={}
        ):
            from flask import request

            request.decoded_token = None
            response = CreateTool().post()

        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.tools.routes import CreateTool

        with app.test_request_context(
            "/api/create_tool",
            method="POST",
            json={"name": "my_tool"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = CreateTool().post()

        assert response.status_code == 400

    def test_returns_404_tool_not_found(self, app):
        from application.api.user.tools.routes import CreateTool

        mock_manager = Mock()
        mock_manager.tools = {}

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/create_tool",
                method="POST",
                json={
                    "name": "nonexistent",
                    "displayName": "X",
                    "description": "D",
                    "config": {},
                    "status": True,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateTool().post()

        assert response.status_code == 404

    def test_returns_400_on_validation_error(self, app):
        from application.api.user.tools.routes import CreateTool

        tool_instance = self._make_tool_instance()
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/create_tool",
                method="POST",
                json={
                    "name": "my_tool",
                    "displayName": "My Tool",
                    "description": "Desc",
                    "config": {},
                    "status": True,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateTool().post()

        assert response.status_code == 400
        assert response.json["message"] == "Validation failed"

    def test_returns_400_on_actions_error(self, app):
        from application.api.user.tools.routes import CreateTool

        tool_instance = Mock()
        tool_instance.get_actions_metadata.side_effect = Exception("boom")
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/create_tool",
                method="POST",
                json={
                    "name": "my_tool",
                    "displayName": "My Tool",
                    "description": "Desc",
                    "config": {},
                    "status": True,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateTool().post()

        assert response.status_code == 400




# ---------------------------------------------------------------------------
# Route: UpdateTool
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUpdateTool:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import UpdateTool

        with app.test_request_context(
            "/api/update_tool", method="POST", json={"id": "abc"}
        ):
            from flask import request

            request.decoded_token = None
            response = UpdateTool().post()

        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.tools.routes import UpdateTool

        with app.test_request_context(
            "/api/update_tool", method="POST", json={}
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateTool().post()

        assert response.status_code == 400







# ---------------------------------------------------------------------------
# Route: UpdateToolConfig
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUpdateToolConfig:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import UpdateToolConfig

        with app.test_request_context(
            "/api/update_tool_config",
            method="POST",
            json={"id": "x", "config": {}},
        ):
            from flask import request

            request.decoded_token = None
            response = UpdateToolConfig().post()

        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.tools.routes import UpdateToolConfig

        with app.test_request_context(
            "/api/update_tool_config",
            method="POST",
            json={"id": "x"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateToolConfig().post()

        assert response.status_code == 400





# ---------------------------------------------------------------------------
# Route: UpdateToolActions
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUpdateToolActions:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import UpdateToolActions

        with app.test_request_context(
            "/api/update_tool_actions",
            method="POST",
            json={"id": "x", "actions": []},
        ):
            from flask import request

            request.decoded_token = None
            response = UpdateToolActions().post()

        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.tools.routes import UpdateToolActions

        with app.test_request_context(
            "/api/update_tool_actions",
            method="POST",
            json={"id": "x"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateToolActions().post()

        assert response.status_code == 400



# ---------------------------------------------------------------------------
# Route: UpdateToolStatus
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUpdateToolStatus:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import UpdateToolStatus

        with app.test_request_context(
            "/api/update_tool_status",
            method="POST",
            json={"id": "x", "status": True},
        ):
            from flask import request

            request.decoded_token = None
            response = UpdateToolStatus().post()

        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.tools.routes import UpdateToolStatus

        with app.test_request_context(
            "/api/update_tool_status",
            method="POST",
            json={"id": "x"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateToolStatus().post()

        assert response.status_code == 400



# ---------------------------------------------------------------------------
# Route: DeleteTool
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDeleteTool:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import DeleteTool

        with app.test_request_context(
            "/api/delete_tool", method="POST", json={"id": "x"}
        ):
            from flask import request

            request.decoded_token = None
            response = DeleteTool().post()

        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.tools.routes import DeleteTool

        with app.test_request_context(
            "/api/delete_tool", method="POST", json={}
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = DeleteTool().post()

        assert response.status_code == 400




# ---------------------------------------------------------------------------
# Route: ParseSpec
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestParseSpec:
    pass

    def test_parses_json_spec_successfully(self, app):
        from application.api.user.tools.routes import ParseSpec

        metadata = {"title": "Pet API"}
        actions = [{"name": "listPets"}]

        with patch(
            "application.api.user.tools.routes.parse_spec",
            return_value=(metadata, actions),
        ):
            with app.test_request_context(
                "/api/parse_spec",
                method="POST",
                json={"spec_content": "openapi: 3.0.0"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ParseSpec().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["metadata"] == metadata
        assert response.json["actions"] == actions

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import ParseSpec

        with app.test_request_context(
            "/api/parse_spec",
            method="POST",
            json={"spec_content": "openapi: 3.0.0"},
        ):
            from flask import request

            request.decoded_token = None
            response = ParseSpec().post()

        assert response.status_code == 401

    def test_returns_400_empty_spec(self, app):
        from application.api.user.tools.routes import ParseSpec

        with app.test_request_context(
            "/api/parse_spec",
            method="POST",
            json={"spec_content": ""},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ParseSpec().post()

        assert response.status_code == 400
        assert "Empty spec content" in response.json["message"]

    def test_returns_400_whitespace_only_spec(self, app):
        from application.api.user.tools.routes import ParseSpec

        with app.test_request_context(
            "/api/parse_spec",
            method="POST",
            json={"spec_content": "   "},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ParseSpec().post()

        assert response.status_code == 400

    def test_returns_400_no_spec_provided(self, app):
        from application.api.user.tools.routes import ParseSpec

        with app.test_request_context(
            "/api/parse_spec",
            method="POST",
            content_type="text/plain",
            data="hello",
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ParseSpec().post()

        assert response.status_code == 400
        assert "No spec provided" in response.json["message"]

    def test_parses_file_upload(self, app):
        from application.api.user.tools.routes import ParseSpec
        from io import BytesIO

        metadata = {"title": "API"}
        actions = [{"name": "a1"}]

        with patch(
            "application.api.user.tools.routes.parse_spec",
            return_value=(metadata, actions),
        ):
            with app.test_request_context(
                "/api/parse_spec",
                method="POST",
                content_type="multipart/form-data",
                data={"file": (BytesIO(b"openapi: 3.0.0"), "spec.yaml")},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ParseSpec().post()

        assert response.status_code == 200
        assert response.json["success"] is True

    def test_returns_400_file_no_filename(self, app):
        from application.api.user.tools.routes import ParseSpec
        from io import BytesIO

        with app.test_request_context(
            "/api/parse_spec",
            method="POST",
            content_type="multipart/form-data",
            data={"file": (BytesIO(b"content"), "")},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ParseSpec().post()

        assert response.status_code == 400
        assert "No file selected" in response.json["message"]

    def test_returns_400_on_value_error(self, app):
        from application.api.user.tools.routes import ParseSpec

        with patch(
            "application.api.user.tools.routes.parse_spec",
            side_effect=ValueError("bad spec"),
        ):
            with app.test_request_context(
                "/api/parse_spec",
                method="POST",
                json={"spec_content": "bad spec content"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ParseSpec().post()

        assert response.status_code == 400
        assert "Invalid specification format" in response.json["error"]

    def test_returns_500_on_generic_error(self, app):
        from application.api.user.tools.routes import ParseSpec

        with patch(
            "application.api.user.tools.routes.parse_spec",
            side_effect=RuntimeError("unexpected"),
        ):
            with app.test_request_context(
                "/api/parse_spec",
                method="POST",
                json={"spec_content": "some spec"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ParseSpec().post()

        assert response.status_code == 500
        assert "Failed to parse specification" in response.json["error"]

    def test_returns_400_invalid_file_encoding(self, app):
        from application.api.user.tools.routes import ParseSpec
        from io import BytesIO

        bad_bytes = b"\x80\x81\x82\x83"

        with app.test_request_context(
            "/api/parse_spec",
            method="POST",
            content_type="multipart/form-data",
            data={"file": (BytesIO(bad_bytes), "spec.bin")},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ParseSpec().post()

        assert response.status_code == 400
        assert "Invalid file encoding" in response.json["message"]


# ---------------------------------------------------------------------------
# Route: GetArtifact
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetArtifact:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import GetArtifact

        with app.test_request_context("/api/artifact/abc"):
            from flask import request

            request.decoded_token = None
            response = GetArtifact().get("abc")

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Happy-path tests using pg_conn
# ---------------------------------------------------------------------------


@contextmanager
def _patch_tools_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.tools.routes.db_session", _yield
    ), patch(
        "application.api.user.tools.routes.db_readonly", _yield
    ):
        yield


def _seed_tool(pg_conn, user="u-tools", name="read_webpage", config=None):
    from application.storage.db.repositories.user_tools import UserToolsRepository
    repo = UserToolsRepository(pg_conn)
    return repo.create(
        user,
        name,
        config=config or {},
        display_name=name,
        description="",
        actions=[],
        status=True,
    )


class TestGetToolsHappy:
    def test_returns_user_tools(self, app, pg_conn):
        from application.api.user.tools.routes import GetTools

        user = "u-get-tools"
        _seed_tool(pg_conn, user=user, name="read_webpage")

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/get_tools"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetTools().get()
        assert response.status_code == 200
        assert response.json["success"] is True
        assert len(response.json["tools"]) == 1

    def test_db_error_returns_400(self, app):
        from application.api.user.tools.routes import GetTools

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.tools.routes.db_readonly", _broken
        ), app.test_request_context("/api/get_tools"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetTools().get()
        assert response.status_code == 400


class TestCreateToolHappy:
    def test_creates_tool_successfully(self, app, pg_conn):
        from application.api.user.tools.routes import CreateTool

        user = "u-create-tool"

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/create_tool",
            method="POST",
            json={
                "name": "read_webpage",
                "displayName": "Read Webpage",
                "description": "d",
                "config": {},
                "customName": "my-webpage",
                "status": True,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateTool().post()
        assert response.status_code == 200
        body = response.json
        assert "id" in body

    def test_db_error_returns_400(self, app):
        from application.api.user.tools.routes import CreateTool

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.tools.routes.db_session", _broken
        ), app.test_request_context(
            "/api/create_tool",
            method="POST",
            json={
                "name": "read_webpage",
                "displayName": "N",
                "description": "d",
                "config": {},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CreateTool().post()
        assert response.status_code == 400


class TestUpdateToolHappy:
    def test_returns_404_not_found(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateTool

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool",
            method="POST",
            json={
                "id": "00000000-0000-0000-0000-000000000000",
                "displayName": "new",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateTool().post()
        assert response.status_code == 404

    def test_updates_tool_display_name(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateTool
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        user = "u-upd"
        tool = _seed_tool(pg_conn, user=user)

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool",
            method="POST",
            json={"id": str(tool["id"]), "displayName": "New Display"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateTool().post()
        assert response.status_code == 200
        got = UserToolsRepository(pg_conn).get(str(tool["id"]), user)
        assert got["display_name"] == "New Display"


class TestUpdateToolConfigHappy:
    def test_returns_404_not_found(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateToolConfig

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool_config",
            method="POST",
            json={
                "id": "00000000-0000-0000-0000-000000000000",
                "config": {"key": "v"},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateToolConfig().post()
        assert response.status_code == 404

    def test_updates_config(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateToolConfig

        user = "u-cfg"
        tool = _seed_tool(pg_conn, user=user)

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool_config",
            method="POST",
            json={
                "id": str(tool["id"]),
                "config": {"timeout": 30},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateToolConfig().post()
        assert response.status_code == 200


class TestUpdateToolActionsHappy:
    def test_returns_404_not_found(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateToolActions

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool_actions",
            method="POST",
            json={
                "id": "00000000-0000-0000-0000-000000000000",
                "actions": [],
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateToolActions().post()
        assert response.status_code == 404

    def test_updates_actions(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateToolActions

        user = "u-actions"
        tool = _seed_tool(pg_conn, user=user)

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool_actions",
            method="POST",
            json={
                "id": str(tool["id"]),
                "actions": [
                    {"name": "action_1", "active": True, "parameters": {}}
                ],
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateToolActions().post()
        assert response.status_code == 200


class TestUpdateToolStatusHappy:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import UpdateToolStatus

        with app.test_request_context(
            "/api/update_tool_status",
            method="POST",
            json={"id": "x", "status": True},
        ):
            from flask import request
            request.decoded_token = None
            response = UpdateToolStatus().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.tools.routes import UpdateToolStatus

        with app.test_request_context(
            "/api/update_tool_status",
            method="POST",
            json={"id": "x"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateToolStatus().post()
        assert response.status_code == 400

    def test_returns_404_not_found(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateToolStatus

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool_status",
            method="POST",
            json={
                "id": "00000000-0000-0000-0000-000000000000",
                "status": False,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateToolStatus().post()
        assert response.status_code == 404

    def test_updates_status(self, app, pg_conn):
        from application.api.user.tools.routes import UpdateToolStatus
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        user = "u-status"
        tool = _seed_tool(pg_conn, user=user)

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/update_tool_status",
            method="POST",
            json={"id": str(tool["id"]), "status": False},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateToolStatus().post()
        assert response.status_code == 200
        got = UserToolsRepository(pg_conn).get(str(tool["id"]), user)
        assert got["status"] is False


class TestDeleteToolHappy:
    def test_returns_404_not_found(self, app, pg_conn):
        from application.api.user.tools.routes import DeleteTool

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/delete_tool",
            method="POST",
            json={"id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteTool().post()
        assert response.status_code == 404

    def test_deletes_tool(self, app, pg_conn):
        from application.api.user.tools.routes import DeleteTool
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        user = "u-deltool"
        tool = _seed_tool(pg_conn, user=user)

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/delete_tool",
            method="POST",
            json={"id": str(tool["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteTool().post()
        assert response.status_code == 200
        assert UserToolsRepository(pg_conn).get(str(tool["id"]), user) is None


class TestGetArtifactHappy:
    def test_returns_404_tool_not_found(self, app, pg_conn):
        from application.api.user.tools.routes import GetArtifact

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/artifact/00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetArtifact().get(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404







