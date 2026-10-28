"""Tests for docsgpt/parser/remote/sitemap_loader.py: the sitemap walk and its page fetches."""

import gc
import tracemalloc
import weakref
from unittest.mock import MagicMock, patch

import pytest
import requests

from docsgpt.core.url_validation import SSRFError
from docsgpt.parser.remote import sitemap_loader
from docsgpt.parser.remote.sitemap_loader import (
    MAX_SITEMAP_DEPTH,
    MAX_XML_NESTING,
    SitemapLoader,
    _read_entries,
)
from docsgpt.parser.schema.base import Document
from docsgpt.security.safe_url import UnsafeUserUrlError

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _sitemap_index(*children):
    locs = "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="{NS}">{locs}</sitemapindex>'.encode()


def _urlset(*pages):
    locs = "".join(f"<url><loc>{p}</loc></url>" for p in pages)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="{NS}">{locs}</urlset>'.encode()


def _serve(sites):
    """A ``fetch_page`` stand-in that answers from a URL -> XML bytes map."""

    def fake(url, *_, **__):
        body = sites[url]
        response = MagicMock()
        response.headers = {"Content-Type": "application/xml"}
        response.url = url
        response.content = body
        response.raise_for_status.return_value = None
        return response

    return MagicMock(side_effect=fake)


def _page_response(text: str) -> MagicMock:
    """A fetched HTML page, shaped like a ``requests.Response``."""
    response = MagicMock()
    response.text = text
    response.content = text.encode()
    response.headers = {"Content-Type": "text/html; charset=utf-8"}
    response.raise_for_status.return_value = None
    return response


@pytest.mark.unit
class TestIsSitemap:
    @pytest.mark.parametrize(
        "content_type, url, content, expected",
        [
            ("application/xml", "https://example.com/sitemap.xml", b"", True),
            ("text/xml; charset=utf-8", "https://example.com/feed", b"", True),
            ("text/html", "https://example.com/sitemap.xml", b"", True),
            ("text/html", "https://example.com/sitemap", b"<sitemapindex><sitemap></sitemap></sitemapindex>", True),
            ("text/html", "https://example.com/page", b"<urlset><url></url></urlset>", True),
            ("text/html", "https://example.com/about", b"<html><body>About us</body></html>", False),
        ],
    )
    def test_by_type_extension_or_root_tag(self, content_type, url, content, expected):
        response = MagicMock()
        response.headers = {"Content-Type": content_type}
        response.url = url

        assert SitemapLoader._is_sitemap(response, content) is expected


@pytest.mark.unit
class TestParseSitemap:

    def test_parse_basic_sitemap(self):
        urls = SitemapLoader()._parse_sitemap(_urlset("https://example.com/page1", "https://example.com/page2"))

        assert urls == ["https://example.com/page1", "https://example.com/page2"]

    def test_parse_nested_sitemap(self):
        child = "https://example.com/sitemap-child.xml"
        with patch.object(sitemap_loader, "fetch_page", _serve({child: _urlset("https://example.com/page1")})):
            urls = SitemapLoader()._parse_sitemap(_sitemap_index(child))

        assert urls == ["https://example.com/page1"]

    def test_exactly_the_limit_is_not_limit_reached(self):
        url = "https://example.com/sitemap.xml"
        exact = SitemapLoader(limit=2)
        more = SitemapLoader(limit=1)
        with patch.object(sitemap_loader, "fetch_page", _serve({url: _urlset("https://e.io/a", "https://e.io/b")})):
            assert exact.collect_urls([url]) == ["https://e.io/a", "https://e.io/b"]
            assert more.collect_urls([url]) == ["https://e.io/a"]

        assert exact.limit_reached is False
        assert more.limit_reached is True

    def test_parse_empty_sitemap(self):
        assert SitemapLoader()._parse_sitemap(_urlset()) == []

    def test_parse_skips_empty_loc_entries(self):
        """Empty or self-closing <loc> tags must not yield None URLs."""
        sitemap_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="{NS}">'
            "<url><loc></loc></url><url><loc>https://example.com/p</loc></url><url><loc/></url></urlset>"
        ).encode()

        assert SitemapLoader()._parse_sitemap(sitemap_xml) == ["https://example.com/p"]


