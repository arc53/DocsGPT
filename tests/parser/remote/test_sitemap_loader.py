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
            loader, "_extract_urls",
            return_value=["https://example.com/page1"]
        ):
            urls = loader._parse_sitemap(parent_xml)
            assert "https://example.com/page1" in urls

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

    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_extract_urls_from_sitemap(self, mock_pinned_request):
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
        mock_pinned_request.return_value = response

        urls = loader._extract_urls("https://example.com/sitemap.xml")
        assert "https://example.com/p" in urls

    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_extract_urls_not_sitemap(self, mock_pinned_request):
        loader = SitemapLoader()

        response = MagicMock()
        response.headers = {"Content-Type": "text/html"}
        response.url = "https://example.com/page"
        response.text = "<html>Normal page</html>"
        response.raise_for_status.return_value = None
        mock_pinned_request.return_value = response

        urls = loader._extract_urls("https://example.com/page")
        assert urls == ["https://example.com/page"]

    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_extract_urls_http_error(self, mock_pinned_request):
        loader = SitemapLoader()
        mock_pinned_request.side_effect = requests.exceptions.HTTPError("404")

        urls = loader._extract_urls("https://example.com/missing")
        assert urls == []

    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_extract_urls_connection_error(self, mock_pinned_request):
        loader = SitemapLoader()
        mock_pinned_request.side_effect = requests.exceptions.ConnectionError()

        urls = loader._extract_urls("https://example.com/bad")
        assert urls == []

    def test_extract_urls_ssrf_blocked(self):
        from docsgpt.security.safe_url import UnsafeUserUrlError

        loader = SitemapLoader()

        with patch(
            "docsgpt.parser.remote.sitemap_loader.pinned_request",
            side_effect=UnsafeUserUrlError("blocked"),
        ):
            urls = loader._extract_urls("http://169.254.169.254/")
            assert urls == []


# =====================================================================
# load_data
# =====================================================================


@pytest.mark.unit
class TestSitemapLoaderLoadData:

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_load_data_success(self, mock_pinned_request, mock_validate):
        loader = SitemapLoader(limit=10)
        mock_validate.side_effect = lambda url: url
        response = MagicMock()
        response.text = "Page body"
        response.raise_for_status.return_value = None
        mock_pinned_request.return_value = response

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
    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_load_data_list_input(self, mock_pinned_request, mock_validate):
        loader = SitemapLoader()
        mock_validate.side_effect = lambda url: url
        response = MagicMock()
        response.text = "List body"
        response.raise_for_status.return_value = None
        mock_pinned_request.return_value = response

        with patch.object(
            loader, "_extract_urls",
            return_value=["https://example.com/page1"]
        ):
            docs = loader.load_data(["https://example.com/sitemap.xml"])
            assert len(docs) == 1
            assert docs[0].text == "List body"

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_load_data_respects_limit(self, mock_pinned_request, mock_validate):
        loader = SitemapLoader(limit=2)
        mock_validate.side_effect = lambda url: url
        response = MagicMock()
        response.text = "Limited body"
        response.raise_for_status.return_value = None
        mock_pinned_request.return_value = response

        urls = [f"https://example.com/page{i}" for i in range(10)]
        with patch.object(loader, "_extract_urls", return_value=urls):
            docs = loader.load_data("https://example.com/sitemap.xml")
            assert len(docs) == 2
            assert mock_pinned_request.call_count == 2

    @patch("docsgpt.parser.remote.sitemap_loader.validate_url")
    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_load_data_handles_url_error(self, mock_pinned_request, mock_validate):
        loader = SitemapLoader()
        mock_validate.side_effect = lambda url: url
        mock_pinned_request.side_effect = Exception("Load failed")

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
    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_load_data_no_limit(self, mock_pinned_request, mock_validate):
        loader = SitemapLoader(limit=None)
        mock_validate.side_effect = lambda url: url
        response = MagicMock()
        response.text = "No limit body"
        response.raise_for_status.return_value = None
        mock_pinned_request.return_value = response

        urls = [f"https://example.com/page{i}" for i in range(5)]
        with patch.object(loader, "_extract_urls", return_value=urls):
            docs = loader.load_data("https://example.com/sitemap.xml")
            assert len(docs) == 5


