import json
import base64
import logging

from application.core.settings import settings
from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator


class OpenAILLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        from openai import OpenAI

        super().__init__(*args, **kwargs)
        if isinstance(settings.OPENAI_BASE_URL, str) and settings.OPENAI_BASE_URL.strip():
            self.client = OpenAI(api_key=api_key, base_url=settings.OPENAI_BASE_URL)
        else:
            DEFAULT_OPENAI_API_BASE = "https://api.openai.com/v1"
            self.client = OpenAI(api_key=api_key, base_url=DEFAULT_OPENAI_API_BASE)
        self.api_key = api_key
        self.user_api_key = user_api_key
        self.storage = StorageCreator.get_storage()

    def _clean_messages_openai(self, messages):
        cleaned_messages = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "model":
                role = "assistant"

            if role and content is not None:
                if isinstance(content, str):
                    cleaned_messages.append({"role": role, "content": content})
                elif isinstance(content, list):
                    for item in content:
                        if "text" in item:
                            cleaned_messages.append(
                                {"role": role, "content": item["text"]}
                            )
                        elif "function_call" in item:
                            tool_call = {
                                "id": item["function_call"]["call_id"],
                                "type": "function",
                                "function": {
                                    "name": item["function_call"]["name"],
                                    "arguments": json.dumps(
                                        item["function_call"]["args"]
                                    ),
                                },
                            }
                            cleaned_messages.append(
                                {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [tool_call],
                                }
                            )
                        elif "function_response" in item:
                            cleaned_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": item["function_response"][
                                        "call_id"
                                    ],
                                    "content": json.dumps(
                                        item["function_response"]["response"]["result"]
                                    ),
                                }
                            )
                        elif isinstance(item, dict):
                            content_parts = []
                            if "text" in item:
                                content_parts.append({"type": "text", "text": item["text"]})
                            elif "type" in item and item["type"] == "text" and "text" in item:
                                content_parts.append(item)
                            elif "type" in item and item["type"] == "file" and "file" in item:
                                content_parts.append(item)
                            elif "type" in item and item["type"] == "image_url" and "image_url" in item:
                                content_parts.append(item)
                            cleaned_messages.append({"role": role, "content": content_parts})
                        else:
                            raise ValueError(
                                f"Unexpected content dictionary format: {item}"
                            )
                else:
                    raise ValueError(f"Unexpected content type: {type(content)}")

        return cleaned_messages

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        engine=settings.AZURE_DEPLOYMENT_NAME,
        **kwargs,
    ):
        messages = self._clean_messages_openai(messages)
        if tools:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=stream,
                tools=tools,
                **kwargs,
            )
            return response.choices[0]
        else:
            response = self.client.chat.completions.create(
                model=model, messages=messages, stream=stream, **kwargs
            )
            return response.choices[0].message.content

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        engine=settings.AZURE_DEPLOYMENT_NAME,
        **kwargs,
    ):
        messages = self._clean_messages_openai(messages)
        if tools:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=stream,
                tools=tools,
                **kwargs,
            )
        else:
            response = self.client.chat.completions.create(
                model=model, messages=messages, stream=stream, **kwargs
            )

        for line in response:
            if len(line.choices) > 0 and line.choices[0].delta.content is not None and len(line.choices[0].delta.content) > 0:
                yield line.choices[0].delta.content
            elif len(line.choices) > 0:
                yield line.choices[0]

    def _supports_tools(self):
        return True

    def get_supported_attachment_types(self):
        """
        Return a list of MIME types supported by OpenAI for file uploads.

        Returns:
            list: List of supported MIME types
        """
        return [
            'application/pdf',
            'image/png',
            'image/jpeg',
            'image/jpg',
            'image/webp',
            'image/gif'
        ]

    def prepare_messages_with_attachments(self, messages, attachments=None):
        """
        Process attachments using OpenAI's file API for more efficient handling.

        Args:
            messages (list): List of message dictionaries.
            attachments (list): List of attachment dictionaries with content and metadata.

        Returns:
            list: Messages formatted with file references for OpenAI API.
        """
        if not attachments:
            return messages

        prepared_messages = messages.copy()

        # Find the user message to attach file_id to the last one
        user_message_index = None
        for i in range(len(prepared_messages) - 1, -1, -1):
            if prepared_messages[i].get("role") == "user":
                user_message_index = i
                break

        if user_message_index is None:
            user_message = {"role": "user", "content": []}
            prepared_messages.append(user_message)
            user_message_index = len(prepared_messages) - 1

        if isinstance(prepared_messages[user_message_index].get("content"), str):
            text_content = prepared_messages[user_message_index]["content"]
            prepared_messages[user_message_index]["content"] = [
                {"type": "text", "text": text_content}
            ]
        elif not isinstance(prepared_messages[user_message_index].get("content"), list):
            prepared_messages[user_message_index]["content"] = []

        for attachment in attachments:
            mime_type = attachment.get('mime_type')

            if mime_type and mime_type.startswith('image/'):
                try:
                    base64_image = self._get_base64_image(attachment)
                    prepared_messages[user_message_index]["content"].append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        }
                    })
                except Exception as e:
                    logging.error(f"Error processing image attachment: {e}", exc_info=True)
                    if 'content' in attachment:
                        prepared_messages[user_message_index]["content"].append({
                            "type": "text",
                            "text": f"[Image could not be processed: {attachment.get('path', 'unknown')}]"
                        })
            # Handle PDFs using the file API
            elif mime_type == 'application/pdf':
                try:
                    file_id = self._upload_file_to_openai(attachment)
                    prepared_messages[user_message_index]["content"].append({
                        "type": "file",
                        "file": {"file_id": file_id}
                    })
                except Exception as e:
                    logging.error(f"Error uploading PDF to OpenAI: {e}", exc_info=True)
                    if 'content' in attachment:
                        prepared_messages[user_message_index]["content"].append({
                            "type": "text",
                            "text": f"File content:\n\n{attachment['content']}"
                        })

        return prepared_messages

    def _get_base64_image(self, attachment):
        """
        Convert an image file to base64 encoding.

        Args:
            attachment (dict): Attachment dictionary with path and metadata.

        Returns:
            str: Base64-encoded image data.
        """
        file_path = attachment.get('path')
        if not file_path:
            raise ValueError("No file path provided in attachment")

        try:
            with self.storage.get_file(file_path) as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}")

    def _upload_file_to_openai(self, attachment):
        """
        Upload a file to OpenAI and return the file_id.

        Args:
            attachment (dict): Attachment dictionary with path and metadata.
                Expected keys:
                - path: Path to the file
                - id: Optional MongoDB ID for caching

        Returns:
            str: OpenAI file_id for the uploaded file.
        """
        import logging

        if 'openai_file_id' in attachment:
            return attachment['openai_file_id']

        file_path = attachment.get('path')

        if not self.storage.file_exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            file_id = self.storage.process_file(
                file_path,
                lambda local_path, **kwargs: self.client.files.create(
                    file=open(local_path, 'rb'),
                    purpose="assistants"
                ).id
            )

            from application.core.mongo_db import MongoDB
            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            attachments_collection = db["attachments"]
            if '_id' in attachment:
                attachments_collection.update_one(
                    {"_id": attachment['_id']},
                    {"$set": {"openai_file_id": file_id}}
                )

            return file_id
        except Exception as e:
            logging.error(f"Error uploading file to OpenAI: {e}", exc_info=True)
            raise


class AzureOpenAILLM(OpenAILLM):

    def __init__(
        self, api_key, user_api_key, *args, **kwargs
    ):

        super().__init__(api_key)
        self.api_base = (settings.OPENAI_API_BASE,)
        self.api_version = (settings.OPENAI_API_VERSION,)
        self.deployment_name = (settings.AZURE_DEPLOYMENT_NAME,)
        from openai import AzureOpenAI

        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=settings.OPENAI_API_VERSION,
            azure_endpoint=settings.OPENAI_API_BASE
        )
