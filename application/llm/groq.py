from application.llm.base import BaseLLM
from openai import OpenAI


class GroqLLM(BaseLLM):
    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        self.api_key = api_key
        self.user_api_key = user_api_key

    def _raw_gen(self, baseself, model, messages, stream=False, tools=None, **kwargs):
        if tools:
            response = self.client.chat.completions.create(
                model=model, messages=messages, stream=stream, tools=tools, **kwargs
            )
            return response.choices[0]
        else:
            response = self.client.chat.completions.create(
                model=model, messages=messages, stream=stream, **kwargs
            )
            return response.choices[0].message.content

    def _raw_gen_stream(
        self, baseself, model, messages, stream=True, tools=None, **kwargs
    ):
        response = self.client.chat.completions.create(
            model=model, messages=messages, stream=stream, **kwargs
        )
        for line in response:
            if line.choices[0].delta.content is not None:
                yield line.choices[0].delta.content
