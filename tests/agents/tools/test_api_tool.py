"""Comprehensive tests for application/agents/tools/api_tool.py

Covers: APITool initialization, all HTTP methods, path param substitution,
SSRF validation, error handling, response parsing, body serialization.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from application.agents.tools.api_tool import APITool, DEFAULT_TIMEOUT


@pytest.fixture
def get_tool():
    return APITool(
        config={
            "url": "https://api.example.com/data",
            "method": "GET",
            "headers": {"Accept": "application/json"},
            "query_params": {},
        }
    )


@pytest.fixture
def post_tool():
    return APITool(
        config={
            "url": "https://api.example.com/items",
            "method": "POST",
            "headers": {},
            "query_params": {},
        }
    )


# =====================================================================
# Initialization
# =====================================================================


@pytest.mark.unit
class TestAPIToolInit:

    def test_default_values(self):
        tool = APITool(config={})
        assert tool.url == ""
        assert tool.method == "GET"
        assert tool.headers == {}
        assert tool.query_params == {}
        assert tool.body_content_type == "application/json"
        assert tool.body_encoding_rules == {}

    def test_custom_config(self):
        tool = APITool(config={
            "url": "https://api.test.com",
            "method": "POST",
            "headers": {"X-Key": "val"},
            "query_params": {"page": "1"},
            "body_content_type": "application/xml",
            "body_encoding_rules": {"field": {"style": "form"}},
        })
        assert tool.url == "https://api.test.com"
        assert tool.method == "POST"
        assert tool.headers == {"X-Key": "val"}
        assert tool.query_params == {"page": "1"}
        assert tool.body_content_type == "application/xml"

    def test_default_timeout_constant(self):
        assert DEFAULT_TIMEOUT == 90


# =====================================================================
# HTTP Methods
# =====================================================================


@pytest.mark.unit
class TestMakeApiCall:

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_successful_get(self, mock_get, mock_validate, get_tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"result": "ok"}
        mock_resp.content = b'{"result":"ok"}'
        mock_get.return_value = mock_resp

        result = get_tool.execute_action("any_action")

        assert result["status_code"] == 200
        assert result["data"] == {"result": "ok"}
        assert result["message"] == "API call successful."

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.post")
    def test_successful_post(self, mock_post, mock_validate, post_tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"id": 1}
        mock_resp.content = b'{"id":1}'
        mock_post.return_value = mock_resp

        result = post_tool.execute_action("create", name="test")
        assert result["status_code"] == 201

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.put")
    def test_put_method(self, mock_put, mock_validate):
        tool = APITool(config={"url": "https://example.com/item/1", "method": "PUT"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_put.return_value = mock_resp

        result = tool.execute_action("update", name="new")
        assert result["status_code"] == 200

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.delete")
    def test_delete_method(self, mock_delete, mock_validate):
        tool = APITool(config={"url": "https://example.com/item/1", "method": "DELETE"})
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.content = b''
        mock_delete.return_value = mock_resp

        result = tool.execute_action("delete")
        assert result["status_code"] == 204

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.patch")
    def test_patch_method(self, mock_patch, mock_validate):
        tool = APITool(config={"url": "https://example.com/item/1", "method": "PATCH"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"patched": True}
        mock_resp.content = b'{"patched":true}'
        mock_patch.return_value = mock_resp

        result = tool.execute_action("patch", field="val")
        assert result["status_code"] == 200

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.head")
    def test_head_method(self, mock_head, mock_validate):
        tool = APITool(config={"url": "https://example.com", "method": "HEAD"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.content = b''
        mock_head.return_value = mock_resp

        result = tool.execute_action("check")
        assert result["status_code"] == 200

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.options")
    def test_options_method(self, mock_options, mock_validate):
        tool = APITool(config={"url": "https://example.com", "method": "OPTIONS"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.content = b''
        mock_options.return_value = mock_resp

        result = tool.execute_action("options")
        assert result["status_code"] == 200

    @patch("application.agents.tools.api_tool.validate_url")
    def test_unsupported_method(self, mock_validate):
        tool = APITool(config={"url": "https://example.com", "method": "CUSTOM"})
        result = tool.execute_action("any")
        assert result["status_code"] is None
        assert "Unsupported" in result["message"]


# =====================================================================
# SSRF Validation
# =====================================================================


@pytest.mark.unit
class TestSSRFValidation:

    @patch("application.agents.tools.api_tool.validate_url")
    def test_ssrf_blocked_initial_url(self, mock_validate, get_tool):
        from application.core.url_validation import SSRFError

        mock_validate.side_effect = SSRFError("blocked")
        result = get_tool.execute_action("any")
        assert result["status_code"] is None
        assert "URL validation error" in result["message"]

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_ssrf_blocked_after_param_substitution(self, mock_get, mock_validate):
        from application.core.url_validation import SSRFError

        tool = APITool(config={
            "url": "https://api.example.com/{host}/data",
            "method": "GET",
            "query_params": {"host": "169.254.169.254"},
        })

        call_count = [0]

        def side_effect(url):
            call_count[0] += 1
            if call_count[0] == 2:
                raise SSRFError("blocked after substitution")

        mock_validate.side_effect = side_effect
        result = tool.execute_action("any")
        assert result["status_code"] is None
        assert "URL validation error" in result["message"]


# =====================================================================
# Error Handling
# =====================================================================


@pytest.mark.unit
class TestErrorHandling:

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_timeout_error(self, mock_get, mock_validate, get_tool):
        mock_get.side_effect = requests.exceptions.Timeout()
        result = get_tool.execute_action("any")
        assert result["status_code"] is None
        assert "timeout" in result["message"].lower()

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_connection_error(self, mock_get, mock_validate, get_tool):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        result = get_tool.execute_action("any")
        assert result["status_code"] is None
        assert "Connection error" in result["message"]

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_http_error_with_json(self, mock_get, mock_validate, get_tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.json.return_value = {"error": "invalid_field"}
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        result = get_tool.execute_action("any")
        assert result["status_code"] == 422
        assert result["data"] == {"error": "invalid_field"}

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_http_error_non_json_body(self, mock_get, mock_validate, get_tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_resp.json.side_effect = json.JSONDecodeError("", "", 0)
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        result = get_tool.execute_action("any")
        assert result["status_code"] == 404
        assert result["data"] == "Not Found"

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_request_exception(self, mock_get, mock_validate, get_tool):
        mock_get.side_effect = requests.exceptions.RequestException("something")
        result = get_tool.execute_action("any")
        assert "API call failed" in result["message"]

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_unexpected_exception(self, mock_get, mock_validate, get_tool):
        mock_get.side_effect = RuntimeError("unexpected")
        result = get_tool.execute_action("any")
        assert "Unexpected error" in result["message"]

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.post")
    def test_body_serialization_error(self, mock_post, mock_validate):
        tool = APITool(config={
            "url": "https://example.com",
            "method": "POST",
            "body_content_type": "application/json",
        })

        with patch(
            "application.agents.tools.api_tool.RequestBodySerializer.serialize",
            side_effect=ValueError("serialize fail"),
        ):
            result = tool.execute_action("any", key="val")
            assert "serialization error" in result["message"].lower()


# =====================================================================
# Path Param Substitution
# =====================================================================


@pytest.mark.unit
class TestPathParamSubstitution:

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_path_params_substituted(self, mock_get, mock_validate):
        tool = APITool(config={
            "url": "https://api.example.com/users/{user_id}/posts/{post_id}",
            "method": "GET",
            "query_params": {"user_id": "42", "post_id": "7"},
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = []
        mock_resp.content = b'[]'
        mock_get.return_value = mock_resp

        tool.execute_action("get")

        called_url = mock_get.call_args[0][0]
        assert "/users/42/posts/7" in called_url
        assert "{user_id}" not in called_url

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_remaining_query_params_appended(self, mock_get, mock_validate):
        tool = APITool(config={
            "url": "https://api.example.com/items",
            "method": "GET",
            "query_params": {"page": "2", "limit": "10"},
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = []
        mock_resp.content = b'[]'
        mock_get.return_value = mock_resp

        tool.execute_action("get")

        called_url = mock_get.call_args[0][0]
        assert "page=2" in called_url
        assert "limit=10" in called_url

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_query_params_append_with_existing_query_string(
        self, mock_get, mock_validate
    ):
        tool = APITool(config={
            "url": "https://api.example.com/items?existing=true",
            "method": "GET",
            "query_params": {"page": "1"},
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = []
        mock_resp.content = b'[]'
        mock_get.return_value = mock_resp

        tool.execute_action("get")

        called_url = mock_get.call_args[0][0]
        assert "&page=1" in called_url

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.post")
    def test_empty_body_no_serialization(self, mock_post, mock_validate):
        tool = APITool(config={"url": "https://example.com", "method": "POST"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_post.return_value = mock_resp

        result = tool.execute_action("create")
        assert result["status_code"] == 200


# =====================================================================
# Parse Response
# =====================================================================


@pytest.mark.unit
class TestParseResponse:

    def test_json_response(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"key": "val"}
        mock_resp.content = b'{"key":"val"}'

        result = get_tool._parse_response(mock_resp)
        assert result == {"key": "val"}

    def test_json_decode_error_falls_back_to_text(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.side_effect = json.JSONDecodeError("", "", 0)
        mock_resp.text = "not valid json"
        mock_resp.content = b"not valid json"

        result = get_tool._parse_response(mock_resp)
        assert result == "not valid json"

    def test_text_response(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.text = "plain text"
        mock_resp.content = b"plain text"

        result = get_tool._parse_response(mock_resp)
        assert result == "plain text"

    def test_xml_response(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/xml"}
        mock_resp.text = "<root><item>1</item></root>"
        mock_resp.content = b"<root><item>1</item></root>"

        result = get_tool._parse_response(mock_resp)
        assert "<root>" in result

    def test_html_response(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<html><body>Hi</body></html>"
        mock_resp.content = b"<html><body>Hi</body></html>"

        result = get_tool._parse_response(mock_resp)
        assert "<html>" in result

    def test_empty_content(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.content = b""

        result = get_tool._parse_response(mock_resp)
        assert result is None

    def test_binary_response(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/octet-stream"}
        mock_resp.text = "binary_text"
        mock_resp.content = b"\x00\x01\x02"

        result = get_tool._parse_response(mock_resp)
        assert result is not None

    def test_text_xml_content_type(self, get_tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/xml"}
        mock_resp.text = "<data/>"
        mock_resp.content = b"<data/>"

        result = get_tool._parse_response(mock_resp)
        assert result == "<data/>"


# =====================================================================
# Metadata
# =====================================================================


@pytest.mark.unit
class TestAPIToolMetadata:

    def test_actions_metadata_empty(self, get_tool):
        assert get_tool.get_actions_metadata() == []

    def test_config_requirements_empty(self, get_tool):
        assert get_tool.get_config_requirements() == {}

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.post")
    def test_content_type_set_for_post_with_no_headers(
        self, mock_post, mock_validate
    ):
        tool = APITool(config={
            "url": "https://example.com",
            "method": "POST",
            "headers": {},
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_post.return_value = mock_resp

        tool.execute_action("create")
        call_headers = mock_post.call_args[1]["headers"]
        assert "Content-Type" in call_headers
