import base64
import json
import logging

from openai import OpenAI

from application.core.settings import settings
from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator


def _truncate_base64_for_logging(messages):
    """
    Create a copy of messages with base64 data truncated for readable logging.

    Args:
        messages: List of message dicts

    Returns:
        Copy of messages with truncated base64 content
    """
    import copy

    def truncate_content(content):
        if isinstance(content, str):
            # Check if it looks like a data URL with base64
            if content.startswith("data:") and ";base64," in content:
                prefix_end = content.index(";base64,") + len(";base64,")
                prefix = content[:prefix_end]
                return f"{prefix}[BASE64_DATA_TRUNCATED, length={len(content) - prefix_end}]"
            return content
        elif isinstance(content, list):
            return [truncate_item(item) for item in content]
        elif isinstance(content, dict):
            return {k: truncate_content(v) for k, v in content.items()}
        return content

    def truncate_item(item):
        if isinstance(item, dict):
            result = {}
            for k, v in item.items():
                if k == "url" and isinstance(v, str) and ";base64," in v:
                    prefix_end = v.index(";base64,") + len(";base64,")
                    prefix = v[:prefix_end]
                    result[k] = f"{prefix}[BASE64_DATA_TRUNCATED, length={len(v) - prefix_end}]"
                elif k == "data" and isinstance(v, str) and len(v) > 100:
                    result[k] = f"[BASE64_DATA_TRUNCATED, length={len(v)}]"
                else:
                    result[k] = truncate_content(v)
            return result
        return truncate_content(item)

    truncated = []
    for msg in messages:
        msg_copy = copy.copy(msg)
        if "content" in msg_copy:
            msg_copy["content"] = truncate_content(msg_copy["content"])
        truncated.append(msg_copy)

    return truncated


class OpenAILLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_key = api_key or settings.OPENAI_API_KEY or settings.API_KEY
        self.user_api_key = user_api_key

        # Priority: 1) Parameter base_url, 2) Settings OPENAI_BASE_URL, 3) Default
        effective_base_url = None
        if base_url and isinstance(base_url, str) and base_url.strip():
            effective_base_url = base_url
        elif (
            isinstance(settings.OPENAI_BASE_URL, str)
            and settings.OPENAI_BASE_URL.strip()
        ):
            effective_base_url = settings.OPENAI_BASE_URL
        else:
            effective_base_url = "https://api.openai.com/v1"

        self.client = OpenAI(api_key=self.api_key, base_url=effective_base_url)
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
                    # Collect all content parts into a single message
                    content_parts = []

                    for item in content:
                        if "function_call" in item:
                            # Function calls need their own message
                            cleaned_args = self._remove_null_values(
                                item["function_call"]["args"]
                            )
                            tool_call = {
                                "id": item["function_call"]["call_id"],
                                "type": "function",
                                "function": {
                                    "name": item["function_call"]["name"],
                                    "arguments": json.dumps(cleaned_args),
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
                            # Function responses need their own message
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
                            # Collect content parts (text, images, files) into a single message
                            if "type" in item and item["type"] == "text" and "text" in item:
                                content_parts.append(item)
                            elif "type" in item and item["type"] == "file" and "file" in item:
                                content_parts.append(item)
                            elif "type" in item and item["type"] == "image_url" and "image_url" in item:
                                content_parts.append(item)
                            elif "text" in item and "type" not in item:
                                # Legacy format: {"text": "..."} without type
                                content_parts.append({"type": "text", "text": item["text"]})

                    # Add the collected content parts as a single message
                    if content_parts:
                        cleaned_messages.append({"role": role, "content": content_parts})
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
        response_format=None,
        **kwargs,
    ):
        messages = self._clean_messages_openai(messages)
        logging.info(f"Cleaned messages: {_truncate_base64_for_logging(messages)}")

        # Convert max_tokens to max_completion_tokens for newer models
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        request_params = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs,
        }

        if tools:
            request_params["tools"] = tools
        if response_format:
            request_params["response_format"] = response_format
        response = self.client.chat.completions.create(**request_params)
        logging.info(f"OpenAI response: {response}")
        if tools:
            return response.choices[0]
        else:
            return response.choices[0].message.content

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        engine=settings.AZURE_DEPLOYMENT_NAME,
        response_format=None,
        **kwargs,
    ):
        messages = self._clean_messages_openai(messages)
        logging.info(f"Cleaned messages: {_truncate_base64_for_logging(messages)}")

        # Convert max_tokens to max_completion_tokens for newer models
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        request_params = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs,
        }

        if tools:
            request_params["tools"] = tools
        if response_format:
            request_params["response_format"] = response_format
        response = self.client.chat.completions.create(**request_params)

        try:
            for line in response:
                logging.debug(f"OpenAI stream line: {line}")
                if (
                    len(line.choices) > 0
                    and line.choices[0].delta.content is not None
                    and len(line.choices[0].delta.content) > 0
                ):
                    yield line.choices[0].delta.content
                elif len(line.choices) > 0:
                    yield line.choices[0]
        finally:
            if hasattr(response, "close"):
                response.close()

    def _supports_tools(self):
        return True

    def _supports_structured_output(self):
        return True

    def prepare_structured_output_format(self, json_schema):
        if not json_schema:
            return None
        try:

            def add_additional_properties_false(schema_obj):
                if isinstance(schema_obj, dict):
                    schema_copy = schema_obj.copy()

                    if schema_copy.get("type") == "object":
                        schema_copy["additionalProperties"] = False
                        # Ensure 'required' includes all properties for OpenAI strict mode

                        if "properties" in schema_copy:
                            schema_copy["required"] = list(
                                schema_copy["properties"].keys()
                            )
                    for key, value in schema_copy.items():
                        if key == "properties" and isinstance(value, dict):
                            schema_copy[key] = {
                                prop_name: add_additional_properties_false(prop_schema)
                                for prop_name, prop_schema in value.items()
                            }
                        elif key == "items" and isinstance(value, dict):
                            schema_copy[key] = add_additional_properties_false(value)
                        elif key in ["anyOf", "oneOf", "allOf"] and isinstance(
                            value, list
                        ):
                            schema_copy[key] = [
                                add_additional_properties_false(sub_schema)
                                for sub_schema in value
                            ]
                    return schema_copy
                return schema_obj

            processed_schema = add_additional_properties_false(json_schema)

            result = {
                "type": "json_schema",
                "json_schema": {
                    "name": processed_schema.get("name", "response"),
                    "description": processed_schema.get(
                        "description", "Structured response"
                    ),
                    "schema": processed_schema,
                    "strict": True,
                },
            }

            return result
        except Exception as e:
            logging.error(f"Error preparing structured output format: {e}")
            return None

    def get_supported_attachment_types(self):
        """
        Return a list of MIME types supported by OpenAI for file uploads.

        This reads from the model config to ensure consistency.
        If no model config found, falls back to images only (safest default).

        Returns:
            list: List of supported MIME types
        """
        from application.core.model_configs import OPENAI_ATTACHMENTS
        return OPENAI_ATTACHMENTS

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
            mime_type = attachment.get("mime_type")
            logging.info(f"Processing attachment with mime_type: {mime_type}, has_data: {'data' in attachment}, has_path: {'path' in attachment}")

            if mime_type and mime_type.startswith("image/"):
                try:
                    # Check if this is a pre-converted image (from PDF-to-image conversion)
                    if "data" in attachment:
                        base64_image = attachment["data"]
                    else:
                        base64_image = self._get_base64_image(attachment)

                    prepared_messages[user_message_index]["content"].append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            },
                        }
                    )

                except Exception as e:
                    logging.error(
                        f"Error processing image attachment: {e}", exc_info=True
                    )
                    if "content" in attachment:
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": f"[Image could not be processed: {attachment.get('path', 'unknown')}]",
                            }
                        )
            # Handle PDFs using the file API

            elif mime_type == "application/pdf":
                logging.info(f"Attempting to upload PDF to OpenAI: {attachment.get('path', 'unknown')}")
                try:
                    file_id = self._upload_file_to_openai(attachment)
                    prepared_messages[user_message_index]["content"].append(
                        {"type": "file", "file": {"file_id": file_id}}
                    )
                except Exception as e:
                    logging.error(f"Error uploading PDF to OpenAI: {e}", exc_info=True)
                    if "content" in attachment:
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": f"File content:\n\n{attachment['content']}",
                            }
                        )
            else:
                logging.warning(f"Unsupported attachment type in OpenAI provider: {mime_type}")
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

        if "openai_file_id" in attachment:
            return attachment["openai_file_id"]
        file_path = attachment.get("path")

        if not self.storage.file_exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        try:
            file_id = self.storage.process_file(
                file_path,
                lambda local_path, **kwargs: self.client.files.create(
                    file=open(local_path, "rb"), purpose="assistants"
                ).id,
            )

            from application.core.mongo_db import MongoDB

            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            attachments_collection = db["attachments"]
            if "_id" in attachment:
                attachments_collection.update_one(
                    {"_id": attachment["_id"]}, {"$set": {"openai_file_id": file_id}}
                )
            return file_id
        except Exception as e:
            logging.error(f"Error uploading file to OpenAI: {e}", exc_info=True)
            raise


class AzureOpenAILLM(OpenAILLM):

    def __init__(self, api_key, user_api_key, *args, **kwargs):

        super().__init__(api_key)
        self.api_base = (settings.OPENAI_API_BASE,)
        self.api_version = (settings.OPENAI_API_VERSION,)
        self.deployment_name = (settings.AZURE_DEPLOYMENT_NAME,)
        from openai import AzureOpenAI

        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=settings.OPENAI_API_VERSION,
            azure_endpoint=settings.OPENAI_API_BASE,
        )