@pytest.mark.unit
class TestCollectUrls:

    def test_a_sitemap_lists_its_pages(self):
        url = "https://example.com/sitemap.xml"
        with patch.object(sitemap_loader, "fetch_page", _serve({url: _urlset("https://example.com/p")})):
            assert SitemapLoader().collect_urls([url]) == ["https://example.com/p"]

    def test_an_address_that_is_not_a_sitemap_lists_nothing(self):
        # A soft 404 at /sitemap.xml is the app's HTML shell, not a page to load.
        response = _page_response("<html>Normal page</html>")
        response.url = "https://example.com/page"
        with patch.object(sitemap_loader, "fetch_page", return_value=response):
            assert SitemapLoader().collect_urls(["https://example.com/page"]) == []

    @pytest.mark.parametrize("error", [
        requests.exceptions.HTTPError("404"),
        requests.exceptions.ConnectionError(),
        UnsafeUserUrlError("blocked"),
    ])
    def test_a_sitemap_that_fails_to_fetch_lists_nothing(self, error):
        with patch.object(sitemap_loader, "fetch_page", side_effect=error):
            assert SitemapLoader().collect_urls(["http://169.254.169.254/"]) == []


@pytest.mark.unit
class TestLoadPages:

    @pytest.fixture
    def fetch(self):
        with patch.object(sitemap_loader, "validate_url", side_effect=lambda url: url), \
                patch.object(sitemap_loader, "fetch_page") as mock_fetch:
            yield mock_fetch

    def test_each_page_is_one_document(self, fetch):
        fetch.return_value = _page_response("Page body")

        docs = SitemapLoader(limit=10).load_pages(["https://example.com/page1"])

        assert len(docs) == 1 and isinstance(docs[0], Document)
        assert docs[0].text == "Page body"
        assert docs[0].extra_info == {
            "source": "https://example.com/page1", "file_path": "page1.md", "requested_urls": [],
        }

    @pytest.mark.parametrize("limit, loaded", [(2, 2), (None, 5)])
    def test_the_limit_caps_the_fetches(self, fetch, limit, loaded):
        fetch.return_value = _page_response("Limited body")

        docs = SitemapLoader(limit=limit).load_pages([f"https://example.com/page{i}" for i in range(5)])

        assert len(docs) == loaded
        assert fetch.call_count == loaded

    def test_a_page_that_fails_is_skipped(self, fetch):
        fetch.side_effect = Exception("Load failed")

        assert SitemapLoader().load_pages(["https://example.com/broken"]) == []

    def test_a_blocked_page_is_never_fetched(self, fetch):
        with patch.object(sitemap_loader, "validate_url", side_effect=SSRFError("blocked")):
            assert SitemapLoader().load_pages(["http://169.254.169.254/"]) == []
        fetch.assert_not_called()

    def test_colliding_pages_get_distinct_file_paths(self, fetch):
        fetch.return_value = _page_response("Page body")

        docs = SitemapLoader().load_pages(["https://x.io/p?page=2", "https://x.io/p", "https://x.io/p.htm"])

        assert [d.extra_info["file_path"] for d in docs] == ["p__page=2.md", "p.md", "p-2.md"]

    @patch("docsgpt.core.url_validation.resolve_hostname", return_value="93.184.216.34")
    def test_malformed_entry_is_skipped_and_the_rest_ingest(self, _mock_resolve):
        with patch.object(sitemap_loader, "fetch_page", return_value=_page_response("Good body")) as mock_fetch:
            docs = SitemapLoader().load_pages(["http://[bad", "https://example.com/good"])

        assert [d.extra_info for d in docs] == [
            {"source": "https://example.com/good", "file_path": "good.md", "requested_urls": []}
        ]
        mock_fetch.assert_called_once()


