from unittest.mock import MagicMock, patch

import pytest

from docsgpt.parser.remote.crawler_loader import CrawlerLoader
from docsgpt.parser.schema.base import Document


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


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_load_data_crawls_same_domain_links(mock_pinned_request, mock_validate_url):
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

    def response_side_effect(_method: str, url: str, timeout=30):
        if url not in responses:
            raise AssertionError(f"Unexpected request for URL: {url}")
        return responses[url]

    mock_pinned_request.side_effect = response_side_effect

    crawler = CrawlerLoader(limit=5)

    result = crawler.load_data("http://example.com")

    assert len(result) == 2
    assert all(isinstance(doc, Document) for doc in result)

    sources = {doc.extra_info.get("source") for doc in result}
    assert sources == {"http://example.com", "http://example.com/about"}

    paths = {doc.extra_info.get("file_path") for doc in result}
    assert paths == {"index.md", "about.md"}

    texts = {doc.text for doc in result}
    assert texts == {"About\nExternal", "About page"}

    assert mock_pinned_request.call_count == 2


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_load_data_accepts_list_input_and_adds_scheme(mock_pinned_request, mock_validate_url):
    mock_pinned_request.return_value = DummyResponse("<html><body>No links here</body></html>")
    crawler = CrawlerLoader()

    result = crawler.load_data(["example.com", "unused.com"])

    mock_pinned_request.assert_called_once_with("GET", "http://example.com", timeout=30)

    assert len(result) == 1
    assert result[0].text == "No links here"
    assert result[0].extra_info == {
        "source": "http://example.com",
        "file_path": "index.md",
    }


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_load_data_respects_limit(mock_pinned_request, mock_validate_url):
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

    mock_pinned_request.side_effect = lambda _method, url, timeout=30: responses[url]

    crawler = CrawlerLoader(limit=1)

    result = crawler.load_data("http://example.com")

    assert len(result) == 1
    assert result[0].text == "About"
    assert mock_pinned_request.call_count == 1


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.logging")
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_load_data_logs_and_skips_on_request_error(mock_pinned_request, mock_logging, mock_validate_url):
    mock_pinned_request.side_effect = Exception("load failure")
    crawler = CrawlerLoader()

    result = crawler.load_data("http://example.com")

    assert result == []
    mock_pinned_request.assert_called_once_with("GET", "http://example.com", timeout=30)

    mock_logging.error.assert_called_once()
    message, = mock_logging.error.call_args.args
    assert "Error processing URL http://example.com" in message
    assert mock_logging.error.call_args.kwargs.get("exc_info") is True


@patch("docsgpt.parser.remote.crawler_loader.validate_url")
def test_load_data_returns_empty_on_ssrf_validation_failure(mock_validate_url):
    """Test that SSRF validation failure returns empty list."""
    from docsgpt.core.url_validation import SSRFError
    mock_validate_url.side_effect = SSRFError("Access to private IP not allowed")

    crawler = CrawlerLoader()
    result = crawler.load_data("http://192.168.1.1")

    assert result == []
    mock_validate_url.assert_called_once()


def test_url_to_virtual_path_variants():
    crawler = CrawlerLoader()

    assert crawler._url_to_virtual_path("https://docs.docsgpt.cloud/") == "index.md"
    assert (
        crawler._url_to_virtual_path("https://docs.docsgpt.cloud/guides/setup")
        == "guides/setup.md"
    )
    assert (
        crawler._url_to_virtual_path("https://docs.docsgpt.cloud/guides/setup/")
        == "guides/setup.md"
    )
    assert crawler._url_to_virtual_path("https://example.com/page.html") == "page.md"


# =====================================================================
# Coverage gap tests  (lines 41-43)
# =====================================================================


