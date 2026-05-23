import pytest
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse

from application.core.url_validation import SSRFError
from application.parser.remote.web_loader import WebLoader, headers
from application.parser.schema.base import Document
from langchain_core.documents import Document as LCDocument


def _mock_validate_url(url):
    """Mock validate_url that allows test URLs through and prepends scheme like the real impl."""
    if not urlparse(url).scheme:
        url = "http://" + url
    return url


def _fake_response(html: str) -> MagicMock:
    """Build a MagicMock that quacks like a requests.Response for our purposes."""
    response = MagicMock()
    response.text = html
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def web_loader():
    return WebLoader()


class TestWebLoaderInitialization:
    """Test WebLoader initialization."""

    def test_init_has_no_loader_attribute(self, web_loader):
        """Post-pinned-request migration, WebLoader no longer keeps a langchain loader class."""
        assert not hasattr(web_loader, "loader")


class TestWebLoaderHeaders:
    """Test WebLoader headers configuration."""

    def test_headers_defined(self):
        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "Referer" in headers
        assert "DNT" in headers
        assert "Connection" in headers
        assert "Upgrade-Insecure-Requests" in headers

    def test_headers_values(self):
        assert headers["User-Agent"] == "Mozilla/5.0"
        assert "text/html" in headers["Accept"]
        assert headers["Referer"] == "https://www.google.com/"
        assert headers["DNT"] == "1"
        assert headers["Connection"] == "keep-alive"


