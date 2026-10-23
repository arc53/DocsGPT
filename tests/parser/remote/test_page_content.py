"""Tests for the shared web page extractor (main content → Markdown)."""

import io
import re
import socket
import time
from unittest.mock import patch

import pytest
import requests

from docsgpt.parser.remote.page_content import (
    FetchBudget,
    RedirectError,
    _listify_link_runs,
    _strip_chrome,
    extract_page,
    fetch_page,
    html_soup,
    page_document,
)

URL = "https://docs.example.com/guide/setup"


def _page(body: str, head: str = "<title>Setup | Example</title>", lang: str = "en") -> str:
    return f"<!doctype html><html lang='{lang}'><head>{head}</head><body>{body}</body></html>"


SITE_CHROME = (
    "<header><a href='/'>Example</a><nav><a href='/a'>Home</a><a href='/b'>Docs</a></nav></header>"
    "<nav aria-label='sidebar'><ul><li><a href='/x'>Sidebar one</a></li>"
    "<li><a href='/y'>Sidebar two</a></li></ul></nav>"
)
FOOTER = "<footer>Copyright Example Inc. <a href='/privacy'>Privacy</a></footer>"
ARTICLE = (
    "<h1>Setup guide</h1>"
    "<p>Install the package, then run the server. This paragraph is long enough to be real content "
    "for the extractor, so it is not mistaken for a stub page by the fallback guard.</p>"
    "<h2>Configure</h2><p>Set <code>ensure_ascii</code> and <code>MAX_TOKENS</code> in the file.</p>"
    "<pre><code class='language-bash'>docker compose up -d\n</code></pre>"
)


class TestMainContent:
    def test_keeps_main_and_drops_site_chrome(self):
        page = extract_page(_page(SITE_CHROME + f"<main>{ARTICLE}</main>" + FOOTER), URL)

        assert "# Setup guide" in page.text
        assert "## Configure" in page.text
        for chrome in ("Sidebar one", "Home", "Copyright", "Privacy"):
            assert chrome not in page.text

    def test_without_main_uses_body_minus_chrome(self):
        page = extract_page(_page(SITE_CHROME + f"<div>{ARTICLE}</div>" + FOOTER), URL)

        assert "# Setup guide" in page.text
        assert "Sidebar one" not in page.text
        assert "Copyright" not in page.text

    def test_a_main_that_holds_a_sliver_of_the_page_is_not_the_root(self):
        # A wrapper <main> around a one-line banner must not hide the article.
        body = "<main><p>Banner</p></main>" + f"<div>{ARTICLE * 3}</div>"
        page = extract_page(_page(body), URL)

        assert "Install the package" in page.text

    def test_keeps_code_fences_and_identifiers_unescaped(self):
        page = extract_page(_page(f"<main>{ARTICLE}</main>"), URL)

        assert "```" in page.text
        assert "docker compose up -d" in page.text
        # Markdown escaping would write ensure\\_ascii and break keyword search.
        assert "ensure_ascii" in page.text
        assert "MAX_TOKENS" in page.text
        assert "\\_" not in page.text

    def test_footnote_aside_is_kept_but_a_link_list_aside_is_dropped(self):
        footnote = (
            "<aside class='footnote'><p>[1] As noted in the errata for RFC 7159, JSON permits U+2028.</p></aside>"
        )
        related = "<aside><a href='/p'>Related one</a> <a href='/q'>Related two</a></aside>"
        page = extract_page(_page(f"<main>{ARTICLE}{footnote}{related}</main>"), URL)

        assert "errata for RFC 7159" in page.text
        assert "Related one" not in page.text

    def test_heading_anchor_links_are_removed(self):
        body = (
            "<main><h2>Basic Usage<a class='headerlink' href='#basic-usage' title='Link to this heading'>¶</a></h2>"
            f"{ARTICLE}</main>"
        )
        page = extract_page(_page(body), URL)

        assert "## Basic Usage" in page.text
        assert "¶" not in page.text

    def test_images_become_their_alt_text(self):
        body = (
            f"<main>{ARTICLE}<p><img src='/img/arch.png' alt='Architecture diagram'></p>"
            "<p><img src='/img/spacer.gif' alt=''></p></main>"
        )
        page = extract_page(_page(body), URL)

        assert "Architecture diagram" in page.text
        assert "arch.png" not in page.text
        assert "spacer.gif" not in page.text
        assert "![" not in page.text

    def test_adjacent_links_become_a_list(self):
        # Card grids and tag lists put links side by side with no text between.
        cards = (
            "<div class='cards'><a href='/q'><span>Quickstart</span></a><a href='/c'><span>Concepts</span></a></div>"
        )
        page = extract_page(_page(f"<main>{ARTICLE}{cards}</main>"), URL)

        assert "QuickstartConcepts" not in page.text
        assert re.search(r"(?m)^[*-] Quickstart$", page.text)
        assert re.search(r"(?m)^[*-] Concepts$", page.text)

    def test_links_inside_a_sentence_stay_in_the_sentence(self):
        body = (
            f"<main>{ARTICLE}<p>Install with <a href='/pip'>pip</a> <a href='/conda'>conda</a> "
            "or from source.</p></main>"
        )
        page = extract_page(_page(body), URL)

        assert "Install with pip conda or from source." in page.text
        assert not re.search(r"(?m)^[*-] pip$", page.text)

    def test_links_ending_a_sentence_stay_in_the_sentence(self):
        body = f"<main>{ARTICLE}<p>See also <a href='/a'>Alpha</a> <a href='/b'>Beta</a></p></main>"
        page = extract_page(_page(body), URL)

        assert "See also Alpha Beta" in page.text

    def test_a_short_article_beside_a_long_sidebar_keeps_its_extract(self):
        # A docs page whose sidebar out-weighs the article: stripping the menu
        # is not the extractor eating the content.
        entries = "".join(f"<li><a href='/s{i}'>Sidebar entry {i}</a></li>" for i in range(60))
        sidebar = f"<nav><ul>{entries}</ul></nav>"
        article = "<h1>Short page</h1><p>Only a short paragraph of real content lives here.</p>"
        page = extract_page(_page(f"<div>{sidebar}<div>{article}</div></div>" + FOOTER), URL)

        assert "# Short page" in page.text
        assert "Sidebar entry" not in page.text


