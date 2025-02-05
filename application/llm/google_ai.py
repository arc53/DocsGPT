from google import genai
from google.genai import types

from application.llm.base import BaseLLM


class GoogleLLM(BaseLLM):
    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self.user_api_key = user_api_key

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
                    parts = [types.Part.from_text(content)]
                elif isinstance(content, list):
                    for item in content:
                        if "text" in item:
                            parts.append(types.Part.from_text(item["text"]))
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

        response = client.models.generate_content_stream(
            model=model,
            contents=messages,
            config=config,
        )
        for chunk in response:
            if chunk.text is not None:
                yield chunk.text

    def _supports_tools(self):
        return True
