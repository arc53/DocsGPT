"""Comprehensive tests for docsgpt/parser/remote/sitemap_loader.py

Covers: SitemapLoader (init, load_data, _extract_urls, _is_sitemap,
_parse_sitemap, URL validation, error handling).
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from docsgpt.parser.remote.sitemap_loader import SitemapLoader
from docsgpt.parser.schema.base import Document


# =====================================================================
# SitemapLoader - Init
# =====================================================================


@pytest.mark.unit
class TestSitemapLoaderInit:

    def test_default_limit(self):
        loader = SitemapLoader()
        assert loader.limit == 20

    def test_custom_limit(self):
        loader = SitemapLoader(limit=5)
        assert loader.limit == 5

    def test_has_loader_class(self):
        loader = SitemapLoader()
        assert not hasattr(loader, "loader")


# =====================================================================
# _is_sitemap
# =====================================================================


@pytest.mark.unit
class TestIsSitemap:

    def test_xml_content_type(self):
        loader = SitemapLoader()
        response = MagicMock()
        response.headers = {"Content-Type": "application/xml"}
        response.url = "https://example.com/sitemap.xml"
        response.text = ""
        assert loader._is_sitemap(response) is True

    def test_xml_url_extension(self):
        loader = SitemapLoader()
        response = MagicMock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://example.com/sitemap.xml"
        response.text = ""
        assert loader._is_sitemap(response) is True

    def test_sitemapindex_in_body(self):
        loader = SitemapLoader()
        response = MagicMock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://example.com/sitemap"
        response.text = "<sitemapindex><sitemap></sitemap></sitemapindex>"
        assert loader._is_sitemap(response) is True

    def test_urlset_in_body(self):
        loader = SitemapLoader()
        response = MagicMock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://example.com/page"
        response.text = "<urlset><url></url></urlset>"
        assert loader._is_sitemap(response) is True

    def test_regular_page(self):
        loader = SitemapLoader()
        response = MagicMock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://example.com/about"
        response.text = "<html><body>About us</body></html>"
        assert loader._is_sitemap(response) is False

    def test_text_xml_content_type(self):
        loader = SitemapLoader()
        response = MagicMock()
        response.headers = {"Content-Type": "text/xml; charset=utf-8"}
        response.url = "https://example.com/feed"
        response.text = ""
        assert loader._is_sitemap(response) is True


# =====================================================================
# _parse_sitemap
# =====================================================================


@pytest.mark.unit
class TestParseSitemap:

    def test_parse_basic_sitemap(self):
        loader = SitemapLoader()
        sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>"""

        urls = loader._parse_sitemap(sitemap_xml)
        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls

    def test_parse_nested_sitemap(self):
        loader = SitemapLoader()

        parent_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap>
                <loc>https://example.com/sitemap-child.xml</loc>
            </sitemap>
        </sitemapindex>"""

        with patch.object(
            loader, "_walk",
            return_value=["https://example.com/page1"]
        ):
            urls = loader._parse_sitemap(parent_xml)
            assert "https://example.com/page1" in urls

    def test_a_nested_entry_that_is_not_a_sitemap_is_dropped(self):
        # Only <url> entries are pages; a child "sitemap" that answers with
        # a page would otherwise skip accept().
        loader = SitemapLoader(accept=lambda url: False)
        parent_xml = _sitemap_index("https://evil.io/page")

        with patch.object(loader, "_walk", return_value=None):
            assert loader._parse_sitemap(parent_xml) == []

    def test_exactly_the_limit_is_not_limit_reached(self):
        url = "https://example.com/sitemap.xml"
        exact = SitemapLoader(limit=2)
        more = SitemapLoader(limit=1)
        fake = _serve({url: _urlset("https://e.io/a", "https://e.io/b")})
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            assert exact.collect_urls([url]) == ["https://e.io/a", "https://e.io/b"]
            assert more.collect_urls([url]) == ["https://e.io/a"]

        assert exact.limit_reached is False
        assert more.limit_reached is True

    def test_parse_empty_sitemap(self):
        loader = SitemapLoader()
        sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        </urlset>"""

        urls = loader._parse_sitemap(sitemap_xml)
        assert urls == []

    def test_parse_skips_empty_loc_entries(self):
        """Empty or self-closing <loc> tags must not yield None URLs."""
        loader = SitemapLoader()
        sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc></loc></url>
            <url><loc>https://example.com/p</loc></url>
            <url><loc/></url>
        </urlset>"""

        urls = loader._parse_sitemap(sitemap_xml)
        assert urls == ["https://example.com/p"]


# =====================================================================
# _extract_urls
# =====================================================================


@pytest.mark.unit
class TestExtractUrls:

    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_extract_urls_from_sitemap(self, mock_fetch):
        loader = SitemapLoader()

        response = MagicMock()
        response.headers = {"Content-Type": "application/xml"}
        response.url = "https://example.com/sitemap.xml"
        response.text = "<urlset><url><loc>https://example.com/p</loc></url></urlset>"
        response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/p</loc></url>
        </urlset>"""
        response.raise_for_status.return_value = None
        mock_fetch.return_value = response

        urls = loader._extract_urls("https://example.com/sitemap.xml")
        assert "https://example.com/p" in urls

    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_extract_urls_not_sitemap(self, mock_fetch):
        loader = SitemapLoader()

        response = MagicMock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://example.com/page"
        response.text = "<html>Normal page</html>"
        response.raise_for_status.return_value = None
        mock_fetch.return_value = response

        urls = loader._extract_urls("https://example.com/page")
        assert urls == ["https://example.com/page"]

    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_extract_urls_http_error(self, mock_fetch):
        loader = SitemapLoader()
        mock_fetch.side_effect = requests.exceptions.HTTPError("404")

        urls = loader._extract_urls("https://example.com/missing")
        assert urls == []

    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_extract_urls_connection_error(self, mock_fetch):
        loader = SitemapLoader()
        mock_fetch.side_effect = requests.exceptions.ConnectionError()

        urls = loader._extract_urls("https://example.com/bad")
        assert urls == []

    def test_extract_urls_ssrf_blocked(self):
        from docsgpt.security.safe_url import UnsafeUserUrlError

        loader = SitemapLoader()

        with patch(
            "docsgpt.parser.remote.sitemap_loader.fetch_page",
            side_effect=UnsafeUserUrlError("blocked"),
        ):
            urls = loader._extract_urls("http://169.254.169.254/")
            assert urls == []


