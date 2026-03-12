import logging

import requests

from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)


class TelegramTool(Tool):
    """
    Telegram Bot
    A flexible Telegram tool for performing various actions (e.g., sending messages, images).
    Requires a bot token and chat ID for configuration
    """

    def __init__(self, config):
        self.config = config
        self.token = config.get("token", "")

    def execute_action(self, action_name, **kwargs):
        actions = {
            "telegram_send_message": self._send_message,
            "telegram_send_image": self._send_image,
        }
        if action_name not in actions:
            raise ValueError(f"Unknown action: {action_name}")
        return actions[action_name](**kwargs)

    def _send_message(self, text, chat_id):
        logger.info(f"Telegram: sending message to {chat_id}")
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        response = requests.post(url, data=payload)
        return {"status_code": response.status_code, "message": "Message sent"}

    def _send_image(self, image_url, chat_id):
        logger.info(f"Telegram: sending image to {chat_id}")
        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": image_url}
        response = requests.post(url, data=payload)
        return {"status_code": response.status_code, "message": "Image sent"}

    def get_actions_metadata(self):
        return [
            {
                "name": "telegram_send_message",
                "description": "Send a notification to Telegram chat",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to send in the notification",
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "Chat ID to send the notification to",
                        },
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "telegram_send_image",
                "description": "Send an image to the Telegram chat",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_url": {
                            "type": "string",
                            "description": "URL of the image to send",
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "Chat ID to send the image to",
                        },
                    },
                    "required": ["image_url"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        return {
            "token": {"type": "string", "description": "Bot token for authentication"},
        }
