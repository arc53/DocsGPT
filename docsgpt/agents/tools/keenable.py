import logging

import requests

from docsgpt.agents.tools.base import Tool

logger = logging.getLogger(__name__)

BASE_URL = "https://api.keenable.ai/v1"
APP_TITLE = "DocsGPT"
DEFAULT_TIMEOUT = 30
MAX_RESULTS_LIMIT = 50


class KeenableSearchTool(Tool):
    """
    Keenable Search
    Web search and page fetch from Keenable's independent web index.
    Works without an API key (rate limited per IP); an optional key lifts the limit.
    """

    def __init__(self, config):
        self.config = config
        self.token = (config.get("token") or "").strip()
        self.timeout = config.get("timeout", DEFAULT_TIMEOUT)

    def _endpoint(self, name):
        # Keyless calls go to the public endpoints, which require an app title header.
        if self.token:
            return f"{BASE_URL}/{name}"
        return f"{BASE_URL}/{name}/public"

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-API-Key"] = self.token
        else:
            headers["X-Keenable-Title"] = APP_TITLE
        return headers

    def execute_action(self, action_name, **kwargs):
        actions = {
            "keenable_web_search": self._web_search,
            "keenable_fetch_page": self._fetch_page,
        }

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _web_search(
        self,
        query,
        max_results=10,
        site=None,
        published_after=None,
    ):
        """
        Performs a web search with the Keenable Search API.
        """
        logger.debug("Performing Keenable web search for: %s", query)

        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 10
        body = {
            "query": query,
            "max_results": max(1, min(max_results, MAX_RESULTS_LIMIT)),
        }
        if site:
            body["site"] = site
        if published_after:
            body["published_after"] = published_after

        try:
            response = requests.post(
                self._endpoint("search"),
                json=body,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            logger.error("Keenable web search failed: %s", e)
            return {
                "status_code": 500,
                "results": [],
                "message": f"Search failed: {e}",
            }

        if response.status_code == 200:
            results = [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet") or item.get("description", ""),
                    "published_at": item.get("published_at"),
                }
                for item in response.json().get("results", [])
            ]
            return {
                "status_code": response.status_code,
                "results": results,
                "message": "Search completed successfully.",
            }
        return {
            "status_code": response.status_code,
            "results": [],
            "message": f"Search failed with status code: {response.status_code}.",
        }

    def _fetch_page(self, url, max_chars=20000, live=False):
        """
        Fetches a page as clean markdown with the Keenable Fetch API.
        """
        logger.debug("Fetching page with Keenable: %s", url)

        params = {"url": url, "max_chars": max_chars}
        if live:
            params["live"] = "true"

        try:
            response = requests.get(
                self._endpoint("fetch"),
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            logger.error("Keenable fetch failed: %s", e)
            return {"status_code": 500, "message": f"Fetch failed: {e}"}

        if response.status_code == 200:
            data = response.json()
            return {
                "status_code": response.status_code,
                "url": data.get("url", url),
                "title": data.get("title", ""),
                "content": data.get("content", ""),
                "message": "Page fetched successfully.",
            }
        return {
            "status_code": response.status_code,
            "message": f"Fetch failed with status code: {response.status_code}.",
        }

    def get_actions_metadata(self):
        return [
            {
                "name": "keenable_web_search",
                "access": "read",
                "description": (
                    "Search the web with Keenable. Returns result titles, URLs, "
                    "snippets and publish dates. Use it for current events or "
                    "information not found in the user's documents."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results to return (1-50, default: 10)",
                        },
                        "site": {
                            "type": "string",
                            "description": "Restrict results to one site, e.g. docs.python.org",
                        },
                        "published_after": {
                            "type": "string",
                            "description": "Only pages published after this date (YYYY-MM-DD)",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "keenable_fetch_page",
                "access": "read",
                "description": (
                    "Fetch a web page as clean markdown with Keenable. Use it "
                    "to read a result from keenable_web_search in full."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL of the page to fetch",
                        },
                        "live": {
                            "type": "boolean",
                            "description": "Fetch the page live instead of from the index (for pages that are not indexed)",
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        return {
            "token": {
                "type": "string",
                "label": "API Key",
                "description": (
                    "Optional Keenable API key. Without one, requests use the "
                    "keyless public endpoint, which is rate limited per IP."
                ),
                "required": False,
                "secret": True,
                "order": 1,
            },
        }
