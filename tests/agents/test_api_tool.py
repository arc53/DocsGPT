"""Tests for application/agents/tools/api_tool.py"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from application.agents.tools.api_tool import APITool


@pytest.fixture
def tool():
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


@pytest.mark.unit
class TestAPIToolInit:
    def test_default_values(self):
        tool = APITool(config={})
        assert tool.url == ""
        assert tool.method == "GET"
        assert tool.headers == {}
        assert tool.query_params == {}


@pytest.mark.unit
class TestMakeApiCall:
    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_successful_get(self, mock_get, mock_validate, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"result": "ok"}
        mock_resp.content = b'{"result":"ok"}'
        mock_get.return_value = mock_resp

        result = tool.execute_action("any_action")

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
    def test_ssrf_blocked(self, mock_validate, tool):
        from application.core.url_validation import SSRFError

        mock_validate.side_effect = SSRFError("blocked")

        result = tool.execute_action("any")

        assert result["status_code"] is None
        assert "URL validation error" in result["message"]

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_timeout_error(self, mock_get, mock_validate, tool):
        mock_get.side_effect = requests.exceptions.Timeout()

        result = tool.execute_action("any")

        assert result["status_code"] is None
        assert "timeout" in result["message"].lower()

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_connection_error(self, mock_get, mock_validate, tool):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        result = tool.execute_action("any")

        assert result["status_code"] is None
        assert "Connection error" in result["message"]

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_http_error(self, mock_get, mock_validate, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_resp.json.side_effect = json.JSONDecodeError("", "", 0)
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_get.return_value = mock_resp

        result = tool.execute_action("any")

        assert result["status_code"] == 404
        assert "HTTP Error" in result["message"]

    @patch("application.agents.tools.api_tool.validate_url")
    def test_unsupported_method(self, mock_validate):
        tool = APITool(
            config={"url": "https://example.com", "method": "CUSTOM"}
        )
        result = tool.execute_action("any")
        assert result["status_code"] is None
        assert "Unsupported" in result["message"]

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


@pytest.mark.unit
class TestPathParamSubstitution:
    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_path_params_substituted(self, mock_get, mock_validate):
        tool = APITool(
            config={
                "url": "https://api.example.com/users/{user_id}/posts/{post_id}",
                "method": "GET",
                "query_params": {"user_id": "42", "post_id": "7"},
            }
        )
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


@pytest.mark.unit
class TestParseResponse:
    def test_json_response(self, tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"key": "val"}
        mock_resp.content = b'{"key":"val"}'

        result = tool._parse_response(mock_resp)
        assert result == {"key": "val"}

    def test_text_response(self, tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.text = "plain text"
        mock_resp.content = b"plain text"

        result = tool._parse_response(mock_resp)
        assert result == "plain text"

    def test_xml_response(self, tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/xml"}
        mock_resp.text = "<root><item>1</item></root>"
        mock_resp.content = b"<root><item>1</item></root>"

        result = tool._parse_response(mock_resp)
        assert "<root>" in result

    def test_empty_content(self, tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.content = b""

        result = tool._parse_response(mock_resp)
        assert result is None

    def test_html_response(self, tool):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<html><body>Hi</body></html>"
        mock_resp.content = b"<html><body>Hi</body></html>"

        result = tool._parse_response(mock_resp)
        assert "<html>" in result


@pytest.mark.unit
class TestAPIToolMetadata:
    def test_actions_metadata_empty(self, tool):
        assert tool.get_actions_metadata() == []

    def test_config_requirements_empty(self, tool):
        assert tool.get_config_requirements() == {}