class TestWebLoaderLoadData:
    """Test WebLoader load_data method."""

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_single_url_string(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response(
            "<html lang='en'><head><title>Test Page</title></head>"
            "<body><p>Test web page content</p></body></html>"
        )

        result = web_loader.load_data("https://example.com")

        assert len(result) == 1
        assert isinstance(result[0], Document)
        assert result[0].text == "Test Page\nTest web page content"
        assert result[0].extra_info == {
            "source": "https://example.com",
            "title": "Test Page",
            "language": "en",
        }
        mock_pinned_request.assert_called_once_with(
            "GET", "https://example.com", headers=headers, timeout=30
        )

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_multiple_urls_list(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.side_effect = [
            _fake_response("<html><body>Content from site 1</body></html>"),
            _fake_response("<html><body>Content from site 2</body></html>"),
        ]

        urls = ["https://site1.com", "https://site2.com"]
        result = web_loader.load_data(urls)

        assert len(result) == 2
        assert all(isinstance(doc, Document) for doc in result)
        assert result[0].text == "Content from site 1"
        assert result[1].text == "Content from site 2"
        assert result[0].extra_info == {"source": "https://site1.com"}
        assert result[1].extra_info == {"source": "https://site2.com"}

        assert mock_pinned_request.call_count == 2
        mock_pinned_request.assert_any_call(
            "GET", "https://site1.com", headers=headers, timeout=30
        )
        mock_pinned_request.assert_any_call(
            "GET", "https://site2.com", headers=headers, timeout=30
        )

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_url_without_scheme(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response(
            "<html><body>Schemeless</body></html>"
        )

        result = web_loader.load_data("example.com")

        assert len(result) == 1
        mock_pinned_request.assert_called_once_with(
            "GET", "http://example.com", headers=headers, timeout=30
        )

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_url_with_scheme(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response(
            "<html><body>Schemed</body></html>"
        )

        result = web_loader.load_data("https://example.com")

        assert len(result) == 1
        mock_pinned_request.assert_called_once_with(
            "GET", "https://example.com", headers=headers, timeout=30
        )

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_skips_pages_without_title(self, mock_pinned_request, mock_validate, web_loader):
        """A page without <title> or <html lang=...> still loads, just with bare metadata."""
        mock_pinned_request.return_value = _fake_response("<p>Bare body</p>")

        result = web_loader.load_data("https://example.com")

        assert len(result) == 1
        assert result[0].text == "Bare body"
        assert result[0].extra_info == {"source": "https://example.com"}


class TestWebLoaderErrorHandling:
    """Test WebLoader error handling."""

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    @patch("application.parser.remote.web_loader.logging")
    def test_load_data_single_url_error(self, mock_logging, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.side_effect = Exception("Network error")

        result = web_loader.load_data("https://invalid-url.com")

        assert result == []
        mock_logging.error.assert_called_once()
        error_call = mock_logging.error.call_args
        assert "Error processing URL https://invalid-url.com" in error_call[0][0]
        assert error_call[1]["exc_info"] is True

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    @patch("application.parser.remote.web_loader.logging")
    def test_load_data_partial_failure(self, mock_logging, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.side_effect = [
            _fake_response("<html><body>Success content</body></html>"),
            Exception("Network error"),
        ]

        urls = ["https://good-url.com", "https://bad-url.com"]
        result = web_loader.load_data(urls)

        assert len(result) == 1
        assert result[0].text == "Success content"
        assert result[0].extra_info == {"source": "https://good-url.com"}

        mock_logging.error.assert_called_once()
        error_call = mock_logging.error.call_args
        assert "Error processing URL https://bad-url.com" in error_call[0][0]


class TestWebLoaderSSRF:
    """Test WebLoader SSRF protection."""

    @patch("application.parser.remote.web_loader.validate_url")
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_skips_url_failing_ssrf_validation(self, mock_pinned_request, mock_validate, web_loader):
        """A URL that fails SSRF validation must be skipped, never reaching the fetcher."""
        mock_validate.side_effect = SSRFError("Access to private/internal IP addresses is not allowed.")

        result = web_loader.load_data("http://169.254.169.254/latest/meta-data/")

        assert result == []
        mock_validate.assert_called_once_with("http://169.254.169.254/latest/meta-data/")
        mock_pinned_request.assert_not_called()

    @patch("application.parser.remote.web_loader.validate_url")
    @patch("application.parser.remote.web_loader.logging")
    def test_load_data_logs_warning_on_ssrf_failure(self, mock_logging, mock_validate, web_loader):
        mock_validate.side_effect = SSRFError("blocked")

        web_loader.load_data("http://127.0.0.1")

        mock_logging.warning.assert_called_once()
        warning_msg = mock_logging.warning.call_args[0][0]
        assert "SSRF" in warning_msg
        assert "127.0.0.1" in warning_msg

    @patch("application.parser.remote.web_loader.validate_url")
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_mixed_safe_and_unsafe_urls(self, mock_pinned_request, mock_validate, web_loader):
        def validate(url):
            if "169.254.169.254" in url:
                raise SSRFError("metadata blocked")
            return url

        mock_validate.side_effect = validate
        mock_pinned_request.return_value = _fake_response(
            "<html><body>Public page</body></html>"
        )

        urls = ["https://example.com", "http://169.254.169.254/latest/meta-data/"]
        result = web_loader.load_data(urls)

        assert len(result) == 1
        assert result[0].text == "Public page"
        mock_pinned_request.assert_called_once_with(
            "GET", "https://example.com", headers=headers, timeout=30
        )


class TestWebLoaderEdgeCases:
    """Test WebLoader edge cases."""

    def test_load_data_empty_list(self, web_loader):
        result = web_loader.load_data([])
        assert result == []

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_data_empty_response_body(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response("")

        result = web_loader.load_data("https://empty-page.com")

        assert len(result) == 1
        assert result[0].text == ""
        assert result[0].extra_info == {"source": "https://empty-page.com"}

    def test_url_scheme_detection(self):
        """Test URL scheme detection logic."""
        assert urlparse("https://example.com").scheme == "https"
        assert urlparse("http://example.com").scheme == "http"
        assert urlparse("ftp://example.com").scheme == "ftp"

        assert urlparse("example.com").scheme == ""
        assert urlparse("www.example.com").scheme == ""


class TestWebLoaderIntegration:
    """Test WebLoader integration with base class."""

    def test_inherits_from_base_remote(self, web_loader):
        from application.parser.remote.base import BaseRemote
        assert isinstance(web_loader, BaseRemote)

    def test_implements_load_data_method(self, web_loader):
        assert hasattr(web_loader, "load_data")
        assert callable(web_loader.load_data)

    @patch("application.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("application.parser.remote.web_loader.pinned_request")
    def test_load_langchain_documents_method(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response(
            "<html><head><title>Test Page</title></head>"
            "<body><p>Test web page content</p></body></html>"
        )

        result = web_loader.load_langchain_documents(inputs="https://example.com")

        assert len(result) == 1
        assert isinstance(result[0], LCDocument)
        assert "Test web page content" in result[0].page_content
        assert result[0].metadata["source"] == "https://example.com"
        assert result[0].metadata["title"] == "Test Page"
