from unittest.mock import MagicMock, patch

from application.parser.remote.crawler_loader import CrawlerLoader
from application.parser.schema.base import Document
from langchain_core.documents import Document as LCDocument


class DummyResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _mock_validate_url(url):
    """Mock validate_url that allows test URLs through."""
    from urllib.parse import urlparse
    if not urlparse(url).scheme:
        url = "http://" + url
    return url


@patch("application.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("application.parser.remote.crawler_loader.requests.get")
def test_load_data_crawls_same_domain_links(mock_requests_get, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            """
            <html>
                <body>
                    <a href='/about'>About</a>
                    <a href='https://external.com/news'>External</a>
                </body>
            </html>
            """
        ),
        "http://example.com/about": DummyResponse("<html><body>About page</body></html>"),
    }

    def response_side_effect(url: str, timeout=30):
        if url not in responses:
            raise AssertionError(f"Unexpected request for URL: {url}")
        return responses[url]

    mock_requests_get.side_effect = response_side_effect

    root_doc = MagicMock(spec=LCDocument)
    root_doc.page_content = "Root content"
    root_doc.metadata = {"source": "http://example.com"}

    about_doc = MagicMock(spec=LCDocument)
    about_doc.page_content = "About content"
    about_doc.metadata = {"source": "http://example.com/about"}

    loader_instances = {
        "http://example.com": MagicMock(),
        "http://example.com/about": MagicMock(),
    }
    loader_instances["http://example.com"].load.return_value = [root_doc]
    loader_instances["http://example.com/about"].load.return_value = [about_doc]

    loader_call_order = []

    def loader_factory(url_list):
        url = url_list[0]
        loader_call_order.append(url)
        return loader_instances[url]

    crawler = CrawlerLoader(limit=5)
    crawler.loader = MagicMock(side_effect=loader_factory)

    result = crawler.load_data("http://example.com")

    assert len(result) == 2
    assert all(isinstance(doc, Document) for doc in result)

    sources = {doc.extra_info.get("source") for doc in result}
    assert sources == {"http://example.com", "http://example.com/about"}

    texts = {doc.text for doc in result}
    assert texts == {"Root content", "About content"}

    assert mock_requests_get.call_count == 2
    assert loader_call_order == ["http://example.com", "http://example.com/about"]


@patch("application.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("application.parser.remote.crawler_loader.requests.get")
def test_load_data_accepts_list_input_and_adds_scheme(mock_requests_get, mock_validate_url):
    mock_requests_get.return_value = DummyResponse("<html><body>No links here</body></html>")

    doc = MagicMock(spec=LCDocument)
    doc.page_content = "Homepage"
    doc.metadata = {"source": "http://example.com"}

    loader_instance = MagicMock()
    loader_instance.load.return_value = [doc]

    crawler = CrawlerLoader()
    crawler.loader = MagicMock(return_value=loader_instance)

    result = crawler.load_data(["example.com", "unused.com"])

    mock_requests_get.assert_called_once_with("http://example.com", timeout=30)
    crawler.loader.assert_called_once_with(["http://example.com"])

    assert len(result) == 1
    assert result[0].text == "Homepage"
    assert result[0].extra_info == {"source": "http://example.com"}


@patch("application.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("application.parser.remote.crawler_loader.requests.get")
def test_load_data_respects_limit(mock_requests_get, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            """
            <html>
                <body>
                    <a href='/about'>About</a>
                </body>
            </html>
            """
        ),
        "http://example.com/about": DummyResponse("<html><body>About</body></html>"),
    }

    mock_requests_get.side_effect = lambda url, timeout=30: responses[url]

    root_doc = MagicMock(spec=LCDocument)
    root_doc.page_content = "Root content"
    root_doc.metadata = {"source": "http://example.com"}

    about_doc = MagicMock(spec=LCDocument)
    about_doc.page_content = "About content"
    about_doc.metadata = {"source": "http://example.com/about"}

    loader_instances = {
        "http://example.com": MagicMock(),
        "http://example.com/about": MagicMock(),
    }
    loader_instances["http://example.com"].load.return_value = [root_doc]
    loader_instances["http://example.com/about"].load.return_value = [about_doc]

    crawler = CrawlerLoader(limit=1)
    crawler.loader = MagicMock(side_effect=lambda url_list: loader_instances[url_list[0]])

    result = crawler.load_data("http://example.com")

    assert len(result) == 1
    assert result[0].text == "Root content"
    assert mock_requests_get.call_count == 1
    assert crawler.loader.call_count == 1


@patch("application.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("application.parser.remote.crawler_loader.logging")
@patch("application.parser.remote.crawler_loader.requests.get")
def test_load_data_logs_and_skips_on_loader_error(mock_requests_get, mock_logging, mock_validate_url):
    mock_requests_get.return_value = DummyResponse("<html><body>Error route</body></html>")

    failing_loader_instance = MagicMock()
    failing_loader_instance.load.side_effect = Exception("load failure")

    crawler = CrawlerLoader()
    crawler.loader = MagicMock(return_value=failing_loader_instance)

    result = crawler.load_data("http://example.com")

    assert result == []
    mock_requests_get.assert_called_once_with("http://example.com", timeout=30)
    failing_loader_instance.load.assert_called_once()

    mock_logging.error.assert_called_once()
    message, = mock_logging.error.call_args.args
    assert "Error processing URL http://example.com" in message
    assert mock_logging.error.call_args.kwargs.get("exc_info") is True


@patch("application.parser.remote.crawler_loader.validate_url")
def test_load_data_returns_empty_on_ssrf_validation_failure(mock_validate_url):
    """Test that SSRF validation failure returns empty list."""
    from application.core.url_validation import SSRFError
    mock_validate_url.side_effect = SSRFError("Access to private IP not allowed")

    crawler = CrawlerLoader()
    result = crawler.load_data("http://192.168.1.1")

    assert result == []
    mock_validate_url.assert_called_once()

