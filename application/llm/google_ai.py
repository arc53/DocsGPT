from google import genai
from google.genai import types
import logging
import json

from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator
from application.core.settings import settings


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
            'application/pdf',
            'image/png',
            'image/jpeg',
            'image/jpg',
            'image/webp',
            'image/gif'
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
            mime_type = attachment.get('mime_type')

            if mime_type in self.get_supported_attachment_types():
                try:
                    file_uri = self._upload_file_to_google(attachment)
                    logging.info(f"GoogleLLM: Successfully uploaded file, got URI: {file_uri}")
                    files.append({"file_uri": file_uri, "mime_type": mime_type})
                except Exception as e:
                    logging.error(f"GoogleLLM: Error uploading file: {e}", exc_info=True)
                    if 'content' in attachment:
                        prepared_messages[user_message_index]["content"].append({
                            "type": "text",
                            "text": f"[File could not be processed: {attachment.get('path', 'unknown')}]"
                        })

        if files:
            logging.info(f"GoogleLLM: Adding {len(files)} files to message")
            prepared_messages[user_message_index]["content"].append({
                "files": files
            })

        return prepared_messages

    def _upload_file_to_google(self, attachment):
        """
        Upload a file to Google AI and return the file URI.

        Args:
            attachment (dict): Attachment dictionary with path and metadata.

        Returns:
            str: Google AI file URI for the uploaded file.
        """
        if 'google_file_uri' in attachment:
            return attachment['google_file_uri']

        file_path = attachment.get('path')
        if not file_path:
            raise ValueError("No file path provided in attachment")

        if not self.storage.file_exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            file_uri = self.storage.process_file(
                file_path,
                lambda local_path, **kwargs: self.client.files.upload(file=local_path).uri
            )

            from application.core.mongo_db import MongoDB
            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            attachments_collection = db["attachments"]
            if '_id' in attachment:
                attachments_collection.update_one(
                    {"_id": attachment['_id']},
                    {"$set": {"google_file_uri": file_uri}}
                )

            return file_uri
        except Exception as e:
            logging.error(f"Error uploading file to Google AI: {e}", exc_info=True)
            raise

    def _clean_messages_google(self, messages):
        cleaned_messages = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "assistant":
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
                                            mime_type=file_data["mime_type"]
                                        )
                                    )
                        else:
                            raise ValueError(
                                f"Unexpected content dictionary format:{item}"
                            )
                else:
                    raise ValueError(f"Unexpected content type: {type(content)}")

                cleaned_messages.append(types.Content(role=role, parts=parts))

        return cleaned_messages

    def _clean_tools_format(self, tools_list):
        genai_tools = []
        for tool_data in tools_list:
            if tool_data["type"] == "function":
                function = tool_data["function"]
                parameters = function["parameters"]
                properties = parameters.get("properties", {})

                if properties:
                    genai_function = dict(
                        name=function["name"],
                        description=function["description"],
                        parameters={
                            "type": "OBJECT",
                            "properties": {
                                k: {
                                    **v,
                                    "type": v["type"].upper() if v["type"] else None,
                                }
                                for k, v in properties.items()
                            },
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
        **kwargs,
    ):
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
            response = client.models.generate_content(
                model=model,
                contents=messages,
                config=config,
            )
            return response
        else:
            response = client.models.generate_content(
                model=model, contents=messages, config=config
            )
            return response.text

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        formatting="openai",
        **kwargs,
    ):
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

        # Check if we have both tools and file attachments
        has_attachments = False
        for message in messages:
            for part in message.parts:
                if hasattr(part, 'file_data') and part.file_data is not None:
                    has_attachments = True
                    break
            if has_attachments:
                break

        logging.info(f"GoogleLLM: Starting stream generation. Model: {model}, Messages: {json.dumps(messages, default=str)}, Has attachments: {has_attachments}")

        response = client.models.generate_content_stream(
            model=model,
            contents=messages,
            config=config,
        )


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

    def _supports_tools(self):
        return True
