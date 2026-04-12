"""Tests for application/agents/tools/brave.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.agents.tools.brave import BraveSearchTool


@pytest.fixture
def tool():
    return BraveSearchTool(config={"token": "test_api_key"})


@pytest.mark.unit
class TestBraveExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("invalid")

    @patch("application.agents.tools.brave.requests.get")
    def test_web_search_success(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"web": {"results": [{"title": "Result"}]}}
        mock_get.return_value = mock_resp

        result = tool.execute_action("brave_web_search", query="python")

        assert result["status_code"] == 200
        assert "results" in result
        assert "successfully" in result["message"]

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["headers"]["X-Subscription-Token"] == "test_api_key"

    @patch("application.agents.tools.brave.requests.get")
    def test_web_search_failure(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp

        result = tool.execute_action("brave_web_search", query="test")

        assert result["status_code"] == 429
        assert "failed" in result["message"].lower()

    @patch("application.agents.tools.brave.requests.get")
    def test_image_search_success(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"url": "https://img.com/1.jpg"}]}
        mock_get.return_value = mock_resp

        result = tool.execute_action("brave_image_search", query="cats")

        assert result["status_code"] == 200
        assert "results" in result

    @patch("application.agents.tools.brave.requests.get")
    def test_image_search_failure(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        result = tool.execute_action("brave_image_search", query="cats")

        assert result["status_code"] == 500

    @patch("application.agents.tools.brave.requests.get")
    def test_count_capped_at_20(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        tool.execute_action("brave_web_search", query="test", count=100)

        params = mock_get.call_args[1]["params"]
        assert params["count"] == 20

    @patch("application.agents.tools.brave.requests.get")
    def test_image_count_capped_at_100(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        tool.execute_action("brave_image_search", query="test", count=500)

        params = mock_get.call_args[1]["params"]
        assert params["count"] == 100

    @patch("application.agents.tools.brave.requests.get")
    def test_freshness_param(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        tool.execute_action("brave_web_search", query="news", freshness="pd")

        params = mock_get.call_args[1]["params"]
        assert params["freshness"] == "pd"

    @patch("application.agents.tools.brave.requests.get")
    def test_offset_capped(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        tool.execute_action("brave_web_search", query="test", offset=100)

        params = mock_get.call_args[1]["params"]
        assert params["offset"] == 9


@pytest.mark.unit
class TestBraveMetadata:
    def test_actions_metadata(self, tool):
        meta = tool.get_actions_metadata()
        assert len(meta) == 2
        names = {a["name"] for a in meta}
        assert "brave_web_search" in names
        assert "brave_image_search" in names

    def test_config_requirements(self, tool):
        reqs = tool.get_config_requirements()
        assert "token" in reqs
        assert reqs["token"]["secret"] is True
        assert reqs["token"]["required"] is True
