import requests
from application.tools.base import Tool


class BraveSearchTool(Tool):
    """
    Brave Search
    A tool for performing web and image searches using the Brave Search API.
    Requires an API key for authentication.
    """

    def __init__(self, config):
        self.config = config
        self.token = config.get("token", "")
        self.base_url = "https://api.search.brave.com/res/v1"

    def execute_action(self, action_name, **kwargs):
        actions = {
            "brave_web_search": self._web_search,
            "brave_image_search": self._image_search,
        }

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _web_search(self, query, country="ALL", search_lang="en", count=10, 
                   offset=0, safesearch="off", freshness=None, 
                   result_filter=None, extra_snippets=False, summary=False):
        """
        Performs a web search using the Brave Search API.
        """
        print(f"Performing Brave web search for: {query}")
        
        url = f"{self.base_url}/web/search"
        
        # Build query parameters
        params = {
            "q": query,
            "country": country,
            "search_lang": search_lang,
            "count": min(count, 20),
            "offset": min(offset, 9),
            "safesearch": safesearch
        }
        
        # Add optional parameters only if they have values
        if freshness:
            params["freshness"] = freshness
        if result_filter:
            params["result_filter"] = result_filter
        if extra_snippets:
            params["extra_snippets"] = 1
        if summary:
            params["summary"] = 1
        
        # Set up headers
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.token
        }
        
        # Make the request
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            return {
                "status_code": response.status_code,
                "results": response.json(),
                "message": "Search completed successfully."
            }
        else:
            return {
                "status_code": response.status_code,
                "message": f"Search failed with status code: {response.status_code}."
            }
    
    def _image_search(self, query, country="ALL", search_lang="en", count=5, 
                     safesearch="off", spellcheck=False):
        """
        Performs an image search using the Brave Search API.
        """
        print(f"Performing Brave image search for: {query}")
        
        url = f"{self.base_url}/images/search"
        
        # Build query parameters
        params = {
            "q": query,
            "country": country,
            "search_lang": search_lang,
            "count": min(count, 100),  # API max is 100
            "safesearch": safesearch,
            "spellcheck": 1 if spellcheck else 0
        }
        
        # Set up headers
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.token
        }
        
        # Make the request
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            return {
                "status_code": response.status_code,
                "results": response.json(),
                "message": "Image search completed successfully."
            }
        else:
            return {
                "status_code": response.status_code,
                "message": f"Image search failed with status code: {response.status_code}."
            }

    def get_actions_metadata(self):
        return [
            {
                "name": "brave_web_search",
                "description": "Perform a web search using Brave Search",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (max 400 characters, 50 words)",
                        },
                        # "country": {
                        #     "type": "string",
                        #     "description": "The 2-character country code (default: US)",
                        # },
                        "search_lang": {
                            "type": "string",
                            "description": "The search language preference (default: en)",
                        },
                        # "count": {
                        #     "type": "integer",
                        #     "description": "Number of results to return (max 20, default: 10)",
                        # },
                        # "offset": {
                        #     "type": "integer",
                        #     "description": "Pagination offset (max 9, default: 0)",
                        # },
                        # "safesearch": {
                        #     "type": "string",
                        #     "description": "Filter level for adult content (off, moderate, strict)",
                        # },
                        "freshness": {
                            "type": "string",
                            "description": "Time filter for results (pd: last 24h, pw: last week, pm: last month, py: last year)",
                        },
                        # "result_filter": {
                        #     "type": "string",
                        #     "description": "Comma-delimited list of result types to include",
                        # },
                        # "extra_snippets": {
                        #     "type": "boolean",
                        #     "description": "Get additional excerpts from result pages",
                        # },
                        # "summary": {
                        #     "type": "boolean",
                        #     "description": "Enable summary generation in search results",
                        # }
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "brave_image_search",
                "description": "Perform an image search using Brave Search",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (max 400 characters, 50 words)",
                        },
                        # "country": {
                        #     "type": "string",
                        #     "description": "The 2-character country code (default: US)",
                        # },
                        # "search_lang": {
                        #     "type": "string",
                        #     "description": "The search language preference (default: en)",
                        # },
                        "count": {
                            "type": "integer",
                            "description": "Number of results to return (max 100, default: 5)",
                        },
                        # "safesearch": {
                        #     "type": "string",
                        #     "description": "Filter level for adult content (off, strict). Default: strict",
                        # },
                        # "spellcheck": {
                        #     "type": "boolean",
                        #     "description": "Whether to spellcheck provided query (default: true)",
                        # }
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ]

    def get_config_requirements(self):
        return {
            "token": {
                "type": "string", 
                "description": "Brave Search API key for authentication"
            },
        }