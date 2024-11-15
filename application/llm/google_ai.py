from application.llm.base import BaseLLM
from application.core.settings import settings




class GoogleLLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self.user_api_key = user_api_key

    def _clean_messages_google(self, messages):
        return [
            {
                "role": "model" if message["role"] == "system" else message["role"],
                "parts": [message["content"]],
            }
            for message in messages[1:]
        ]

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        **kwargs
    ):  
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(model, system_instruction=messages[0]["content"])
        response = model.generate_content(self._clean_messages_google(messages))
        return response.text

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        **kwargs
    ):  
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(model, system_instruction=messages[0]["content"])
        response = model.generate_content(self._clean_messages_google(messages), stream=True)
        for line in response:
            if line.text is not None:
                yield line.text