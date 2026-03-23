import logging
import os
from typing import Any, Dict, Optional

from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)


class TavilySearchTool(Tool):
    """
    Tavily Search
    A tool for performing web and news searches using the Tavily Search API.
    Requires a TAVILY_API_KEY for authentication.
    """

    def __init__(self, config):
        self.config = config
        self.api_key = config.get("token", "") or os.environ.get(
            "TAVILY_API_KEY", ""
        )

    def _get_client(self):
        from tavily import TavilyClient

        return TavilyClient(api_key=self.api_key)

    def execute_action(self, action_name, **kwargs):
        actions = {
            "tavily_web_search": self._web_search,
            "tavily_news_search": self._news_search,
        }
        if action_name not in actions:
            raise ValueError(f"Unknown action: {action_name}")
        return actions[action_name](**kwargs)

    def _web_search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: Optional[list] = None,
        exclude_domains: Optional[list] = None,
        time_range: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Tavily web search: {query}")
        try:
            client = self._get_client()
            kwargs: Dict[str, Any] = {
                "query": query,
                "max_results": min(max_results, 20),
                "search_depth": search_depth,
                "topic": "general",
            }
            if include_domains:
                kwargs["include_domains"] = include_domains
            if exclude_domains:
                kwargs["exclude_domains"] = exclude_domains
            if time_range:
                kwargs["time_range"] = time_range

            response = client.search(**kwargs)
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0),
                }
                for r in response.get("results", [])
            ]
            return {
                "status_code": 200,
                "results": results,
                "message": "Web search completed successfully.",
            }
        except Exception as e:
            logger.error(f"Tavily web search failed: {e}")
            return {
                "status_code": 500,
                "results": [],
                "message": f"Web search failed: {str(e)}",
            }

    def _news_search(
        self,
        query: str,
        max_results: int = 5,
        time_range: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Tavily news search: {query}")
        try:
            client = self._get_client()
            kwargs: Dict[str, Any] = {
                "query": query,
                "max_results": min(max_results, 20),
                "topic": "news",
            }
            if time_range:
                kwargs["time_range"] = time_range

            response = client.search(**kwargs)
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0),
                }
                for r in response.get("results", [])
            ]
            return {
                "status_code": 200,
                "results": results,
                "message": "News search completed successfully.",
            }
        except Exception as e:
            logger.error(f"Tavily news search failed: {e}")
            return {
                "status_code": 500,
                "results": [],
                "message": f"News search failed: {str(e)}",
            }

    def get_actions_metadata(self):
        return [
            {
                "name": "tavily_web_search",
                "description": "Search the web using Tavily. Returns titles, URLs, content snippets, and relevance scores.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (max 400 characters)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default: 5, max: 20)",
                        },
                        "search_depth": {
                            "type": "string",
                            "description": "Search depth: basic (fast) or advanced (thorough, 2 credits)",
                        },
                        "time_range": {
                            "type": "string",
                            "description": "Time filter: d (day), w (week), m (month), y (year)",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "tavily_news_search",
                "description": "Search for recent news articles using Tavily. Returns news with titles, URLs, and summaries.",
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
                        "time_range": {
                            "type": "string",
                            "description": "Time filter: d (day), w (week), m (month), y (year)",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        return {
            "token": {
                "type": "string",
                "label": "API Key",
                "description": "Tavily API key for authentication (or set TAVILY_API_KEY env var)",
                "required": True,
                "secret": True,
                "order": 1,
            },
        }