class TestLinks:
    PROSE = (
        "<p>JSON is specified by <a href='https://datatracker.ietf.org/doc/html/rfc7159.html'>RFC 7159</a> "
        "and the <a href='../reference#errors'>error reference</a>. Jump to <a href='#top'>the top</a>.</p>"
        "<ul><li><a href='/guide/next'>Next page</a></li></ul>"
    )

    def test_links_keep_their_text_and_drop_the_url_by_default(self):
        page = extract_page(_page(f"<main>{ARTICLE}{self.PROSE}</main>"), URL)

        assert "RFC 7159" in page.text
        assert "](" not in page.text
        assert "datatracker" not in page.text

    def test_keep_links_keeps_absolute_urls_for_links_inside_sentences(self):
        page = extract_page(_page(f"<main>{ARTICLE}{self.PROSE}</main>"), URL, keep_links=True)

        assert "[RFC 7159](https://datatracker.ietf.org/doc/html/rfc7159.html)" in page.text
        # Relative links resolve against the page.
        assert "[error reference](https://docs.example.com/reference#errors)" in page.text
        # In-page anchors and link-only list items stay text.
        assert "[the top]" not in page.text
        assert "the top" in page.text
        assert "[Next page]" not in page.text
        assert "Next page" in page.text

    def test_a_destination_with_parentheses_or_spaces_is_kept_whole(self):
        prose = (
            "<p>See <a href='https://en.wikipedia.org/wiki/Foo_(bar)'>Foo</a> and "
            "<a href='/files/release notes.pdf'>the notes</a> and <a href='/q?a=<b>'>a query</a>.</p>"
        )
        page = extract_page(_page(f"<main>{ARTICLE}{prose}</main>"), URL, keep_links=True)

        assert "[Foo](<https://en.wikipedia.org/wiki/Foo_(bar)>)" in page.text
        # Spaces and angle brackets are escaped, so they can't end the destination.
        assert "[the notes](https://docs.example.com/files/release%20notes.pdf)" in page.text
        assert "[a query](https://docs.example.com/q?a=%3Cb%3E)" in page.text


