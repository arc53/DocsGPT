"""Tests for docsgpt.parser.remote.remote_creator."""

import json

import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.unit
class TestRemoteCreator:
    def test_create_loader_valid_type(self):
        """Cover line 34: returns loader instance for valid type."""
        from docsgpt.parser.remote.remote_creator import RemoteCreator

        mock_loader_cls = MagicMock()
        original_loaders = RemoteCreator.loaders.copy()
        RemoteCreator.loaders["url"] = mock_loader_cls
        try:
            RemoteCreator.create_loader("url")
            mock_loader_cls.assert_called_once()
        finally:
            RemoteCreator.loaders = original_loaders

    def test_create_loader_invalid_type_raises(self):
        """Cover lines 32-33: raises ValueError for unknown type."""
        from docsgpt.parser.remote.remote_creator import RemoteCreator

        with pytest.raises(ValueError, match="No loader class found"):
            RemoteCreator.create_loader("nonexistent_xyz")

    def test_create_loader_case_insensitive(self):
        """Cover line 31: type.lower() normalization."""
        from docsgpt.parser.remote.remote_creator import RemoteCreator

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
        from docsgpt.parser.remote.remote_creator import RemoteCreator
        from docsgpt.parser.remote.website_loader import WebsiteLoader

        assert isinstance(RemoteCreator.create_loader("website"), WebsiteLoader)

    @pytest.mark.parametrize("stored", [CONFIG, json.dumps(CONFIG)])
    def test_normalize_returns_the_validated_config(self, stored):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("website", stored)

        assert result["entries"][0]["discovery"] == "auto"
        assert result["skip"] == ["https://x.io/old"]

    def test_normalize_drops_an_unsyncable_config(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("website", {"entries": []}) is None
        assert normalize_remote_data("website", "https://x.io") is None

    def test_normalize_reads_a_config_over_a_lowered_cap(self):
        # The page cap is a write limit; a sync of a stored source still runs.
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        stored = {"entries": [{"url": f"https://x.io/{i}", "mode": "page"} for i in range(3)]}
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            config = normalize_remote_data("website", stored)

        assert config is not None and len(config["entries"]) == 3

    def test_normalize_drops_a_config_with_a_bad_url(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("website", {"entries": [{"url": "http://[x", "mode": "page"}]}) is None


@pytest.mark.unit
class TestNormalizeRemoteData:
    """``normalize_remote_data`` maps a stored JSONB ``remote_data`` value
    back to the ``source_data`` shape each loader expects."""

    def test_none_passes_through(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("crawler", None) is None

    def test_crawler_dict_with_url_key(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "crawler", {"url": "https://example.com", "provider": "crawler"}
        )
        assert result == "https://example.com"

    def test_url_dict_with_url_key(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("url", {"url": "https://example.com"})
        assert result == "https://example.com"

    def test_url_legacy_raw_key(self):
        """Legacy rows wrapped a bare URL string as ``{"raw": ...}``."""
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("crawler", {"raw": "https://legacy.example.com"})
        assert result == "https://legacy.example.com"

    def test_url_dict_with_urls_list(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "url", {"urls": ["https://a.example.com", "https://b.example.com"]}
        )
        assert result == ["https://a.example.com", "https://b.example.com"]

    def test_github_repo_url_key(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "github", {"repo_url": "https://github.com/arc53/DocsGPT"}
        )
        assert result == "https://github.com/arc53/DocsGPT"

    def test_sitemap_dict_with_url_key(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("sitemap", {"url": "https://example.com/sitemap.xml"})
        assert result == "https://example.com/sitemap.xml"

    def test_plain_string_url_passes_through(self):
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("crawler", "https://example.com") == "https://example.com"

    def test_url_dict_without_url_key_returns_none(self):
        """A URL-type loader must never receive a dict, even a malformed one."""
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("crawler", {"provider": "crawler"}) is None

    def test_reddit_dict_serialized_to_json_string(self):
        """reddit's loader runs json.loads() — it needs a JSON string."""
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "reddit", {"client_id": "x", "search_queries": ["y"]}
        )
        assert isinstance(result, str)
        assert json.loads(result) == {"client_id": "x", "search_queries": ["y"]}

    def test_s3_dict_passes_through(self):
        """S3Loader.load_data() accepts a dict, so it is left untouched."""
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        data = {"bucket": "b", "prefix": "k"}
        assert normalize_remote_data("s3", data) == data

    def test_json_string_remote_data_is_parsed(self):
        """Legacy rows that stored the JSON itself as a string still resolve."""
        from docsgpt.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("crawler", '{"url": "https://example.com"}')
        assert result == "https://example.com"
