import logging
from typing import Any

import requests

from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)

API_URL = "https://xquik.com/api/v1/x/tweets/search"
API_CONTRACT = "2026-04-29"
DEFAULT_TIMEOUT = 30
MAX_RESULTS = 100
SEARCH_ARGUMENTS = frozenset({"query", "query_type", "max_results", "cursor"})


def _bounded_integer(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Return an integer constrained to the inclusive bounds."""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _error_result(status_code: int, message: str, **details: str) -> dict[str, Any]:
    """Return a failure payload recognized by the tool executor."""

    return {
        "status": "error",
        "status_code": status_code,
        "results": [],
        "message": message,
        **details,
    }


class XquikSearchTool(Tool):
    """Xquik Search

    Search current X posts through the Xquik API.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Configure the API credential and request timeout."""

        self.config = config
        configured_key = config.get("api_key")
        self.api_key = configured_key.strip() if isinstance(configured_key, str) else ""
        self.timeout = _bounded_integer(config.get("timeout"), DEFAULT_TIMEOUT, 1, 300)

    def execute_action(self, action_name: str, **kwargs: Any) -> dict[str, Any]:
        """Run a supported Xquik action."""

        if action_name != "xquik_search_posts":
            raise ValueError(f"Unknown action: {action_name}")
        if set(kwargs) - SEARCH_ARGUMENTS:
            return _error_result(
                400,
                "Unsupported search parameter. Remove extra fields.",
            )
        return self._search_posts(**kwargs)

    @staticmethod
    def _error_message(payload: Any, status_code: int) -> str:
        """Extract public API guidance without returning the response body."""

        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str) and message:
                return message
            error = payload.get("error")
            if isinstance(error, dict):
                structured_message = error.get("message")
                if isinstance(structured_message, str) and structured_message:
                    return structured_message
            if isinstance(error, str) and error:
                return error.replace("_", " ").capitalize() + "."
        return f"Xquik search failed with status code: {status_code}."

    def _search_posts(
        self,
        query: str = "",
        query_type: str = "Latest",
        max_results: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Search X posts and return normalized DocsGPT tool output."""

        if not self.api_key:
            return _error_result(
                401,
                "Xquik API key required. Configure the tool first.",
            )
        if not isinstance(query, str) or not query.strip():
            return _error_result(400, "Search query required. Enter a query first.")

        normalized_query_type = str(query_type).strip().title()
        if normalized_query_type not in {"Latest", "Top"}:
            return _error_result(400, "Invalid result order. Use Latest or Top.")
        if cursor is not None and not isinstance(cursor, str):
            return _error_result(
                400,
                "Invalid cursor. Use the cursor returned by Xquik.",
            )

        params: dict[str, str | int] = {
            "q": query,
            "queryType": normalized_query_type,
            "limit": _bounded_integer(max_results, 20, 1, MAX_RESULTS),
        }
        if cursor:
            params["cursor"] = cursor

        try:
            response = requests.get(
                API_URL,
                params=params,
                headers={
                    "Accept": "application/json",
                    "x-api-key": self.api_key,
                    "xquik-api-contract": API_CONTRACT,
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            logger.warning(
                "Xquik X post search request failed: %s",
                error.__class__.__name__,
            )
            return _error_result(503, "Xquik search is unavailable. Try again.")

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code != 200:
            retry_after = response.headers.get("Retry-After")
            return _error_result(
                response.status_code,
                self._error_message(payload, response.status_code),
                **({"retry_after": retry_after} if retry_after else {}),
            )

        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("tweets"), list)
            or not all(isinstance(tweet, dict) for tweet in payload["tweets"])
        ):
            return _error_result(
                502,
                "Xquik returned an invalid search response. Try again.",
            )

        has_next_page = payload.get("has_next_page", False)
        next_cursor = payload.get("next_cursor", "")
        if not isinstance(has_next_page, bool) or not isinstance(next_cursor, str):
            return _error_result(
                502,
                "Xquik returned an invalid search response. Try again.",
            )

        return {
            "status_code": 200,
            "results": payload["tweets"],
            "has_next_page": has_next_page,
            "next_cursor": next_cursor,
            "message": "X post search completed successfully.",
        }

    def get_actions_metadata(self) -> list[dict[str, Any]]:
        """Describe the search action for agent tool selection."""

        return [
            {
                "name": "xquik_search_posts",
                "description": (
                    "Search current X posts with Xquik. Returns post text, "
                    "authors, engagement, and cursor pagination. Use it for "
                    "current X discussions or account activity not found in "
                    "the user's documents."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": ("X search query, post ID, or status URL. Send the user's query unchanged."),
                            "required": True,
                        },
                        "query_type": {
                            "type": "string",
                            "enum": ["Latest", "Top"],
                            "default": "Latest",
                            "description": ("Latest returns chronological posts. Top ranks engagement."),
                        },
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_RESULTS,
                            "default": 20,
                            "description": "Maximum posts to return (default: 20, max: 100)",
                        },
                        "cursor": {
                            "type": "string",
                            "description": ("Cursor from a previous result page. Pass it unchanged."),
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ]

    def get_config_requirements(self) -> dict[str, dict[str, Any]]:
        """Describe the encrypted credential and timeout configuration."""

        return {
            "api_key": {
                "type": "string",
                "label": "Xquik API key",
                "description": "API key from xquik.com/settings/api-keys",
                "required": True,
                "secret": True,
                "order": 1,
            },
            "timeout": {
                "type": "number",
                "label": "Timeout (seconds)",
                "description": "Request timeout in seconds (1-300)",
                "default": DEFAULT_TIMEOUT,
                "required": False,
                "secret": False,
                "order": 2,
            },
        }
