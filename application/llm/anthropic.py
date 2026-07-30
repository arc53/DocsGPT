import base64
import logging

from anthropic import Anthropic

from application.core.settings import settings
from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator

logger = logging.getLogger(__name__)


class AnthropicLLM(BaseLLM):
    provider_name = "anthropic"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_key = api_key or settings.ANTHROPIC_API_KEY or settings.API_KEY
        self.user_api_key = user_api_key

        # Use custom base_url if provided
        if base_url:
            self.anthropic = Anthropic(api_key=self.api_key, base_url=base_url)
        else:
            self.anthropic = Anthropic(api_key=self.api_key)

        self.storage = StorageCreator.get_storage()

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        max_tokens=300,
        **kwargs,
    ):
        system, api_messages = self._split_messages(messages)
        request_params = {"model": model, "max_tokens": max_tokens, "messages": api_messages}
        if system:
            request_params["system"] = system
        response = self.anthropic.messages.create(**request_params)
        return response.content[0].text

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        max_tokens=300,
        **kwargs,
    ):
        system, api_messages = self._split_messages(messages)
        request_params = {"model": model, "max_tokens": max_tokens, "messages": api_messages}
        if system:
            request_params["system"] = system
        with self.anthropic.messages.stream(**request_params) as stream_response:
            for text in stream_response.text_stream:
                yield text

    def _split_messages(self, messages):
        """Separate an optional leading system message from the conversation turns.

        Returns a (system, api_messages) tuple where system is a string or None
        and api_messages is the list of user/assistant turns for the Messages API.
        """
        system = None
        api_messages = []
        for msg in messages:
            if msg.get("role") == "system" and system is None and not api_messages:
                system = msg["content"]
            else:
                api_messages.append({"role": msg["role"], "content": msg["content"]})
        return system, api_messages

    def get_supported_attachment_types(self):
        """
        Return a list of MIME types supported by Anthropic Claude for file uploads.
        Claude supports images but not PDFs natively.
        PDFs are synthetically supported via PDF-to-image conversion in the handler.

        Returns:
            list: List of supported MIME types
        """
        return [
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
            "image/gif",
        ]

    def prepare_messages_with_attachments(self, messages, attachments=None):
        """
        Process attachments for Anthropic Claude API.
        Formats images using Claude's vision message format.

        Args:
            messages (list): List of message dictionaries.
            attachments (list): List of attachment dictionaries with content and metadata.

        Returns:
            list: Messages formatted with image content for Claude API.
        """
        if not attachments:
            return messages

        prepared_messages = messages.copy()

        # Find the last user message to attach images to
        user_message_index = None
        for i in range(len(prepared_messages) - 1, -1, -1):
            if prepared_messages[i].get("role") == "user":
                user_message_index = i
                break

        if user_message_index is None:
            user_message = {"role": "user", "content": []}
            prepared_messages.append(user_message)
            user_message_index = len(prepared_messages) - 1

        # Convert content to list format if it's a string
        if isinstance(prepared_messages[user_message_index].get("content"), str):
            text_content = prepared_messages[user_message_index]["content"]
            prepared_messages[user_message_index]["content"] = [
                {"type": "text", "text": text_content}
            ]
        elif not isinstance(prepared_messages[user_message_index].get("content"), list):
            prepared_messages[user_message_index]["content"] = []

        for attachment in attachments:
            mime_type = attachment.get("mime_type")

            if mime_type and mime_type.startswith("image/"):
                try:
                    # Check if this is a pre-converted image (from PDF-to-image conversion)
                    # These have 'data' key with base64 already
                    if "data" in attachment:
                        base64_image = attachment["data"]
                    else:
                        base64_image = self._get_base64_image(attachment)

                    # Claude uses a specific format for images
                    prepared_messages[user_message_index]["content"].append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": base64_image,
                            },
                        }
                    )

                except Exception as e:
                    logger.error(
                        f"Error processing image attachment: {e}", exc_info=True
                    )
                    if "content" in attachment:
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": f"[Image could not be processed: {attachment.get('path', 'unknown')}]",
                            }
                        )

        return prepared_messages

    def _get_base64_image(self, attachment):
        """
        Convert an image file to base64 encoding.

        Args:
            attachment (dict): Attachment dictionary with path and metadata.

        Returns:
            str: Base64-encoded image data.
        """
        file_path = attachment.get("path")
        if not file_path:
            raise ValueError("No file path provided in attachment")
        try:
            with self.storage.get_file(file_path) as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}")
