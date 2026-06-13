from markdownify import markdownify
from application.agents.tools.base import Tool
from application.security.safe_url import UnsafeUserUrlError, pinned_request

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

        try:
            response = pinned_request(
                "GET",
                url,
                headers={'User-Agent': 'DocsGPT-Agent/1.0'},
                timeout=10,
            )
            response.raise_for_status()

            html_content = response.text
            markdown_content = markdownify(html_content, heading_style="ATX", newline_style="BACKSLASH")

            return markdown_content

        except UnsafeUserUrlError as e:
            return f"Error: URL validation failed - {e}"
        except Exception as e:
            return f"Error fetching URL {url}: {e}"

    def get_actions_metadata(self):
        """
        Returns metadata for the actions supported by this tool.
        """
        return [
            {
                "name": "read_webpage",
                "description": (
                    "Fetch a webpage and return its content as clean Markdown "
                    "text. Use it whenever the user shares a URL or the answer "
                    "depends on a specific page. Input must be a fully "
                    "qualified URL."
                ),
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
