"""Tests for application.parser.remote.remote_creator."""

import json

import pytest
from unittest.mock import MagicMock


@pytest.mark.unit
class TestRemoteCreator:
    def test_create_loader_valid_type(self):
        """Cover line 34: returns loader instance for valid type."""
        from application.parser.remote.remote_creator import RemoteCreator

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
        from application.parser.remote.remote_creator import RemoteCreator

        with pytest.raises(ValueError, match="No loader class found"):
            RemoteCreator.create_loader("nonexistent_xyz")

    def test_create_loader_case_insensitive(self):
        """Cover line 31: type.lower() normalization."""
        from application.parser.remote.remote_creator import RemoteCreator

        mock_loader_cls = MagicMock()
        original_loaders = RemoteCreator.loaders.copy()
        RemoteCreator.loaders["sitemap"] = mock_loader_cls
        try:
            RemoteCreator.create_loader("SITEMAP")
            mock_loader_cls.assert_called_once()
        finally:
            RemoteCreator.loaders = original_loaders


@pytest.mark.unit
class TestNormalizeRemoteData:
    """``normalize_remote_data`` maps a stored JSONB ``remote_data`` value
    back to the ``source_data`` shape each loader expects."""

    def test_none_passes_through(self):
        from application.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("crawler", None) is None

    def test_crawler_dict_with_url_key(self):
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "crawler", {"url": "https://example.com", "provider": "crawler"}
        )
        assert result == "https://example.com"

    def test_url_dict_with_url_key(self):
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("url", {"url": "https://example.com"})
        assert result == "https://example.com"

    def test_url_legacy_raw_key(self):
        """Legacy rows wrapped a bare URL string as ``{"raw": ...}``."""
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("crawler", {"raw": "https://legacy.example.com"})
        assert result == "https://legacy.example.com"

    def test_url_dict_with_urls_list(self):
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "url", {"urls": ["https://a.example.com", "https://b.example.com"]}
        )
        assert result == ["https://a.example.com", "https://b.example.com"]

    def test_github_repo_url_key(self):
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "github", {"repo_url": "https://github.com/arc53/DocsGPT"}
        )
        assert result == "https://github.com/arc53/DocsGPT"

    def test_sitemap_dict_with_url_key(self):
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("sitemap", {"url": "https://example.com/sitemap.xml"})
        assert result == "https://example.com/sitemap.xml"

    def test_plain_string_url_passes_through(self):
        from application.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("crawler", "https://example.com") == "https://example.com"

    def test_url_dict_without_url_key_returns_none(self):
        """A URL-type loader must never receive a dict, even a malformed one."""
        from application.parser.remote.remote_creator import normalize_remote_data

        assert normalize_remote_data("crawler", {"provider": "crawler"}) is None

    def test_reddit_dict_serialized_to_json_string(self):
        """reddit's loader runs json.loads() — it needs a JSON string."""
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data(
            "reddit", {"client_id": "x", "search_queries": ["y"]}
        )
        assert isinstance(result, str)
        assert json.loads(result) == {"client_id": "x", "search_queries": ["y"]}

    def test_s3_dict_passes_through(self):
        """S3Loader.load_data() accepts a dict, so it is left untouched."""
        from application.parser.remote.remote_creator import normalize_remote_data

        data = {"bucket": "b", "prefix": "k"}
        assert normalize_remote_data("s3", data) == data

    def test_json_string_remote_data_is_parsed(self):
        """Legacy rows that stored the JSON itself as a string still resolve."""
        from application.parser.remote.remote_creator import normalize_remote_data

        result = normalize_remote_data("crawler", '{"url": "https://example.com"}')
        assert result == "https://example.com"
