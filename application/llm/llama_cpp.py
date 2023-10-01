from application.llm.base import BaseLLM

class LlamaCpp(BaseLLM):

    def __init__(self, api_key, llm_name='/Users/pavel/Desktop/docsgpt/application/models/orca-test.bin'):
        global llama
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError("Please install llama_cpp using pip install llama-cpp-python")

        llama = Llama(model_path=llm_name)

    def gen(self, model, engine, messages, stream=False, **kwargs):
        context = messages[0]['content']
        user_question = messages[-1]['content']
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        result = llama(prompt, max_tokens=150, echo=False)

        # import sys
        # print(result['choices'][0]['text'].split('### Answer \n')[-1], file=sys.stderr)
        
        return result['choices'][0]['text'].split('### Answer \n')[-1]

    def gen_stream(self, model, engine, messages, stream=True, **kwargs):
        context = messages[0]['content']
        user_question = messages[-1]['content']
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        result = llama(prompt, max_tokens=150, echo=False, stream=stream)

        # import sys
        # print(list(result), file=sys.stderr)

        for item in result:
            for choice in item['choices']:
                yield choice['text']
