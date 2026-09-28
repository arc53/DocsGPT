import pytest
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse

from docsgpt.core.url_validation import SSRFError
from docsgpt.parser.remote.web_loader import WebLoader, headers
from docsgpt.parser.schema.base import Document
from docsgpt.vectorstore.document_class import Document as LCDocument


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

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_same_host_urls_get_path_only_file_paths(self, mock_pinned_request, mock_validate, web_loader):
        # The tree and the chunk path filter both key off file_path, so each
        # page needs a stable, distinct one (not its title).
        mock_pinned_request.side_effect = [
            _fake_response("<html><head><title>Home</title></head><body>a</body></html>"),
            _fake_response("<html><head><title>Setup</title></head><body>b</body></html>"),
        ]

        result = web_loader.load_data(["https://docs.x.io/", "https://docs.x.io/guides/setup.html"])

        assert [d.extra_info["file_path"] for d in result] == ["index.md", "guides/setup.md"]

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
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
            "file_path": "index.md",
        }
        mock_pinned_request.assert_called_once_with(
            "GET", "https://example.com", headers=headers, timeout=30
        )

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
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
        # Two hosts would both map to index.md, so the host prefixes the path.
        assert result[0].extra_info == {"source": "https://site1.com", "file_path": "site1.com/index.md"}
        assert result[1].extra_info == {"source": "https://site2.com", "file_path": "site2.com/index.md"}

        assert mock_pinned_request.call_count == 2
        mock_pinned_request.assert_any_call(
            "GET", "https://site1.com", headers=headers, timeout=30
        )
        mock_pinned_request.assert_any_call(
            "GET", "https://site2.com", headers=headers, timeout=30
        )

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_load_data_url_without_scheme(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response(
            "<html><body>Schemeless</body></html>"
        )

        result = web_loader.load_data("example.com")

        assert len(result) == 1
        mock_pinned_request.assert_called_once_with(
            "GET", "http://example.com", headers=headers, timeout=30
        )

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_load_data_url_with_scheme(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response(
            "<html><body>Schemed</body></html>"
        )

        result = web_loader.load_data("https://example.com")

        assert len(result) == 1
        mock_pinned_request.assert_called_once_with(
            "GET", "https://example.com", headers=headers, timeout=30
        )

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_load_data_skips_pages_without_title(self, mock_pinned_request, mock_validate, web_loader):
        """A page without <title> or <html lang=...> still loads, just with bare metadata."""
        mock_pinned_request.return_value = _fake_response("<p>Bare body</p>")

        result = web_loader.load_data("https://example.com")

        assert len(result) == 1
        assert result[0].text == "Bare body"
        assert result[0].extra_info == {"source": "https://example.com", "file_path": "index.md"}

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_load_data_extracts_title_with_nested_markup(self, mock_pinned_request, mock_validate, web_loader):
        """<title> with nested-looking content must still produce a non-empty title.

        BS4's `html.parser` differs across Python/bs4 versions: some treat
        `<title>` as RAWTEXT (per HTML5 spec) and return the literal string
        ``"Hello <span>World</span>"``; others parse the inner tag and return
        ``"HelloWorld"``. The regression guarded here is that ``soup.title.string``
        returns ``None`` in *either* case, dropping the title entirely — using
        ``get_text`` keeps it. Assert only that the title survives.
        """
        mock_pinned_request.return_value = _fake_response(
            "<html><head><title>Hello <span>World</span></title></head>"
            "<body><p>x</p></body></html>"
        )

        result = web_loader.load_data("https://example.com")

        title = result[0].extra_info.get("title")
        assert title, "title was dropped — soup.title.string regression?"
        assert "Hello" in title


class TestWebLoaderErrorHandling:
    """Test WebLoader error handling."""

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    @patch("docsgpt.parser.remote.web_loader.logging")
    def test_load_data_single_url_error(self, mock_logging, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.side_effect = Exception("Network error")

        result = web_loader.load_data("https://invalid-url.com")

        assert result == []
        mock_logging.error.assert_called_once()
        error_call = mock_logging.error.call_args
        assert "Error processing URL https://invalid-url.com" in error_call[0][0]
        assert error_call[1]["exc_info"] is True

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    @patch("docsgpt.parser.remote.web_loader.logging")
    def test_load_data_partial_failure(self, mock_logging, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.side_effect = [
            _fake_response("<html><body>Success content</body></html>"),
            Exception("Network error"),
        ]

        urls = ["https://good-url.com", "https://bad-url.com"]
        result = web_loader.load_data(urls)

        assert len(result) == 1
        assert result[0].text == "Success content"
        assert result[0].extra_info == {"source": "https://good-url.com", "file_path": "good-url.com/index.md"}

        mock_logging.error.assert_called_once()
        error_call = mock_logging.error.call_args
        assert "Error processing URL https://bad-url.com" in error_call[0][0]


class TestWebLoaderSSRF:
    """Test WebLoader SSRF protection."""

    @patch("docsgpt.parser.remote.web_loader.validate_url")
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_load_data_skips_url_failing_ssrf_validation(self, mock_pinned_request, mock_validate, web_loader):
        """A URL that fails SSRF validation must be skipped, never reaching the fetcher."""
        mock_validate.side_effect = SSRFError("Access to private/internal IP addresses is not allowed.")

        result = web_loader.load_data("http://169.254.169.254/latest/meta-data/")

        assert result == []
        mock_validate.assert_called_once_with("http://169.254.169.254/latest/meta-data/")
        mock_pinned_request.assert_not_called()

    @patch("docsgpt.parser.remote.web_loader.validate_url")
    @patch("docsgpt.parser.remote.web_loader.logging")
    def test_load_data_logs_warning_on_ssrf_failure(self, mock_logging, mock_validate, web_loader):
        mock_validate.side_effect = SSRFError("blocked")

        web_loader.load_data("http://127.0.0.1")

        mock_logging.warning.assert_called_once()
        warning_msg = mock_logging.warning.call_args[0][0]
        assert "SSRF" in warning_msg
        assert "127.0.0.1" in warning_msg

    @patch("docsgpt.parser.remote.web_loader.validate_url")
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
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

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_load_data_empty_response_body(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response("")

        result = web_loader.load_data("https://empty-page.com")

        assert len(result) == 1
        assert result[0].text == ""
        assert result[0].extra_info == {"source": "https://empty-page.com", "file_path": "index.md"}

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
        from docsgpt.parser.remote.base import BaseRemote
        assert isinstance(web_loader, BaseRemote)

    def test_implements_load_data_method(self, web_loader):
        assert hasattr(web_loader, "load_data")
        assert callable(web_loader.load_data)

    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_load_vector_documents_method(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.return_value = _fake_response(
            "<html><head><title>Test Page</title></head>"
            "<body><p>Test web page content</p></body></html>"
        )

        result = web_loader.load_vector_documents(inputs="https://example.com")

        assert len(result) == 1
        assert isinstance(result[0], LCDocument)
        assert "Test web page content" in result[0].page_content
        assert result[0].metadata["source"] == "https://example.com"
        assert result[0].metadata["title"] == "Test Page"


@pytest.mark.unit
class TestWebLoaderDistinctPaths:
    @patch("docsgpt.parser.remote.web_loader.validate_url", side_effect=_mock_validate_url)
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_colliding_pages_get_distinct_file_paths(self, mock_pinned_request, mock_validate, web_loader):
        mock_pinned_request.side_effect = lambda *a, **k: _fake_response("<html><body>x</body></html>")

        result = web_loader.load_data(
            [
                "https://x.io/list?page=1",
                "https://x.io/list?page=2",
                "https://x.io/a.html",
                "https://x.io/a",
            ]
        )

        assert [d.extra_info["file_path"] for d in result] == [
            "list__page=1.md", "list__page=2.md", "a-2.md", "a.md"
        ]


@pytest.mark.unit
class TestWebLoaderMalformedUrl:
    @patch("docsgpt.core.url_validation.resolve_hostname", return_value="93.184.216.34")
    @patch("docsgpt.parser.remote.web_loader.pinned_request")
    def test_malformed_url_is_skipped_and_the_rest_ingest(self, mock_pinned_request, _mock_resolve, web_loader):
        mock_pinned_request.side_effect = lambda *a, **k: _fake_response("<html><body>good</body></html>")

        result = web_loader.load_data(["http://[bad", "https://x.io/good"])

        assert [d.extra_info["source"] for d in result] == ["https://x.io/good"]
        assert result[0].extra_info["file_path"] == "good.md"
