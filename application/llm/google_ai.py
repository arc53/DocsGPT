from google import genai
from google.genai import types

from application.core.settings import settings
from application.llm.base import BaseLLM


class GoogleLLM(BaseLLM):
    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = genai.Client(api_key=api_key)

    def _clean_messages_google(self, messages):
        cleaned_messages = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role and content is not None:
                if isinstance(content, str):
                    parts = [types.Part.from_text(content)]
                elif isinstance(content, list):
                    parts = content
                else:
                    raise ValueError(f"Unexpected content type: {type(content)}")

                cleaned_messages.append(types.Content(role=role, parts=parts))

        return cleaned_messages

    def _clean_tools_format(self, tools_list):
        genai_tools = []
        for tool_data in tools_list:
            if tool_data["type"] == "function":
                function = tool_data["function"]
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
                            for k, v in function["parameters"]["properties"].items()
                        },
                        "required": (
                            function["parameters"]["required"]
                            if "required" in function["parameters"]
                            else []
                        ),
                    },
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
        client = self.client
        if formatting == "openai":
            messages = self._clean_messages_google(messages)
        config = types.GenerateContentConfig()

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
        client = self.client
        if formatting == "openai":
            cleaned_messages = self._clean_messages_google(messages)
        config = types.GenerateContentConfig()

        if tools:
            cleaned_tools = self._clean_tools_format(tools)
            config.tools = cleaned_tools

        response = client.models.generate_content_stream(
            model=model,
            contents=cleaned_messages,
            config=config,
        )
        for chunk in response:
            if chunk.text is not None:
                yield chunk.text

    def _supports_tools(self):
        return True
