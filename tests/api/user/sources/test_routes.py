"""Tests for sources routes.

All Mongo-coupled tests (patching ``sources_collection``, using ``mock_mongo_db``,
``ObjectId``) have been removed as part of the MongoDB->Postgres cutover. The
integration suite at ``tests/integration/test_sources.py`` now covers the
route-level behaviour that used to live here.

Only pure helper-function tests that don't touch any datastore remain below.
"""

import json


class TestGetProviderFromRemoteData:
    """Test the _get_provider_from_remote_data helper function."""

    def test_returns_none_for_none_input(self):
        """Should return None when remote_data is None."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data(None)
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Should return None when remote_data is empty string."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data("")
        assert result is None

    def test_extracts_provider_from_dict(self):
        """Should extract provider from dict remote_data."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        remote_data = {"provider": "s3", "bucket": "my-bucket"}
        result = _get_provider_from_remote_data(remote_data)
        assert result == "s3"

    def test_extracts_provider_from_json_string(self):
        """Should extract provider from JSON string remote_data."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        remote_data = json.dumps({"provider": "github", "repo": "test/repo"})
        result = _get_provider_from_remote_data(remote_data)
        assert result == "github"

    def test_returns_none_for_dict_without_provider(self):
        """Should return None when dict has no provider key."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        remote_data = {"bucket": "my-bucket", "region": "us-east-1"}
        result = _get_provider_from_remote_data(remote_data)
        assert result is None

    def test_returns_none_for_invalid_json(self):
        """Should return None for invalid JSON string."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data("not valid json")
        assert result is None

    def test_returns_none_for_json_array(self):
        """Should return None when JSON parses to non-dict."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data('["item1", "item2"]')
        assert result is None

    def test_returns_none_for_non_string_non_dict(self):
        """Should return None for other types like int."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data(123)
        assert result is None