class TestMetadataAndGuards:
    def test_title_and_language(self):
        page = extract_page(_page(f"<main>{ARTICLE}</main>", lang="de"), URL)

        assert page.title == "Setup | Example"
        assert page.language == "de"

    def test_title_falls_back_to_the_first_heading(self):
        page = extract_page(_page(f"<main>{ARTICLE}</main>", head=""), URL)

        assert page.title == "Setup guide"

    def test_charset_is_read_from_the_page_bytes(self):
        html = (
            "<html><head><meta charset='windows-1252'><title>Caf\xe9</title></head>"
            f"<body><main>{ARTICLE}<p>Caf\xe9 cr\xe8me</p></main></body></html>"
        ).encode("cp1252")
        page = extract_page(html, URL)

        assert page.title == "Café"
        assert "Café crème" in page.text

    def test_a_near_empty_extract_falls_back_to_the_page_text(self):
        # Content rendered into a structure the extractor strips (here a <form>)
        # must not leave the page empty.
        long_text = "Pricing details and plan limits for every tier. " * 20
        page = extract_page(_page(f"<main><form><div>{long_text}</div></form></main>"), URL)

        assert "Pricing details" in page.text


class TestPageDocument:
    def test_builds_a_document_with_web_metadata(self):
        doc = page_document(_page(f"<main>{ARTICLE}</main>").encode(), "text/html; charset=utf-8", URL)

        assert doc is not None
        assert "# Setup guide" in doc.text
        assert doc.extra_info == {
            "source": URL,
            "title": "Setup | Example",
            "language": "en",
            "file_path": "guide/setup.md",
        }

    def test_host_prefixed_file_path_when_asked(self):
        doc = page_document(_page(f"<main>{ARTICLE}</main>"), "text/html", URL, include_host=True)

        assert doc.extra_info["file_path"] == "docs.example.com/guide/setup.md"

    def test_non_html_responses_are_skipped(self):
        assert page_document(b"%PDF-1.7 binary", "application/pdf", URL) is None
        assert page_document(b"\x89PNG", "image/png", URL) is None

    def test_missing_content_type_is_treated_as_html(self):
        doc = page_document(_page(f"<main>{ARTICLE}</main>"), None, URL)

        assert doc is not None

    @pytest.mark.parametrize("content_type", ["text/plain; charset=utf-8", "text/markdown", "text/x-markdown"])
    def test_plain_text_and_markdown_are_kept_as_written(self, content_type):
        # llms.txt, a raw README: on main the url loader took any response's text.
        body = "# Example docs\n\n> Read this first.\n\n- [Setup](https://x.io/setup): install <b>it</b>\n"
        doc = page_document(body.encode(), content_type, "https://x.io/llms.txt")

        assert doc is not None
        assert doc.text == body.strip()
        assert doc.extra_info["source"] == "https://x.io/llms.txt"
        assert doc.extra_info["title"] == "Example docs"
        assert doc.extra_info["file_path"]

    @pytest.mark.parametrize("codec", ["iso-8859-2", "shift_jis"])
    def test_html_uses_the_header_charset_when_the_page_has_no_meta(self, codec):
        text = {"iso-8859-2": "Zażółć gęślą jaźń", "shift_jis": "設定ガイド"}[codec]
        html = (
            f"<html><head><title>{text}</title></head><body><main><h1>{text}</h1>"
            f"<p>{text} is the guide to the product.</p></main></body></html>"
        ).encode(codec)

        doc = page_document(html, f"text/html; charset={codec}", URL)

        assert doc.extra_info["title"] == text
        assert f"{text} is the guide" in doc.text

    def test_the_header_charset_wins_over_the_meta_tag(self):
        text = "Résumé — “quoted” €5"
        html = (
            f"<html><head><meta charset='iso-8859-1'><title>{text}</title></head>"
            f"<body><main><p>{text} and more words here.</p></main></body></html>"
        ).encode("utf-8")

        doc = page_document(html, 'text/html; charset="UTF-8"', URL)

        assert doc.extra_info["title"] == text

    def test_a_byte_order_mark_wins_over_the_header_charset(self):
        html = "﻿<html><head><title>Café crème</title></head><body><main><p>Body.</p></main></body></html>"

        doc = page_document(html.encode("utf-8"), "text/html; charset=iso-8859-1", URL)

        assert doc.extra_info["title"] == "Café crème"

    def test_an_unknown_header_charset_falls_back_to_the_page(self):
        html = (
            "<html><head><meta charset='windows-1252'><title>Caf\xe9</title></head>"
            f"<body><main>{ARTICLE}</main></body></html>"
        ).encode("cp1252")

        doc = page_document(html, "text/html; charset=x-bogus", URL)

        assert doc.extra_info["title"] == "Café"

    def test_plain_text_uses_the_declared_charset(self):
        doc = page_document("Grüße aus Köln".encode("latin-1"), "text/plain; charset=latin-1", URL)

        assert doc.text == "Grüße aus Köln"
        assert "title" not in doc.extra_info

    def test_plain_text_is_capped_at_the_markup_limit(self):
        body = ("line of text\n" * 100).encode()
        with patch("docsgpt.parser.remote.page_content.settings") as fake_settings:
            fake_settings.MARKUP_MAX_BYTES = 130
            doc = page_document(body, "text/plain", URL)

        assert len(doc.text.encode()) <= 130

    def test_empty_plain_text_is_skipped(self):
        assert page_document(b"  \n", "text/plain", URL) is None

    def test_json_is_text_only_when_the_page_was_asked_for(self):
        body = b'{"name": "example", "version": 2}'

        assert page_document(body, "application/json", URL) is None
        doc = page_document(body, "application/json", URL, explicit=True)
        assert doc.text == body.decode()

    @pytest.mark.parametrize(
        "line, title",
        [
            ("# Example docs", "Example docs"),
            ("# Example docs ##", "Example docs"),
            ("#\tTabbed  #  ", "Tabbed"),
            ("# C# notes", "C# notes"),
            ("# Issue#", "Issue#"),
        ],
    )
    def test_markdown_title_drops_a_closing_hash_run(self, line, title):
        doc = page_document(f"{line}\n\nBody text.".encode(), "text/markdown", URL)

        assert doc.extra_info["title"] == title

    @pytest.mark.parametrize("filler", [" ", "#", " #", "\t"])
    def test_a_long_heading_line_cannot_stall_the_title(self, filler):
        # A backtracking title pattern took 45 s on one 2 kB line.
        body = ("# a" + filler * 20000 + "x\n\nhello").encode()

        started = time.monotonic()
        doc = page_document(body, "text/plain; charset=utf-8", URL)

        assert time.monotonic() - started < 1
        assert doc.extra_info["title"].startswith("a")

    def test_title_is_read_from_the_start_of_the_text_only(self):
        body = ("filler line\n" * 2000 + "# Late heading\n").encode()

        doc = page_document(body, "text/markdown", URL)

        assert "title" not in doc.extra_info

    def test_json_is_never_searched_for_a_title(self):
        with patch("docsgpt.parser.remote.page_content._ATX_TITLE") as pattern:
            doc = page_document(b'"# not a heading"', "application/json", URL, explicit=True)

        pattern.search.assert_not_called()
        assert "title" not in doc.extra_info


