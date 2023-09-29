from application.llm.base import BaseLLM
from application.core.settings import settings
import requests
import json

class SagemakerAPILLM(BaseLLM):

    def __init__(self, *args, **kwargs):
        self.url = settings.SAGEMAKER_API_URL

    def gen(self, model, engine, messages, stream=False, **kwargs):
        context = messages[0]['content']
        user_question = messages[-1]['content']
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        response = requests.post(
                    url=self.url,
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    data=json.dumps({"input": prompt})
        )

        return response.json()['answer']

    def gen_stream(self, model, engine, messages, stream=True, **kwargs):
        raise NotImplementedError("Sagemaker does not support streaming")