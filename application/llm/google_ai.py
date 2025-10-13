import json
import logging

from google import genai
from google.genai import types

from application.core.settings import settings

from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator


class GoogleLLM(BaseLLM):
    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self.user_api_key = user_api_key
        self.client = genai.Client(api_key=self.api_key)
        self.storage = StorageCreator.get_storage()

    def get_supported_attachment_types(self):
        """
        Return a list of MIME types supported by Google Gemini for file uploads.

        Returns:
            list: List of supported MIME types
        """
        return [
            "application/pdf",
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
            "image/gif",
        ]

    def prepare_messages_with_attachments(self, messages, attachments=None):
        """
        Process attachments using Google AI's file API for more efficient handling.

        Args:
            messages (list): List of message dictionaries.
            attachments (list): List of attachment dictionaries with content and metadata.

        Returns:
            list: Messages formatted with file references for Google AI API.
        """
        if not attachments:
            return messages

        prepared_messages = messages.copy()

        # Find the user message to attach files to the last one
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

        files = []
        for attachment in attachments:
            mime_type = attachment.get("mime_type")

            if mime_type in self.get_supported_attachment_types():
                try:
                    file_uri = self._upload_file_to_google(attachment)
                    logging.info(
                        f"GoogleLLM: Successfully uploaded file, got URI: {file_uri}"
                    )
                    files.append({"file_uri": file_uri, "mime_type": mime_type})
                except Exception as e:
                    logging.error(
                        f"GoogleLLM: Error uploading file: {e}", exc_info=True
                    )
                    if "content" in attachment:
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": f"[File could not be processed: {attachment.get('path', 'unknown')}]",
                            }
                        )

        if files:
            logging.info(f"GoogleLLM: Adding {len(files)} files to message")
            prepared_messages[user_message_index]["content"].append({"files": files})

        return prepared_messages

    def _upload_file_to_google(self, attachment):
        """
        Upload a file to Google AI and return the file URI.

        Args:
            attachment (dict): Attachment dictionary with path and metadata.

        Returns:
            str: Google AI file URI for the uploaded file.
        """
        if "google_file_uri" in attachment:
            return attachment["google_file_uri"]

        file_path = attachment.get("path")
        if not file_path:
            raise ValueError("No file path provided in attachment")

        if not self.storage.file_exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            file_uri = self.storage.process_file(
                file_path,
                lambda local_path, **kwargs: self.client.files.upload(
                    file=local_path
                ).uri,
            )

            from application.core.mongo_db import MongoDB

            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            attachments_collection = db["attachments"]
            if "_id" in attachment:
                attachments_collection.update_one(
                    {"_id": attachment["_id"]}, {"$set": {"google_file_uri": file_uri}}
                )

            return file_uri
        except Exception as e:
            logging.error(f"Error uploading file to Google AI: {e}", exc_info=True)
            raise

    def _clean_messages_google(self, messages):
        """Convert OpenAI format messages to Google AI format."""
        cleaned_messages = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "assistant":
                role = "model"
            elif role == "tool":
                role = "model"

            parts = []
            if role and content is not None:
                if isinstance(content, str):
                    parts = [types.Part.from_text(text=content)]
                elif isinstance(content, list):
                    for item in content:
                        if "text" in item:
                            parts.append(types.Part.from_text(text=item["text"]))
                        elif "function_call" in item:
                            parts.append(
                                types.Part.from_function_call(
                                    name=item["function_call"]["name"],
                                    args=item["function_call"]["args"],
                                )
                            )
                        elif "function_response" in item:
                            parts.append(
                                types.Part.from_function_response(
                                    name=item["function_response"]["name"],
                                    response=item["function_response"]["response"],
                                )
                            )
                        elif "files" in item:
                            for file_data in item["files"]:
                                parts.append(
                                    types.Part.from_uri(
                                        file_uri=file_data["file_uri"],
                                        mime_type=file_data["mime_type"],
                                    )
                                )
                        else:
                            raise ValueError(
                                f"Unexpected content dictionary format:{item}"
                            )
                else:
                    raise ValueError(f"Unexpected content type: {type(content)}")

                if parts:
                    cleaned_messages.append(types.Content(role=role, parts=parts))

        return cleaned_messages

    def _clean_schema(self, schema_obj):
        """
        Recursively remove unsupported fields from schema objects
        and validate required properties.
        """
        if not isinstance(schema_obj, dict):
            return schema_obj
        allowed_fields = {
            "type",
            "description",
            "items",
            "properties",
            "required",
            "enum",
            "pattern",
            "minimum",
            "maximum",
            "nullable",
            "default",
        }

        cleaned = {}
        for key, value in schema_obj.items():
            if key not in allowed_fields:
                continue
            elif key == "type" and isinstance(value, str):
                cleaned[key] = value.upper()
            elif isinstance(value, dict):
                cleaned[key] = self._clean_schema(value)
            elif isinstance(value, list):
                cleaned[key] = [self._clean_schema(item) for item in value]
            else:
                cleaned[key] = value

        # Validate that required properties actually exist in properties
        if "required" in cleaned and "properties" in cleaned:
            valid_required = []
            properties_keys = set(cleaned["properties"].keys())
            for required_prop in cleaned["required"]:
                if required_prop in properties_keys:
                    valid_required.append(required_prop)
            if valid_required:
                cleaned["required"] = valid_required
            else:
                cleaned.pop("required", None)
        elif "required" in cleaned and "properties" not in cleaned:
            cleaned.pop("required", None)

        return cleaned

    def _clean_tools_format(self, tools_list):
        """Convert OpenAI format tools to Google AI format."""
        genai_tools = []
        for tool_data in tools_list:
            if tool_data["type"] == "function":
                function = tool_data["function"]
                parameters = function["parameters"]
                properties = parameters.get("properties", {})

                if properties:
                    cleaned_properties = {}
                    for k, v in properties.items():
                        cleaned_properties[k] = self._clean_schema(v)

                    genai_function = dict(
                        name=function["name"],
                        description=function["description"],
                        parameters={
                            "type": "OBJECT",
                            "properties": cleaned_properties,
                            "required": (
                                parameters["required"]
                                if "required" in parameters
                                else []
                            ),
                        },
                    )
                else:
                    genai_function = dict(
                        name=function["name"],
                        description=function["description"],
                    )

                genai_tool = types.Tool(function_declarations=[genai_function])
                genai_tools.append(genai_tool)

        return genai_tools

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        formatting="openai",
        response_schema=None,
        **kwargs,
    ):
        """Generate content using Google AI API without streaming."""
        client = genai.Client(api_key=self.api_key)
        if formatting == "openai":
            messages = self._clean_messages_google(messages)
        config = types.GenerateContentConfig()
        if messages[0].role == "system":
            config.system_instruction = messages[0].parts[0].text
            messages = messages[1:]

        if tools:
            cleaned_tools = self._clean_tools_format(tools)
            config.tools = cleaned_tools

        # Add response schema for structured output if provided
        if response_schema:
            config.response_schema = response_schema
            config.response_mime_type = "application/json"

        response = client.models.generate_content(
            model=model,
            contents=messages,
            config=config,
        )

        if tools:
            return response
        else:
            return response.text

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        formatting="openai",
        response_schema=None,
        **kwargs,
    ):
        """Generate content using Google AI API with streaming."""
        client = genai.Client(api_key=self.api_key)
        if formatting == "openai":
            messages = self._clean_messages_google(messages)
        config = types.GenerateContentConfig()
        if messages[0].role == "system":
            config.system_instruction = messages[0].parts[0].text
            messages = messages[1:]

        if tools:
            cleaned_tools = self._clean_tools_format(tools)
            config.tools = cleaned_tools

        # Add response schema for structured output if provided
        if response_schema:
            config.response_schema = response_schema
            config.response_mime_type = "application/json"

        # Check if we have both tools and file attachments
        has_attachments = False
        for message in messages:
            for part in message.parts:
                if hasattr(part, "file_data") and part.file_data is not None:
                    has_attachments = True
                    break
            if has_attachments:
                break

        logging.info(
            f"GoogleLLM: Starting stream generation. Model: {model}, Messages: {json.dumps(messages, default=str)}, Has attachments: {has_attachments}"
        )

        response = client.models.generate_content_stream(
            model=model,
            contents=messages,
            config=config,
        )

        try:
            for chunk in response:
                if hasattr(chunk, "candidates") and chunk.candidates:
                    for candidate in chunk.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if part.function_call:
                                    yield part
                                elif part.text:
                                    yield part.text
                elif hasattr(chunk, "text"):
                    yield chunk.text
        finally:
            if hasattr(response, 'close'):
                response.close()

    def _supports_tools(self):
        """Return whether this LLM supports function calling."""
        return True

    def _supports_structured_output(self):
        """Return whether this LLM supports structured JSON output."""
        return True

    def prepare_structured_output_format(self, json_schema):
        """Convert JSON schema to Google AI structured output format."""
        if not json_schema:
            return None

        type_map = {
            "object": "OBJECT",
            "array": "ARRAY",
            "string": "STRING",
            "integer": "INTEGER",
            "number": "NUMBER",
            "boolean": "BOOLEAN",
        }

        def convert(schema):
            if not isinstance(schema, dict):
                return schema

            result = {}
            schema_type = schema.get("type")
            if schema_type:
                result["type"] = type_map.get(schema_type.lower(), schema_type.upper())

            for key in [
                "description",
                "nullable",
                "enum",
                "minItems",
                "maxItems",
                "required",
                "propertyOrdering",
            ]:
                if key in schema:
                    result[key] = schema[key]

            if "format" in schema:
                format_value = schema["format"]
                if schema_type == "string":
                    if format_value == "date":
                        result["format"] = "date-time"
                    elif format_value in ["enum", "date-time"]:
                        result["format"] = format_value
                else:
                    result["format"] = format_value

            if "properties" in schema:
                result["properties"] = {
                    k: convert(v) for k, v in schema["properties"].items()
                }
                if "propertyOrdering" not in result and result.get("type") == "OBJECT":
                    result["propertyOrdering"] = list(result["properties"].keys())

            if "items" in schema:
                result["items"] = convert(schema["items"])

            for field in ["anyOf", "oneOf", "allOf"]:
                if field in schema:
                    result[field] = [convert(s) for s in schema[field]]

            return result

        try:
            return convert(json_schema)
        except Exception as e:
            logging.error(
                f"Error preparing structured output format for Google: {e}",
                exc_info=True,
            )
            return None