@pytest.mark.unit
class TestSitemapLoaderDistinctPaths:
    @patch("docsgpt.parser.remote.sitemap_loader.validate_url", side_effect=lambda url: url)
    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_colliding_pages_get_distinct_file_paths(self, mock_pinned_request, mock_validate):
        loader = SitemapLoader(limit=None)
        response = MagicMock()
        response.text = "Page body"
        response.raise_for_status.return_value = None
        mock_pinned_request.return_value = response
        urls = ["https://x.io/p?page=2", "https://x.io/p", "https://x.io/p.htm"]

        with patch.object(loader, "_extract_urls", return_value=urls):
            docs = loader.load_data("https://x.io/sitemap.xml")

        assert [d.extra_info["file_path"] for d in docs] == ["p__page=2.md", "p.md", "p-2.md"]


@pytest.mark.unit
class TestSitemapLoaderMalformedEntry:

    @patch("docsgpt.core.url_validation.resolve_hostname", return_value="93.184.216.34")
    @patch("docsgpt.parser.remote.sitemap_loader.pinned_request")
    def test_malformed_entry_is_skipped_and_the_rest_ingest(self, mock_pinned_request, _mock_resolve):
        loader = SitemapLoader()
        response = MagicMock()
        response.text = "Good body"
        response.raise_for_status.return_value = None
        mock_pinned_request.return_value = response

        with patch.object(
            loader, "_extract_urls",
            return_value=["http://[bad", "https://example.com/good"],
        ):
            docs = loader.load_data("https://example.com/sitemap.xml")

        assert [d.extra_info for d in docs] == [
            {"source": "https://example.com/good", "file_path": "good.md"}
        ]
        mock_pinned_request.assert_called_once()


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
    """A ``pinned_request`` stand-in that answers from a URL -> XML bytes map."""

    def fake(method, url, **kwargs):
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
        with patch("docsgpt.parser.remote.sitemap_loader.pinned_request", fake):
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
        with patch("docsgpt.parser.remote.sitemap_loader.pinned_request", fake):
            SitemapLoader()._extract_urls(a)

        fetched = [call.args[1] for call in fake.call_args_list]
        assert sorted(fetched) == [a, b]

    def test_nesting_deeper_than_the_cap_stops(self, caplog):
        from docsgpt.parser.remote.sitemap_loader import MAX_SITEMAP_DEPTH

        chain = [f"https://example.com/s{i}.xml" for i in range(MAX_SITEMAP_DEPTH + 5)]
        sites = {u: _sitemap_index(chain[i + 1]) for i, u in enumerate(chain[:-1])}
        sites[chain[-1]] = _urlset("https://example.com/deep")
        fake = _serve(sites)
        with patch("docsgpt.parser.remote.sitemap_loader.pinned_request", fake):
            urls = SitemapLoader()._extract_urls(chain[0])

        assert urls == []
        assert fake.call_count == MAX_SITEMAP_DEPTH + 1
        assert "depth" in caplog.text.lower()

    def test_limit_stops_following_child_sitemaps(self):
        index = "https://example.com/index.xml"
        children = [f"https://example.com/child{i}.xml" for i in range(50)]
        sites = {index: _sitemap_index(*children)}
        for i, child in enumerate(children):
            sites[child] = _urlset(f"https://example.com/page{i}")
        fake = _serve(sites)
        with patch("docsgpt.parser.remote.sitemap_loader.pinned_request", fake):
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
        with patch("docsgpt.parser.remote.sitemap_loader.pinned_request", fake):
            urls = SitemapLoader(limit=3)._extract_urls(root)

        fetched_children = [c.args[1] for c in fake.call_args_list if c.args[1] in children]
        assert fetched_children == [children[0]]
        assert urls == ["https://example.com/a", "https://example.com/b", "https://example.com/child-page0"]

    def test_limit_caps_leaf_urls_in_one_sitemap(self):
        url = "https://example.com/sitemap.xml"
        fake = _serve({url: _urlset(*[f"https://example.com/p{i}" for i in range(10)])})
        with patch("docsgpt.parser.remote.sitemap_loader.pinned_request", fake):
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
        with patch("docsgpt.parser.remote.sitemap_loader.pinned_request", fake):
            urls = SitemapLoader()._extract_urls(index)

        assert urls == ["https://example.com/ok"]
