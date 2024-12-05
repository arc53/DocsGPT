from application.tools.base import Tool
import requests

class TelegramTool(Tool):
    def __init__(self, config):
        self.config = config
        self.chat_id = config.get("chat_id", "142189016")
        self.token = config.get("token", "YOUR_TG_TOKEN")

    def execute_action(self, action_name, **kwargs):
        actions = {
            "telegram_send_message": self.send_message,
            "telegram_send_image": self.send_image
        }

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def send_message(self, text):
        print(f"Sending message: {text}")
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text}
        response = requests.post(url, data=payload)
        return {"status_code": response.status_code, "message": "Message sent"}

    def send_image(self, image_url):
        print(f"Sending image: {image_url}")
        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        payload = {"chat_id": self.chat_id, "photo": image_url}
        response = requests.post(url, data=payload)
        return {"status_code": response.status_code, "message": "Image sent"}

    def get_actions_metadata(self):
        return [
            {
                "name": "telegram_send_message",
                "description": "Send a notification to telegram chat",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to send in the notification"
                        }
                    },
                    "required": ["text"],
                    "additionalProperties": False
                }
            },
            {
                "name": "telegram_send_image",
                "description": "Send an image to the Telegram chat",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_url": {
                            "type": "string",
                            "description": "URL of the image to send"
                        }
                    },
                    "required": ["image_url"],
                    "additionalProperties": False
                }
            }
        ]

    def get_config_requirements(self):
        return {
            "chat_id": {
                "type": "string",
                "description": "Telegram chat ID to send messages to"
            },
            "token": {
                "type": "string",
                "description": "Bot token for authentication"
            }
        }