class TestKeepLinksCost:
    def test_many_links_in_one_block_stay_linear(self):
        # Each link used to re-read its whole block's text: quadratic in links.
        links = "".join(f'word <a href="/l{i}">x{i}</a> ' for i in range(4000))
        body = f"<html><body><main><p>{links}</p></main></body></html>".encode()

        started = time.monotonic()
        doc = page_document(body, "text/html", URL, keep_links=True)

        assert time.monotonic() - started < 5
        assert "[x3999](https://docs.example.com/l3999)" in doc.text

    def test_nested_asides_are_measured_once(self):
        # Each aside used to re-read the text and links of every aside inside it.
        soup = html_soup("<html><body>" + "<aside>t " * 4000 + "</body></html>")

        started = time.monotonic()
        _strip_chrome(soup.body)

        assert time.monotonic() - started < 2
        assert len(soup.find_all("aside")) == 4000

    def test_nested_link_runs_read_their_text_once(self):
        # Each level's running-text check used to read the whole subtree below it.
        soup = html_soup("<html><body>" + "<span><a href=/a>a</a><a href=/b>b</a>" * 4000 + "</body></html>")

        started = time.monotonic()
        _listify_link_runs(soup, soup.body)

        assert time.monotonic() - started < 2
        # The nested span beside each run holds text: the links stay in it,
        # spaced. Only the innermost run stands alone and becomes a list.
        assert len(soup.find_all("ul")) == 1
        assert soup.body.span.get_text().startswith("a b")

    def test_nested_page_headers_inside_an_article_are_looked_up_once(self):
        soup = html_soup("<html><body><article>" + "<header>t " * 4000 + "</article></body></html>")

        started = time.monotonic()
        _strip_chrome(soup.body)

        assert time.monotonic() - started < 2
        assert len(soup.find_all("header")) == 4000

    def test_a_link_list_aside_inside_a_kept_aside_is_still_dropped(self):
        body = _page(
            "<main>" + ARTICLE + "<aside><p>A footnote that explains the setup in a full sentence of text.</p>"
            "<aside><a href='/x'>Related one</a> <a href='/y'>Related two</a></aside></aside></main>"
        )

        page = extract_page(body, URL)

        assert "A footnote that explains" in page.text
        assert "Related one" not in page.text

    def test_bare_and_inline_links_are_still_told_apart(self):
        body = _page(
            "<main><ul><li><a href='/menu'>Menu entry</a></li></ul>"
            "<p>Read the <a href='/guide'>setup guide</a> first. " + "More words here. " * 10 + "</p></main>"
        )

        doc = page_document(body.encode(), "text/html", URL, keep_links=True)

        assert "[setup guide](https://docs.example.com/guide)" in doc.text
        assert "Menu entry" in doc.text and "(https://docs.example.com/menu)" not in doc.text


