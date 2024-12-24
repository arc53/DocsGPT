from application.llm.base import BaseLLM
from application.core.settings import settings
import logging

class GoogleLLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_key = settings.API_KEY
        self.user_api_key = user_api_key

    def _clean_messages_google(self, messages):
        return [
            {
                "role": "model" if message["role"] == "system" else message["role"],
                "parts": [message["content"]],
            }
            for message in messages[1:]
        ]
        
    def _clean_tools_format(self, tools_data):
        """
        Cleans the tools data format, converting string type representations
        to the expected dictionary structure for google-generativeai.
        """
        if isinstance(tools_data, list):
            return [self._clean_tools_format(item) for item in tools_data]
        elif isinstance(tools_data, dict):
            if 'function' in tools_data and 'type' in tools_data and tools_data['type'] == 'function':
                # Handle the case where tools are nested under 'function'
                cleaned_function = self._clean_tools_format(tools_data['function'])
                return {'function_declarations': [cleaned_function]}
            elif 'function' in tools_data and 'type_' in tools_data and tools_data['type_'] == 'function':
                # Handle the case where tools are nested under 'function' and type is already 'type_'
                cleaned_function = self._clean_tools_format(tools_data['function'])
                return {'function_declarations': [cleaned_function]}
            else:
                new_tools_data = {}
                for key, value in tools_data.items():
                    if key == 'type':
                        if value == 'string':
                            new_tools_data['type_'] = 'STRING'  # Keep as string for now
                        elif value == 'object':
                            new_tools_data['type_'] = 'OBJECT'  # Keep as string for now
                    elif key == 'additionalProperties':
                        continue
                    elif key == 'properties':
                        if isinstance(value, dict):
                            new_properties = {}
                            for prop_name, prop_value in value.items():
                                if isinstance(prop_value, dict) and 'type' in prop_value:
                                    if prop_value['type'] == 'string':
                                        new_properties[prop_name] = {'type_': 'STRING', 'description': prop_value.get('description')}
                                    # Add more type mappings as needed
                                else:
                                    new_properties[prop_name] = self._clean_tools_format(prop_value)
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
        **kwargs
    ):  
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)

        config = {
        }
        model = 'gemini-2.0-flash-exp'
        
        model = genai.GenerativeModel(
            model_name=model,
            generation_config=config,
            system_instruction=messages[0]["content"],
            tools=self._clean_tools_format(tools)
            )
        chat_session = model.start_chat(
            history=self._clean_messages_google(messages)[:-1]
        )
        response = chat_session.send_message(
            self._clean_messages_google(messages)[-1]
        )
        logging.info(response)
        return response.text

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        **kwargs
    ):  
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        config = {
        }
        model = genai.GenerativeModel(
            model_name=model,
            generation_config=config,
            system_instruction=messages[0]["content"]
            )
        chat_session = model.start_chat(
            history=self._clean_messages_google(messages)[:-1],
        )
        response = chat_session.send_message(
            self._clean_messages_google(messages)[-1]
            , stream=stream
        )
        for line in response:
            if line.text is not None:
                yield line.text
                
    def _supports_tools(self):
        return True