from application.llm.base import BaseLLM
import json
import requests

class DocsGPTAPILLM(BaseLLM):

    def __init__(self, *args, **kwargs):
        self.endpoint =  "https://llm.docsgpt.co.uk"


    def gen(self, model, engine, messages, stream=False, **kwargs):
        context = messages[0]['content']
        user_question = messages[-1]['content']
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        response = requests.post(
            f"{self.endpoint}/answer",
            json={
                "prompt": prompt,
                "max_new_tokens": 30
            }
        )
        response_clean = response.json()['a'].replace("###", "")

        return response_clean

    def gen_stream(self, model, engine, messages, stream=True, **kwargs):
        context = messages[0]['content']
        user_question = messages[-1]['content']
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        # send prompt to endpoint /stream
        response = requests.post(
            f"{self.endpoint}/stream",
            json={
                "prompt": prompt,
                "max_new_tokens": 256
            },
            stream=True
        )
    
        for line in response.iter_lines():
            if line:
                #data = json.loads(line)
                data_str = line.decode('utf-8')
                if data_str.startswith("data: "):
                    data = json.loads(data_str[6:])
                    yield data['a']
                    