class _Hops:
    """A ``pinned_fetch_bytes`` stand-in: URL -> (status, headers, body); records each call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, *, max_bytes, headers=None, timeout=10.0, total_timeout=None, truncate=False):
        self.calls.append(url)
        status, response_headers, body = self.routes[url]
        response = requests.Response()
        response.status_code = status
        response.url = "http://93.184.216.34/pinned"  # the dialed address, never the page's
        response.headers.update(response_headers)
        return body, response


class TestFetchPageRedirects:
    PAGE = (200, {"Content-Type": "text/html"}, b"<html><body>Real docs</body></html>")

    def _fetch(self, routes, url="https://x.io/docs", **kwargs):
        hops = _Hops(routes)
        with patch("docsgpt.parser.remote.page_content.pinned_fetch_bytes", hops):
            return fetch_page(url, **kwargs), hops

    def test_follows_redirects_to_the_final_page(self):
        response, hops = self._fetch({
            "https://x.io/docs": (301, {"Location": "/docs/"}, b"<h1>301 Moved Permanently</h1>"),
            "https://x.io/docs/": (302, {"Location": "https://www.x.io/docs/"}, b""),
            "https://www.x.io/docs/": self.PAGE,
        })

        assert response.status_code == 200
        assert response.content == self.PAGE[2]
        assert response.url == "https://www.x.io/docs/"
        assert hops.calls == ["https://x.io/docs", "https://x.io/docs/", "https://www.x.io/docs/"]

    def test_a_page_that_does_not_redirect_keeps_its_address(self):
        response, _ = self._fetch({"https://x.io/docs": self.PAGE})

        assert response.url == "https://x.io/docs"

    def test_each_hop_is_charged_to_the_budget(self):
        budget = FetchBudget(1)
        routes = {
            "https://x.io/docs": (301, {"Location": "/a"}, b""),
            "https://x.io/a": (301, {"Location": "/b"}, b""),
            "https://x.io/b": self.PAGE,
        }

        with pytest.raises(RedirectError, match="budget"):
            self._fetch(routes, budget=budget)
        assert budget.remaining == 0
        response, _ = self._fetch(routes, budget=FetchBudget(2))
        assert response.url == "https://x.io/b"

    def test_a_redirect_loop_fails(self):
        with pytest.raises(RedirectError, match="loop"):
            self._fetch({
                "https://x.io/docs": (301, {"Location": "/a"}, b""),
                "https://x.io/a": (302, {"Location": "https://x.io/docs"}, b""),
            })

    def test_more_than_five_redirects_fail(self):
        routes = {f"https://x.io/{i}": (307, {"Location": f"/{i + 1}"}, b"") for i in range(6)}
        routes["https://x.io/6"] = self.PAGE

        with pytest.raises(RedirectError, match="redirects"):
            self._fetch(routes, url="https://x.io/0")
        response, _ = self._fetch(routes, url="https://x.io/1")
        assert response.url == "https://x.io/6"

    @pytest.mark.parametrize("status, headers", [(301, {}), (302, {"Location": "  "}), (304, {}), (300, {})])
    def test_a_3xx_without_a_location_is_a_failure_not_content(self, status, headers):
        with pytest.raises(RedirectError):
            self._fetch({"https://x.io/docs": (status, headers, b"<h1>Moved</h1>")})

    def test_every_hop_passes_the_ssrf_guard(self, monkeypatch):
        from docsgpt.security.safe_url import UnsafeUserUrlError

        def send(self, prepared, **kwargs):
            response = requests.Response()
            response.status_code = 302
            response.headers["Location"] = "http://169.254.169.254/latest/meta-data/"
            response.raw = io.BytesIO(b"")
            return response

        monkeypatch.setattr(requests.Session, "send", send)
        addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        with patch("socket.getaddrinfo", return_value=addrinfo):
            with pytest.raises(UnsafeUserUrlError):
                fetch_page("http://example.com/start")