@pytest.mark.unit
class TestCrawlerLoaderGaps:
    def test_pinned_fetch_builds_document_without_webbase_loader(self):
        """The crawler should index the response body it already fetched."""
        from docsgpt.parser.remote.crawler_loader import CrawlerLoader

        loader = CrawlerLoader(limit=5)
        with patch(
            "docsgpt.parser.remote.crawler_loader.validate_url",
            return_value="https://example.com",
        ):
            with patch(
                "docsgpt.parser.remote.crawler_loader.pinned_request"
            ) as mock_pinned_request:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = "<html><body>test</body></html>"
                mock_response.raise_for_status.return_value = None
                mock_pinned_request.return_value = mock_response

                result = loader.load_data("https://example.com")
                assert result[0].text == "test"


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_colliding_pages_get_distinct_file_paths(mock_pinned_request, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            "<html><body><a href='/a'>A</a><a href='/a.html'>A2</a>"
            "<a href='/l?page=2'>L</a></body></html>"
        ),
        "http://example.com/a": DummyResponse("<html><body>a</body></html>"),
        "http://example.com/a.html": DummyResponse("<html><body>a2</body></html>"),
        "http://example.com/l?page=2": DummyResponse("<html><body>l</body></html>"),
    }
    mock_pinned_request.side_effect = lambda _m, url, timeout=30: responses[url]

    result = CrawlerLoader(limit=10).load_data("http://example.com")

    paths = {doc.extra_info["source"]: doc.extra_info["file_path"] for doc in result}
    assert paths == {
        "http://example.com": "index.md",
        "http://example.com/a": "a.md",
        "http://example.com/a.html": "a-2.md",
        "http://example.com/l?page=2": "l__page=2.md",
    }


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_reordered_query_and_fragment_variants_are_fetched_once(mock_pinned_request, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            "<html><body><a href='/p?a=1&b=2'>P</a><a href='/p?b=2&a=1'>P2</a>"
            "<a href='/p?a=1&b=2#top'>P3</a></body></html>"
        ),
        "http://example.com/p?a=1&b=2": DummyResponse("<html><body>p</body></html>"),
        "http://example.com/p?b=2&a=1": DummyResponse("<html><body>p</body></html>"),
        "http://example.com/p?a=1&b=2#top": DummyResponse("<html><body>p</body></html>"),
    }
    mock_pinned_request.side_effect = lambda _m, url, timeout=30: responses[url]

    result = CrawlerLoader(limit=10).load_data("http://example.com")

    fetched = [c.args[1] for c in mock_pinned_request.call_args_list]
    assert fetched[0] == "http://example.com"
    assert len(fetched) == 2
    # The page is fetched as a link wrote it, not as its normalized key.
    assert fetched[1] in responses
    assert len(result) == 2


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_malformed_link_does_not_abort_the_crawl(mock_pinned_request, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            "<html><body><a href='http://[bad'>Bad</a><a href='/good'>Good</a></body></html>"
        ),
        "http://example.com/good": DummyResponse("<html><body>good</body></html>"),
    }
    mock_pinned_request.side_effect = lambda _m, url, timeout=30: responses[url]

    result = CrawlerLoader(limit=10).load_data("http://example.com")

    assert {d.extra_info["source"] for d in result} == {"http://example.com", "http://example.com/good"}


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.pinned_request")
def test_links_that_only_mention_the_site_are_not_crawled(mock_pinned_request, mock_validate_url):
    requested = []

    def response_side_effect(_method: str, url: str, timeout=30):
        requested.append(url)
        if url == "http://example.com":
            return DummyResponse(
                """
                <html><body>
                    <a href='/docs'>Docs</a>
                    <a href='https://twitter.com/share?url=http://example.com/docs'>Share</a>
                    <a href='http://example.com.evil.io/docs'>Lookalike</a>
                </body></html>
                """
            )
        return DummyResponse("<html><body>page</body></html>")

    mock_pinned_request.side_effect = response_side_effect

    result = CrawlerLoader(limit=5).load_data("http://example.com")

    assert sorted(requested) == ["http://example.com", "http://example.com/docs"]
    sources = {doc.extra_info.get("source") for doc in result}
    assert sources == {"http://example.com", "http://example.com/docs"}
