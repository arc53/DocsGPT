from application.llm.base import BaseLLM
import json
import requests


class DocsGPTAPILLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self.user_api_key = user_api_key
        self.endpoint = "https://llm.arc53.com"

    def _raw_gen(self, baseself, model, messages, stream=False, *args, **kwargs):
        response = requests.post(
            f"{self.endpoint}/answer", json={"messages": messages, "max_new_tokens": 30}
        )
        response_clean = response.json()["a"].replace("###", "")

        return response_clean

    def _raw_gen_stream(self, baseself, model, messages, stream=True, *args, **kwargs):
        response = requests.post(
            f"{self.endpoint}/stream",
            json={"messages": messages, "max_new_tokens": 256},
            stream=True,
        )

        for line in response.iter_lines():
            if line:
                data_str = line.decode("utf-8")
                if data_str.startswith("data: "):
                    data = json.loads(data_str[6:])
                    yield data["a"]
