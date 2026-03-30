"""Tests for application/agents/tools/read_webpage.py"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from application.agents.tools.read_webpage import ReadWebpageTool


@pytest.fixture
def tool():
    return ReadWebpageTool()


@pytest.mark.unit
class TestReadWebpageExecuteAction:
    def test_unknown_action(self, tool):
        result = tool.execute_action("unknown_action")
        assert "Error" in result
        assert "Unknown action" in result

    def test_missing_url(self, tool):
        result = tool.execute_action("read_webpage")
        assert "Error" in result
        assert "URL parameter is missing" in result

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_successful_fetch(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h1>Title</h1><p>Content</p></body></html>"
        mock_get.return_value = mock_resp

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "Title" in result
        assert "Content" in result

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_request_error(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com"
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "Error fetching URL" in result

    @patch("application.agents.tools.read_webpage.validate_url")
    def test_ssrf_blocked(self, mock_validate, tool):
        from application.core.url_validation import SSRFError

        mock_validate.side_effect = SSRFError("blocked")

        result = tool.execute_action("read_webpage", url="http://169.254.169.254/")

        assert "Error" in result
        assert "validation failed" in result

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_http_error(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com/404"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
        mock_get.return_value = mock_resp

        result = tool.execute_action("read_webpage", url="https://example.com/404")

        assert "Error fetching URL" in result


@pytest.mark.unit
class TestReadWebpageMetadata:
    def test_actions_metadata(self, tool):
        meta = tool.get_actions_metadata()
        assert len(meta) == 1
        assert meta[0]["name"] == "read_webpage"
        assert "url" in meta[0]["parameters"]["properties"]
        assert "url" in meta[0]["parameters"]["required"]

    def test_config_requirements(self, tool):
        assert tool.get_config_requirements() == {}
