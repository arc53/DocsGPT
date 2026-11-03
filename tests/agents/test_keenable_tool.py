"""Tests for docsgpt/agents/tools/keenable.py"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from docsgpt.agents.tools.keenable import KeenableSearchTool


@pytest.fixture
def keyless_tool():
    return KeenableSearchTool(config={})


@pytest.fixture
def keyed_tool():
    return KeenableSearchTool(config={"token": "keen_test"})


def _response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    return resp


@pytest.mark.unit
class TestKeenableExecuteAction:
    def test_unknown_action_raises(self, keyless_tool):
        with pytest.raises(ValueError, match="Unknown action"):
            keyless_tool.execute_action("invalid")

    @patch("docsgpt.agents.tools.keenable.requests.post")
    def test_keyless_search_uses_public_endpoint(self, mock_post, keyless_tool):
        mock_post.return_value = _response(
            payload={
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.com",
                        "description": "",
                        "snippet": "Some text",
                        "published_at": "2026-01-01T00:00:00Z",
                    }
                ]
            }
        )

        result = keyless_tool.execute_action("keenable_web_search", query="python")

        assert result["status_code"] == 200
        assert result["results"] == [
            {
                "title": "Result",
                "url": "https://example.com",
                "snippet": "Some text",
                "published_at": "2026-01-01T00:00:00Z",
            }
        ]
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.keenable.ai/v1/search/public"
        assert kwargs["headers"]["X-Keenable-Title"] == "DocsGPT"
        assert "X-API-Key" not in kwargs["headers"]
        assert kwargs["json"] == {"query": "python", "max_results": 10}

    @patch("docsgpt.agents.tools.keenable.requests.post")
    def test_keyed_search_uses_api_key(self, mock_post, keyed_tool):
        mock_post.return_value = _response(payload={"results": []})

        keyed_tool.execute_action(
            "keenable_web_search",
            query="python",
            max_results=200,
            site="docs.python.org",
            published_after="2026-01-01",
        )

        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.keenable.ai/v1/search"
        assert kwargs["headers"]["X-API-Key"] == "keen_test"
        assert "X-Keenable-Title" not in kwargs["headers"]
        assert kwargs["json"] == {
            "query": "python",
            "max_results": 50,
            "site": "docs.python.org",
            "published_after": "2026-01-01",
        }

    @patch("docsgpt.agents.tools.keenable.requests.post")
    def test_search_http_error(self, mock_post, keyless_tool):
        mock_post.return_value = _response(status_code=429)

        result = keyless_tool.execute_action("keenable_web_search", query="test")

        assert result["status_code"] == 429
        assert result["results"] == []
        assert "failed" in result["message"].lower()

    @patch("docsgpt.agents.tools.keenable.requests.post")
    def test_search_network_error(self, mock_post, keyless_tool):
        mock_post.side_effect = requests.ConnectionError("boom")

        result = keyless_tool.execute_action("keenable_web_search", query="test")

        assert result["status_code"] == 500
        assert result["results"] == []

    @patch("docsgpt.agents.tools.keenable.requests.get")
    def test_fetch_page_keyless(self, mock_get, keyless_tool):
        mock_get.return_value = _response(
            payload={
                "url": "https://example.com",
                "title": "Example",
                "content": "# Example",
            }
        )

        result = keyless_tool.execute_action(
            "keenable_fetch_page", url="https://example.com", live=True
        )

        assert result["status_code"] == 200
        assert result["content"] == "# Example"
        args, kwargs = mock_get.call_args
        assert args[0] == "https://api.keenable.ai/v1/fetch/public"
        assert kwargs["params"]["url"] == "https://example.com"
        assert kwargs["params"]["live"] == "true"
        assert kwargs["headers"]["X-Keenable-Title"] == "DocsGPT"

    @patch("docsgpt.agents.tools.keenable.requests.get")
    def test_fetch_page_error(self, mock_get, keyed_tool):
        mock_get.return_value = _response(status_code=404)

        result = keyed_tool.execute_action("keenable_fetch_page", url="https://x.y")

        assert result["status_code"] == 404
        assert mock_get.call_args[0][0] == "https://api.keenable.ai/v1/fetch"


@pytest.mark.unit
class TestKeenableMetadata:
    def test_actions_metadata(self, keyless_tool):
        names = [a["name"] for a in keyless_tool.get_actions_metadata()]
        assert names == ["keenable_web_search", "keenable_fetch_page"]

    def test_api_key_is_optional(self, keyless_tool):
        token = keyless_tool.get_config_requirements()["token"]
        assert token["required"] is False
        assert token["secret"] is True
