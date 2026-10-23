from unittest.mock import patch

import pytest

from docsgpt.parser.remote.crawler_loader import CrawlerLoader
from docsgpt.parser.schema.base import Document


class DummyResponse:
    def __init__(self, text: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.text = text
        self.content = text.encode()
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


def _mock_validate_url(url):
    """Mock validate_url that allows test URLs through."""
    from urllib.parse import urlparse
    if not urlparse(url).scheme:
        url = "http://" + url
    return url


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_load_data_crawls_same_domain_links(mock_fetch, mock_validate_url):
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

    def response_side_effect(url: str, *_, **__):
        if url not in responses:
            raise AssertionError(f"Unexpected request for URL: {url}")
        return responses[url]

    mock_fetch.side_effect = response_side_effect

    crawler = CrawlerLoader(limit=5)

    result = crawler.load_data("http://example.com")

    assert len(result) == 2
    assert all(isinstance(doc, Document) for doc in result)

    sources = {doc.extra_info.get("source") for doc in result}
    assert sources == {"http://example.com", "http://example.com/about"}

    paths = {doc.extra_info.get("file_path") for doc in result}
    assert paths == {"index.md", "about.md"}

    # Side-by-side links read as a list, not as glued text.
    texts = {doc.text for doc in result}
    assert texts == {"* About\n* External", "About page"}

    assert mock_fetch.call_count == 2


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_load_data_accepts_list_input_and_adds_scheme(mock_fetch, mock_validate_url):
    mock_fetch.return_value = DummyResponse("<html><body>No links here</body></html>")
    crawler = CrawlerLoader()

    result = crawler.load_data(["example.com", "unused.com"])

    mock_fetch.assert_called_once_with("http://example.com", timeout=30, budget=None)

    assert len(result) == 1
    assert result[0].text == "No links here"
    assert result[0].extra_info == {
        "source": "http://example.com",
        "file_path": "index.md",
        "requested_urls": [],
    }


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_load_data_respects_limit(mock_fetch, mock_validate_url):
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

    mock_fetch.side_effect = lambda url, *_, **__: responses[url]

    crawler = CrawlerLoader(limit=1)

    result = crawler.load_data("http://example.com")

    assert len(result) == 1
    assert result[0].text == "About"
    assert mock_fetch.call_count == 1


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.logging")
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_load_data_logs_and_skips_on_request_error(mock_fetch, mock_logging, mock_validate_url):
    mock_fetch.side_effect = Exception("load failure")
    crawler = CrawlerLoader()

    result = crawler.load_data("http://example.com")

    assert result == []
    mock_fetch.assert_called_once_with("http://example.com", timeout=30, budget=None)

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
                "docsgpt.parser.remote.crawler_loader.fetch_page"
            ) as mock_fetch:
                mock_fetch.return_value = DummyResponse("<html><body>test</body></html>")

                result = loader.load_data("https://example.com")
                assert result[0].text == "test"


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_colliding_pages_get_distinct_file_paths(mock_fetch, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            "<html><body><a href='/a'>A</a><a href='/a.html'>A2</a>"
            "<a href='/l?page=2'>L</a></body></html>"
        ),
        "http://example.com/a": DummyResponse("<html><body>a</body></html>"),
        "http://example.com/a.html": DummyResponse("<html><body>a2</body></html>"),
        "http://example.com/l?page=2": DummyResponse("<html><body>l</body></html>"),
    }
    mock_fetch.side_effect = lambda url, *_, **__: responses[url]

    result = CrawlerLoader(limit=10).load_data("http://example.com")

    paths = {doc.extra_info["source"]: doc.extra_info["file_path"] for doc in result}
    assert paths == {
        "http://example.com": "index.md",
        "http://example.com/a": "a.md",
        "http://example.com/a.html": "a-2.md",
        "http://example.com/l?page=2": "l__page=2.md",
    }


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_reordered_query_and_fragment_variants_are_fetched_once(mock_fetch, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            "<html><body><a href='/p?a=1&b=2'>P</a><a href='/p?b=2&a=1'>P2</a>"
            "<a href='/p?a=1&b=2#top'>P3</a></body></html>"
        ),
        "http://example.com/p?a=1&b=2": DummyResponse("<html><body>p</body></html>"),
        "http://example.com/p?b=2&a=1": DummyResponse("<html><body>p</body></html>"),
        "http://example.com/p?a=1&b=2#top": DummyResponse("<html><body>p</body></html>"),
    }
    mock_fetch.side_effect = lambda url, *_, **__: responses[url]

    result = CrawlerLoader(limit=10).load_data("http://example.com")

    fetched = [c.args[0] for c in mock_fetch.call_args_list]
    assert fetched[0] == "http://example.com"
    assert len(fetched) == 2
    # The page is fetched as a link wrote it, not as its normalized key.
    assert fetched[1] in responses
    assert len(result) == 2


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_malformed_link_does_not_abort_the_crawl(mock_fetch, mock_validate_url):
    responses = {
        "http://example.com": DummyResponse(
            "<html><body><a href='http://[bad'>Bad</a><a href='/good'>Good</a></body></html>"
        ),
        "http://example.com/good": DummyResponse("<html><body>good</body></html>"),
    }
    mock_fetch.side_effect = lambda url, *_, **__: responses[url]

    result = CrawlerLoader(limit=10).load_data("http://example.com")

    assert {d.extra_info["source"] for d in result} == {"http://example.com", "http://example.com/good"}


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_links_that_only_mention_the_site_are_not_crawled(mock_fetch, mock_validate_url):
    requested = []

    def response_side_effect(url: str, *_, **__):
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

    mock_fetch.side_effect = response_side_effect

    result = CrawlerLoader(limit=5).load_data("http://example.com")

    assert sorted(requested) == ["http://example.com", "http://example.com/docs"]
    sources = {doc.extra_info.get("source") for doc in result}
    assert sources == {"http://example.com", "http://example.com/docs"}


