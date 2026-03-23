import logging

from tavily import TavilyClient

from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)


class TavilySearchTool(Tool):
    """
    Tavily Search
    A tool for performing web searches and URL content extraction using the
    Tavily API. Requires an API key for authentication.
    """

    def __init__(self, config):
        self.config = config
        api_key = config.get("api_key", "")
        self.client = TavilyClient(api_key=api_key)

    def execute_action(self, action_name, **kwargs):
        actions = {
            "tavily_web_search": self._web_search,
            "tavily_extract": self._extract,
        }

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _web_search(
        self,
        query,
        max_results=10,
        search_depth="basic",
        topic="general",
        include_domains=None,
        exclude_domains=None,
    ):
        """
        Performs a web search using the Tavily Search API.
        """
        logger.debug("Performing Tavily web search for: %s", query)

        try:
            params = {
                "query": query,
                "max_results": min(max_results, 20),
                "search_depth": search_depth,
                "topic": topic,
            }
            if include_domains:
                params["include_domains"] = include_domains
            if exclude_domains:
                params["exclude_domains"] = exclude_domains

            response = self.client.search(**params)

            return {
                "status_code": 200,
                "results": response,
                "message": "Search completed successfully.",
            }
        except Exception as e:
            logger.error("Tavily web search failed: %s", str(e))
            return {
                "status_code": 500,
                "message": f"Search failed: {str(e)}",
            }

    def _extract(
        self,
        urls,
        query=None,
        chunks_per_source=3,
    ):
        """
        Extracts content from specified URLs using the Tavily Extract API.
        """
        logger.debug("Performing Tavily extraction for: %s", urls)

        try:
            if isinstance(urls, str):
                urls = [urls]

            params = {
                "urls": urls[:20],
                "chunks_per_source": chunks_per_source,
            }
            if query:
                params["query"] = query

            response = self.client.extract(**params)

            return {
                "status_code": 200,
                "results": response,
                "message": "Extraction completed successfully.",
            }
        except Exception as e:
            logger.error("Tavily extraction failed: %s", str(e))
            return {
                "status_code": 500,
                "message": f"Extraction failed: {str(e)}",
            }

    def get_actions_metadata(self):
        return [
            {
                "name": "tavily_web_search",
                "description": "Perform a web search using Tavily Search",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (max 400 characters)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results to return (max 20, default: 10)",
                        },
                        "search_depth": {
                            "type": "string",
                            "description": "Search depth: 'basic' (fast) or 'advanced' (highest relevance)",
                        },
                        "topic": {
                            "type": "string",
                            "description": "Search topic: 'general', 'news', or 'finance'",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "tavily_extract",
                "description": "Extract content from specified URLs using Tavily",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of URLs to extract content from (max 20)",
                        },
                        "query": {
                            "type": "string",
                            "description": "Optional query to rerank extracted chunks by relevance",
                        },
                    },
                    "required": ["urls"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        return {
            "api_key": {
                "type": "string",
                "label": "API Key",
                "description": "Tavily API key for authentication",
                "required": True,
                "secret": True,
                "order": 1,
            },
        }
