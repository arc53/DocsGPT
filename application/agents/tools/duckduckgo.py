import logging
import time
from typing import Any, Dict, Optional

from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2.0
DEFAULT_TIMEOUT = 15


class DuckDuckGoSearchTool(Tool):
    """
    DuckDuckGo Search
    A tool for performing web and image searches using DuckDuckGo.
    """

    def __init__(self, config):
        self.config = config
        self.timeout = config.get("timeout", DEFAULT_TIMEOUT)

    def _get_ddgs_client(self):
        from ddgs import DDGS

        return DDGS(timeout=self.timeout)

    def _execute_with_retry(self, operation, operation_name: str) -> Dict[str, Any]:
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                results = operation()
                return {
                    "status_code": 200,
                    "results": list(results) if results else [],
                    "message": f"{operation_name} completed successfully.",
                }
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "ratelimit" in error_str or "429" in error_str:
                    if attempt < MAX_RETRIES:
                        delay = RETRY_DELAY * attempt
                        logger.warning(
                            f"{operation_name} rate limited, retrying in {delay}s (attempt {attempt}/{MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        continue
                logger.error(f"{operation_name} failed: {e}")
                break
        return {
            "status_code": 500,
            "results": [],
            "message": f"{operation_name} failed: {str(last_error)}",
        }

    def execute_action(self, action_name, **kwargs):
        actions = {
            "ddg_web_search": self._web_search,
            "ddg_image_search": self._image_search,
            "ddg_news_search": self._news_search,
        }
        if action_name not in actions:
            raise ValueError(f"Unknown action: {action_name}")
        return actions[action_name](**kwargs)

    def _web_search(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"DuckDuckGo web search: {query}")

        def operation():
            client = self._get_ddgs_client()
            return client.text(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=min(max_results, 20),
            )

        return self._execute_with_retry(operation, "Web search")

    def _image_search(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"DuckDuckGo image search: {query}")

        def operation():
            client = self._get_ddgs_client()
            return client.images(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=min(max_results, 50),
            )

        return self._execute_with_retry(operation, "Image search")

    def _news_search(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"DuckDuckGo news search: {query}")

        def operation():
            client = self._get_ddgs_client()
            return client.news(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=min(max_results, 20),
            )

        return self._execute_with_retry(operation, "News search")

    def get_actions_metadata(self):
        return [
            {
                "name": "ddg_web_search",
                "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default: 5, max: 20)",
                        },
                        "region": {
                            "type": "string",
                            "description": "Region code (default: wt-wt for worldwide, us-en for US)",
                        },
                        "timelimit": {
                            "type": "string",
                            "description": "Time filter: d (day), w (week), m (month), y (year)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "ddg_image_search",
                "description": "Search for images using DuckDuckGo. Returns image URLs and metadata.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Image search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default: 5, max: 50)",
                        },
                        "region": {
                            "type": "string",
                            "description": "Region code (default: wt-wt for worldwide)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "ddg_news_search",
                "description": "Search for news articles using DuckDuckGo. Returns recent news.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "News search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default: 5, max: 20)",
                        },
                        "timelimit": {
                            "type": "string",
                            "description": "Time filter: d (day), w (week), m (month)",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    def get_config_requirements(self):
        return {}
