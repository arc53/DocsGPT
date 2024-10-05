from application.llm.base import BaseLLM



class GroqLLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        from openai import OpenAI

        super().__init__(*args, **kwargs)
        self.client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        self.api_key = api_key
        self.user_api_key = user_api_key

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        **kwargs
    ):  
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
        **kwargs
    ):  
        response = self.client.chat.completions.create(
            model=model, messages=messages, stream=stream, **kwargs
        )

        for line in response:
            # import sys
            # print(line.choices[0].delta.content, file=sys.stderr)
            if line.choices[0].delta.content is not None:
                yield line.choices[0].delta.content
