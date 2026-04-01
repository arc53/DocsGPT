import logging

from tavily import TavilyClient

from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)


class TavilySearchTool(Tool):
    """
    Tavily Search
    A tool for performing web and image searches using the Tavily Search API.
    Requires an API key for authentication.
    """

    def __init__(self, config):
        self.config = config
        self.client = TavilyClient(api_key=config.get("token", ""))

    def execute_action(self, action_name, **kwargs):
        actions = {
            "tavily_web_search": self._web_search,
            "tavily_image_search": self._image_search,
        }

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _web_search(
        self,
        query,
        search_depth="advanced",
        topic="general",
        max_results=10,
        search_lang="en",
        time_range=None,
    ):
        """
        Performs a web search using the Tavily Search API.
        """
        logger.debug("Performing Tavily web search for: %s", query)

        try:
            params = {
                "query": query,
                "search_depth": search_depth,
                "topic": topic,
                "max_results": min(max_results, 20),
            }

            if time_range:
                params["time_range"] = time_range

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

    def _image_search(
        self,
        query,
        search_depth="advanced",
        topic="general",
        max_results=5,
    ):
        """
        Performs an image search using the Tavily Search API.
        """
        logger.debug("Performing Tavily image search for: %s", query)

        try:
            response = self.client.search(
                query=query,
                search_depth=search_depth,
                topic=topic,
                max_results=min(max_results, 20),
                include_images=True,
            )

            return {
                "status_code": 200,
                "results": response,
                "message": "Image search completed successfully.",
            }
        except Exception as e:
            logger.error("Tavily image search failed: %s", str(e))
            return {
                "status_code": 500,
                "message": f"Image search failed: {str(e)}",
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
                        "search_depth": {
                            "type": "string",
                            "description": "Search depth: 'basic' or 'advanced' (default: advanced)",
                        },
                        "time_range": {
                            "type": "string",
                            "description": "Time filter for results (day, week, month, year)",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "tavily_image_search",
                "description": "Perform an image search using Tavily Search",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (max 400 characters)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results to return (max 20, default: 5)",
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
                "description": "Tavily Search API key for authentication",
                "required": True,
                "secret": True,
                "order": 1,
            },
        }
