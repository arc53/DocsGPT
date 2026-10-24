from unittest.mock import patch
from urllib.parse import urlparse

import pytest

from docsgpt.core.url_validation import SSRFError
from docsgpt.parser.remote import crawler_loader
from docsgpt.parser.remote.crawler_loader import CrawlerLoader
from docsgpt.parser.remote.website_loader import SiteScope
from docsgpt.parser.schema.base import Document


class DummyResponse:
    def __init__(self, text: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.text = text
        self.content = text.encode()
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


class _BytesResponse:
    """A fetched response with raw bytes and, for a redirect, the address it landed on."""

    def __init__(self, content: bytes, content_type: str = "text/html", url: str = "") -> None:
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.url = url

    def raise_for_status(self) -> None:
        return None


def _mock_validate_url(url):
    """Mock validate_url that allows test URLs through."""
    if not urlparse(url).scheme:
        url = "http://" + url
    return url


def _crawl(responses: dict, start="http://example.com/", limit=10, accept=None):
    """Crawl a fake site from ``start``, its scope the start page's site unless ``accept`` says otherwise.

    Args:
        responses: URL -> response (a ``DummyResponse``, or HTML for one); any other URL fails the test.
        start: The start address (or a list whose first item is).
        limit: The crawl's page limit.
        accept: The crawl's scope; ``None`` for ``SiteScope`` of the start page.

    Returns:
        ``(docs, fetched, crawler)``: the documents, the URLs fetched in order, and the loader.
    """
    fetched = []

    def fetch(url: str, *_, **kwargs):
        fetched.append(url)
        assert kwargs == {"timeout": 30, "budget": None}
        if url not in responses:
            raise AssertionError(f"Unexpected request for URL: {url}")
        response = responses[url]
        return DummyResponse(response) if isinstance(response, str) else response

    first = start[0] if isinstance(start, list) else start
    crawler = CrawlerLoader(accept or SiteScope(_mock_validate_url(first)).accepts, limit=limit)
    with patch.object(crawler_loader, "validate_url", side_effect=_mock_validate_url), \
            patch.object(crawler_loader, "fetch_page", side_effect=fetch):
        docs = crawler.load_data(start)
    return docs, fetched, crawler


def sources(docs):
    return [doc.extra_info["source"] for doc in docs]


def test_load_data_crawls_same_domain_links():
    docs, fetched, _ = _crawl({
        "http://example.com": "<html><body><a href='/about'>About</a>"
                              "<a href='https://external.com/news'>External</a></body></html>",
        "http://example.com/about": "<html><body>About page</body></html>",
    }, start="http://example.com", limit=5)

    assert all(isinstance(doc, Document) for doc in docs)
    assert sources(docs) == ["http://example.com", "http://example.com/about"]
    assert [doc.extra_info["file_path"] for doc in docs] == ["index.md", "about.md"]
    # Side-by-side links read as a list, not as glued text.
    assert [doc.text for doc in docs] == ["* About\n* External", "About page"]
    assert fetched == ["http://example.com", "http://example.com/about"]


def test_load_data_accepts_list_input_and_adds_scheme():
    docs, fetched, _ = _crawl(
        {"http://example.com": "<html><body>No links here</body></html>"}, start=["example.com", "unused.com"],
    )

    assert fetched == ["http://example.com"]
    assert [doc.text for doc in docs] == ["No links here"]
    assert docs[0].extra_info == {"source": "http://example.com", "file_path": "index.md", "requested_urls": []}


def test_load_data_respects_limit():
    docs, fetched, crawler = _crawl({
        "http://example.com": "<html><body><a href='/about'>About</a></body></html>",
        "http://example.com/about": "<html><body>About</body></html>",
    }, start="http://example.com", limit=1)

    assert [doc.text for doc in docs] == ["About"]
    assert fetched == ["http://example.com"]
    assert crawler.limit_reached is True


@patch("docsgpt.parser.remote.crawler_loader.logging")
def test_load_data_logs_and_skips_on_request_error(mock_logging):
    def fail(url, *_, **__):
        raise Exception("load failure")

    with patch.object(crawler_loader, "validate_url", side_effect=_mock_validate_url), \
            patch.object(crawler_loader, "fetch_page", side_effect=fail):
        result = CrawlerLoader(lambda url: True).load_data("http://example.com")

    assert result == []
    mock_logging.error.assert_called_once()
    message, = mock_logging.error.call_args.args
    assert "Error processing URL http://example.com" in message
    assert mock_logging.error.call_args.kwargs.get("exc_info") is True


@patch("docsgpt.parser.remote.crawler_loader.fetch_page")
@patch("docsgpt.parser.remote.crawler_loader.validate_url", side_effect=SSRFError("Access to private IP not allowed"))
def test_load_data_returns_empty_on_ssrf_validation_failure(mock_validate_url, mock_fetch):
    assert CrawlerLoader(lambda url: True).load_data("http://192.168.1.1") == []
    mock_validate_url.assert_called_once()
    mock_fetch.assert_not_called()


def test_colliding_pages_get_distinct_file_paths():
    docs, _, _ = _crawl({
        "http://example.com": "<html><body><a href='/a'>A</a><a href='/a.html'>A2</a>"
                              "<a href='/l?page=2'>L</a></body></html>",
        "http://example.com/a": "<html><body>a</body></html>",
        "http://example.com/a.html": "<html><body>a2</body></html>",
        "http://example.com/l?page=2": "<html><body>l</body></html>",
    }, start="http://example.com")

    assert {doc.extra_info["source"]: doc.extra_info["file_path"] for doc in docs} == {
        "http://example.com": "index.md",
        "http://example.com/a": "a.md",
        "http://example.com/a.html": "a-2.md",
        "http://example.com/l?page=2": "l__page=2.md",
    }


def test_reordered_query_and_fragment_variants_are_fetched_once():
    responses = {
        "http://example.com": "<html><body><a href='/p?a=1&b=2'>P</a><a href='/p?b=2&a=1'>P2</a>"
                              "<a href='/p?a=1&b=2#top'>P3</a></body></html>",
        "http://example.com/p?a=1&b=2": "<html><body>p</body></html>",
        "http://example.com/p?b=2&a=1": "<html><body>p</body></html>",
        "http://example.com/p?a=1&b=2#top": "<html><body>p</body></html>",
    }
    docs, fetched, _ = _crawl(responses, start="http://example.com")

    assert fetched[0] == "http://example.com"
    assert len(fetched) == 2
    # The page is fetched as a link wrote it, not as its normalized key.
    assert fetched[1] in responses
    assert len(docs) == 2


def test_malformed_link_does_not_abort_the_crawl():
    docs, _, _ = _crawl({
        "http://example.com": "<html><body><a href='http://[bad'>Bad</a><a href='/good'>Good</a></body></html>",
        "http://example.com/good": "<html><body>good</body></html>",
    }, start="http://example.com")

    assert sources(docs) == ["http://example.com", "http://example.com/good"]


def test_links_that_only_mention_the_site_are_not_crawled():
    docs, fetched, _ = _crawl({
        "http://example.com": """
            <html><body>
                <a href='/docs'>Docs</a>
                <a href='https://twitter.com/share?url=http://example.com/docs'>Share</a>
                <a href='http://example.com.evil.io/docs'>Lookalike</a>
            </body></html>
        """,
        "http://example.com/docs": "<html><body>page</body></html>",
    }, start="http://example.com", limit=5)

    assert fetched == ["http://example.com", "http://example.com/docs"]
    assert sources(docs) == ["http://example.com", "http://example.com/docs"]


def test_a_capped_crawl_takes_pages_breadth_first_in_link_order():
    links = "".join(f"<p><a href='/p{i}'>P{i}</a></p>" for i in range(12))
    pages = {"http://example.com": f"<html><body>{links}</body></html>"}
    pages.update({
        f"http://example.com/p{i}": f"<html><body><a href='/deep{i}'>Page {i}</a></body></html>" for i in range(12)
    })

    docs, _, crawler = _crawl(pages, start="http://example.com", limit=4)

    assert sources(docs) == [
        "http://example.com", "http://example.com/p0", "http://example.com/p1", "http://example.com/p2",
    ]
    assert crawler.limit_reached is True


def test_slash_www_and_scheme_variants_are_one_page():
    variants = ["/a", "/a/", "http://www.example.com/a", "https://example.com/a/", "/b"]
    anchors = "".join(f"<p><a href='{href}'>link {i}</a></p>" for i, href in enumerate(variants))

    docs, fetched, _ = _crawl({
        "http://example.com": f"<html><body>{anchors}</body></html>",
        "http://example.com/a": "<html><body>A</body></html>",
        "http://example.com/b": "<html><body>B</body></html>",
    }, start="http://example.com", limit=3, accept=lambda url: True)

    assert sources(docs) == ["http://example.com", "http://example.com/a", "http://example.com/b"]
    assert len(fetched) == 3


def test_the_queue_of_pages_to_visit_is_capped():
    links = "".join(f"<a href='/p{i}'>P{i}</a> " for i in range(500))
    pages = {"http://example.com": f"<html><body><p>{links}</p></body></html>"}
    pages.update({f"http://example.com/p{i}": "<html><body>Leaf</body></html>" for i in range(500)})
    considered = []

    def accept(url):
        considered.append(url)
        return True

    with patch.object(crawler_loader, "_QUEUE_PER_PAGE", 2):
        _, _, crawler = _crawl(pages, start="http://example.com", limit=5, accept=accept)

    # Five pages may queue ten links; the rest are dropped, not held.
    assert len(considered) <= 1 + 10
    assert crawler.limit_reached is True


def test_a_crawl_stays_on_the_start_page_port():
    docs, fetched, _ = _crawl({
        "http://example.com": "<html><body><p><a href='http://example.com:8080/admin'>Admin</a></p>"
                              "<p><a href='http://example.com:80/a'>A</a></p></body></html>",
        "http://example.com:80/a": "<html><body>A</body></html>",
    }, start="http://example.com", limit=5)

    assert sources(docs) == ["http://example.com", "http://example.com:80/a"]
    assert fetched == ["http://example.com", "http://example.com:80/a"]


def test_links_are_read_in_the_header_charset():
    # No <meta charset>: only the Content-Type says the bytes are ISO-8859-2.
    home = "<html><body><p>Start</p><p><a href='/zażółć'>Zażółć</a></p></body></html>".encode("iso-8859-2")

    docs, _, _ = _crawl({
        "http://example.com": _BytesResponse(home, "text/html; charset=iso-8859-2"),
        "http://example.com/zażółć": _BytesResponse(b"<html><body>Leaf</body></html>"),
    }, start="http://example.com", limit=5)

    assert sources(docs) == ["http://example.com", "http://example.com/zażółć"]


NAV = "<nav><ul><li><a href='/docs/a'>Guide A</a></li><li><a href='/docs/b'>Guide B</a></li></ul></nav>"


def _guide(name: str) -> DummyResponse:
    return DummyResponse(f"<html><body><main><h1>Guide {name}</h1><p>Real text of guide {name}.</p></main></body></html>")


@pytest.mark.parametrize("chrome", [
    NAV,
    NAV.replace("nav>", "header>"),
    NAV.replace("nav>", "footer>"),
    NAV.replace("<nav>", "<div role='navigation'>").replace("</nav>", "</div>"),
    NAV.replace("nav>", "aside>"),
])
def test_a_start_page_of_only_menus_still_leads_to_its_links(chrome):
    # Its extract is empty, so it isn't a document; its links are still followed.
    docs, fetched, _ = _crawl({
        "http://example.com/": f"<html><body>{chrome}</body></html>",
        "http://example.com/docs/a": _guide("A"),
        "http://example.com/docs/b": _guide("B"),
    })

    assert sources(docs) == ["http://example.com/docs/a", "http://example.com/docs/b"]
    assert fetched == ["http://example.com/", "http://example.com/docs/a", "http://example.com/docs/b"]


def test_a_menu_only_hub_does_not_cut_off_the_pages_below_it():
    docs, _, _ = _crawl({
        "http://example.com/":
            "<html><body><main><h1>Welcome</h1><p>Intro text. See the <a href='/hub'>hub</a>.</p></main></body></html>",
        "http://example.com/hub": f"<html><body>{NAV}</body></html>",
        "http://example.com/docs/a": _guide("A"),
        "http://example.com/docs/b": _guide("B"),
    })

    assert sources(docs) == ["http://example.com/", "http://example.com/docs/a", "http://example.com/docs/b"]


def test_a_page_whose_extraction_fails_still_leads_to_its_links():
    real = crawler_loader.page_document

    def page_document(body, content_type, url, **kwargs):
        if url == "http://example.com/":
            raise RuntimeError("extractor bug")
        return real(body, content_type, url, **kwargs)

    with patch.object(crawler_loader, "page_document", side_effect=page_document):
        docs, _, _ = _crawl({
            "http://example.com/": f"<html><body><p>Text</p>{NAV}</body></html>",
            "http://example.com/docs/a": _guide("A"),
            "http://example.com/docs/b": _guide("B"),
        })

    assert sources(docs) == ["http://example.com/docs/a", "http://example.com/docs/b"]


def test_a_non_html_page_that_fails_to_extract_is_still_skipped():
    with patch.object(crawler_loader, "page_document", side_effect=RuntimeError("bad text")):
        docs, fetched, _ = _crawl(
            {"http://example.com/notes.txt": DummyResponse("[a](/docs/a)", "text/plain")},
            start="http://example.com/notes.txt",
        )

    assert docs == []
    assert fetched == ["http://example.com/notes.txt"]


@pytest.mark.parametrize("base, linked", [
    ("/docs/", "http://example.com/docs/a"),
    # Not a web address: links resolve against the page itself.
    ("javascript:void(0)", "http://example.com/a"),
])
def test_links_resolve_against_the_page_base_href(base, linked):
    _, fetched, _ = _crawl({
        "http://example.com/": f"<html><head><base href='{base}'></head><body><main><h1>Home</h1>"
                               "<p>Read the <a href='a'>guide</a>.</p></main></body></html>",
        linked: _guide("A"),
    })

    assert fetched == ["http://example.com/", linked]


def test_an_href_with_surrounding_whitespace_is_read_without_it():
    # Browsers strip it: ``/a `` is ``/a``, not ``/a%20``.
    _, fetched, _ = _crawl({
        "http://example.com/":
            "<html><body><main><h1>Home</h1><p>Read <a href=' /a \n'>A</a>.</p></main></body></html>",
        "http://example.com/a": _guide("A"),
    })

    assert fetched == ["http://example.com/", "http://example.com/a"]


def test_a_crawled_page_is_stored_without_the_link_fragment():
    docs, fetched, _ = _crawl({
        "http://example.com/":
            "<html><body><main><h1>Home</h1><p>Read <a href='/a#install'>A</a>.</p></main></body></html>",
        "http://example.com/a": _guide("A"),
    })

    assert fetched == ["http://example.com/", "http://example.com/a"]
    assert docs[-1].extra_info["source"] == "http://example.com/a"
    assert docs[-1].extra_info["requested_urls"] == []
