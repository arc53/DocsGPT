from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from application.parser.remote.crawler_markdown import CrawlerLoader
from application.parser.schema.base import Document


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


@pytest.fixture(autouse=True)
def _patch_tldextract(monkeypatch):
    monkeypatch.setattr(
        "application.parser.remote.crawler_markdown.tldextract.extract",
        _fake_extract,
    )


@pytest.fixture(autouse=True)
def _patch_markdownify(monkeypatch):
    outputs = {}

    def fake_markdownify(html, *_, **__):
        return outputs.get(html, html)

    monkeypatch.setattr(
        "application.parser.remote.crawler_markdown.markdownify",
        fake_markdownify,
    )
    return outputs


def _setup_session(mock_get_side_effect):
    session = MagicMock()
    session.get.side_effect = mock_get_side_effect
    return session


def test_load_data_filters_external_links(_patch_markdownify):
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

    loader = CrawlerLoader(limit=5)
    loader.session = _setup_session(lambda url, timeout=10: responses[url])

    docs = loader.load_data("http://example.com")

    assert len(docs) == 2
    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.extra_info["source"] in responses
    texts = {doc.text for doc in docs}
    assert texts == {"Home Markdown", "About Markdown"}


def test_load_data_allows_subdomains(_patch_markdownify):
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

    loader = CrawlerLoader(limit=5, allow_subdomains=True)
    loader.session = _setup_session(lambda url, timeout=10: responses[url])

    docs = loader.load_data("http://example.com")

    sources = {doc.extra_info["source"] for doc in docs}
    assert "http://blog.example.com/post" in sources
    assert len(docs) == 2


def test_load_data_handles_fetch_errors(monkeypatch, _patch_markdownify):
    root_html = """
    <html><head><title>Home</title></head>
    <body><a href="/about">About</a></body>
    </html>
    """

    _patch_markdownify[root_html] = "Home Markdown"

    def side_effect(url, timeout=10):
        if url == "http://example.com":
            return DummyResponse(root_html)
        raise requests.exceptions.RequestException("boom")

    loader = CrawlerLoader(limit=5)
    loader.session = _setup_session(side_effect)
    mock_print = MagicMock()
    monkeypatch.setattr("builtins.print", mock_print)

    docs = loader.load_data("http://example.com")

    assert len(docs) == 1
    assert docs[0].text == "Home Markdown"
    assert mock_print.called

