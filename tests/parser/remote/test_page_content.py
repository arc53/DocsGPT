"""Tests for the shared web page extractor (main content → Markdown)."""

import re
from unittest.mock import patch

import pytest

from docsgpt.parser.remote.page_content import extract_page, page_document

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
