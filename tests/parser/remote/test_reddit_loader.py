import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from application.parser.remote.reddit_loader import RedditPostsLoaderRemote


def _post(post_id, title, body):
    post = MagicMock()
    post.id = post_id
    post.title = title
    post.selftext = body
    post.subreddit_name_prefixed = "r/python"
    post.score = 42
    post.url = f"https://reddit.com/{post_id}"
    post.author = "someone"
    return post


def _fake_praw(posts):
    """Install a stub ``praw`` module whose listings yield ``posts``."""
    praw = types.ModuleType("praw")
    reddit = MagicMock()
    listing = MagicMock()
    listing.new.return_value = posts
    listing.hot.return_value = posts
    reddit.subreddit.return_value = listing
    reddit.redditor.return_value = MagicMock(submissions=listing)
    praw.Reddit = MagicMock(return_value=reddit)
    return praw, reddit, listing


BASE_PAYLOAD = {
    "client_id": "cid",
    "client_secret": "csecret",
    "user_agent": "ua",
    "search_queries": ["python"],
}


@pytest.mark.unit
class TestRedditPostsLoaderRemote:
    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON input"):
            RedditPostsLoaderRemote().load_data("not a json")

    def test_missing_required_fields_raises(self):
        with pytest.raises(ValueError, match="Missing required fields") as exc:
            RedditPostsLoaderRemote().load_data(json.dumps({"client_id": "id"}))
        assert "client_secret" in str(exc.value)

    def test_invalid_mode_raises(self):
        payload = {**BASE_PAYLOAD, "mode": "comments"}
        praw, _, _ = _fake_praw([])
        with patch.dict(sys.modules, {"praw": praw}):
            with pytest.raises(ValueError, match="username.*subreddit|subreddit"):
                RedditPostsLoaderRemote().load_data(json.dumps(payload))

    def test_subreddit_mode_returns_documents(self):
        praw, reddit, listing = _fake_praw([_post("p1", "First", "Body one")])
        with patch.dict(sys.modules, {"praw": praw}):
            docs = RedditPostsLoaderRemote().load_data(json.dumps(BASE_PAYLOAD))

        praw.Reddit.assert_called_once_with(
            client_id="cid", client_secret="csecret", user_agent="ua"
        )
        reddit.subreddit.assert_called_with("python")
        # Default categories are new + hot, so the single post arrives twice.
        assert len(docs) == 2
        assert docs[0].text == "Body one"
        assert docs[0].doc_id == "p1"
        assert docs[0].extra_info["title"] == "First"
        assert docs[0].extra_info["source"] == "https://reddit.com/p1"
        assert docs[0].extra_info["post_category"] == "new"

    def test_documents_convert_to_vector_format(self):
        """The remote base class calls to_vector_format on every result."""
        praw, _, _ = _fake_praw([_post("p1", "First", "Body one")])
        with patch.dict(sys.modules, {"praw": praw}):
            docs = RedditPostsLoaderRemote().load_data(json.dumps(BASE_PAYLOAD))
        converted = docs[0].to_vector_format()
        assert converted.page_content == "Body one"
        assert converted.metadata["title"] == "First"

    def test_username_mode_uses_redditor_submissions(self):
        payload = {**BASE_PAYLOAD, "mode": "username", "categories": ["new"]}
        praw, reddit, _ = _fake_praw([_post("p2", "Second", "Body two")])
        with patch.dict(sys.modules, {"praw": praw}):
            docs = RedditPostsLoaderRemote().load_data(json.dumps(payload))

        reddit.redditor.assert_called_with("python")
        assert len(docs) == 1 and docs[0].text == "Body two"

    def test_number_posts_and_categories_are_forwarded(self):
        payload = {**BASE_PAYLOAD, "categories": ["hot"], "number_posts": 3}
        praw, _, listing = _fake_praw([])
        with patch.dict(sys.modules, {"praw": praw}):
            RedditPostsLoaderRemote().load_data(json.dumps(payload))
        listing.hot.assert_called_once_with(limit=3)
        listing.new.assert_not_called()
