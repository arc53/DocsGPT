import json

from application.core.settings import settings
from application.llm.base import BaseLLM


class DocsGPTAPILLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        from openai import OpenAI

        super().__init__(*args, **kwargs)
        self.client = OpenAI(api_key="sk-docsgpt-public", base_url="https://oai.arc53.com")
        self.user_api_key = user_api_key
        self.api_key = api_key

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
                model="docsgpt",
                messages=messages,
                stream=stream,
                tools=tools,
                **kwargs,
            )
            return response.choices[0]
        else:
            response = self.client.chat.completions.create(
                model="docsgpt", messages=messages, stream=stream, **kwargs
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
                model="docsgpt",
                messages=messages,
                stream=stream,
                tools=tools,
                **kwargs,
            )
        else:
            response = self.client.chat.completions.create(
                model="docsgpt", messages=messages, stream=stream, **kwargs
            )

        for line in response:
            if len(line.choices) > 0 and line.choices[0].delta.content is not None and len(line.choices[0].delta.content) > 0:
                yield line.choices[0].delta.content
            elif len(line.choices) > 0:
                yield line.choices[0]

    def _supports_tools(self):
        return True