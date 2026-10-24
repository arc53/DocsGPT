"""Tests for the shared web page extractor (main content → Markdown)."""

import io
import re
import socket
import time
from functools import partial
from unittest.mock import patch

import pytest
import requests

from docsgpt.parser.remote.page_content import (
    CredentialsInUrlError,
    FetchBudget,
    RedirectError,
    _listify_link_runs,
    _strip_chrome,
    extract_page,
    fetch_page,
    header_charset,
    html_soup,
    page_document,
)
from docsgpt.security.safe_url import UnsafeUserUrlError

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

    def test_adjacent_links_in_a_heading_or_table_cell_stay_on_their_line(self):
        body = (
            f"<main>{ARTICLE}<h2><a href='/a'>Part</a><a href='/b'>One</a></h2><p>Body text paragraph.</p>"
            "<table><tr><th>Name</th><th>Links</th></tr>"
            "<tr><td>Foo</td><td><a href='/d'>Docs</a> <a href='/api'>API</a></td></tr></table></main>"
        )
        page = extract_page(_page(body), URL)

        assert "## Part One" in page.text
        assert "| Foo | Docs API |" in page.text

    def test_adjacent_links_in_code_are_kept_as_written(self):
        body = f"<main>{ARTICLE}<p>Code:</p><pre><a href='/x'>foo</a><a href='/y'>bar</a>()</pre></main>"
        page = extract_page(_page(body), URL)

        assert "foobar()" in page.text

    def test_a_quote_or_article_footer_is_content_but_the_page_footer_is_not(self):
        body = (
            "<div><article><p>Article text that is long enough to stand as the content here.</p>"
            "<footer>Posted by Ada</footer></article><article><p>A second post.</p></article>"
            "<blockquote><p>Simplicity is prerequisite for reliability.</p><footer>Edsger Dijkstra</footer>"
            f"</blockquote></div>{FOOTER}"
        )
        page = extract_page(_page(body), URL)

        assert "Edsger Dijkstra" in page.text
        assert "Posted by Ada" in page.text
        assert "Copyright" not in page.text

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

    def test_keep_links_resolves_against_the_page_base_href(self):
        body = _page(
            f"<main>{ARTICLE}<p>Read the <a href='setup'>setup page</a> first, then the rest.</p></main>",
            head="<title>T</title><base href='https://docs.example.com/v2/'>",
        )

        page = extract_page(body, URL, keep_links=True)

        assert "[setup page](https://docs.example.com/v2/setup)" in page.text

    @pytest.mark.parametrize("href", ["http://[bad", "https://[not-an-ip]/guide"])
    def test_a_malformed_inline_link_keeps_the_page_and_link_text(self, href):
        body = _page(f"<main>{ARTICLE}<p>Read the <a href='{href}'>manual</a> for details.</p></main>")

        document = page_document(body, "text/html", URL, keep_links=True)

        assert document is not None
        assert "# Setup guide" in document.text
        assert "Read the manual for details." in document.text
        assert href not in document.text

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

    def test_an_inline_svg_title_is_not_the_page_title(self):
        body = "<svg><title>Close icon</title></svg><main><h1>Real heading</h1><p>Body text.</p></main>"

        assert extract_page(_page(body, head=""), URL).title == "Real heading"
        assert extract_page(_page(body), URL).title == "Setup | Example"

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


