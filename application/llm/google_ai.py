import google.generativeai as genai

from application.core.settings import settings
from application.llm.base import BaseLLM


class GoogleLLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = settings.API_KEY
        genai.configure(api_key=self.api_key)

    def _clean_messages_google(self, messages):
        cleaned_messages = []
        for message in messages[1:]:
            cleaned_messages.append(
                {
                    "role": "model" if message["role"] == "system" else message["role"],
                    "parts": [message["content"]],
                }
            )
        return cleaned_messages

    def _clean_tools_format(self, tools_data):
        if isinstance(tools_data, list):
            return [self._clean_tools_format(item) for item in tools_data]
        elif isinstance(tools_data, dict):
            if (
                "function" in tools_data
                and "type" in tools_data
                and tools_data["type"] == "function"
            ):
                # Handle the case where tools are nested under 'function'
                cleaned_function = self._clean_tools_format(tools_data["function"])
                return {"function_declarations": [cleaned_function]}
            elif (
                "function" in tools_data
                and "type_" in tools_data
                and tools_data["type_"] == "function"
            ):
                # Handle the case where tools are nested under 'function' and type is already 'type_'
                cleaned_function = self._clean_tools_format(tools_data["function"])
                return {"function_declarations": [cleaned_function]}
            else:
                new_tools_data = {}
                for key, value in tools_data.items():
                    if key == "type":
                        if value == "string":
                            new_tools_data["type_"] = "STRING"
                        elif value == "object":
                            new_tools_data["type_"] = "OBJECT"
                    elif key == "additionalProperties":
                        continue
                    elif key == "properties":
                        if isinstance(value, dict):
                            new_properties = {}
                            for prop_name, prop_value in value.items():
                                if (
                                    isinstance(prop_value, dict)
                                    and "type" in prop_value
                                ):
                                    if prop_value["type"] == "string":
                                        new_properties[prop_name] = {
                                            "type_": "STRING",
                                            "description": prop_value.get(
                                                "description"
                                            ),
                                        }
                                    # Add more type mappings as needed
                                else:
                                    new_properties[prop_name] = (
                                        self._clean_tools_format(prop_value)
                                    )
                            new_tools_data[key] = new_properties
                        else:
                            new_tools_data[key] = self._clean_tools_format(value)

                    else:
                        new_tools_data[key] = self._clean_tools_format(value)
                return new_tools_data
        else:
            return tools_data

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        formatting="openai",
        **kwargs
    ):
        config = {}
        model_name = "gemini-2.0-flash-exp"

        if formatting == "raw":
            client = genai.GenerativeModel(model_name=model_name)
            response = client.generate_content(contents=messages)
            return response.text
        else:
            if tools:
                client = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=config,
                    system_instruction=messages[0]["content"],
                    tools=self._clean_tools_format(tools),
                )
                chat_session = gen_model.start_chat(
                    history=self._clean_messages_google(messages)[:-1]
                )
                response = chat_session.send_message(
                    self._clean_messages_google(messages)[-1]
                )
                return response
            else:
                gen_model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=config,
                    system_instruction=messages[0]["content"],
                )
                chat_session = gen_model.start_chat(
                    history=self._clean_messages_google(messages)[:-1]
                )
                response = chat_session.send_message(
                    self._clean_messages_google(messages)[-1]
                )
                return response.text

    def _raw_gen_stream(
        self, baseself, model, messages, stream=True, tools=None, **kwargs
    ):
        config = {}
        model_name = "gemini-2.0-flash-exp"

        gen_model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=config,
            system_instruction=messages[0]["content"],
            tools=self._clean_tools_format(tools),
        )
        chat_session = gen_model.start_chat(
            history=self._clean_messages_google(messages)[:-1],
        )
        response = chat_session.send_message(
            self._clean_messages_google(messages)[-1], stream=stream
        )
        for chunk in response:
            if chunk.text is not None:
                yield chunk.text

    def _supports_tools(self):
        return True