# =====================================================================
# load_data
# =====================================================================


def _page_response(text: str) -> MagicMock:
    """A fetched HTML page, shaped like a ``requests.Response``."""
    response = MagicMock()
    response.text = text
    response.content = text.encode()
    response.headers = {"Content-Type": "text/html; charset=utf-8"}
    response.raise_for_status.return_value = None
    return response


@pytest.mark.unit
class TestSitemapLoaderLoadData:

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_load_data_success(self, mock_fetch, mock_validate):
        loader = SitemapLoader(limit=10)
        mock_validate.side_effect = lambda url: url
        mock_fetch.return_value = _page_response("Page body")

        with patch.object(
            loader, "_extract_urls",
            return_value=["https://example.com/page1"]
        ):
            docs = loader.load_data("https://example.com/sitemap.xml")
            assert len(docs) == 1
            assert isinstance(docs[0], Document)
            assert docs[0].text == "Page body"
            assert docs[0].extra_info == {
                "source": "https://example.com/page1",
                "file_path": "page1.md",
            }

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    def test_load_data_no_urls(self, mock_validate):
        loader = SitemapLoader()

        with patch.object(loader, "_extract_urls", return_value=[]):
            docs = loader.load_data("https://example.com/empty-sitemap.xml")
            assert docs == []

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_load_data_list_input(self, mock_fetch, mock_validate):
        loader = SitemapLoader()
        mock_validate.side_effect = lambda url: url
        mock_fetch.return_value = _page_response("List body")

        with patch.object(
            loader, "_extract_urls",
            return_value=["https://example.com/page1"]
        ):
            docs = loader.load_data(["https://example.com/sitemap.xml"])
            assert len(docs) == 1
            assert docs[0].text == "List body"

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_load_data_respects_limit(self, mock_fetch, mock_validate):
        loader = SitemapLoader(limit=2)
        mock_validate.side_effect = lambda url: url
        mock_fetch.return_value = _page_response("Limited body")

        urls = [f"https://example.com/page{i}" for i in range(10)]
        with patch.object(loader, "_extract_urls", return_value=urls):
            docs = loader.load_data("https://example.com/sitemap.xml")
            assert len(docs) == 2
            assert mock_fetch.call_count == 2

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_load_data_handles_url_error(self, mock_fetch, mock_validate):
        loader = SitemapLoader()
        mock_validate.side_effect = lambda url: url
        mock_fetch.side_effect = Exception("Load failed")

        with patch.object(
            loader, "_extract_urls",
            return_value=["https://example.com/broken"]
        ):
            docs = loader.load_data("https://example.com/sitemap.xml")
            assert docs == []

    def test_load_data_ssrf_blocked(self):
        from docsgpt.core.url_validation import SSRFError

        loader = SitemapLoader()

        with patch(
            "docsgpt.parser.remote.sitemap_loader.validate_url",
            side_effect=SSRFError("blocked"),
        ):
            docs = loader.load_data("http://169.254.169.254/")
            assert docs == []

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_load_data_no_limit(self, mock_fetch, mock_validate):
        loader = SitemapLoader(limit=None)
        mock_validate.side_effect = lambda url: url
        mock_fetch.return_value = _page_response("No limit body")

        urls = [f"https://example.com/page{i}" for i in range(5)]
        with patch.object(loader, "_extract_urls", return_value=urls):
            docs = loader.load_data("https://example.com/sitemap.xml")
            assert len(docs) == 5