# =====================================================================
# Nested sitemap safety (#3036)
# =====================================================================


@pytest.mark.unit
class TestNestedSitemapSafety:

    def test_self_referencing_index_is_fetched_once(self):
        url = "https://example.com/sitemap.xml"
        fake = _serve({url: _sitemap_index(url)})
        with patch.object(sitemap_loader, "fetch_page", fake):
            urls = SitemapLoader().collect_urls([url])

        assert urls == []
        assert fake.call_count == 1

    def test_mutually_referencing_indexes_are_each_fetched_once(self):
        a = "https://example.com/a.xml"
        b = "https://example.com/b.xml"
        fake = _serve({a: _sitemap_index(b), b: _sitemap_index(a)})
        with patch.object(sitemap_loader, "fetch_page", fake):
            SitemapLoader().collect_urls([a])

        assert sorted(call.args[0] for call in fake.call_args_list) == [a, b]

    def test_nesting_deeper_than_the_cap_stops(self, caplog):
        chain = [f"https://example.com/s{i}.xml" for i in range(MAX_SITEMAP_DEPTH + 5)]
        sites = {u: _sitemap_index(chain[i + 1]) for i, u in enumerate(chain[:-1])}
        sites[chain[-1]] = _urlset("https://example.com/deep")
        fake = _serve(sites)
        with patch.object(sitemap_loader, "fetch_page", fake):
            urls = SitemapLoader().collect_urls([chain[0]])

        assert urls == []
        assert fake.call_count == MAX_SITEMAP_DEPTH + 1
        assert "depth" in caplog.text.lower()

    def test_elements_that_never_close_stop_the_reading(self, caplog):
        # Every element is dropped once it closes; one that never closes was
        # kept, so a small gzip of nested open tags held gigabytes.
        content = (
            b'<?xml version="1.0"?><urlset><url><loc>https://example.com/a</loc></url>'
            + b"<a>" * 300_000 + b"<url><loc>https://example.com/b</loc></url>"
        )
        pages = []

        tracemalloc.start()
        try:
            _read_entries(content, pages.append, lambda url: None, lambda: False)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert pages == ["https://example.com/a"]
        assert peak < 5 * 1024 * 1024
        assert f"nested more than {MAX_XML_NESTING}" in caplog.text

    def test_a_real_sitemap_is_well_within_the_nesting_bound(self):
        content = (
            b'<?xml version="1.0"?><urlset xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
            b"<url><loc>https://example.com/a</loc><image:image><image:loc>https://example.com/i.png</image:loc>"
            b"</image:image></url></urlset>"
        )
        pages = []

        _read_entries(content, pages.append, lambda url: None, lambda: False)

        assert pages == ["https://example.com/a"]

    def test_limit_stops_following_child_sitemaps(self):
        index = "https://example.com/index.xml"
        children = [f"https://example.com/child{i}.xml" for i in range(50)]
        sites = {index: _sitemap_index(*children)}
        for i, child in enumerate(children):
            sites[child] = _urlset(f"https://example.com/page{i}")
        fake = _serve(sites)
        with patch.object(sitemap_loader, "fetch_page", fake):
            urls = SitemapLoader(limit=3).collect_urls([index])

        assert urls == [f"https://example.com/page{i}" for i in range(3)]
        # The index, and children until one page past the limit (to tell "more left").
        assert fake.call_count == 1 + 4

    def test_limit_is_shared_across_nested_indexes(self):
        root = "https://example.com/index.xml"
        pages = "https://example.com/pages.xml"
        nested = "https://example.com/nested.xml"
        children = [f"https://example.com/child{i}.xml" for i in range(5)]
        sites = {
            root: _sitemap_index(pages, nested),
            pages: _urlset("https://example.com/a", "https://example.com/b"),
            nested: _sitemap_index(*children),
        }
        for i, child in enumerate(children):
            sites[child] = _urlset(f"https://example.com/child-page{i}")
        fake = _serve(sites)
        with patch.object(sitemap_loader, "fetch_page", fake):
            urls = SitemapLoader(limit=3).collect_urls([root])

        fetched_children = [c.args[0] for c in fake.call_args_list if c.args[0] in children]
        assert fetched_children == children[:2]
        assert urls == ["https://example.com/a", "https://example.com/b", "https://example.com/child-page0"]

    def test_limit_caps_leaf_urls_in_one_sitemap(self):
        url = "https://example.com/sitemap.xml"
        fake = _serve({url: _urlset(*[f"https://example.com/p{i}" for i in range(10)])})
        with patch.object(sitemap_loader, "fetch_page", fake):
            urls = SitemapLoader(limit=3).collect_urls([url])

        assert urls == ["https://example.com/p0", "https://example.com/p1", "https://example.com/p2"]

    def test_malformed_xml_returns_no_urls(self):
        assert SitemapLoader()._parse_sitemap(b"<urlset><url>") == []

    def test_malformed_child_does_not_drop_its_siblings(self):
        index = "https://example.com/index.xml"
        bad = "https://example.com/bad.xml"
        good = "https://example.com/good.xml"
        fake = _serve({
            index: _sitemap_index(bad, good),
            bad: b"<urlset><url><loc>https://example.com/x",
            good: _urlset("https://example.com/ok"),
        })
        with patch.object(sitemap_loader, "fetch_page", fake):
            urls = SitemapLoader().collect_urls([index])

        assert urls == ["https://example.com/ok"]


