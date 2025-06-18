import requests
from application.agents.tools.base import Tool

class NtfyTool(Tool):
    """
    Ntfy Tool
    A tool for sending notifications to ntfy topics on a specified server.
    """

    def __init__(self, config):
        """
        Initialize the NtfyTool with configuration.

        Args:
            config (dict): Configuration dictionary containing the access token.
        """
        self.config = config
        self.token = config.get("token", "")

    def execute_action(self, action_name, **kwargs):
        """
        Execute the specified action with given parameters.

        Args:
            action_name (str): Name of the action to execute.
            **kwargs: Parameters for the action, including server_url.

        Returns:
            dict: Result of the action with status code and message.

        Raises:
            ValueError: If the action name is unknown.
        """
        actions = {
            "ntfy_send_message": self._send_message,
        }
        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _send_message(self, server_url, message, topic, title=None, priority=None):
        """
        Send a message to an ntfy topic on the specified server.

        Args:
            server_url (str): Base URL of the ntfy server (e.g., https://ntfy.sh).
            message (str): The message text to send.
            topic (str): The topic to send the message to.
            title (str, optional): Title of the notification.
            priority (int, optional): Priority of the notification (1-5).

        Returns:
            dict: Response with status code and a confirmation message.

        Raises:
            ValueError: If priority is not an integer between 1 and 5.
        """
        url = f"{server_url.rstrip('/')}/{topic}"
        headers = {}
        if title:
            headers["X-Title"] = title
        if priority:
            try:
                priority = int(priority)
            except (ValueError, TypeError):
                raise ValueError("Priority must be convertible to an integer")
            if priority < 1 or priority > 5:
                raise ValueError("Priority must be an integer between 1 and 5")
            headers["X-Priority"] = str(priority)
        if self.token:
            headers["Authorization"] = f"Basic {self.token}"
        data = message.encode("utf-8")
        response = requests.post(url, headers=headers, data=data)
        return {"status_code": response.status_code, "message": "Message sent"}

    def get_actions_metadata(self):
        """
        Provide metadata about available actions.

        Returns:
            list: List of dictionaries describing each action.
        """
        return [
            {
                "name": "ntfy_send_message",
                "description": "Send a notification to an ntfy topic",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server_url": {
                            "type": "string",
                            "description": "Base URL of the ntfy server",
                        },
                        "message": {
                            "type": "string",
                            "description": "Text to send in the notification",
                        },
                        "topic": {
                            "type": "string",
                            "description": "Topic to send the notification to",
                        },
                        "title": {
                            "type": "string",
                            "description": "Title of the notification (optional)",
                        },
                        "priority": {
                            "type": "integer",
                            "description": "Priority of the notification (1-5, optional)",
                        },
                    },
                    "required": ["server_url", "message", "topic"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        """
        Specify the configuration requirements.

        Returns:
            dict: Dictionary describing required config parameters.
        """
        return {
            "token": {"type": "string", "description": "Access token for authentication"},
        }