@pytest.mark.unit
class TestSitemapLoaderDistinctPaths:
    @patch("docsgpt.parser.remote.sitemap_loader.validate_url", side_effect=lambda url: url)
    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_colliding_pages_get_distinct_file_paths(self, mock_fetch, mock_validate):
        loader = SitemapLoader(limit=None)
        mock_fetch.return_value = _page_response("Page body")
        urls =["https://x.io/p?page=2", "https://x.io/p", "https://x.io/p.htm"]

        with patch.object(loader, "_extract_urls", return_value=urls):
            docs = loader.load_data("https://x.io/sitemap.xml")

        assert [d.extra_info["file_path"] for d in docs] == ["p__page=2.md", "p.md", "p-2.md"]


@pytest.mark.unit
class TestSitemapLoaderMalformedEntry:

    @patch("docsgpt.core.url_validation.resolve_hostname", return_value="93.184.216.34")
    @patch("docsgpt.parser.remote.sitemap_loader.fetch_page")
    def test_malformed_entry_is_skipped_and_the_rest_ingest(self, mock_fetch, _mock_resolve):
        loader = SitemapLoader()
        mock_fetch.return_value = _page_response("Good body")

        with patch.object(
            loader, "_extract_urls",
            return_value=["http://[bad", "https://example.com/good"],
        ):
            docs = loader.load_data("https://example.com/sitemap.xml")

        assert [d.extra_info for d in docs] == [
            {"source": "https://example.com/good", "file_path": "good.md"}
        ]
        mock_fetch.assert_called_once()


# =====================================================================
# Nested sitemap safety (#3036)
# =====================================================================


def _sitemap_index(*children):
    locs = "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</sitemapindex>'
    ).encode()


def _urlset(*pages):
    locs = "".join(f"<url><loc>{p}</loc></url>" for p in pages)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'
    ).encode()


def _serve(sites):
    """A ``fetch_page`` stand-in that answers from a URL -> XML bytes map."""

    def fake(url, *_, **__):
        body = sites[url]
        response = MagicMock()
        response.headers = {"Content-Type": "application/xml"}
        response.url = url
        response.content = body
        response.text = body.decode("utf-8", "replace")
        response.raise_for_status.return_value = None
        return response

    return MagicMock(side_effect=fake)