def _site(pages):
    """A ``fetch_page`` stand-in answering from a URL -> HTML map; others raise."""

    def fetch(url, *_, **__):
        if url not in pages:
            raise AssertionError(f"Unexpected request for URL: {url}")
        return DummyResponse(pages[url])

    return fetch


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_a_capped_crawl_takes_pages_breadth_first_in_link_order(mock_fetch, mock_validate_url):
    links = "".join(f"<p><a href='/p{i}'>P{i}</a></p>" for i in range(12))
    pages = {"http://example.com": f"<html><body>{links}</body></html>"}
    pages.update({
        f"http://example.com/p{i}": f"<html><body><a href='/deep{i}'>Page {i}</a></body></html>" for i in range(12)
    })
    mock_fetch.side_effect = _site(pages)

    crawler = CrawlerLoader(limit=4)
    result = crawler.load_data("http://example.com")

    assert [doc.extra_info["source"] for doc in result] == [
        "http://example.com", "http://example.com/p0", "http://example.com/p1", "http://example.com/p2",
    ]
    assert crawler.limit_reached is True


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_slash_www_and_scheme_variants_are_one_page(mock_fetch, mock_validate_url):
    variants = ["/a", "/a/", "http://www.example.com/a", "https://example.com/a/", "/b"]
    anchors = "".join(f"<p><a href='{href}'>link {i}</a></p>" for i, href in enumerate(variants))
    mock_fetch.side_effect = _site({
        "http://example.com": f"<html><body>{anchors}</body></html>",
        "http://example.com/a": "<html><body>A</body></html>",
        "http://example.com/b": "<html><body>B</body></html>",
    })

    result = CrawlerLoader(limit=3, accept=lambda url: True).load_data("http://example.com")

    assert [doc.extra_info["source"] for doc in result] == [
        "http://example.com", "http://example.com/a", "http://example.com/b",
    ]
    assert mock_fetch.call_count == 3


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_the_queue_of_pages_to_visit_is_capped(mock_fetch, mock_validate_url):
    from docsgpt.parser.remote import crawler_loader

    links = "".join(f"<a href='/p{i}'>P{i}</a> " for i in range(500))
    pages = {"http://example.com": f"<html><body><p>{links}</p></body></html>"}
    pages.update({f"http://example.com/p{i}": "<html><body>Leaf</body></html>" for i in range(500)})
    mock_fetch.side_effect = _site(pages)

    considered = []

    def accept(url):
        considered.append(url)
        return True

    with patch.object(crawler_loader, "_QUEUE_PER_PAGE", 2):
        crawler = CrawlerLoader(limit=5, accept=accept)
        crawler.load_data("http://example.com")

    # Five pages may queue ten links; the rest are dropped, not held.
    assert len(considered) <= 1 + 10
    assert crawler.limit_reached is True


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_a_crawl_stays_on_the_start_page_port(mock_fetch, mock_validate_url):
    mock_fetch.side_effect = _site({
        "http://example.com": "<html><body><p><a href='http://example.com:8080/admin'>Admin</a></p>"
                              "<p><a href='http://example.com:80/a'>A</a></p></body></html>",
        "http://example.com:80/a": "<html><body>A</body></html>",
    })

    result = CrawlerLoader(limit=5).load_data("http://example.com")

    assert [doc.extra_info["source"] for doc in result] == ["http://example.com", "http://example.com:80/a"]
    assert [c.args[0] for c in mock_fetch.call_args_list] == ["http://example.com", "http://example.com:80/a"]


