import json
from unittest.mock import patch, MagicMock
import pytest

from application.parser.remote.reddit_loader import RedditPostsLoaderRemote


class TestRedditPostsLoaderRemote:
    def test_invalid_json_raises(self):
        loader = RedditPostsLoaderRemote()
        with pytest.raises(ValueError) as exc:
            loader.load_data("not a json")
        assert "Invalid JSON input" in str(exc.value)

    def test_missing_required_fields_raises(self):
        loader = RedditPostsLoaderRemote()
        payload = json.dumps({"client_id": "id"})
        with pytest.raises(ValueError) as exc:
            loader.load_data(payload)
        assert "Missing required fields" in str(exc.value)
        assert "client_secret" in str(exc.value)

    @patch("application.parser.remote.reddit_loader.RedditPostsLoader")
    def test_constructs_loader_and_loads_with_defaults(self, MockRedditLoader):
        loader = RedditPostsLoaderRemote()

        instance = MagicMock()
        docs = [MagicMock(), MagicMock()]
        instance.load.return_value = docs
        MockRedditLoader.return_value = instance

        payload = {
            "client_id": "cid",
            "client_secret": "csecret",
            "user_agent": "ua",
            "search_queries": ["r/langchain"],
        }

        result = loader.load_data(json.dumps(payload))

        MockRedditLoader.assert_called_once_with(
            client_id="cid",
            client_secret="csecret",
            user_agent="ua",
            categories=["new", "hot"],
            mode="subreddit",
            search_queries=["r/langchain"],
            number_posts=10,
        )
        instance.load.assert_called_once()
        assert result == docs

    @patch("application.parser.remote.reddit_loader.RedditPostsLoader")
    def test_constructs_loader_and_loads_with_overrides(self, MockRedditLoader):
        loader = RedditPostsLoaderRemote()

        instance = MagicMock()
        instance.load.return_value = []
        MockRedditLoader.return_value = instance

        payload = {
            "client_id": "cid",
            "client_secret": "csecret",
            "user_agent": "ua",
            "search_queries": ["python"],
            "categories": ["hot"],
            "mode": "comments",
            "number_posts": 3,
        }

        loader.load_data(json.dumps(payload))

        MockRedditLoader.assert_called_once_with(
            client_id="cid",
            client_secret="csecret",
            user_agent="ua",
            categories=["hot"],
            mode="comments",
            search_queries=["python"],
            number_posts=3,
        )
        instance.load.assert_called_once()

