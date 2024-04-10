from application.llm.base import BaseLLM
from application.core.settings import settings

class PremAILLM(BaseLLM):

    def __init__(self, api_key):
        from premai import Prem
        
        self.client = Prem(
            api_key=api_key
        )
        self.api_key = api_key
        self.project_id = settings.PREMAI_PROJECT_ID

    def gen(self, model, messages, stream=False, **kwargs):
        response = self.client.chat.completions.create(model=model,
            project_id=self.project_id,
            messages=messages,
            stream=stream,
            **kwargs)

        return response.choices[0].message["content"]

    def gen_stream(self, model, messages, stream=True, **kwargs):
        response = self.client.chat.completions.create(model=model,
            project_id=self.project_id,
            messages=messages,
            stream=stream,
            **kwargs)

        for line in response:
            if line.choices[0].delta["content"] is not None:
                yield line.choices[0].delta["content"]
