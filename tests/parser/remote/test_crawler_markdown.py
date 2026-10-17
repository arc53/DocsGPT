from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
import requests

from docsgpt.parser.remote.crawler_markdown import CrawlerLoader
from docsgpt.parser.schema.base import Document


class DummyResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def _fake_extract(value: str) -> SimpleNamespace:
    value = value.split("//")[-1]
    host = value.split("/")[0]
    parts = host.split(".")
    if len(parts) >= 2:
        domain = parts[-2]
        suffix = parts[-1]
    else:
        domain = host
        suffix = ""
    return SimpleNamespace(domain=domain, suffix=suffix)


def _mock_validate_url(url):
    """Mock validate_url that allows test URLs through."""
    if not urlparse(url).scheme:
        url = "http://" + url
    return url


@pytest.fixture(autouse=True)
def _patch_validate_url(monkeypatch):
    monkeypatch.setattr(
        "docsgpt.parser.remote.crawler_markdown.validate_url",
        _mock_validate_url,
    )


@pytest.fixture(autouse=True)
def _patch_tldextract(monkeypatch):
    monkeypatch.setattr(
        "docsgpt.parser.remote.crawler_markdown._extract",
        _fake_extract,
    )


@pytest.fixture(autouse=True)
def _patch_markdownify(monkeypatch):
    outputs = {}

    def fake_markdownify(html, *_, **__):
        return outputs.get(html, html)

    monkeypatch.setattr(
        "docsgpt.parser.remote.crawler_markdown.markdownify",
        fake_markdownify,
    )
    return outputs


def _patch_pinned_request(monkeypatch, side_effect):
    """Replace pinned_request with a stub that maps URL -> response or raises."""
    def fake_pinned_request(method, url, **_kwargs):
        return side_effect(url)

    monkeypatch.setattr(
        "docsgpt.parser.remote.crawler_markdown.pinned_request",
        fake_pinned_request,
    )


def test_load_data_filters_external_links(monkeypatch, _patch_markdownify):
    root_html = """
    <html><head><title>Home</title></head>
    <body><a href="/about">About</a><a href="https://other.com">Other</a><p>Welcome</p></body>
    </html>
    """
    about_html = "<html><head><title>About</title></head><body>About page</body></html>"

    _patch_markdownify[root_html] = "Home Markdown"
    _patch_markdownify[about_html] = "About Markdown"

    responses = {
        "http://example.com": DummyResponse(root_html),
        "http://example.com/about": DummyResponse(about_html),
    }

    _patch_pinned_request(monkeypatch, lambda url: responses[url])

    loader = CrawlerLoader(limit=5)

    docs = loader.load_data("http://example.com")

    assert len(docs) == 2
    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.extra_info["source"] in responses
    texts = {doc.text for doc in docs}
    assert texts == {"Home Markdown", "About Markdown"}


def test_load_data_allows_subdomains(monkeypatch, _patch_markdownify):
    root_html = """
    <html><head><title>Home</title></head>
    <body><a href="http://blog.example.com/post">Blog</a></body>
    </html>
    """
    blog_html = "<html><head><title>Blog</title></head><body>Blog post</body></html>"

    _patch_markdownify[root_html] = "Home Markdown"
    _patch_markdownify[blog_html] = "Blog Markdown"

    responses = {
        "http://example.com": DummyResponse(root_html),
        "http://blog.example.com/post": DummyResponse(blog_html),
    }

    _patch_pinned_request(monkeypatch, lambda url: responses[url])

    loader = CrawlerLoader(limit=5, allow_subdomains=True)

    docs = loader.load_data("http://example.com")

    sources = {doc.extra_info["source"] for doc in docs}
    assert "http://blog.example.com/post" in sources
    assert len(docs) == 2