class TestDeepMarkup:
    def test_a_page_nested_too_deep_to_convert_keeps_its_text(self):
        # Markdown conversion recurses per level: thousands of nested
        # elements used to raise RecursionError and lose the page.
        body = (
            "<html><body><main><h1>Title</h1><p>real content here</p>" + "<div>" * 3000 + "deep text"
            + "</div>" * 3000 + "</main></body></html>"
        ).encode()

        doc = page_document(body, "text/html", URL)

        assert doc is not None
        assert "Title" in doc.text and "real content here" in doc.text and "deep text" in doc.text

    @pytest.mark.parametrize("tag", ["p", "li", "span", "font", "b"])
    def test_hundreds_of_unclosed_elements_keep_the_page(self, tag):
        # html.parser nests each unclosed element in the one before it.
        body = "<html><body><h1>Changelog</h1>" + "".join(f"<{tag}>entry {i}\n" for i in range(600)) + "</body></html>"

        doc = page_document(body.encode(), "text/html", URL)

        assert doc is not None
        assert "Changelog" in doc.text
        assert "entry 0" in doc.text and "entry 599" in doc.text

    def test_unclosed_list_items_still_convert_to_a_list(self):
        # Browsers close an <li> at the next one; reparsed that way, the page
        # keeps its Markdown rather than falling back to plain text.
        pytest.importorskip("lxml")
        body = "<html><body><h1>Changelog</h1><ul>" + "".join(f"<li>entry {i}\n" for i in range(600)) + "</ul></body></html>"

        doc = page_document(body.encode(), "text/html", URL)

        assert "# Changelog" in doc.text
        assert "* entry 599" in doc.text or "- entry 599" in doc.text


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

    @pytest.mark.parametrize(
        "html, content_type, title",
        [
            # No <meta>: the header's charset decodes the page.
            *[
                (
                    f"<html><head><title>{text}</title></head><body><main><h1>{text}</h1>"
                    f"<p>{text} is the guide to the product.</p></main></body></html>".encode(codec),
                    f"text/html; charset={codec}",
                    text,
                )
                for codec, text in (("iso-8859-2", "Zażółć gęślą jaźń"), ("shift_jis", "設定ガイド"))
            ],
            # The header's charset wins over the <meta> tag, as in browsers.
            (
                "<html><head><meta charset='iso-8859-1'><title>Résumé — “quoted” €5</title></head>"
                "<body><main><p>Résumé — “quoted” €5 and more words here.</p></main></body></html>".encode(),
                'text/html; charset="UTF-8"',
                "Résumé — “quoted” €5",
            ),
            # A byte-order mark wins over the header's charset.
            (
                "\ufeff<html><head><title>Café crème</title></head><body><main><p>Body.</p></main></body></html>"
                .encode("utf-8"),
                "text/html; charset=iso-8859-1",
                "Café crème",
            ),
            # An unknown header charset leaves the page's own <meta>.
            (
                "<html><head><meta charset='windows-1252'><title>Caf\xe9</title></head>"
                f"<body><main>{ARTICLE}</main></body></html>".encode("cp1252"),
                "text/html; charset=x-bogus",
                "Café",
            ),
        ],
    )
    def test_html_is_decoded_by_the_charset_that_wins(self, html, content_type, title):
        doc = page_document(html, content_type, URL)

        assert doc.extra_info["title"] == title

    @pytest.mark.parametrize("charset", ["base64", "rot13", "zlib", "hex", "bz2", "uu", "idna", "punycode"])
    def test_a_header_charset_that_is_no_text_encoding_keeps_the_page(self, charset):
        # Python knows these names, but as bytes-to-bytes codecs (or ones
        # that refuse ``errors="replace"``): decoding by them raised.
        html = f"<html><body><main>{ARTICLE}</main></body></html>".encode()

        text = page_document("# Hello\nplain text".encode(), f"text/plain; charset={charset}", URL)
        page = page_document(html, f"text/html; charset={charset}", URL)

        assert text.text == "# Hello\nplain text"
        assert "Install the package" in page.text

    @pytest.mark.parametrize("charset", ["base64", "rot13", "zlib", "hex", "bz2"])
    def test_header_charset_names_only_text_encodings(self, charset):
        assert header_charset(f"text/html; charset={charset}") is None
        assert header_charset("text/html; charset=Shift_JIS") == "Shift_JIS"

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


class TestNulCharacters:
    # PostgreSQL text and JSONB refuse U+0000: a page carrying one failed its store.
    def test_plain_text_drops_nul_from_text_and_title(self):
        doc = page_document(b"# Ti\x00tle\nhello\x00world\n", "text/plain", URL, explicit=True)

        assert doc.text == "# Title\nhelloworld"
        assert doc.extra_info["title"] == "Title"

    def test_html_drops_nul_from_text_title_and_language(self):
        body = b"<html lang='e\x00n'><head><title>T\x00x</title></head><body><p>hello\x00world</p></body></html>"

        # charset-normalizer, BeautifulSoup's guesser when chardet is absent, reads these NULs as UTF-16.
        with patch("bs4.dammit._chardet_dammit", return_value="utf_16_be"):
            doc = page_document(body, "text/html", URL)

        assert "\x00" not in doc.text and "helloworld" in doc.text
        assert doc.extra_info["title"] == "Tx"
        assert doc.extra_info["language"] == "en"

    def test_a_page_of_only_nul_is_skipped(self):
        assert page_document(b"\x00\x00", "text/plain", URL, explicit=True) is None


