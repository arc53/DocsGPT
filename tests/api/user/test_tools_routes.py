"""Tests for application/api/user/tools/routes.py.

Previously coupled to bson.ObjectId + Mongo-shaped collection mocks.
Scheduled for rewrite against pg_conn + UserToolsRepository.
"""

import pytest


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


# ---------------------------------------------------------------------------
# Helper: _encrypt_secret_fields
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEncryptSecretFields:

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

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import AvailableTools

        with app.test_request_context("/api/available_tools"):
            from flask import request

            request.decoded_token = None
            response = AvailableTools().get()

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Route: GetTools
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetTools:

    def test_returns_user_tools(self, app):
        from application.api.user.tools.routes import GetTools

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": tool_id,
                "name": "my_tool",
                "user": "user1",
                "config": {"base_url": "http://example.com"},
                "configRequirements": {"base_url": {"secret": False}},
            }
        ]

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", Mock()
        ):
            with app.test_request_context("/api/get_tools"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTools().get()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert len(response.json["tools"]) == 1
        assert response.json["tools"][0]["id"] == str(tool_id)

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import GetTools

        with app.test_request_context("/api/get_tools"):
            from flask import request

            request.decoded_token = None
            response = GetTools().get()

        assert response.status_code == 401

    def test_masks_encrypted_credentials(self, app):
        from application.api.user.tools.routes import GetTools

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": tool_id,
                "name": "my_tool",
                "user": "user1",
                "config": {
                    "base_url": "http://example.com",
                    "encrypted_credentials": "blob",
                },
                "configRequirements": {
                    "api_key": {"secret": True},
                },
            }
        ]

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", Mock()
        ):
            with app.test_request_context("/api/get_tools"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTools().get()

        tool_data = response.json["tools"][0]
        assert tool_data["config"].get("has_encrypted_credentials") is True
        assert "encrypted_credentials" not in tool_data["config"]

    def test_loads_config_requirements_from_tool_manager(self, app):
        from application.api.user.tools.routes import GetTools

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": tool_id,
                "name": "my_tool",
                "user": "user1",
                "config": {"base_url": "http://example.com"},
                "configRequirements": {},
            }
        ]

        mock_tool_instance = Mock()
        mock_tool_instance.get_config_requirements.return_value = {
            "base_url": {"secret": False}
        }
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": mock_tool_instance}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context("/api/get_tools"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTools().get()

        tool_data = response.json["tools"][0]
        assert "base_url" in tool_data["configRequirements"]

    def test_returns_400_on_error(self, app):
        from application.api.user.tools.routes import GetTools

        mock_collection = Mock()
        mock_collection.find.side_effect = Exception("db error")

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/get_tools"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTools().get()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Route: CreateTool
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCreateTool:

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

    def test_creates_tool_successfully(self, app):
        from application.api.user.tools.routes import CreateTool

        tool_instance = self._make_tool_instance()
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}
        mock_collection = Mock()
        inserted_id = ObjectId()
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ), patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.encrypt_credentials",
            return_value="blob",
        ):
            with app.test_request_context(
                "/api/create_tool",
                method="POST",
                json={
                    "name": "my_tool",
                    "displayName": "My Tool",
                    "description": "Desc",
                    "config": {"api_key": "secret123"},
                    "status": True,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateTool().post()

        assert response.status_code == 200
        assert response.json["id"] == str(inserted_id)
        mock_collection.insert_one.assert_called_once()

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

    def test_returns_400_on_insert_error(self, app):
        from application.api.user.tools.routes import CreateTool

        tool_instance = Mock()
        tool_instance.get_actions_metadata.return_value = []
        tool_instance.get_config_requirements.return_value = {}
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}
        mock_collection = Mock()
        mock_collection.insert_one.side_effect = Exception("db fail")

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ), patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
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

    def test_includes_custom_name(self, app):
        from application.api.user.tools.routes import CreateTool

        tool_instance = Mock()
        tool_instance.get_actions_metadata.return_value = []
        tool_instance.get_config_requirements.return_value = {}
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}
        mock_collection = Mock()
        inserted_id = ObjectId()
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ), patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
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
                    "customName": "Custom",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateTool().post()

        assert response.status_code == 200
        call_arg = mock_collection.insert_one.call_args[0][0]
        assert call_arg["customName"] == "Custom"

    def test_rejects_mcp_tool_with_ssrf_url(self, app):
        from application.api.user.tools.routes import CreateTool
        from application.core.url_validation import SSRFError

        mock_manager = Mock()
        mock_manager.tools = {"mcp_tool": Mock()}

        with patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ), patch(
            "application.api.user.tools.routes.validate_url",
            side_effect=SSRFError("private address"),
        ):
            with app.test_request_context(
                "/api/create_tool",
                method="POST",
                json={
                    "name": "mcp_tool",
                    "displayName": "MCP",
                    "description": "Desc",
                    "config": {"server_url": "http://169.254.169.254"},
                    "status": True,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateTool().post()

        assert response.status_code == 400
        assert "Invalid server URL" in response.json["message"]


# ---------------------------------------------------------------------------
# Route: UpdateTool
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUpdateTool:

    def test_updates_tool_successfully(self, app):
        from application.api.user.tools.routes import UpdateTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "name": "my_tool",
            "config": {"base_url": "http://old.com"},
        }

        tool_instance = Mock()
        tool_instance.get_config_requirements.return_value = {}
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool",
                method="POST",
                json={
                    "id": str(tool_id),
                    "displayName": "Updated Name",
                    "config": {"base_url": "http://new.com"},
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateTool().post()

        assert response.status_code == 200
        assert response.json["success"] is True

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

    def test_returns_404_tool_not_found(self, app):
        from application.api.user.tools.routes import UpdateTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        mock_manager = Mock()
        mock_manager.tools = {}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool",
                method="POST",
                json={
                    "id": str(tool_id),
                    "config": {"base_url": "http://new.com"},
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateTool().post()

        assert response.status_code == 404

    def test_returns_400_on_invalid_function_name(self, app):
        from application.api.user.tools.routes import UpdateTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_manager = Mock()
        mock_manager.tools = {}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool",
                method="POST",
                json={
                    "id": str(tool_id),
                    "config": {
                        "actions": {"invalid name!": {}}
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateTool().post()

        assert response.status_code == 400
        assert "Invalid function name" in response.json["message"]

    def test_returns_400_on_validation_error(self, app):
        from application.api.user.tools.routes import UpdateTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "name": "my_tool",
            "config": {},
        }

        tool_instance = Mock()
        tool_instance.get_config_requirements.return_value = {
            "api_key": {"required": True, "label": "API Key"},
        }
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool",
                method="POST",
                json={
                    "id": str(tool_id),
                    "config": {},
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateTool().post()

        assert response.status_code == 400
        assert response.json["message"] == "Validation failed"

    def test_updates_multiple_fields(self, app):
        from application.api.user.tools.routes import UpdateTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_manager = Mock()
        mock_manager.tools = {}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool",
                method="POST",
                json={
                    "id": str(tool_id),
                    "name": "new_name",
                    "displayName": "New Display",
                    "customName": "Custom",
                    "description": "New desc",
                    "actions": [{"name": "a1"}],
                    "status": False,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateTool().post()

        assert response.status_code == 200
        call_args = mock_collection.update_one.call_args[0][1]["$set"]
        assert call_args["name"] == "new_name"
        assert call_args["displayName"] == "New Display"
        assert call_args["customName"] == "Custom"
        assert call_args["description"] == "New desc"
        assert call_args["status"] is False

    def test_returns_400_on_exception(self, app):
        from application.api.user.tools.routes import UpdateTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("db error")
        mock_manager = Mock()
        mock_manager.tools = {}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool",
                method="POST",
                json={
                    "id": str(tool_id),
                    "config": {"base_url": "http://new.com"},
                },
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

    def test_updates_config_successfully(self, app):
        from application.api.user.tools.routes import UpdateToolConfig

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "name": "my_tool",
            "config": {"base_url": "http://old.com"},
        }

        tool_instance = Mock()
        tool_instance.get_config_requirements.return_value = {}
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool_config",
                method="POST",
                json={"id": str(tool_id), "config": {"base_url": "http://new.com"}},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateToolConfig().post()

        assert response.status_code == 200
        assert response.json["success"] is True

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

    def test_returns_404_tool_not_found(self, app):
        from application.api.user.tools.routes import UpdateToolConfig

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_tool_config",
                method="POST",
                json={"id": str(tool_id), "config": {"base_url": "x"}},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateToolConfig().post()

        assert response.status_code == 404

    def test_returns_400_on_validation_error(self, app):
        from application.api.user.tools.routes import UpdateToolConfig

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "name": "my_tool",
            "config": {},
        }

        tool_instance = Mock()
        tool_instance.get_config_requirements.return_value = {
            "api_key": {"required": True, "label": "API Key"},
        }
        mock_manager = Mock()
        mock_manager.tools = {"my_tool": tool_instance}

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.tool_manager", mock_manager
        ):
            with app.test_request_context(
                "/api/update_tool_config",
                method="POST",
                json={"id": str(tool_id), "config": {}},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateToolConfig().post()

        assert response.status_code == 400
        assert response.json["message"] == "Validation failed"

    def test_returns_400_on_exception(self, app):
        from application.api.user.tools.routes import UpdateToolConfig

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_tool_config",
                method="POST",
                json={"id": str(tool_id), "config": {"a": "b"}},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateToolConfig().post()

        assert response.status_code == 400

    def test_rejects_mcp_tool_config_with_ssrf_url(self, app):
        from application.api.user.tools.routes import UpdateToolConfig
        from application.core.url_validation import SSRFError

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "name": "mcp_tool",
            "config": {},
        }

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.routes.validate_url",
            side_effect=SSRFError("private address"),
        ):
            with app.test_request_context(
                "/api/update_tool_config",
                method="POST",
                json={"id": str(tool_id), "config": {"server_url": "http://169.254.169.254"}},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateToolConfig().post()

        assert response.status_code == 400
        assert "Invalid server URL" in response.json["message"]


# ---------------------------------------------------------------------------
# Route: UpdateToolActions
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUpdateToolActions:

    def test_updates_actions_successfully(self, app):
        from application.api.user.tools.routes import UpdateToolActions

        tool_id = ObjectId()
        mock_collection = Mock()

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_tool_actions",
                method="POST",
                json={"id": str(tool_id), "actions": [{"name": "a1"}]},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateToolActions().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        mock_collection.update_one.assert_called_once()

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

    def test_returns_400_on_exception(self, app):
        from application.api.user.tools.routes import UpdateToolActions

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.update_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_tool_actions",
                method="POST",
                json={"id": str(tool_id), "actions": [{"name": "a1"}]},
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

    def test_updates_status_successfully(self, app):
        from application.api.user.tools.routes import UpdateToolStatus

        tool_id = ObjectId()
        mock_collection = Mock()

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_tool_status",
                method="POST",
                json={"id": str(tool_id), "status": False},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateToolStatus().post()

        assert response.status_code == 200
        assert response.json["success"] is True

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

    def test_returns_400_on_exception(self, app):
        from application.api.user.tools.routes import UpdateToolStatus

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.update_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_tool_status",
                method="POST",
                json={"id": str(tool_id), "status": True},
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

    def test_deletes_tool_successfully(self, app):
        from application.api.user.tools.routes import DeleteTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.delete_one.return_value = Mock(deleted_count=1)

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/delete_tool",
                method="POST",
                json={"id": str(tool_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteTool().post()

        assert response.status_code == 200
        assert response.json["success"] is True

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

    def test_returns_404_not_found(self, app):
        from application.api.user.tools.routes import DeleteTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.delete_one.return_value = Mock(deleted_count=0)

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/delete_tool",
                method="POST",
                json={"id": str(tool_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteTool().post()

        assert response.status_code == 404

    def test_returns_400_on_exception(self, app):
        from application.api.user.tools.routes import DeleteTool

        tool_id = ObjectId()
        mock_collection = Mock()
        mock_collection.delete_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.tools.routes.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/delete_tool",
                method="POST",
                json={"id": str(tool_id)},
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

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.routes import GetArtifact

        with app.test_request_context("/api/artifact/abc"):
            from flask import request

            request.decoded_token = None
            response = GetArtifact().get("abc")

        assert response.status_code == 401

    def test_returns_400_invalid_artifact_id(self, app):
        from application.api.user.tools.routes import GetArtifact

        with app.test_request_context("/api/artifact/not-valid-oid"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = GetArtifact().get("not-valid-oid")

        assert response.status_code == 400
        assert "Invalid artifact ID" in response.json["message"]

    def test_returns_note_artifact(self, app):
        from application.api.user.tools.routes import GetArtifact

        artifact_id = ObjectId()
        updated_at = datetime(2025, 1, 15, 10, 30)
        mock_notes = Mock()
        mock_notes.find_one.return_value = {
            "_id": artifact_id,
            "user_id": "user1",
            "note": "Line1\nLine2\nLine3",
            "updated_at": updated_at,
        }
        mock_todos = Mock()
        mock_todos.find_one.return_value = None

        mock_db = {"notes": mock_notes, "todos": mock_todos}

        with patch(
            "application.core.mongo_db.MongoDB.get_client",
            return_value={"test_db": mock_db},
        ), patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"

            with app.test_request_context(f"/api/artifact/{artifact_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetArtifact().get(str(artifact_id))

        assert response.status_code == 200
        artifact = response.json["artifact"]
        assert artifact["artifact_type"] == "note"
        assert artifact["data"]["content"] == "Line1\nLine2\nLine3"
        assert artifact["data"]["line_count"] == 3
        assert artifact["data"]["updated_at"] == updated_at.isoformat()

    def test_returns_note_with_no_updated_at(self, app):
        from application.api.user.tools.routes import GetArtifact

        artifact_id = ObjectId()
        mock_notes = Mock()
        mock_notes.find_one.return_value = {
            "_id": artifact_id,
            "user_id": "user1",
            "note": "Content",
        }

        mock_db = {"notes": mock_notes, "todos": Mock()}

        with patch(
            "application.core.mongo_db.MongoDB.get_client",
            return_value={"test_db": mock_db},
        ), patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"

            with app.test_request_context(f"/api/artifact/{artifact_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetArtifact().get(str(artifact_id))

        assert response.status_code == 200
        assert response.json["artifact"]["data"]["updated_at"] is None

    def test_returns_empty_note_line_count_zero(self, app):
        from application.api.user.tools.routes import GetArtifact

        artifact_id = ObjectId()
        mock_notes = Mock()
        mock_notes.find_one.return_value = {
            "_id": artifact_id,
            "user_id": "user1",
            "note": "",
        }
        mock_db = {"notes": mock_notes, "todos": Mock()}

        with patch(
            "application.core.mongo_db.MongoDB.get_client",
            return_value={"test_db": mock_db},
        ), patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"

            with app.test_request_context(f"/api/artifact/{artifact_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetArtifact().get(str(artifact_id))

        assert response.status_code == 200
        assert response.json["artifact"]["data"]["line_count"] == 0

    def test_returns_todo_artifact(self, app):
        from application.api.user.tools.routes import GetArtifact

        artifact_id = ObjectId()
        created_at = datetime(2025, 1, 15, 10, 0)
        updated_at = datetime(2025, 1, 15, 12, 0)
        mock_notes = Mock()
        mock_notes.find_one.return_value = None
        mock_todos = Mock()
        mock_todos.find_one.return_value = {
            "_id": artifact_id,
            "user_id": "user1",
            "tool_id": "tool123",
        }
        mock_todos.find.return_value = [
            {
                "todo_id": "t1",
                "title": "Task 1",
                "status": "open",
                "created_at": created_at,
                "updated_at": updated_at,
            },
            {
                "todo_id": "t2",
                "title": "Task 2",
                "status": "completed",
                "created_at": created_at,
                "updated_at": updated_at,
            },
        ]

        mock_db = {"notes": mock_notes, "todos": mock_todos}

        with patch(
            "application.core.mongo_db.MongoDB.get_client",
            return_value={"test_db": mock_db},
        ), patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"

            with app.test_request_context(f"/api/artifact/{artifact_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetArtifact().get(str(artifact_id))

        assert response.status_code == 200
        artifact = response.json["artifact"]
        assert artifact["artifact_type"] == "todo_list"
        assert artifact["data"]["total_count"] == 2
        assert artifact["data"]["open_count"] == 1
        assert artifact["data"]["completed_count"] == 1

    def test_returns_todo_with_no_dates(self, app):
        from application.api.user.tools.routes import GetArtifact

        artifact_id = ObjectId()
        mock_notes = Mock()
        mock_notes.find_one.return_value = None
        mock_todos = Mock()
        mock_todos.find_one.return_value = {
            "_id": artifact_id,
            "user_id": "user1",
            "tool_id": "tool123",
        }
        mock_todos.find.return_value = [
            {"todo_id": "t1", "title": "Task 1"},
        ]

        mock_db = {"notes": mock_notes, "todos": mock_todos}

        with patch(
            "application.core.mongo_db.MongoDB.get_client",
            return_value={"test_db": mock_db},
        ), patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"

            with app.test_request_context(f"/api/artifact/{artifact_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetArtifact().get(str(artifact_id))

        assert response.status_code == 200
        item = response.json["artifact"]["data"]["items"][0]
        assert item["created_at"] is None
        assert item["updated_at"] is None

    def test_returns_404_not_found(self, app):
        from application.api.user.tools.routes import GetArtifact

        artifact_id = ObjectId()
        mock_notes = Mock()
        mock_notes.find_one.return_value = None
        mock_todos = Mock()
        mock_todos.find_one.return_value = None

        mock_db = {"notes": mock_notes, "todos": mock_todos}

        with patch(
            "application.core.mongo_db.MongoDB.get_client",
            return_value={"test_db": mock_db},
        ), patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.MONGO_DB_NAME = "test_db"

            with app.test_request_context(f"/api/artifact/{artifact_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetArtifact().get(str(artifact_id))

        assert response.status_code == 404
        assert "Artifact not found" in response.json["message"]