def test_load_data_handles_fetch_errors(monkeypatch, _patch_markdownify, _patch_validate_url):
    root_html = """
    <html><head><title>Home</title></head>
    <body><a href="/about">About</a></body>
    </html>
    """

    _patch_markdownify[root_html] = "Home Markdown"

    def side_effect(url):
        if url == "http://example.com":
            return DummyResponse(root_html)
        raise requests.exceptions.RequestException("boom")

    _patch_pinned_request(monkeypatch, side_effect)

    loader = CrawlerLoader(limit=5)
    mock_print = MagicMock()
    monkeypatch.setattr("builtins.print", mock_print)

    docs = loader.load_data("http://example.com")

    assert len(docs) == 1
    assert docs[0].text == "Home Markdown"
    assert mock_print.called


def test_load_data_returns_empty_on_ssrf_validation_failure(monkeypatch):
    """Test that SSRF validation failure returns empty list."""
    from docsgpt.core.url_validation import SSRFError

    def raise_ssrf_error(url):
        raise SSRFError("Access to private IP not allowed")

    monkeypatch.setattr(
        "docsgpt.parser.remote.crawler_markdown.validate_url",
        raise_ssrf_error,
    )

    loader = CrawlerLoader()
    result = loader.load_data("http://192.168.1.1")

    assert result == []



def test_colliding_pages_get_distinct_file_paths(monkeypatch, _patch_markdownify):
    root_html = (
        "<html><head><title>Home</title></head><body>"
        "<a href='/a'>A</a><a href='/a.html'>A2</a><a href='/l?page=2'>L</a>"
        "</body></html>"
    )
    responses = {
        "http://example.com": DummyResponse(root_html),
        "http://example.com/a": DummyResponse("<html><body>a</body></html>"),
        "http://example.com/a.html": DummyResponse("<html><body>a2</body></html>"),
        "http://example.com/l?page=2": DummyResponse("<html><body>l</body></html>"),
    }
    _patch_pinned_request(monkeypatch, lambda url: responses[url])

    docs = CrawlerLoader(limit=10).load_data("http://example.com")

    paths = {doc.extra_info["source"]: doc.extra_info["file_path"] for doc in docs}
    assert paths == {
        "http://example.com": "index.md",
        "http://example.com/a": "a.md",
        "http://example.com/a.html": "a-2.md",
        "http://example.com/l?page=2": "l__page=2.md",
    }


def test_reordered_query_and_fragment_variants_are_fetched_once(monkeypatch, _patch_markdownify):
    root_html = (
        "<html><head><title>Home</title></head><body>"
        "<a href='/p?a=1&b=2'>P</a><a href='/p?b=2&a=1'>P2</a><a href='/p?a=1&b=2#top'>P3</a>"
        "</body></html>"
    )
    page_html = "<html><body>p</body></html>"
    responses = {
        "http://example.com": DummyResponse(root_html),
        "http://example.com/p?a=1&b=2": DummyResponse(page_html),
        "http://example.com/p?b=2&a=1": DummyResponse(page_html),
        "http://example.com/p?a=1&b=2#top": DummyResponse(page_html),
    }
    fetched = []

    def side_effect(url):
        fetched.append(url)
        return responses[url]

    _patch_pinned_request(monkeypatch, side_effect)

    docs = CrawlerLoader(limit=10).load_data("http://example.com")

    assert len(fetched) == 2
    assert fetched[0] == "http://example.com"
    # The page is fetched as a link wrote it, not as its normalized key.
    assert fetched[1] in responses
    assert len(docs) == 2


def test_malformed_link_does_not_abort_the_crawl(monkeypatch, _patch_markdownify):
    root_html = (
        "<html><head><title>Home</title></head><body>"
        "<a href='http://[bad'>Bad</a><a href='/good'>Good</a></body></html>"
    )
    responses = {
        "http://example.com": DummyResponse(root_html),
        "http://example.com/good": DummyResponse("<html><body>good</body></html>"),
    }
    _patch_pinned_request(monkeypatch, lambda url: responses[url])

    docs = CrawlerLoader(limit=10).load_data("http://example.com")

    assert {d.extra_info["source"] for d in docs} == {"http://example.com", "http://example.com/good"}
