import requests
from markdownify import markdownify
from application.agents.tools.base import Tool
from urllib.parse import urlparse

class ReadWebpageTool(Tool):
    """
    Read Webpage (browser)
    A tool to fetch the HTML content of a URL and convert it to Markdown.
    """

    def __init__(self, config=None):
        """
        Initializes the tool.
        :param config: Optional configuration dictionary. Not used by this tool.
        """
        self.config = config

    def execute_action(self, action_name: str, **kwargs) -> str:
        """
        Executes the specified action. For this tool, the only action is 'read_webpage'.

        :param action_name: The name of the action to execute. Should be 'read_webpage'.
        :param kwargs: Keyword arguments, must include 'url'.
        :return: The Markdown content of the webpage or an error message.
        """
        if action_name != "read_webpage":
            return f"Error: Unknown action '{action_name}'. This tool only supports 'read_webpage'."

        url = kwargs.get("url")
        if not url:
            return "Error: URL parameter is missing."

        # Ensure the URL has a scheme (if not, default to http)
        parsed_url = urlparse(url)
        if not parsed_url.scheme:
            url = "http://" + url
        
        try:
            response = requests.get(url, timeout=10, headers={'User-Agent': 'DocsGPT-Agent/1.0'})
            response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
            
            html_content = response.text
            #soup = BeautifulSoup(html_content, 'html.parser')
            
            
            markdown_content = markdownify(html_content, heading_style="ATX", newline_style="BACKSLASH")
            
            return markdown_content

        except requests.exceptions.RequestException as e:
            return f"Error fetching URL {url}: {e}"
        except Exception as e:
            return f"Error processing URL {url}: {e}"

    def get_actions_metadata(self):
        """
        Returns metadata for the actions supported by this tool.
        """
        return [
            {
                "name": "read_webpage",
                "description": "Fetches the HTML content of a given URL and returns it as clean Markdown text. Input must be a valid URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The fully qualified URL of the webpage to read (e.g., 'https://www.example.com').",
                        }
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            }
        ]

    def get_config_requirements(self):
        """
        Returns a dictionary describing the configuration requirements for the tool.
        This tool does not require any specific configuration.
        """
        return {}
