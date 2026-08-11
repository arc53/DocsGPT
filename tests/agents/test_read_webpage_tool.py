"""Tests for application/agents/tools/read_webpage.py"""

from unittest.mock import patch

import pytest
import requests

from application.agents.tools.read_webpage import ReadWebpageTool
from application.security.safe_url import ResponseTooLargeError


class _FakeResponse:
    def __init__(self, status_code: int = 200, headers=None):
        self.status_code = status_code
        self.headers = headers if headers is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))


def _fetch_result(body: bytes, content_type=None, status_code: int = 200, headers=None):
    headers = dict(headers or {})
    if content_type is not None:
        headers["Content-Type"] = content_type
    return body, _FakeResponse(status_code=status_code, headers=headers)


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

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_successful_fetch(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            b"<html><body><h1>Title</h1><p>Content</p></body></html>",
            content_type="text/html; charset=utf-8",
        )

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "Title" in result
        assert "Content" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_request_error(self, mock_fetch, tool):
        mock_fetch.side_effect = requests.exceptions.ConnectionError("refused")

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "Error fetching URL" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_ssrf_blocked(self, mock_fetch, tool):
        from application.security.safe_url import UnsafeUserUrlError

        mock_fetch.side_effect = UnsafeUserUrlError("blocked")

        result = tool.execute_action("read_webpage", url="http://169.254.169.254/")

        assert "Error" in result
        assert "validation failed" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_http_error(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(b"", status_code=404)

        result = tool.execute_action("read_webpage", url="https://example.com/404")

        assert "Error fetching URL" in result


@pytest.mark.unit
class TestReadWebpageContentGuards:
    """Regression tests for the PDF-as-text incident: a binary body must
    never come back as NUL-laden 'markdown'."""

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_rejects_pdf_content_type(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            b"%PDF-1.7 binary...", content_type="application/pdf",
        )

        result = tool.execute_action("read_webpage", url="https://example.com/doc.pdf")

        assert result.startswith("Error")
        assert "application/pdf" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_rejects_pdf_magic_without_content_type(self, mock_fetch, tool):
        # No Content-Type header at all — the 07-17 incident shape.
        mock_fetch.return_value = _fetch_result(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3...")

        result = tool.execute_action("read_webpage", url="https://example.com/doc.pdf")

        assert result.startswith("Error")

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_rejects_nul_laden_body_despite_html_content_type(self, mock_fetch, tool):
        # Mislabeled binary: content-type lies, the NUL sniff must catch it.
        mock_fetch.return_value = _fetch_result(
            b"<html>\x00\x00\x00binary\x00garbage\x00\x00</html>",
            content_type="text/html",
        )

        result = tool.execute_action("read_webpage", url="https://example.com/fake")

        assert result.startswith("Error")
        assert "\x00" not in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_rejects_octet_stream(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            b"anything", content_type="application/octet-stream",
        )

        result = tool.execute_action("read_webpage", url="https://example.com/blob")

        assert result.startswith("Error")
        assert "application/octet-stream" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_response_too_large(self, mock_fetch, tool):
        mock_fetch.side_effect = ResponseTooLargeError("body exceeds 10485760 bytes")

        result = tool.execute_action("read_webpage", url="https://example.com/huge")

        assert result.startswith("Error")
        assert "large" in result.lower()

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_utf8_decoded_without_declared_charset(self, mock_fetch, tool):
        # text/html with no charset param: requests' RFC-2616 ISO-8859-1
        # fallback would mojibake this; we must default to UTF-8.
        mock_fetch.return_value = _fetch_result(
            "<html><body><p>café über</p></body></html>".encode("utf-8"),
            content_type="text/html",
        )

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "café über" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_declared_charset_respected(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            "<html><body><p>café</p></body></html>".encode("latin-1"),
            content_type="text/html; charset=ISO-8859-1",
        )

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "café" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_unknown_declared_charset_falls_back_to_utf8(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            "<html><body><p>ok</p></body></html>".encode("utf-8"),
            content_type="text/html; charset=not-a-real-charset",
        )

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "ok" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_text_plain_allowed(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            b"plain text document", content_type="text/plain",
        )

        result = tool.execute_action("read_webpage", url="https://example.com/readme")

        assert "plain text document" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_utf16_page_with_declared_charset_allowed(self, mock_fetch, tool):
        # UTF-16 text is NUL-dense; a correct charset declaration must
        # win over the NUL sniff (which is for undeclared/mislabeled bodies).
        mock_fetch.return_value = _fetch_result(
            "<html><body>Hello world</body></html>".encode("utf-16"),
            content_type="text/html; charset=utf-16",
        )

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "Hello world" in result
        assert "\x00" not in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_pdf_magic_beats_declared_charset(self, mock_fetch, tool):
        # The magic-prefix check stays unconditional: a lying
        # ``text/html; charset=utf-8`` header must not sneak a PDF through.
        mock_fetch.return_value = _fetch_result(
            b"%PDF-1.7 binary...",
            content_type="text/html; charset=utf-8",
        )

        result = tool.execute_action("read_webpage", url="https://example.com/fake")

        assert result.startswith("Error")

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_nuls_past_sniff_window_are_stripped(self, mock_fetch, tool):
        # The sniff only sees the first KB; NULs beyond it must still
        # never leave the tool (self-contained, not reliant on the
        # executor's sanitizer).
        body = b"<html><p>" + b"x" * 1100 + b"\x00\x00 tail</p></html>"
        mock_fetch.return_value = _fetch_result(body, content_type="text/html")

        result = tool.execute_action("read_webpage", url="https://example.com")

        assert "\x00" not in result
        assert "tail" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_text_csv_allowed(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            b"name,qty\nwidget,2", content_type="text/csv",
        )

        result = tool.execute_action("read_webpage", url="https://example.com/data.csv")

        assert "widget" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_redirect_reported_with_target(self, mock_fetch, tool):
        # allow_redirects=False (SSRF) means a 3xx would otherwise return
        # the redirect body as near-empty markdown with no hint.
        mock_fetch.return_value = _fetch_result(
            b"", status_code=301,
            headers={"Location": "https://example.com/moved-here"},
        )

        result = tool.execute_action("read_webpage", url="https://example.com/old")

        assert result.startswith("Error")
        assert "https://example.com/moved-here" in result

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_redirect_without_location_reported(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(b"", status_code=302)

        result = tool.execute_action("read_webpage", url="https://example.com/old")

        assert result.startswith("Error")
        assert "redirect" in result.lower()

    @patch("application.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_rss_feed_allowed(self, mock_fetch, tool):
        mock_fetch.return_value = _fetch_result(
            b"<rss><channel><title>Feed title</title></channel></rss>",
            content_type="application/rss+xml",
        )

        result = tool.execute_action("read_webpage", url="https://example.com/feed")

        assert "Feed title" in result


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
