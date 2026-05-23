"""Comprehensive tests for application/parser/remote/sitemap_loader.py

Covers: SitemapLoader (init, load_data, _extract_urls, _is_sitemap,
_parse_sitemap, URL validation, error handling).
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from application.parser.remote.sitemap_loader import SitemapLoader
from application.parser.schema.base import Document


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


# =====================================================================
# _extract_urls
# =====================================================================


@pytest.mark.unit
class TestExtractUrls:

    @patch("application.parser.remote.sitemap_loader.pinned_request")
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

    @patch("application.parser.remote.sitemap_loader.pinned_request")
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

    @patch("application.parser.remote.sitemap_loader.pinned_request")
    def test_extract_urls_http_error(self, mock_pinned_request):
        loader = SitemapLoader()
        mock_pinned_request.side_effect = requests.exceptions.HTTPError("404")

        urls = loader._extract_urls("https://example.com/missing")
        assert urls == []

    @patch("application.parser.remote.sitemap_loader.pinned_request")
    def test_extract_urls_connection_error(self, mock_pinned_request):
        loader = SitemapLoader()
        mock_pinned_request.side_effect = requests.exceptions.ConnectionError()

        urls = loader._extract_urls("https://example.com/bad")
        assert urls == []

    def test_extract_urls_ssrf_blocked(self):
        from application.security.safe_url import UnsafeUserUrlError

        loader = SitemapLoader()

        with patch(
            "application.parser.remote.sitemap_loader.pinned_request",
            side_effect=UnsafeUserUrlError("blocked"),
        ):
            urls = loader._extract_urls("http://169.254.169.254/")
            assert urls == []


# =====================================================================
# load_data
# =====================================================================


@pytest.mark.unit
class TestSitemapLoaderLoadData:

    @patch("application.parser.remote.sitemap_loader.validate_url")
    @patch("application.parser.remote.sitemap_loader.pinned_request")
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
            assert docs[0].extra_info == {"source": "https://example.com/page1"}

    @patch("application.parser.remote.sitemap_loader.validate_url")
    def test_load_data_no_urls(self, mock_validate):
        loader = SitemapLoader()

        with patch.object(loader, "_extract_urls", return_value=[]):
            docs = loader.load_data("https://example.com/empty-sitemap.xml")
            assert docs == []

    @patch("application.parser.remote.sitemap_loader.validate_url")
    @patch("application.parser.remote.sitemap_loader.pinned_request")
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

    @patch("application.parser.remote.sitemap_loader.validate_url")
    @patch("application.parser.remote.sitemap_loader.pinned_request")
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

    @patch("application.parser.remote.sitemap_loader.validate_url")
    @patch("application.parser.remote.sitemap_loader.pinned_request")
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
        from application.core.url_validation import SSRFError

        loader = SitemapLoader()

        with patch(
            "application.parser.remote.sitemap_loader.validate_url",
            side_effect=SSRFError("blocked"),
        ):
            docs = loader.load_data("http://169.254.169.254/")
            assert docs == []

    @patch("application.parser.remote.sitemap_loader.validate_url")
    @patch("application.parser.remote.sitemap_loader.pinned_request")
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
