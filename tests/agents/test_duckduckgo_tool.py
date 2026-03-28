"""Tests for application/agents/tools/duckduckgo.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.agents.tools.duckduckgo import DuckDuckGoSearchTool


@pytest.fixture
def tool():
    return DuckDuckGoSearchTool(config={})


@pytest.mark.unit
class TestDuckDuckGoExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("invalid")

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_web_search_success(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.text.return_value = [
            {"title": "Result 1", "href": "https://example.com", "body": "snippet"}
        ]
        mock_client_factory.return_value = mock_client

        result = tool.execute_action("ddg_web_search", query="python")

        assert result["status_code"] == 200
        assert len(result["results"]) == 1
        assert "successfully" in result["message"]

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_image_search_success(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.images.return_value = [{"image": "https://img.com/1.jpg"}]
        mock_client_factory.return_value = mock_client

        result = tool.execute_action("ddg_image_search", query="cats")

        assert result["status_code"] == 200
        assert len(result["results"]) == 1

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_news_search_success(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.news.return_value = [{"title": "News"}]
        mock_client_factory.return_value = mock_client

        result = tool.execute_action("ddg_news_search", query="tech")

        assert result["status_code"] == 200
        assert len(result["results"]) == 1

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_search_error_returns_500(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.text.side_effect = Exception("Network error")
        mock_client_factory.return_value = mock_client

        result = tool.execute_action("ddg_web_search", query="test")

        assert result["status_code"] == 500
        assert "failed" in result["message"].lower()
        assert result["results"] == []

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_max_results_capped_at_20(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.text.return_value = []
        mock_client_factory.return_value = mock_client

        tool.execute_action("ddg_web_search", query="test", max_results=100)

        call_kwargs = mock_client.text.call_args[1]
        assert call_kwargs["max_results"] == 20

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_image_max_results_capped_at_50(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.images.return_value = []
        mock_client_factory.return_value = mock_client

        tool.execute_action("ddg_image_search", query="test", max_results=200)

        call_kwargs = mock_client.images.call_args[1]
        assert call_kwargs["max_results"] == 50

    @patch("application.agents.tools.duckduckgo.time.sleep")
    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_rate_limit_retries(self, mock_client_factory, mock_sleep, tool):
        mock_client = MagicMock()
        mock_client.text.side_effect = [
            Exception("RateLimit exceeded"),
            [{"title": "Result"}],
        ]
        mock_client_factory.return_value = mock_client

        result = tool.execute_action("ddg_web_search", query="test")

        assert result["status_code"] == 200
        assert len(result["results"]) == 1
        mock_sleep.assert_called_once()

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_empty_results(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.text.return_value = []
        mock_client_factory.return_value = mock_client

        result = tool.execute_action("ddg_web_search", query="obscure query")

        assert result["status_code"] == 200
        assert result["results"] == []

    @patch.object(DuckDuckGoSearchTool, "_get_ddgs_client")
    def test_none_results(self, mock_client_factory, tool):
        mock_client = MagicMock()
        mock_client.text.return_value = None
        mock_client_factory.return_value = mock_client

        result = tool.execute_action("ddg_web_search", query="test")

        assert result["status_code"] == 200
        assert result["results"] == []


@pytest.mark.unit
class TestDuckDuckGoMetadata:
    def test_actions_metadata(self, tool):
        meta = tool.get_actions_metadata()
        assert len(meta) == 3
        names = {a["name"] for a in meta}
        assert "ddg_web_search" in names
        assert "ddg_image_search" in names
        assert "ddg_news_search" in names

    def test_config_requirements(self, tool):
        assert tool.get_config_requirements() == {}

    def test_custom_timeout(self):
        tool = DuckDuckGoSearchTool(config={"timeout": 30})
        assert tool.timeout == 30