class _BytesResponse:
    """A fetched response with raw bytes and, for a redirect, the address it landed on."""

    def __init__(self, content: bytes, content_type: str = "text/html", url: str = "") -> None:
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.url = url

    def raise_for_status(self) -> None:
        return None


@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url)
@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
def test_links_are_read_in_the_header_charset(mock_fetch, mock_validate_url):
    # No <meta charset>: only the Content-Type says the bytes are ISO-8859-2.
    home = "<html><body><p>Start</p><p><a href='/zażółć'>Zażółć</a></p></body></html>".encode("iso-8859-2")
    pages = {
        "http://example.com": _BytesResponse(home, "text/html; charset=iso-8859-2"),
        "http://example.com/zażółć": _BytesResponse(b"<html><body>Leaf</body></html>"),
    }
    mock_fetch.side_effect = lambda url, *_, **__: pages[url]

    result = CrawlerLoader(limit=5).load_data("http://example.com")

    assert [doc.extra_info["source"] for doc in result] == ["http://example.com", "http://example.com/zażółć"]


NAV = "<nav><ul><li><a href='/docs/a'>Guide A</a></li><li><a href='/docs/b'>Guide B</a></li></ul></nav>"


def _guide(name: str) -> DummyResponse:
    return DummyResponse(f"<html><body><main><h1>Guide {name}</h1><p>Real text of guide {name}.</p></main></body></html>")


def _crawl(responses: dict, start: str = "http://example.com/"):
    fetched = []

    def fetch(url: str, *_, **__):
        fetched.append(url)
        if url not in responses:
            raise AssertionError(f"Unexpected request for URL: {url}")
        return responses[url]

    with patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=_mock_validate_url), \
            patch("docsgpt.parser.remote.crawler_loader.fetch_page", side_effect=fetch):
        docs = CrawlerLoader(limit=10).load_data(start)
    return docs, fetched


@pytest.mark.parametrize("chrome", [
    NAV,
    NAV.replace("nav>", "header>"),
    NAV.replace("nav>", "footer>"),
    NAV.replace("<nav>", "<div role='navigation'>").replace("</nav>", "</div>"),
    NAV.replace("nav>", "aside>"),
])
def test_a_start_page_of_only_menus_still_leads_to_its_links(chrome):
    # Its extract is empty, so it isn't a document; its links are still followed.
    docs, fetched = _crawl({
        "http://example.com/": DummyResponse(f"<html><body>{chrome}</body></html>"),
        "http://example.com/docs/a": _guide("A"),
        "http://example.com/docs/b": _guide("B"),
    })

    assert [doc.extra_info["source"] for doc in docs] == ["http://example.com/docs/a", "http://example.com/docs/b"]
    assert fetched == ["http://example.com/", "http://example.com/docs/a", "http://example.com/docs/b"]


def test_a_menu_only_hub_does_not_cut_off_the_pages_below_it():
    docs, _ = _crawl({
        "http://example.com/": DummyResponse(
            "<html><body><main><h1>Welcome</h1><p>Intro text. See the <a href='/hub'>hub</a>.</p></main></body></html>"
        ),
        "http://example.com/hub": DummyResponse(f"<html><body>{NAV}</body></html>"),
        "http://example.com/docs/a": _guide("A"),
        "http://example.com/docs/b": _guide("B"),
    })

    assert [doc.extra_info["source"] for doc in docs] == [
        "http://example.com/", "http://example.com/docs/a", "http://example.com/docs/b",
    ]


def test_a_page_whose_extraction_fails_still_leads_to_its_links():
    from docsgpt.parser.remote import crawler_loader

    real = crawler_loader.page_document

    def page_document(body, content_type, url, **kwargs):
        if url == "http://example.com/":
            raise RuntimeError("extractor bug")
        return real(body, content_type, url, **kwargs)

    with patch.object(crawler_loader, "page_document", side_effect=page_document):
        docs, _ = _crawl({
            "http://example.com/": DummyResponse(f"<html><body><p>Text</p>{NAV}</body></html>"),
            "http://example.com/docs/a": _guide("A"),
            "http://example.com/docs/b": _guide("B"),
        })

    assert [doc.extra_info["source"] for doc in docs] == ["http://example.com/docs/a", "http://example.com/docs/b"]


def test_a_non_html_page_that_fails_to_extract_is_still_skipped():
    from docsgpt.parser.remote import crawler_loader

    with patch.object(crawler_loader, "page_document", side_effect=RuntimeError("bad text")):
        docs, fetched = _crawl(
            {"http://example.com/notes.txt": DummyResponse("[a](/docs/a)", "text/plain")},
            start="http://example.com/notes.txt",
        )

    assert docs == []
    assert fetched == ["http://example.com/notes.txt"]
