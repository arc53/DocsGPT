"""
PoC tests for CWE-918: SSRF via API tool redirect following.

The API tool validates the initial URL and the URL after parameter substitution,
but does NOT disable HTTP redirect following. This means:
1. A user-configured URL pointing to an external server can redirect to
   internal IPs (169.254.169.254, 127.0.0.1, etc.)
2. Path parameters filled by the LLM are not URL-encoded, allowing
   path traversal and query injection.

These tests verify that the fix:
- Disables automatic redirect following (allow_redirects=False)
- URL-encodes path parameter values before substitution
"""

import json
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from application.agents.tools.api_tool import APITool


class TestSSRFRedirectPrevention:
    """Verify that HTTP redirect following is disabled to prevent SSRF."""

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_get_disables_redirects(self, mock_get, mock_validate):
        """GET requests must pass allow_redirects=False."""
        tool = APITool(config={
            "url": "https://api.example.com/data",
            "method": "GET",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_get.return_value = mock_resp

        tool.execute_action("any")

        _, kwargs = mock_get.call_args
        assert kwargs.get("allow_redirects") is False, (
            "GET request must set allow_redirects=False to prevent SSRF via redirects"
        )

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.post")
    def test_post_disables_redirects(self, mock_post, mock_validate):
        """POST requests must pass allow_redirects=False."""
        tool = APITool(config={
            "url": "https://api.example.com/data",
            "method": "POST",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_post.return_value = mock_resp

        tool.execute_action("create", name="test")

        _, kwargs = mock_post.call_args
        assert kwargs.get("allow_redirects") is False, (
            "POST request must set allow_redirects=False to prevent SSRF via redirects"
        )

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.put")
    def test_put_disables_redirects(self, mock_put, mock_validate):
        """PUT requests must pass allow_redirects=False."""
        tool = APITool(config={
            "url": "https://api.example.com/item/1",
            "method": "PUT",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_put.return_value = mock_resp

        tool.execute_action("update", name="new")

        _, kwargs = mock_put.call_args
        assert kwargs.get("allow_redirects") is False

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.delete")
    def test_delete_disables_redirects(self, mock_delete, mock_validate):
        """DELETE requests must pass allow_redirects=False."""
        tool = APITool(config={
            "url": "https://api.example.com/item/1",
            "method": "DELETE",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.content = b''
        mock_delete.return_value = mock_resp

        tool.execute_action("delete")

        _, kwargs = mock_delete.call_args
        assert kwargs.get("allow_redirects") is False

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.patch")
    def test_patch_disables_redirects(self, mock_patch, mock_validate):
        """PATCH requests must pass allow_redirects=False."""
        tool = APITool(config={
            "url": "https://api.example.com/item/1",
            "method": "PATCH",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_patch.return_value = mock_resp

        tool.execute_action("patch", field="val")

        _, kwargs = mock_patch.call_args
        assert kwargs.get("allow_redirects") is False

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.head")
    def test_head_disables_redirects(self, mock_head, mock_validate):
        """HEAD requests must pass allow_redirects=False."""
        tool = APITool(config={
            "url": "https://api.example.com",
            "method": "HEAD",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.content = b''
        mock_head.return_value = mock_resp

        tool.execute_action("check")

        _, kwargs = mock_head.call_args
        assert kwargs.get("allow_redirects") is False

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.options")
    def test_options_disables_redirects(self, mock_options, mock_validate):
        """OPTIONS requests must pass allow_redirects=False."""
        tool = APITool(config={
            "url": "https://api.example.com",
            "method": "OPTIONS",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.content = b''
        mock_options.return_value = mock_resp

        tool.execute_action("check")

        _, kwargs = mock_options.call_args
        assert kwargs.get("allow_redirects") is False


class TestPathParamEncoding:
    """Verify that LLM-provided path parameters are URL-encoded."""

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_path_param_slash_encoded(self, mock_get, mock_validate):
        """Path parameter containing slashes must be URL-encoded."""
        tool = APITool(config={
            "url": "https://api.example.com/v1/users/{user_id}/profile",
            "method": "GET",
            "query_params": {"user_id": "../../admin"},
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_get.return_value = mock_resp

        tool.execute_action("get")

        called_url = mock_get.call_args[0][0]
        # Slashes in param value should be encoded as %2F
        assert "../../admin" not in called_url, (
            "Path parameter with slashes must be URL-encoded to prevent path traversal"
        )
        assert "%2F" in called_url or "%2f" in called_url

    @patch("application.agents.tools.api_tool.validate_url")
    @patch("application.agents.tools.api_tool.requests.get")
    def test_path_param_query_injection_encoded(self, mock_get, mock_validate):
        """Path parameter containing '?' must be URL-encoded."""
        tool = APITool(config={
            "url": "https://api.example.com/v1/items/{item_id}",
            "method": "GET",
            "query_params": {"item_id": "x?admin=true"},
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {}
        mock_resp.content = b'{}'
        mock_get.return_value = mock_resp

        tool.execute_action("get")

        called_url = mock_get.call_args[0][0]
        # The ? in the param value should be encoded, not treated as query delimiter
        assert "x?admin=true" not in called_url, (
            "Path parameter with '?' must be URL-encoded to prevent query injection"
        )
