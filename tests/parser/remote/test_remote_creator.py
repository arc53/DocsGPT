"""Tests for docsgpt.parser.remote.remote_creator."""

import json

import pytest
from unittest.mock import MagicMock, patch

from docsgpt.parser.remote.remote_creator import RemoteCreator, normalize_remote_data
from docsgpt.parser.remote.website_loader import WebsiteLoader


@pytest.mark.unit
class TestRemoteCreator:
    def test_create_loader_valid_type(self):
        mock_loader_cls = MagicMock()
        original_loaders = RemoteCreator.loaders.copy()
        RemoteCreator.loaders["url"] = mock_loader_cls
        try:
            RemoteCreator.create_loader("url")
            mock_loader_cls.assert_called_once()
        finally:
            RemoteCreator.loaders = original_loaders

    def test_create_loader_invalid_type_raises(self):
        with pytest.raises(ValueError, match="No loader class found"):
            RemoteCreator.create_loader("nonexistent_xyz")

    def test_create_loader_case_insensitive(self):
        mock_loader_cls = MagicMock()
        original_loaders = RemoteCreator.loaders.copy()
        RemoteCreator.loaders["sitemap"] = mock_loader_cls
        try:
            RemoteCreator.create_loader("SITEMAP")
            mock_loader_cls.assert_called_once()
        finally:
            RemoteCreator.loaders = original_loaders


@pytest.mark.unit
class TestWebsiteType:
    CONFIG = {"entries": [{"url": "https://x.io/", "mode": "site"}], "skip": ["https://x.io/old"]}

    def test_website_is_a_registered_loader(self):
        assert isinstance(RemoteCreator.create_loader("website"), WebsiteLoader)

    @pytest.mark.parametrize("stored", [CONFIG, json.dumps(CONFIG)])
    def test_normalize_returns_the_validated_config(self, stored):
        result = normalize_remote_data("website", stored)

        assert result["entries"][0]["discovery"] == "auto"
        assert result["skip"] == ["https://x.io/old"]

    def test_normalize_drops_an_unsyncable_config(self):
        assert normalize_remote_data("website", {"entries": []}) is None
        assert normalize_remote_data("website", "https://x.io") is None

    def test_normalize_reads_a_config_over_a_lowered_cap(self):
        # The page cap is a write limit; a sync of a stored source still runs.
        stored = {"entries": [{"url": f"https://x.io/{i}", "mode": "page"} for i in range(3)]}
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            config = normalize_remote_data("website", stored)

        assert config is not None and len(config["entries"]) == 3

    def test_normalize_drops_a_config_with_a_bad_url(self):
        assert normalize_remote_data("website", {"entries": [{"url": "http://[x", "mode": "page"}]}) is None


@pytest.mark.unit
class TestLegacyWebTypes:
    """url, crawler and sitemap sources load through the Website loader, as the config they convert to."""

    @pytest.mark.parametrize("source_type", ["url", "crawler", "sitemap"])
    def test_each_is_a_website_loader(self, source_type):
        assert isinstance(RemoteCreator.create_loader(source_type), WebsiteLoader)

    @pytest.mark.parametrize(
        "source_type, stored, expected",
        [
            ("url", {"url": "https://example.com"}, [("https://example.com", "page")]),
            ("url", {"urls": ["https://a.example.com", "https://b.example.com"]},
             [("https://a.example.com", "page"), ("https://b.example.com", "page")]),
            ("crawler", {"url": "https://example.com", "provider": "crawler"}, [("https://example.com", "site")]),
            # Legacy rows wrapped a bare URL string as ``{"raw": ...}``, or stored the JSON as a string.
            ("crawler", {"raw": "https://legacy.example.com"}, [("https://legacy.example.com", "site")]),
            ("crawler", '{"url": "https://example.com"}', [("https://example.com", "site")]),
            ("crawler", "https://example.com", [("https://example.com", "site")]),
            ("sitemap", {"url": "https://example.com/sitemap.xml"}, [("https://example.com/sitemap.xml", "site")]),
        ],
    )
    def test_normalize_returns_the_converted_config(self, source_type, stored, expected):
        config = normalize_remote_data(source_type, stored)

        assert [(e["url"], e["mode"]) for e in config["entries"]] == expected

    @pytest.mark.parametrize("stored", [None, {"provider": "crawler"}, "http://[bad"])
    def test_normalize_drops_a_row_with_nothing_to_fetch(self, stored):
        assert normalize_remote_data("crawler", stored) is None

    @pytest.mark.parametrize("source_type", ["url", "crawler", "sitemap"])
    def test_a_website_config_stored_on_a_legacy_row_still_syncs(self, source_type):
        stored = {"entries": [{"url": "https://x.io/a", "mode": "page"}], "skip": ["https://x.io/old"]}

        for value in (stored, json.dumps(stored)):
            config = normalize_remote_data(source_type, value)

            assert config["entries"][0]["url"] == "https://x.io/a"
            assert config["skip"] == ["https://x.io/old"]

    @pytest.mark.parametrize(
        "inputs",
        [
            # A sync hands the loader the converted config ...
            {"entries": [{"url": "https://x.io/", "mode": "site", "discovery": "links", "max_pages": 10}]},
            # ... a new upload the address it was given.
            "https://x.io/",
        ],
    )
    def test_the_loader_runs_the_website_load(self, inputs):
        loader = RemoteCreator.create_loader("crawler")
        report = {"url": "https://x.io/", "found_with": None, "pages": 0, "limit_reached": False}
        with patch.object(WebsiteLoader, "_load_site", return_value=([], report)) as load_site:
            assert loader.load_data(inputs) == []

        entry = load_site.call_args.args[0]
        assert (entry["url"], entry["discovery"], entry["max_pages"]) == ("https://x.io/", "links", 10)
        # The site is loaded against the Website load's fetch budget, deadline included.
        assert load_site.call_args.args[4].deadline is not None
        assert loader.report["sites"] == [report]

    def test_an_upload_with_no_web_address_loads_nothing(self):
        loader = RemoteCreator.create_loader("url")

        assert loader.load_data("not a url at all") == []
        assert loader.report["pages"] == 0


@pytest.mark.unit
class TestNormalizeRemoteData:
    """``normalize_remote_data`` maps a stored JSONB ``remote_data`` value
    back to the ``source_data`` shape each loader expects."""

    def test_none_passes_through(self):
        assert normalize_remote_data("github", None) is None

    def test_github_repo_url_key(self):
        result = normalize_remote_data("github", {"repo_url": "https://github.com/arc53/DocsGPT"})
        assert result == "https://github.com/arc53/DocsGPT"

    def test_github_dict_without_url_key_returns_none(self):
        """A URL-type loader must never receive a dict, even a malformed one."""
        assert normalize_remote_data("github", {"provider": "github"}) is None

    def test_reddit_dict_serialized_to_json_string(self):
        """reddit's loader runs json.loads() — it needs a JSON string."""
        result = normalize_remote_data("reddit", {"client_id": "x", "search_queries": ["y"]})
        assert isinstance(result, str)
        assert json.loads(result) == {"client_id": "x", "search_queries": ["y"]}

    def test_s3_dict_passes_through(self):
        """S3Loader.load_data() accepts a dict, so it is left untouched."""
        data = {"bucket": "b", "prefix": "k"}
        assert normalize_remote_data("s3", data) == data

    def test_json_string_remote_data_is_parsed(self):
        """Legacy rows that stored the JSON itself as a string still resolve."""
        result = normalize_remote_data("github", '{"repo_url": "https://github.com/a/b"}')
        assert result == "https://github.com/a/b"