@pytest.mark.unit
class TestNestedSitemapSafety:

    def test_self_referencing_index_is_fetched_once(self):
        url = "https://example.com/sitemap.xml"
        fake = _serve({url: _sitemap_index(url)})
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            urls = SitemapLoader()._extract_urls(url)

        assert urls == []
        assert fake.call_count == 1

    def test_mutually_referencing_indexes_are_each_fetched_once(self):
        a = "https://example.com/a.xml"
        b = "https://example.com/b.xml"
        fake = _serve({
            a: _sitemap_index(b),
            b: _sitemap_index(a),
        })
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            SitemapLoader()._extract_urls(a)

        fetched = [call.args[0] for call in fake.call_args_list]
        assert sorted(fetched) == [a, b]

    def test_nesting_deeper_than_the_cap_stops(self, caplog):
        from docsgpt.parser.remote.sitemap_loader import MAX_SITEMAP_DEPTH

        chain = [f"https://example.com/s{i}.xml" for i in range(MAX_SITEMAP_DEPTH + 5)]
        sites = {u: _sitemap_index(chain[i + 1]) for i, u in enumerate(chain[:-1])}
        sites[chain[-1]] = _urlset("https://example.com/deep")
        fake = _serve(sites)
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            urls = SitemapLoader()._extract_urls(chain[0])

        assert urls == []
        assert fake.call_count == MAX_SITEMAP_DEPTH + 1
        assert "depth" in caplog.text.lower()

    def test_elements_that_never_close_stop_the_reading(self, caplog):
        # Every element is dropped once it closes; one that never closes was
        # kept, so a small gzip of nested open tags held gigabytes.
        import tracemalloc

        from docsgpt.parser.remote.sitemap_loader import MAX_XML_NESTING, _read_entries

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
        from docsgpt.parser.remote.sitemap_loader import _read_entries

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
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            urls = SitemapLoader(limit=3)._extract_urls(index)

        assert len(urls) >= 3
        assert fake.call_count <= 4

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
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            urls = SitemapLoader(limit=3)._extract_urls(root)

        fetched_children = [c.args[0] for c in fake.call_args_list if c.args[0] in children]
        assert fetched_children == [children[0]]
        assert urls == ["https://example.com/a", "https://example.com/b", "https://example.com/child-page0"]

    def test_limit_caps_leaf_urls_in_one_sitemap(self):
        url = "https://example.com/sitemap.xml"
        fake = _serve({url: _urlset(*[f"https://example.com/p{i}" for i in range(10)])})
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            urls = SitemapLoader(limit=3)._extract_urls(url)

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
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            urls = SitemapLoader()._extract_urls(index)

        assert urls == ["https://example.com/ok"]


NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


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

    def test_the_declared_encoding_is_honoured(self):
        xml = (
            f'<?xml version="1.0" encoding="ISO-8859-1"?><urlset xmlns="{NS}">'
            "<url><loc>https://e.io/caf\xe9</loc></url><url><loc>https://e.io/b</loc></url></urlset>"
        ).encode("latin-1")

        assert SitemapLoader()._parse_sitemap(xml) == ["https://e.io/caf\xe9", "https://e.io/b"]

    def test_a_sitemap_index_with_single_quotes_is_followed(self):
        index = "https://e.io/index.xml"
        child = "https://e.io/child.xml"
        fake = _serve({
            index: f"<sitemapindex xmlns='{NS}'><sitemap><loc>{child}</loc></sitemap></sitemapindex>".encode(),
            child: _urlset("https://e.io/a"),
        })
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
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
        import tracemalloc

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
        from docsgpt.parser.remote import sitemap_loader

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
        import gc
        import weakref

        from docsgpt.parser.remote import sitemap_loader

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

    @pytest.mark.parametrize("codec", ["GBK", "Shift_JIS", "EUC-KR", "Big5", "ISO-8859-2"])
    def test_an_encoding_expat_cannot_read_is_decoded(self, codec):
        xml = (
            f'<?xml version="1.0" encoding="{codec}"?><urlset xmlns="{NS}">'
            "<url><loc>https://e.io/a</loc></url><url><loc>https://e.io/b</loc></url></urlset>"
        ).encode(codec)

        assert SitemapLoader()._parse_sitemap(xml) == ["https://e.io/a", "https://e.io/b"]

    def test_a_multibyte_encoding_keeps_its_characters(self):
        xml = (
            f"<?xml version='1.0' encoding='Shift_JIS'?><urlset xmlns='{NS}'>"
            "<url><loc>https://e.io/文書</loc></url></urlset>"
        ).encode("shift_jis")

        assert SitemapLoader()._parse_sitemap(xml) == ["https://e.io/文書"]

    def test_an_unknown_encoding_label_is_read_as_utf8(self):
        xml = (
            f'<?xml version="1.0" encoding="x-no-such-charset"?><urlset xmlns="{NS}">'
            "<url><loc>https://e.io/café</loc></url></urlset>"
        ).encode()

        assert SitemapLoader()._parse_sitemap(xml) == ["https://e.io/café"]

    def test_a_sitemap_in_an_unreadable_encoding_does_not_stop_the_walk(self):
        index = "https://e.io/index.xml"
        bad = "https://e.io/bad.xml"
        good = "https://e.io/good.xml"
        fake = _serve({
            index: _sitemap_index(bad, good),
            bad: b'<?xml version="1.0" encoding="GBK"?><urlset><url><loc>https://e.io/x</loc></url></urlset>',
            good: _urlset("https://e.io/ok"),
        })
        with patch("docsgpt.parser.remote.sitemap_loader.fetch_page", fake):
            urls = SitemapLoader().collect_urls([index])

        assert urls == ["https://e.io/x", "https://e.io/ok"]
