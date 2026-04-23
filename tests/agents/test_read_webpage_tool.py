"""Tests for application/agents/tools/read_webpage.py"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from application.agents.tools.read_webpage import MAX_CONTENT_BYTES, ReadWebpageTool


@pytest.fixture
def tool():
    return ReadWebpageTool()


def _make_streaming_response(html: str, encoding: str = "utf-8", headers: dict = None):
    """Helper: build a mock streaming response for the given HTML string."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = headers or {}
    mock_resp.encoding = encoding
    raw = html.encode(encoding)
    mock_resp.iter_content.return_value = iter([raw])
    return mock_resp


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
        mock_get.return_value = _make_streaming_response(
            "<html><body><h1>Title</h1><p>Content</p></body></html>"
        )

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

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_content_length_too_large_rejected(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com/huge"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {"Content-Length": str(MAX_CONTENT_BYTES + 1)}
        mock_get.return_value = mock_resp

        result = tool.execute_action("read_webpage", url="https://example.com/huge")

        assert "too large" in result.lower()
        mock_resp.iter_content.assert_not_called()
        mock_resp.close.assert_called_once()

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_streaming_body_too_large_rejected(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com/stream"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {}
        # each chunk is 8192 bytes; send enough to exceed MAX_CONTENT_BYTES
        chunk = b"x" * 8192
        num_chunks = (MAX_CONTENT_BYTES // 8192) + 2
        mock_resp.iter_content.return_value = iter([chunk] * num_chunks)
        mock_get.return_value = mock_resp

        result = tool.execute_action("read_webpage", url="https://example.com/stream")

        assert "too large" in result.lower()
        mock_resp.close.assert_called_once()

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_content_at_limit_allowed(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com/ok"
        html = "<p>ok</p>"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {"Content-Length": str(MAX_CONTENT_BYTES)}
        mock_resp.encoding = "utf-8"
        mock_resp.iter_content.return_value = iter([html.encode("utf-8")])
        mock_get.return_value = mock_resp

        result = tool.execute_action("read_webpage", url="https://example.com/ok")

        assert "too large" not in result.lower()
        assert "ok" in result

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_uses_stream_true(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com"
        mock_get.return_value = _make_streaming_response("<p>hi</p>")

        tool.execute_action("read_webpage", url="https://example.com")

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs.get("stream") is True

    @patch("application.agents.tools.read_webpage.validate_url")
    @patch("application.agents.tools.read_webpage.requests.get")
    def test_user_agent_header_sent(self, mock_get, mock_validate, tool):
        mock_validate.return_value = "https://example.com"
        mock_get.return_value = _make_streaming_response("<p>hi</p>")

        tool.execute_action("read_webpage", url="https://example.com")

        headers = mock_get.call_args[1]["headers"]
        assert headers["User-Agent"] == "DocsGPT-Agent/1.0"


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