class TestWideEncodings:
    # Browsers read a page as UTF-16 or UTF-32 only by its byte-order mark or HTTP header, never by a guess.
    # An even number of ASCII bytes, so UTF-16 decodes it without an error.
    PAGE = "<html><head><title>Setup</title></head><body><p>hello, world</p></body></html>"

    @pytest.mark.parametrize("guess", ["utf_16_be", "UTF-16", "utf-16le"])
    def test_a_guessed_wide_encoding_is_not_used(self, guess):
        with patch("bs4.dammit._chardet_dammit", return_value=guess):
            doc = page_document(self.PAGE.encode(), "text/html", URL)

        assert doc.text == "hello, world" and doc.extra_info["title"] == "Setup"

    def test_a_byte_order_mark_still_reads_utf_16(self):
        doc = page_document(self.PAGE.encode("utf-16"), "text/html", URL)

        assert doc.text == "hello, world" and doc.extra_info["title"] == "Setup"

    def test_a_header_charset_still_reads_utf_16(self):
        doc = page_document(self.PAGE.encode("utf-16-le"), "text/html; charset=utf-16le", URL)

        assert doc.text == "hello, world" and doc.extra_info["title"] == "Setup"


def _fastest(fn, make_args=tuple, times=3):
    """The seconds of the fastest of ``times`` calls of ``fn(*make_args())``, and the last call's result.

    ``make_args`` isn't timed. The cost tests compare two of these from one
    run, as an absolute limit fails on a slow runner or under coverage. Each
    sits at a size where the quadratic code it guards against cost several
    times its limit.
    """
    best = float("inf")
    for _ in range(times):
        args = make_args()
        started = time.perf_counter()
        result = fn(*args)
        best = min(best, time.perf_counter() - started)
    return best, result


