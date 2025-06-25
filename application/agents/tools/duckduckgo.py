from application.agents.tools.base import Tool
from duckduckgo_search import DDGS


class DuckDuckGoSearchTool(Tool):
    """
    DuckDuckGo Search
    A tool for performing web and image searches using DuckDuckGo.
    """

    def __init__(self, config):
        self.config = config

    def execute_action(self, action_name, **kwargs):
        actions = {
            "ddg_web_search": self._web_search,
            "ddg_image_search": self._image_search,
        }

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _web_search(
        self,
        query,
        max_results=5,
    ):
        print(f"Performing DuckDuckGo web search for: {query}")

        try:
            results = DDGS().text(
                query,
                max_results=max_results,
            )

            return {
                "status_code": 200,
                "results": results,
                "message": "Web search completed successfully.",
            }
        except Exception as e:
            return {
                "status_code": 500,
                "message": f"Web search failed: {str(e)}",
            }

    def _image_search(
        self,
        query,
        max_results=5,
    ):
        print(f"Performing DuckDuckGo image search for: {query}")

        try:
            results = DDGS().images(
                keywords=query,
                max_results=max_results,
            )

            return {
                "status_code": 200,
                "results": results,
                "message": "Image search completed successfully.",
            }
        except Exception as e:
            return {
                "status_code": 500,
                "message": f"Image search failed: {str(e)}",
            }

    def get_actions_metadata(self):
        return [
            {
                "name": "ddg_web_search",
                "description": "Perform a web search using DuckDuckGo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results to return (default: 5)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "ddg_image_search",
                "description": "Perform an image search using DuckDuckGo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results to return (default: 5, max: 50)",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    def get_config_requirements(self):
        return {}
