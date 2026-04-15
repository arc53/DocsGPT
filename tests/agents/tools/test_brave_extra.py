"""Extra tests for brave tool optional params."""

from unittest.mock import MagicMock, patch

import pytest


class TestBraveOptionalParams:
    def test_result_filter_added_to_params(self):
        from application.agents.tools.brave import BraveSearchTool

        tool = BraveSearchTool(config={"token": "tk"})
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {"web": {"results": []}}

        with patch(
            "application.agents.tools.brave.requests.get",
            return_value=fake_response,
        ) as mock_get:
            tool.execute_action(
                "brave_web_search",
                query="x",
                result_filter="news",
            )

        # Called with params including result_filter
        params = mock_get.call_args.kwargs["params"]
        assert params.get("result_filter") == "news"

    def test_extra_snippets_flag(self):
        from application.agents.tools.brave import BraveSearchTool

        tool = BraveSearchTool(config={"token": "tk"})
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {"web": {"results": []}}

        with patch(
            "application.agents.tools.brave.requests.get",
            return_value=fake_response,
        ) as mock_get:
            tool.execute_action(
                "brave_web_search", query="x", extra_snippets=True,
            )
        params = mock_get.call_args.kwargs["params"]
        assert params.get("extra_snippets") == 1

    def test_summary_flag(self):
        from application.agents.tools.brave import BraveSearchTool

        tool = BraveSearchTool(config={"token": "tk"})
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {"web": {"results": []}}

        with patch(
            "application.agents.tools.brave.requests.get",
            return_value=fake_response,
        ) as mock_get:
            tool.execute_action("brave_web_search", query="x", summary=True)
        params = mock_get.call_args.kwargs["params"]
        assert params.get("summary") == 1