class TestKeepLinksCost:
    def _keeping_links_costs_little(self, body):
        # Two runs each: a page this size takes a second to parse under coverage.
        plain, _ = _fastest(partial(page_document, body, "text/html", URL), times=2)
        kept, doc = _fastest(partial(page_document, body, "text/html", URL, keep_links=True), times=2)

        assert kept < 2.5 * plain
        return doc

    def test_many_links_in_one_block_stay_linear(self):
        # Each link used to re-read its whole block's text: quadratic in links.
        links = "".join(f'word <a href="/l{i}">x{i}</a> ' for i in range(1000))
        body = f"<html><body><main><p>{links}</p></main></body></html>".encode()

        doc = self._keeping_links_costs_little(body)

        assert "[x999](https://docs.example.com/l999)" in doc.text

    def test_links_nested_deep_in_one_block_find_it_once(self):
        # Each link used to walk up every element between it and its paragraph.
        links = "<a href='/y'>l</a> word " * 500
        body = f"<html><body><main><p>{'<b>' * 400}{links}{'</b>' * 400}</p></main></body></html>".encode()

        doc = self._keeping_links_costs_little(body)

        assert "[l](https://docs.example.com/y)" in doc.text

    def _costs_little_beside_parsing(self, markup, fn):
        """Time ``fn`` on the parsed ``markup`` against parsing it; returns the soup ``fn`` changed."""
        parse, _ = _fastest(html_soup, lambda: (markup,))
        work, soup = _fastest(lambda soup: fn(soup) or soup, lambda: (html_soup(markup),))

        assert work < 12 * parse
        return soup

    def test_nested_asides_are_measured_once(self):
        # Each aside used to re-read the text and links of every aside inside it.
        markup = "<html><body>" + "<aside>t " * 1000 + "</body></html>"

        soup = self._costs_little_beside_parsing(markup, lambda soup: _strip_chrome(soup.body))

        assert len(soup.find_all("aside")) == 1000

    def test_nested_link_runs_read_their_text_once(self):
        # Each level's running-text check used to read the whole subtree below it.
        markup = "<html><body>" + "<span><a href=/a>a</a><a href=/b>b</a>" * 1000 + "</body></html>"

        soup = self._costs_little_beside_parsing(markup, lambda soup: _listify_link_runs(soup, soup.body))

        # The nested span beside each run holds text: the links stay in it,
        # spaced. Only the innermost run stands alone and becomes a list.
        assert len(soup.find_all("ul")) == 1
        assert soup.body.span.get_text().startswith("a b")

    def test_nested_page_headers_inside_an_article_are_looked_up_once(self):
        markup = "<html><body><article>" + "<header>t " * 1000 + "</article></body></html>"

        soup = self._costs_little_beside_parsing(markup, lambda soup: _strip_chrome(soup.body))

        assert len(soup.find_all("header")) == 1000

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

    def test_an_address_with_credentials_is_not_fetched(self):
        # The fetcher would send them as Basic auth, and the page's source
        # (shown in citations) would carry the password.
        with pytest.raises(CredentialsInUrlError):
            self._fetch({"https://alice:s3cret@x.io/docs": self.PAGE}, url="https://alice:s3cret@x.io/docs")

    def test_a_redirect_to_an_address_with_credentials_is_not_followed(self):
        with pytest.raises(CredentialsInUrlError):
            self._fetch({
                "https://x.io/docs": (302, {"Location": "https://alice:s3cret@x.io/private"}, b""),
                "https://alice:s3cret@x.io/private": self.PAGE,
            })

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

    def test_a_location_with_raw_utf8_is_followed_to_the_right_address(self):
        # http.client reads header bytes as latin-1, so a raw UTF-8 ``/café``
        # arrives as ``/cafÃ©``; browsers and requests read it as UTF-8.
        mangled = "/café".encode("utf-8").decode("latin-1")
        response, hops = self._fetch({
            "https://x.io/docs": (301, {"Location": mangled}, b""),
            "https://x.io/café": self.PAGE,
        })

        assert hops.calls[-1] == "https://x.io/café"
        assert response.url == "https://x.io/café"

    def test_a_latin1_location_is_kept_as_it_was_read(self):
        response, hops = self._fetch({
            "https://x.io/docs": (301, {"Location": "/caf\xe9"}, b""),
            "https://x.io/caf\xe9": self.PAGE,
        })

        assert response.url == "https://x.io/caf\xe9"

    @staticmethod
    def _stub(content: str, title: str = "Redirecting...") -> tuple:
        body = (
            f"<html><head><title>{title}</title><meta http-equiv='Refresh' content=\"{content}\"></head>"
            "<body><h1>Redirecting...</h1><a href='/new/'>Click here if you are not redirected.</a></body></html>"
        )
        return 200, {"Content-Type": "text/html"}, body.encode()

    @pytest.mark.parametrize("content", ["0; url=/new/", "0;URL='/new/#top'", "1, /new/", " 0 ; url = '/new/'"])
    def test_a_meta_refresh_stub_is_followed_like_a_redirect(self, content):
        budget = FetchBudget(5)
        response, hops = self._fetch(
            {"https://x.io/old/": self._stub(content), "https://x.io/new/": self.PAGE},
            url="https://x.io/old/",
            budget=budget,
        )

        assert response.url == "https://x.io/new/"
        assert response.content == self.PAGE[2]
        assert hops.calls == ["https://x.io/old/", "https://x.io/new/"]
        assert budget.remaining == 4

    @pytest.mark.parametrize("content", ["5; url=/new/", "0", "0; url=javascript:alert(1)", "0; url=/old/"])
    def test_a_slow_empty_foreign_or_self_refresh_is_a_page(self, content):
        response, hops = self._fetch({"https://x.io/old/": self._stub(content)}, url="https://x.io/old/")

        assert response.url == "https://x.io/old/"
        assert hops.calls == ["https://x.io/old/"]

    def test_meta_refresh_hops_count_toward_the_redirect_limit(self):
        routes = {f"https://x.io/{i}": self._stub(f"0; url=/{i + 1}") for i in range(6)}
        routes["https://x.io/6"] = self.PAGE

        with pytest.raises(RedirectError, match="redirects"):
            self._fetch(routes, url="https://x.io/0")

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
