from application.llm.base import BaseLLM
import json
import requests
from application.usage import gen_token_usage, stream_token_usage


class DocsGPTAPILLM(BaseLLM):

    def __init__(self, api_key, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self.endpoint = "https://llm.docsgpt.co.uk"

    @gen_token_usage
    def gen(self, model, messages, stream=False, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        response = requests.post(
            f"{self.endpoint}/answer", json={"prompt": prompt, "max_new_tokens": 30}
        )
        response_clean = response.json()["a"].replace("###", "")

        return response_clean

    @stream_token_usage
    def gen_stream(self, model, messages, stream=True, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        # send prompt to endpoint /stream
        response = requests.post(
            f"{self.endpoint}/stream",
            json={"prompt": prompt, "max_new_tokens": 256},
            stream=True,
        )

        for line in response.iter_lines():
            if line:
                # data = json.loads(line)
                data_str = line.decode("utf-8")
                if data_str.startswith("data: "):
                    data = json.loads(data_str[6:])
                    yield data["a"]
