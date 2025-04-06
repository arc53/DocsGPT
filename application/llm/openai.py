import json

from application.core.settings import settings
from application.llm.base import BaseLLM


class OpenAILLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        from openai import OpenAI

        super().__init__(*args, **kwargs)
        if settings.OPENAI_BASE_URL:
            self.client = OpenAI(api_key=api_key, base_url=settings.OPENAI_BASE_URL)
        else:
            self.client = OpenAI(api_key=api_key)
        self.api_key = api_key
        self.user_api_key = user_api_key

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
                        elif isinstance(item, dict):
                            content_parts = []
                            if "text" in item:
                                content_parts.append({"type": "text", "text": item["text"]})
                            elif "type" in item and item["type"] == "text" and "text" in item:
                                content_parts.append(item)
                            elif "type" in item and item["type"] == "file" and "file" in item:
                                content_parts.append(item)
                            cleaned_messages.append({"role": role, "content": content_parts})
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
            # Upload the file to OpenAI
            try:
                file_id = self._upload_file_to_openai(attachment)
                
                prepared_messages[user_message_index]["content"].append({
                    "type": "file",
                    "file": {"file_id": file_id}
                })
            except Exception as e:
                import logging
                logging.error(f"Error uploading attachment to OpenAI: {e}")
                if 'content' in attachment:
                    prepared_messages[user_message_index]["content"].append({
                        "type": "text", 
                        "text": f"File content:\n\n{attachment['content']}"
                    })
        
        return prepared_messages

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
        import os
        import mimetypes
        
        # Check if we already have the file_id cached
        if 'openai_file_id' in attachment:
            return attachment['openai_file_id']
        
        file_path = attachment.get('path')
        if not file_path:
            raise ValueError("No file path provided in attachment")
        
        # Make path absolute if it's relative
        if not os.path.isabs(file_path):
            current_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            file_path = os.path.join(current_dir,"application", file_path)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        mime_type = attachment.get('mime_type')
        if not mime_type:
            mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        
        supported_mime_types = ['application/pdf', 'image/png', 'image/jpeg', 'image/gif']
        if mime_type not in supported_mime_types:
            import logging
            logging.warning(f"MIME type {mime_type} not supported by OpenAI for file uploads. Falling back to text.")
            raise ValueError(f"Unsupported MIME type: {mime_type}")
        
        try:
            with open(file_path, 'rb') as file:
                response = self.client.files.create(
                    file=file,
                    purpose="assistants"
                )
            
            file_id = response.id
            
            from application.core.mongo_db import MongoDB
            mongo = MongoDB.get_client()
            db = mongo["docsgpt"]
            attachments_collection = db["attachments"]
            if '_id' in attachment:
                attachments_collection.update_one(
                    {"_id": attachment['_id']},
                    {"$set": {"openai_file_id": file_id}}
                )
            
            return file_id
        except Exception as e:
            import logging
            logging.error(f"Error uploading file to OpenAI: {e}")
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