@pytest.mark.unit
class TestSitemapFormats:

    @pytest.mark.parametrize(
        "xml",
        [
            # Single-quoted namespace.
            f"<?xml version='1.0'?><urlset xmlns='{NS}'><url><loc>https://e.io/a</loc></url></urlset>".encode(),
            # A prefixed namespace.
            f'<sm:urlset xmlns:sm="{NS}"><sm:url><sm:loc>https://e.io/a</sm:loc></sm:url></sm:urlset>'.encode(),
            # A byte-order mark.
            b"\xef\xbb\xbf" + _urlset("https://e.io/a"),
            # No namespace at all.
            b"<urlset><url><loc> https://e.io/a </loc></url></urlset>",
        ],
    )
    def test_valid_sitemaps_are_read(self, xml):
        assert SitemapLoader()._parse_sitemap(xml) == ["https://e.io/a"]

    @pytest.mark.parametrize(
        "label, codec, loc",
        [
            # Declared and honoured.
            ("ISO-8859-1", "latin-1", "https://e.io/caf\xe9"),
            # Encodings expat can't read itself are decoded first.
            *[(codec, codec, "https://e.io/a") for codec in ("GBK", "Shift_JIS", "EUC-KR", "Big5", "ISO-8859-2")],
            # A multibyte encoding keeps its characters.
            ("Shift_JIS", "shift_jis", "https://e.io/文書"),
            # An unknown label is read as UTF-8.
            ("x-no-such-charset", "utf-8", "https://e.io/café"),
        ],
    )
    def test_the_declared_encoding_is_read(self, label, codec, loc):
        xml = (
            f'<?xml version="1.0" encoding="{label}"?><urlset xmlns="{NS}">'
            f"<url><loc>{loc}</loc></url><url><loc>https://e.io/b</loc></url></urlset>"
        ).encode(codec)

        assert SitemapLoader()._parse_sitemap(xml) == [loc, "https://e.io/b"]

    def test_a_sitemap_index_with_single_quotes_is_followed(self):
        index = "https://e.io/index.xml"
        child = "https://e.io/child.xml"
        fake = _serve({
            index: f"<sitemapindex xmlns='{NS}'><sitemap><loc>{child}</loc></sitemap></sitemapindex>".encode(),
            child: _urlset("https://e.io/a"),
        })
        with patch.object(sitemap_loader, "fetch_page", fake):
            assert SitemapLoader().collect_urls([index]) == ["https://e.io/a"]

    def test_entities_stay_forbidden(self):
        xml = (
            b'<?xml version="1.0"?><!DOCTYPE u [<!ENTITY e "https://e.io/x">]>'
            b"<urlset><url><loc>&e;</loc></url></urlset>"
        )

        assert SitemapLoader()._parse_sitemap(xml) == []

    def test_parsing_stops_once_the_limit_is_collected(self):
        # Read incrementally: a broken tail past the limit is never reached.
        xml = _urlset(*[f"https://e.io/p{i}" for i in range(10)])[:-len("</urlset>")] + b"<url><loc>"

        assert SitemapLoader(limit=3)._parse_sitemap(xml) == ["https://e.io/p0", "https://e.io/p1", "https://e.io/p2"]

    def test_a_large_sitemap_is_parsed_in_bounded_memory(self):
        xml = _urlset(*[f"https://elsewhere.io/page/{i}" for i in range(40000)])
        loader = SitemapLoader(limit=10, accept=lambda url: False)

        tracemalloc.start()
        try:
            assert loader._parse_sitemap(xml) == []
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        # The whole tree of 40k entries takes several times the 1.5 MB file.
        assert peak < len(xml)

    def test_junk_elements_are_not_kept_while_parsing(self):
        # Every element is dropped once read, not only <url>: a 47 KB gzip of
        # millions of <x/> grew a tree past a gigabyte.
        junk = b"<x>text</x><lastmod>2024</lastmod>" * 1000
        xml = (
            f'<?xml version="1.0"?><urlset xmlns="{NS}">'.encode()
            + junk
            + b"<url><loc>https://e.io/a</loc>" + junk + b"</url>"
            + b"<url><loc>https://e.io/b</loc></url></urlset>"
        )
        real_iterparse = sitemap_loader.ET.iterparse
        tree_sizes = []

        def tracking_iterparse(*args, **kwargs):
            root = None
            for event, element in real_iterparse(*args, **kwargs):
                root = element if root is None else root
                if event == "end" and sitemap_loader._local_name(element.tag) == "url":
                    tree_sizes.append(sum(1 for _ in root.iter()))
                yield event, element

        with patch.object(sitemap_loader.ET, "iterparse", tracking_iterparse):
            assert SitemapLoader()._parse_sitemap(xml) == ["https://e.io/a", "https://e.io/b"]

        # The root and the entries the parser has read ahead; nothing earlier.
        assert len(tree_sizes) == 2 and max(tree_sizes) <= 6

    def test_the_tree_is_released_before_child_sitemaps_are_walked(self):
        index = "https://e.io/index.xml"
        child = "https://e.io/child.xml"
        serve = _serve({index: _sitemap_index(child), child: _urlset("https://e.io/a")})
        real_iterparse = sitemap_loader.ET.iterparse
        roots = []
        alive_during_child = []

        def tracking_iterparse(*args, **kwargs):
            for event, element in real_iterparse(*args, **kwargs):
                if not roots:
                    roots.append(weakref.ref(element))
                yield event, element

        def fake(url, *args, **kwargs):
            if url == child:
                gc.collect()
                alive_during_child.append(roots[0]() is not None)
            return serve(url, *args, **kwargs)

        with patch.object(sitemap_loader, "fetch_page", fake), \
                patch.object(sitemap_loader.ET, "iterparse", tracking_iterparse):
            assert SitemapLoader().collect_urls([index]) == ["https://e.io/a"]

        assert alive_during_child == [False]

    def test_a_sitemap_in_an_unreadable_encoding_does_not_stop_the_walk(self):
        index = "https://e.io/index.xml"
        bad = "https://e.io/bad.xml"
        good = "https://e.io/good.xml"
        fake = _serve({
            index: _sitemap_index(bad, good),
            bad: b'<?xml version="1.0" encoding="GBK"?><urlset><url><loc>https://e.io/x</loc></url></urlset>',
            good: _urlset("https://e.io/ok"),
        })
        with patch.object(sitemap_loader, "fetch_page", fake):
            urls = SitemapLoader().collect_urls([index])

        assert urls == ["https://e.io/x", "https://e.io/ok"]
