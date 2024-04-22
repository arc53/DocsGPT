from application.llm.base import BaseLLM
from application.core.settings import settings


class PremAILLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        from premai import Prem

        super().__init__(*args, **kwargs)
        self.client = Prem(api_key=api_key)
        self.api_key = api_key
        self.user_api_key = user_api_key
        self.project_id = settings.PREMAI_PROJECT_ID

    def _raw_gen(self, baseself, model, messages, stream=False, **kwargs):
        response = self.client.chat.completions.create(
            model=model,
            project_id=self.project_id,
            messages=messages,
            stream=stream,
            **kwargs
        )

        return response.choices[0].message["content"]

    def _raw_gen_stream(self, baseself, model, messages, stream=True, **kwargs):
        response = self.client.chat.completions.create(
            model=model,
            project_id=self.project_id,
            messages=messages,
            stream=stream,
            **kwargs
        )

        for line in response:
            if line.choices[0].delta["content"] is not None:
                yield line.choices[0].delta["content"]
