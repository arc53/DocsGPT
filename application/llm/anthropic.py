import base64
import logging

from anthropic import AI_PROMPT, Anthropic, HUMAN_PROMPT

from application.core.settings import settings
from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator

logger = logging.getLogger(__name__)


class AnthropicLLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_key = api_key or settings.ANTHROPIC_API_KEY or settings.API_KEY
        self.user_api_key = user_api_key

        # Use custom base_url if provided
        if base_url:
            self.anthropic = Anthropic(api_key=self.api_key, base_url=base_url)
        else:
            self.anthropic = Anthropic(api_key=self.api_key)

        self.HUMAN_PROMPT = HUMAN_PROMPT
        self.AI_PROMPT = AI_PROMPT
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
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Context \n {context} \n ### Question \n {user_question}"
        if stream:
            return self.gen_stream(model, prompt, stream, max_tokens, **kwargs)
        completion = self.anthropic.completions.create(
            model=model,
            max_tokens_to_sample=max_tokens,
            stream=stream,
            prompt=f"{self.HUMAN_PROMPT} {prompt}{self.AI_PROMPT}",
        )
        return completion.completion

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
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Context \n {context} \n ### Question \n {user_question}"
        stream_response = self.anthropic.completions.create(
            model=model,
            prompt=f"{self.HUMAN_PROMPT} {prompt}{self.AI_PROMPT}",
            max_tokens_to_sample=max_tokens,
            stream=True,
        )

        try:
            for completion in stream_response:
                yield completion.completion
        finally:
            if hasattr(stream_response, "close"):
                stream_response.close()

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
