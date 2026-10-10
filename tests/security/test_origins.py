"""Origin normalization and the origin a request came from."""

from __future__ import annotations

import pytest

from docsgpt.security.origins import canonical_origin, normalize_origin, request_origin


@pytest.mark.unit
class TestNormalizeOrigin:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://example.com", "https://example.com"),
            ("HTTPS://Example.COM", "https://example.com"),
            ("https://example.com/", "https://example.com"),
            ("https://example.com/docs/page?q=1#top", "https://example.com"),
            ("https://example.com:443", "https://example.com"),
            ("http://example.com:80", "http://example.com"),
            ("https://example.com:8443", "https://example.com:8443"),
            ("http://localhost:5173", "http://localhost:5173"),
            ("http://[::1]:8080/x", "http://[::1]:8080"),
            ("  https://example.com  ", "https://example.com"),
        ],
    )
    def test_normalizes(self, url, expected):
        assert normalize_origin(url) == expected

    @pytest.mark.parametrize(
        "url", [None, "", "example.com", "ftp://example.com", "https://", "https://example.com:99999", "null"]
    )
    def test_rejects_non_origins(self, url):
        assert normalize_origin(url) is None


@pytest.mark.unit
class TestCanonicalOrigin:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://Example.com/", "https://example.com"),
            ("http://localhost:3000", "http://localhost:3000"),
            ("https://example.com:443", "https://example.com"),
            ("https://bücher.de", "https://xn--bcher-kva.de"),
            ("http://[::1]:8080", "http://[::1]:8080"),
            ("  https://docs.example.com  ", "https://docs.example.com"),
        ],
    )
    def test_canonical_form(self, value, expected):
        assert canonical_origin(value) == expected

    @pytest.mark.parametrize(
        "value, message",
        [
            ("", "cannot be empty"),
            ("example.com", "must start with http:// or https://"),
            ("ftp://example.com", "must start with http:// or https://"),
            ("https://", "has no host"),
            ("https://example.com/path", "without a path"),
            ("https://example.com/?q=1", "without a path"),
            ("https://example.com/#frag", "without a path"),
            ("https://*.example.com", "wildcard"),
            ("https://user:pass@example.com", "credentials"),
            ("https://example.com:99999", "not a valid origin"),
        ],
    )
    def test_refuses_what_is_not_an_origin(self, value, message):
        with pytest.raises(ValueError, match=message):
            canonical_origin(value)

    def test_matches_what_a_browser_sends(self):
        # A stored entry and the request's Origin header compare by equality.
        assert canonical_origin("https://Bücher.de/") == request_origin({"Origin": "https://xn--bcher-kva.de"})


@pytest.mark.unit
class TestRequestOrigin:
    def test_origin_header(self):
        assert request_origin({"Origin": "https://Example.com"}) == "https://example.com"

    def test_origin_wins_over_referer(self):
        headers = {"Origin": "https://a.com", "Referer": "https://b.com/page"}
        assert request_origin(headers) == "https://a.com"

    def test_referer_stands_in_without_origin(self):
        assert request_origin({"Referer": "https://b.com/docs/page?x=1"}) == "https://b.com"

    def test_opaque_null_origin_names_none(self):
        # A sandboxed frame says ``null``; its Referer must not let it through.
        assert request_origin({"Origin": "null", "Referer": "https://b.com/page"}) is None

    def test_empty_origin_falls_back_to_referer(self):
        assert request_origin({"Origin": "", "Referer": "https://b.com/"}) == "https://b.com"

    def test_no_headers(self):
        assert request_origin({}) is None

    def test_lowercase_header_names(self):
        # FastMCP's get_http_headers returns a plain dict with lowercase names.
        assert request_origin({"origin": "https://a.com"}) == "https://a.com"
        assert request_origin({"referer": "https://b.com/x"}) == "https://b.com"
