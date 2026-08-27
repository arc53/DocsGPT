"""Tests for the Xquik X post search tool."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from application.agents.tools.xquik import XquikSearchTool


@pytest.fixture
def tool():
    return XquikSearchTool(config={"api_key": "xq_test_key"})


def response(status_code=200, payload=None, headers=None):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = headers or {}
    mock_response.json.return_value = payload
    return mock_response


@pytest.mark.unit
class TestXquikExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("invalid")

    @patch("application.agents.tools.xquik.requests.get")
    def test_missing_api_key_fails_before_request(self, mock_get):
        result = XquikSearchTool(config={}).execute_action("xquik_search_posts", query="DocsGPT")

        assert result == {
            "status": "error",
            "status_code": 401,
            "results": [],
            "message": "Xquik API key required. Configure the tool first.",
        }
        mock_get.assert_not_called()

    @patch("application.agents.tools.xquik.requests.get")
    def test_non_string_api_key_fails_before_request(self, mock_get):
        result = XquikSearchTool(config={"api_key": None}).execute_action("xquik_search_posts", query="DocsGPT")

        assert result["status_code"] == 401
        mock_get.assert_not_called()

    @patch("application.agents.tools.xquik.requests.get")
    def test_blank_query_fails_before_request(self, mock_get, tool):
        result = tool.execute_action("xquik_search_posts", query="  ")

        assert result["status_code"] == 400
        assert result["results"] == []
        mock_get.assert_not_called()

    @patch("application.agents.tools.xquik.requests.get")
    def test_invalid_query_type_fails_before_request(self, mock_get, tool):
        result = tool.execute_action("xquik_search_posts", query="DocsGPT", query_type="Popular")

        assert result["status_code"] == 400
        assert "Latest or Top" in result["message"]
        mock_get.assert_not_called()

    @patch("application.agents.tools.xquik.requests.get")
    def test_invalid_cursor_fails_before_request(self, mock_get, tool):
        result = tool.execute_action("xquik_search_posts", query="DocsGPT", cursor=123)

        assert result["status_code"] == 400
        assert "cursor" in result["message"].lower()
        mock_get.assert_not_called()

    @pytest.mark.parametrize(("requested", "expected"), [(0, 1), (20, 20), (500, 100)])
    @patch("application.agents.tools.xquik.requests.get")
    def test_result_limit_is_bounded(self, mock_get, requested, expected, tool):
        mock_get.return_value = response(payload={"tweets": [], "has_next_page": False, "next_cursor": ""})

        tool.execute_action("xquik_search_posts", query="DocsGPT", max_results=requested)

        assert mock_get.call_args.kwargs["params"]["limit"] == expected

    @patch("application.agents.tools.xquik.requests.get")
    def test_success_uses_published_contract_and_preserves_pagination(self, mock_get, tool):
        tweets = [
            {
                "id": "123",
                "url": "https://x.com/arc53/status/123",
                "text": "DocsGPT release",
                "author": {"username": "arc53"},
            }
        ]
        mock_get.return_value = response(
            payload={
                "tweets": tweets,
                "has_next_page": True,
                "next_cursor": "cursor-2",
            }
        )

        result = tool.execute_action(
            "xquik_search_posts",
            query="DocsGPT release",
            query_type="top",
            max_results=12,
            cursor="cursor-1",
        )

        assert result == {
            "status_code": 200,
            "results": tweets,
            "has_next_page": True,
            "next_cursor": "cursor-2",
            "message": "X post search completed successfully.",
        }
        mock_get.assert_called_once_with(
            "https://xquik.com/api/v1/x/tweets/search",
            params={
                "q": "DocsGPT release",
                "queryType": "Top",
                "limit": 12,
                "cursor": "cursor-1",
            },
            headers={
                "Accept": "application/json",
                "x-api-key": "xq_test_key",
                "xquik-api-contract": "2026-04-29",
            },
            timeout=30,
            allow_redirects=False,
        )

    @patch("application.agents.tools.xquik.requests.get")
    def test_empty_success_defaults_missing_pagination_fields(self, mock_get, tool):
        mock_get.return_value = response(payload={"tweets": []})

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result["results"] == []
        assert result["has_next_page"] is False
        assert result["next_cursor"] == ""

    @pytest.mark.parametrize(
        "payload",
        [None, [], {}, {"tweets": "not-a-list"}, {"tweets": ["not-an-object"]}],
    )
    @patch("application.agents.tools.xquik.requests.get")
    def test_malformed_success_returns_gateway_error(self, mock_get, payload, tool):
        mock_get.return_value = response(payload=payload)

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result == {
            "status": "error",
            "status_code": 502,
            "results": [],
            "message": "Xquik returned an invalid search response. Try again.",
        }

    @patch("application.agents.tools.xquik.requests.get")
    def test_non_json_success_returns_gateway_error(self, mock_get, tool):
        mock_response = response(payload=None)
        mock_response.json.side_effect = ValueError("invalid JSON")
        mock_get.return_value = mock_response

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result["status_code"] == 502
        assert result["results"] == []

    @pytest.mark.parametrize(
        "payload",
        [
            {"tweets": [], "has_next_page": "false", "next_cursor": ""},
            {"tweets": [], "has_next_page": False, "next_cursor": None},
        ],
    )
    @patch("application.agents.tools.xquik.requests.get")
    def test_invalid_pagination_returns_gateway_error(self, mock_get, payload, tool):
        mock_get.return_value = response(payload=payload)

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result["status_code"] == 502
        assert result["results"] == []

    @patch("application.agents.tools.xquik.requests.get")
    def test_structured_error_preserves_guidance_and_retry_delay(self, mock_get, tool):
        mock_get.return_value = response(
            status_code=429,
            payload={
                "error": {
                    "message": "Rate limit reached. Retry later.",
                    "type": "rate_limit_error",
                    "code": "rate_limited",
                }
            },
            headers={"Retry-After": "4"},
        )

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result == {
            "status": "error",
            "status_code": 429,
            "results": [],
            "message": "Rate limit reached. Retry later.",
            "retry_after": "4",
        }

    @patch("application.agents.tools.xquik.requests.get")
    def test_legacy_error_uses_message_without_exposing_response(self, mock_get, tool):
        mock_get.return_value = response(
            status_code=402,
            payload={"error": "no_credits", "message": "Credits required. Add credits first."},
        )

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result["status_code"] == 402
        assert result["message"] == "Credits required. Add credits first."
        assert result["results"] == []

    @patch("application.agents.tools.xquik.requests.get")
    def test_legacy_error_code_becomes_readable(self, mock_get, tool):
        mock_get.return_value = response(
            status_code=402,
            payload={"error": "no_credits"},
        )

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result["message"] == "No credits."

    @patch("application.agents.tools.xquik.requests.get")
    def test_non_json_error_uses_status_code(self, mock_get, tool):
        mock_response = response(status_code=500, payload=None)
        mock_response.json.side_effect = ValueError("invalid JSON")
        mock_get.return_value = mock_response

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result["message"] == "Xquik search failed with status code: 500."

    @patch("application.agents.tools.xquik.requests.get")
    def test_network_error_returns_secret_safe_failure(self, mock_get, tool):
        mock_get.side_effect = requests.Timeout("xq_test_key timed out")

        result = tool.execute_action("xquik_search_posts", query="DocsGPT")

        assert result == {
            "status": "error",
            "status_code": 503,
            "results": [],
            "message": "Xquik search is unavailable. Try again.",
        }
        assert "xq_test_key" not in str(result)


@pytest.mark.unit
class TestXquikMetadata:
    def test_docstring_exposes_catalog_name_and_description(self):
        name, description = XquikSearchTool.__doc__.strip().split("\n", 1)

        assert name == "Xquik Search"
        assert description.strip() == "Search current X posts through the Xquik API."

    def test_actions_metadata_declares_search_contract(self, tool):
        metadata = tool.get_actions_metadata()

        assert len(metadata) == 1
        action = metadata[0]
        assert action["name"] == "xquik_search_posts"
        assert action["parameters"]["required"] == ["query"]
        assert action["parameters"]["properties"]["query_type"]["enum"] == [
            "Latest",
            "Top",
        ]
        assert action["parameters"]["additionalProperties"] is False

    def test_config_requirements_keep_api_key_secret(self, tool):
        requirements = tool.get_config_requirements()

        assert requirements["api_key"]["required"] is True
        assert requirements["api_key"]["secret"] is True
        assert requirements["timeout"]["default"] == 30

    @pytest.mark.parametrize(("configured", "expected"), [("60", 60), ("bad", 30), (500, 300)])
    def test_timeout_is_normalized(self, configured, expected):
        assert XquikSearchTool({"timeout": configured}).timeout == expected
